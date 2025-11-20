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

from .core import AddRoleModal, LeagueHierarchyModal, TournamentRolesCore


class AdminRoleManagementView(ui.View):
    """Administrative view for managing tournament roles."""

    def __init__(self, cog: BaseCog, guild_id: int, user_id: int):
        super().__init__(timeout=600)
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

        league_hierarchy = self.core.get_league_hierarchy(self.guild_id)
        modal = AddRoleModal(league_hierarchy)
        await interaction.response.send_modal(modal)

        # Wait for modal result
        await modal.wait()
        if hasattr(modal, "result"):
            await self._handle_add_role(interaction, modal.result)

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
                    placement_roles.append(f"{role_info} (Top {config.threshold})")
                else:  # Wave
                    league = config.league
                    wave_roles.append(f"{role_info} ({league} wave {config.threshold}+)")

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
        super().__init__(timeout=60)
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
