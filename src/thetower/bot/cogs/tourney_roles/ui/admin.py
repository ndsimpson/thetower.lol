"""
Administrative interfaces for the Tournament Roles cog.

This module contains:
- Admin and moderator interfaces for managing tournament roles
- Bulk operations and oversight tools
- Role configuration and management commands
"""

from typing import Any, Dict

import discord
from discord import app_commands, ui

from thetower.bot.basecog import BaseCog

from .core import LeagueHierarchyModal, TournamentRolesCore


class AddRoleSearchModal(ui.Modal, title="Add Tournament Role"):
    """Modal for searching and selecting a role to add."""

    role_input = ui.TextInput(
        label="Role Name or ID",
        placeholder="Enter role name or ID",
        required=True,
        max_length=100,
    )

    def __init__(self, cog, guild_id: int, original_interaction):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.original_interaction = original_interaction

    async def on_submit(self, interaction: discord.Interaction):
        """Handle the modal submission."""
        guild = interaction.guild
        input_value = self.role_input.value.strip()

        # Try to find the role
        role = None

        # First, try as role ID
        if input_value.isdigit():
            role = guild.get_role(int(input_value))

        # If not found, try by name (case-insensitive)
        if not role:
            role = discord.utils.get(guild.roles, name=input_value)

        # If still not found, try partial match
        if not role:
            matching_roles = [r for r in guild.roles if input_value.lower() in r.name.lower()]
            if len(matching_roles) == 1:
                role = matching_roles[0]
            elif len(matching_roles) > 1:
                role_names = ", ".join([f"`{r.name}`" for r in matching_roles[:5]])
                more = f" and {len(matching_roles) - 5} more" if len(matching_roles) > 5 else ""
                await interaction.response.send_message(
                    f"❌ Multiple roles match '{input_value}': {role_names}{more}\n" f"Please be more specific or use the role ID.",
                    ephemeral=True,
                )
                return

        # Validate the role
        if not role:
            await interaction.response.send_message(
                f"❌ Could not find role '{input_value}'\n" f"Please enter a valid role name or ID.",
                ephemeral=True,
            )
            return

        if role.is_default():
            await interaction.response.send_message("❌ Cannot use @everyone as a tournament role", ephemeral=True)
            return

        if role.managed:
            await interaction.response.send_message(f"❌ Cannot use managed role {role.mention} (managed by bot/integration)", ephemeral=True)
            return

        if role >= guild.me.top_role:
            await interaction.response.send_message(
                f"❌ Cannot manage role {role.mention} - it's higher than or equal to the bot's highest role", ephemeral=True
            )
            return

        # Move to method selection
        method_view = AddRoleMethodView(self.cog, self.guild_id, role)
        embed = discord.Embed(
            title="Add Tournament Role - Step 2: Select Method",
            description=f"Selected role: {role.mention}\n\nChoose how this role should be assigned based on tournament performance.",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Assignment Methods",
            value="• **Champion**: Awarded to the winner of the latest tournament in the top league\n"
            "• **Placement**: Awarded based on best placement across all tournaments\n"
            "• **Wave**: Awarded based on highest wave reached in a specific league",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, view=method_view, ephemeral=True)

        # Update original message to show progress
        try:
            await self.original_interaction.edit_original_response(
                embed=discord.Embed(
                    title="Add Tournament Role - In Progress",
                    description=f"Selected role: {role.mention}\nContinue in the new message above.",
                    color=discord.Color.green(),
                ),
                view=None,
            )
        except Exception:
            pass  # Original message might be gone


class AdminRoleManagementView(ui.View):
    """Administrative view for managing tournament roles."""

    def __init__(self, cog: BaseCog, guild_id: int, user_id: int):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id
        self.core = TournamentRolesCore(cog)

    @ui.button(label="Add Role", style=discord.ButtonStyle.primary, emoji="➕")
    async def add_role(self, interaction: discord.Interaction, button: ui.Button):
        """Add a new tournament role."""
        # Check permissions
        if not await self._check_admin_permission(interaction):
            return

        # Show modal for role search
        modal = AddRoleSearchModal(self.cog, self.guild_id, interaction)
        await interaction.response.send_modal(modal)

    async def _handle_add_role(self, interaction: discord.Interaction, result: Dict[str, Any]):
        """Handle the result of adding a role."""
        try:
            # Get existing roles config
            roles_config = self.core.get_roles_config(self.guild_id)

            # Check if this is a duplicate role name
            role_name = result["role_name"]
            if role_name in roles_config:
                await interaction.followup.send(f"❌ Role with name '{role_name}' already exists", ephemeral=True)
                return

            # Add new role configuration
            roles_config[role_name] = {"id": result["role_id"], "method": result["method"], "threshold": result["threshold"]}
            if result["method"] == "Wave":
                roles_config[role_name]["league"] = result["league"]

            # Save updated configuration
            self.cog.set_setting("roles_config", roles_config, guild_id=self.guild_id)

            await interaction.followup.send(f"✅ Added tournament role '{role_name}' with {result['method']} method", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ Error adding role: {str(e)}", ephemeral=True)

    @ui.button(label="Remove Role", style=discord.ButtonStyle.danger, emoji="➖")
    async def remove_role(self, interaction: discord.Interaction, button: ui.Button):
        """Remove a tournament role."""
        if not await self._check_admin_permission(interaction):
            return

        roles_config = self.core.get_roles_config(self.guild_id)
        if not roles_config:
            await interaction.followup.send("❌ No tournament roles have been configured", ephemeral=True)
            return

        # Create select menu for role removal
        options = []
        for role_name, config in roles_config.items():
            role = interaction.guild.get_role(int(config.id))
            role_display = role.name if role else f"ID: {config.id}"
            options.append(discord.SelectOption(label=role_name, description=f"{config.method} - {role_display}", value=role_name))

        if not options:
            await interaction.followup.send("❌ No roles available to remove", ephemeral=True)
            return

        select = ui.Select(placeholder="Select role to remove", options=options[:25])  # Discord limit

        async def select_callback(select_interaction: discord.Interaction):
            role_name = select.values[0]

            # Confirm removal
            confirm_view = ConfirmRemoveView(self.cog, self.guild_id, role_name)
            embed = discord.Embed(
                title="Confirm Role Removal",
                description=f"Are you sure you want to remove the tournament role '{role_name}'?",
                color=discord.Color.orange(),
            )
            await select_interaction.response.send_message(embed=embed, view=confirm_view, ephemeral=True)

        select.callback = select_callback

        view = ui.View()
        view.add_item(select)
        await interaction.response.send_message("Select a role to remove:", view=view, ephemeral=True)

    @ui.button(label="List Roles", style=discord.ButtonStyle.secondary, emoji="📋")
    async def list_roles(self, interaction: discord.Interaction, button: ui.Button):
        """List all configured tournament roles."""
        roles_config = self.core.get_roles_config(self.guild_id)

        if not roles_config:
            embed = discord.Embed(
                title="Tournament Roles Configuration", description="No tournament roles have been configured", color=discord.Color.blue()
            )
        else:
            embed = discord.Embed(
                title="Tournament Roles Configuration", description=f"{len(roles_config)} roles configured", color=discord.Color.blue()
            )

            # Group roles by method
            champion_roles = []
            placement_roles = []
            wave_roles = []

            for role_name, config in roles_config.items():
                role = interaction.guild.get_role(int(config.id))
                role_display = role.name if role else f"(ID: {config.id})"

                role_info = f"• **{role_name}** - {role_display}"

                if config.method == "Champion":
                    champion_roles.append(role_info)
                elif config.method == "Placement":
                    placement_roles.append((config.threshold, f"{role_info} (Top {config.threshold})"))
                else:  # Wave
                    league = config.league
                    # Get league hierarchy for sorting
                    league_hierarchy = self.core.get_league_hierarchy(self.guild_id)
                    league_index = league_hierarchy.index(league) if league in league_hierarchy else 999
                    wave_roles.append((league_index, config.threshold, f"{role_info} ({league} wave {config.threshold}+)"))

            # Sort placement roles by threshold (numerically)
            placement_roles.sort(key=lambda x: x[0])
            placement_roles = [role_str for _, role_str in placement_roles]

            # Sort wave roles by league (hierarchy order) then by threshold
            wave_roles.sort(key=lambda x: (x[0], x[1]))
            wave_roles = [role_str for _, _, role_str in wave_roles]

            # Add fields for each method
            if champion_roles:
                embed.add_field(name="Champion Method: Latest Tournament Winner", value="\n".join(champion_roles), inline=False)

            if placement_roles:
                embed.add_field(name="Placement Method: Placement-Based", value="\n".join(placement_roles), inline=False)

            if wave_roles:
                embed.add_field(name="Wave Method: Wave-Based", value="\n".join(wave_roles), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Set League Hierarchy", style=discord.ButtonStyle.secondary, emoji="🏆")
    async def set_league_hierarchy(self, interaction: discord.Interaction, button: ui.Button):
        """Set the league hierarchy."""
        if not await self._check_admin_permission(interaction):
            return

        current_hierarchy = self.core.get_league_hierarchy(self.guild_id)
        modal = LeagueHierarchyModal(current_hierarchy)
        await interaction.response.send_modal(modal)

        # Wait for modal result
        await modal.wait()
        if hasattr(modal, "result"):
            # Save the league hierarchy
            self.cog.set_setting("league_hierarchy", modal.result, guild_id=self.guild_id)
            await interaction.followup.send(f"✅ League hierarchy set: {', '.join(modal.result)}", ephemeral=True)

    async def _check_admin_permission(self, interaction: discord.Interaction) -> bool:
        """Check if user has admin permission."""
        # Check bot owner or guild owner
        is_bot_owner = await self.cog.bot.is_owner(interaction.user)
        is_guild_owner = interaction.guild.owner_id == interaction.user.id

        if is_bot_owner or is_guild_owner:
            return True

        # Check for manage_guild permission
        if interaction.user.guild_permissions.manage_guild:
            return True

        await interaction.response.send_message("❌ You need administrator permissions to use this feature", ephemeral=True)
        return False


class ConfirmRemoveView(ui.View):
    """Confirmation view for removing a role."""

    def __init__(self, cog: BaseCog, guild_id: int, role_name: str):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild_id = guild_id
        self.role_name = role_name

    @ui.button(label="Confirm", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        """Confirm role removal."""
        try:
            # Get existing roles config
            from .core import TournamentRolesCore

            core = TournamentRolesCore(self.cog)
            roles_config = core.get_roles_config(self.guild_id)

            # Check if the role exists
            if self.role_name not in roles_config:
                await interaction.response.send_message(f"❌ Role configuration '{self.role_name}' not found", ephemeral=True)
                return

            # Remove the role
            removed_config = roles_config.pop(self.role_name)
            self.cog.set_setting("roles_config", roles_config, guild_id=self.guild_id)

            # Get the actual role name for confirmation message
            role_id = removed_config.get("id")
            role_obj = interaction.guild.get_role(int(role_id)) if role_id else None
            role_display = role_obj.name if role_obj else f"ID: {role_id}"

            await interaction.response.send_message(f"✅ Removed tournament role '{self.role_name}' ({role_display})", ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"❌ Error removing role: {str(e)}", ephemeral=True)

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        """Cancel role removal."""
        await interaction.response.send_message("Role removal cancelled", ephemeral=True)


class AddRoleMethodView(ui.View):
    """View for selecting the assignment method."""

    def __init__(self, cog: BaseCog, guild_id: int, selected_role: discord.Role):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild_id = guild_id
        self.selected_role = selected_role
        self.core = TournamentRolesCore(cog)

    @ui.button(label="Champion", style=discord.ButtonStyle.primary, emoji="🏆")
    async def champion_method(self, interaction: discord.Interaction, button: ui.Button):
        """Select Champion method."""
        # For Champion method, threshold is always 1 (first place)
        await self._finalize_role(interaction, "Champion", 1, None)

    @ui.button(label="Placement", style=discord.ButtonStyle.primary, emoji="📊")
    async def placement_method(self, interaction: discord.Interaction, button: ui.Button):
        """Select Placement method."""
        # Move to threshold selection for placement
        threshold_view = AddRoleThresholdView(self.cog, self.guild_id, self.selected_role, "Placement")
        embed = discord.Embed(
            title="Add Tournament Role - Step 3: Placement Threshold",
            description=f"Selected role: {self.selected_role.mention}\nMethod: **Placement**\n\n"
            "Enter the placement threshold (e.g., 100 for Top 100, 50 for Top 50).",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="How it works",
            value="Players with a placement of this number or better across all their tournaments will receive this role.",
            inline=False,
        )
        await interaction.response.edit_message(embed=embed, view=threshold_view)

    @ui.button(label="Wave", style=discord.ButtonStyle.primary, emoji="🌊")
    async def wave_method(self, interaction: discord.Interaction, button: ui.Button):
        """Select Wave method."""
        # Move to threshold selection for wave
        threshold_view = AddRoleThresholdView(self.cog, self.guild_id, self.selected_role, "Wave")
        embed = discord.Embed(
            title="Add Tournament Role - Step 3: Wave Threshold",
            description=f"Selected role: {self.selected_role.mention}\nMethod: **Wave**\n\n"
            "Enter the wave threshold (e.g., 500 for Wave 500+, 300 for Wave 300+).",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="How it works", value="Players who have reached this wave or higher in tournaments will receive this role.", inline=False
        )
        await interaction.response.edit_message(embed=embed, view=threshold_view)

    async def _finalize_role(self, interaction: discord.Interaction, method: str, threshold: int, league: str = None):
        """Finalize the role configuration."""
        try:
            # Generate role name based on method
            if method == "Champion":
                role_name = "Current Champion"
            elif method == "Placement":
                role_name = f"Top{threshold}"
            else:  # Wave
                role_name = f"{league}{threshold}"

            # Check if this is a duplicate role name
            roles_config = self.core.get_roles_config(self.guild_id)
            if role_name in roles_config:
                await interaction.response.send_message(
                    f"❌ A role with the name '{role_name}' already exists. Please choose different parameters.", ephemeral=True
                )
                return

            # Add new role configuration
            roles_config[role_name] = {"id": str(self.selected_role.id), "method": method, "threshold": threshold}
            if method == "Wave":
                roles_config[role_name]["league"] = league

            # Save updated configuration
            self.cog.set_setting("roles_config", roles_config, guild_id=self.guild_id)

            # Success message
            embed = discord.Embed(
                title="✅ Role Added Successfully", description=f"Tournament role '{role_name}' has been configured.", color=discord.Color.green()
            )
            embed.add_field(
                name="Configuration",
                value=f"**Role:** {self.selected_role.mention}\n"
                f"**Method:** {method}\n"
                f"**Threshold:** {threshold}{f' in {league}' if league else ''}",
                inline=False,
            )
            await interaction.response.edit_message(embed=embed, view=None)

        except Exception as e:
            await interaction.response.send_message(f"❌ Error adding role: {str(e)}", ephemeral=True)


class AddRoleThresholdView(ui.View):
    """View for entering threshold values."""

    def __init__(self, cog: BaseCog, guild_id: int, selected_role: discord.Role, method: str):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild_id = guild_id
        self.selected_role = selected_role
        self.method = method
        self.core = TournamentRolesCore(cog)

    @ui.button(label="Enter Threshold", style=discord.ButtonStyle.primary, emoji="📝")
    async def enter_threshold(self, interaction: discord.Interaction, button: ui.Button):
        """Open modal to enter threshold."""
        modal = ThresholdModal(self.method)
        await interaction.response.send_modal(modal)

        await modal.wait()
        if hasattr(modal, "result"):
            threshold = modal.result

            if self.method == "Wave":
                # For Wave method, need to select league next
                league_view = AddRoleLeagueView(self.cog, self.guild_id, self.selected_role, threshold)
                embed = discord.Embed(
                    title="Add Tournament Role - Step 4: Select League",
                    description=f"Selected role: {self.selected_role.mention}\nMethod: **Wave**\nThreshold: **{threshold}+**\n\n"
                    "Choose the league this wave threshold applies to.",
                    color=discord.Color.blue(),
                )
                embed.add_field(
                    name="Available Leagues", value="Select from the dropdown below. The league hierarchy determines role priority.", inline=False
                )
                await interaction.followup.edit_message(interaction.message.id, embed=embed, view=league_view)
            else:
                # For Placement method, we're done
                await self._finalize_role(interaction, self.method, threshold, None)

    @ui.button(label="Back", style=discord.ButtonStyle.gray, emoji="⬅️")
    async def back(self, interaction: discord.Interaction, button: ui.Button):
        """Go back to method selection."""
        method_view = AddRoleMethodView(self.cog, self.guild_id, self.selected_role)
        embed = discord.Embed(
            title="Add Tournament Role - Step 2: Select Method",
            description=f"Selected role: {self.selected_role.mention}\n\nChoose how this role should be assigned based on tournament performance.",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Assignment Methods",
            value="• **Champion**: Awarded to the winner of the latest tournament in the top league\n"
            "• **Placement**: Awarded based on best placement across all tournaments\n"
            "• **Wave**: Awarded based on highest wave reached in a specific league",
            inline=False,
        )
        await interaction.response.edit_message(embed=embed, view=method_view)

    async def _finalize_role(self, interaction: discord.Interaction, method: str, threshold: int, league: str = None):
        """Finalize the role configuration."""
        try:
            # Generate role name based on method
            if method == "Placement":
                role_name = f"Top{threshold}"

            # Check if this is a duplicate role name
            roles_config = self.core.get_roles_config(self.guild_id)
            if role_name in roles_config:
                await interaction.response.send_message(
                    f"❌ A role with the name '{role_name}' already exists. Please choose different parameters.", ephemeral=True
                )
                return

            # Add new role configuration
            roles_config[role_name] = {"id": str(self.selected_role.id), "method": method, "threshold": threshold}
            if method == "Wave":
                roles_config[role_name]["league"] = league

            # Save updated configuration
            self.cog.set_setting("roles_config", roles_config, guild_id=self.guild_id)

            # Success message
            embed = discord.Embed(
                title="✅ Role Added Successfully", description=f"Tournament role '{role_name}' has been configured.", color=discord.Color.green()
            )
            embed.add_field(
                name="Configuration",
                value=f"**Role:** {self.selected_role.mention}\n"
                f"**Method:** {method}\n"
                f"**Threshold:** {threshold}{f' in {league}' if league else ''}",
                inline=False,
            )
            success_view = RoleCreationSuccessView(self.cog, self.guild_id)
            await interaction.response.edit_message(embed=embed, view=success_view)

        except Exception as e:
            await interaction.response.send_message(f"❌ Error adding role: {str(e)}", ephemeral=True)


class RoleCreationSuccessView(ui.View):
    """View shown after successfully creating a role."""

    def __init__(self, cog: BaseCog, guild_id: int):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild_id = guild_id

    @ui.button(label="Back to Main Menu", style=discord.ButtonStyle.primary, emoji="🏠")
    async def back_to_main(self, interaction: discord.Interaction, button: ui.Button):
        """Go back to the main tournament roles management menu."""
        embed = discord.Embed(
            title="Tournament Roles Management",
            description="Administrative tools for configuring tournament-based role assignment.",
            color=discord.Color.gold(),
        )

        embed.add_field(
            name="Available Actions",
            value="• **Add Role**: Configure a new tournament role\n"
            "• **Remove Role**: Remove an existing tournament role\n"
            "• **List Roles**: View all configured roles\n"
            "• **Set League Hierarchy**: Configure league priority order",
            inline=False,
        )

        view = AdminRoleManagementView(self.cog, self.guild_id, interaction.user.id)
        await interaction.response.edit_message(embed=embed, view=view)

    @ui.button(label="Add Another Role", style=discord.ButtonStyle.secondary, emoji="➕")
    async def add_another_role(self, interaction: discord.Interaction, button: ui.Button):
        """Start the process to add another role."""
        # Show modal for role search in a new ephemeral message
        modal = AddRoleSearchModal(self.cog, self.guild_id, interaction)
        await interaction.response.send_modal(modal)


class AddRoleLeagueView(ui.View):
    """View for selecting the league for Wave method."""

    def __init__(self, cog: BaseCog, guild_id: int, selected_role: discord.Role, threshold: int):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild_id = guild_id
        self.selected_role = selected_role
        self.threshold = threshold
        self.core = TournamentRolesCore(cog)

        # Get available leagues
        league_hierarchy = self.core.get_league_hierarchy(guild_id)

        # Create league options
        options = []
        for league in league_hierarchy:
            options.append(discord.SelectOption(label=league, value=league, description=f"Priority: {league_hierarchy.index(league) + 1}"))

        if options:
            self.league_select = ui.Select(placeholder="Choose a league...", options=options, min_values=1, max_values=1)
            self.league_select.callback = self.league_selected
            self.add_item(self.league_select)
        else:
            self.add_item(ui.Button(label="No leagues configured", disabled=True))

    async def league_selected(self, interaction: discord.Interaction):
        """Handle league selection."""
        selected_league = self.league_select.values[0]

        # Finalize the role configuration
        await self._finalize_role(interaction, "Wave", self.threshold, selected_league)

    @ui.button(label="Back", style=discord.ButtonStyle.gray, emoji="⬅️")
    async def back(self, interaction: discord.Interaction, button: ui.Button):
        """Go back to threshold selection."""
        threshold_view = AddRoleThresholdView(self.cog, self.guild_id, self.selected_role, "Wave")
        embed = discord.Embed(
            title="Add Tournament Role - Step 3: Wave Threshold",
            description=f"Selected role: {self.selected_role.mention}\nMethod: **Wave**\n\n"
            "Enter the wave threshold (e.g., 500 for Wave 500+, 300 for Wave 300+).",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="How it works", value="Players who have reached this wave or higher in tournaments will receive this role.", inline=False
        )
        await interaction.response.edit_message(embed=embed, view=threshold_view)

    async def _finalize_role(self, interaction: discord.Interaction, method: str, threshold: int, league: str = None):
        """Finalize the role configuration."""
        try:
            # Generate role name based on method
            if method == "Wave":
                role_name = f"{league}{threshold}"

            # Check if this is a duplicate role name
            roles_config = self.core.get_roles_config(self.guild_id)
            if role_name in roles_config:
                await interaction.response.send_message(
                    f"❌ A role with the name '{role_name}' already exists. Please choose different parameters.", ephemeral=True
                )
                return

            # Add new role configuration
            roles_config[role_name] = {"id": str(self.selected_role.id), "method": method, "threshold": threshold, "league": league}

            # Save updated configuration
            self.cog.set_setting("roles_config", roles_config, guild_id=self.guild_id)

            # Success message
            embed = discord.Embed(
                title="✅ Role Added Successfully", description=f"Tournament role '{role_name}' has been configured.", color=discord.Color.green()
            )
            embed.add_field(
                name="Configuration",
                value=f"**Role:** {self.selected_role.mention}\n" f"**Method:** {method}\n" f"**Threshold:** {threshold}+\n" f"**League:** {league}",
                inline=False,
            )
            success_view = RoleCreationSuccessView(self.cog, self.guild_id)
            await interaction.response.edit_message(embed=embed, view=success_view)

        except Exception as e:
            await interaction.response.send_message(f"❌ Error adding role: {str(e)}", ephemeral=True)


class ThresholdModal(ui.Modal, title="Enter Threshold"):
    """Modal for entering threshold values."""

    def __init__(self, method: str):
        super().__init__()
        self.method = method

        label = "Wave Threshold" if method == "Wave" else "Placement Threshold"
        placeholder = "500" if method == "Wave" else "100"

        self.threshold_input = ui.TextInput(label=label, placeholder=placeholder, required=True, min_length=1, max_length=6)
        self.add_item(self.threshold_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission."""
        try:
            threshold = int(self.threshold_input.value)
            if threshold < 1:
                await interaction.response.send_message("❌ Threshold must be a positive number", ephemeral=True)
                return

            if self.method == "Wave" and threshold > 100000:
                await interaction.response.send_message("❌ Wave threshold seems too high (max reasonable: 100,000)", ephemeral=True)
                return

            if self.method == "Placement" and threshold > 10000:
                await interaction.response.send_message("❌ Placement threshold seems too high (max reasonable: 10000)", ephemeral=True)
                return

            self.result = threshold
            await interaction.response.send_message(f"✅ Threshold set to {threshold}", ephemeral=True)

        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number", ephemeral=True)


class AdminTournamentRoles(BaseCog):
    """Administrative commands for tournament role management."""

    def __init__(self, bot):
        super().__init__(bot)
        self.core = TournamentRolesCore(self)

    @app_commands.command(name="manage-tournament-roles", description="[Admin] Manage tournament roles configuration")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def manage_tournament_roles(self, interaction: discord.Interaction):
        """Administrative interface for managing tournament roles."""
        embed = discord.Embed(
            title="Tournament Roles Management",
            description="Administrative tools for configuring tournament-based role assignment.",
            color=discord.Color.gold(),
        )

        embed.add_field(
            name="Available Actions",
            value="• **Add Role**: Configure a new tournament role\n"
            "• **Remove Role**: Remove an existing tournament role\n"
            "• **List Roles**: View all configured roles\n"
            "• **Set League Hierarchy**: Configure league priority order",
            inline=False,
        )

        # Check if user has permission
        is_bot_owner = await self.bot.is_owner(interaction.user)
        is_guild_owner = interaction.guild.owner_id == interaction.user.id
        has_manage_guild = interaction.user.guild_permissions.manage_guild

        if not (is_bot_owner or is_guild_owner or has_manage_guild):
            embed.add_field(
                name="Permission Required", value="You need `Manage Server` permission or be the server owner to use these features.", inline=False
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        view = AdminRoleManagementView(self, interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    """Setup function for the admin commands cog."""
    await bot.add_cog(AdminTournamentRoles(bot))
