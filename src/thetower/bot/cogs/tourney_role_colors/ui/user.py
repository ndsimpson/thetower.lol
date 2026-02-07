"""User-facing role selection views for Tourney Role Colors cog."""

from typing import Dict, List

import discord
from discord import ui

from thetower.bot.cogs.tourney_role_colors.ui.settings import _sort_roles_by_inheritance


class RoleSelectionView(ui.View):
    """Main view for users to select their tourney role color."""

    def __init__(self, cog, interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.cog = cog
        self.interaction = interaction
        self.guild = interaction.guild
        self.member = interaction.user

        # Get user's current roles
        user_role_ids = [role.id for role in self.member.roles]

        # Get all managed roles to see what they currently have
        all_managed_roles = self.cog.get_all_managed_roles(self.guild.id)
        self.current_role_id = None
        for role_id in user_role_ids:
            if role_id in all_managed_roles:
                self.current_role_id = role_id
                break

        # Get eligible roles
        self.eligible_roles = self.cog.get_eligible_roles(self.guild.id, user_role_ids)

        # Group by category
        self.roles_by_category = {}
        for role_config in self.eligible_roles:
            category = role_config["category"]
            if category not in self.roles_by_category:
                self.roles_by_category[category] = []
            self.roles_by_category[category].append(role_config)

        # Add category buttons first (sorted alphabetically) with explicit row assignment
        # Discord layout: 5 buttons per row (rows 0-4, max 5 rows)
        sorted_categories = sorted(self.roles_by_category.keys())
        for idx, category_name in enumerate(sorted_categories):
            btn = ui.Button(label=category_name, style=discord.ButtonStyle.primary, row=idx // 5)
            btn.callback = self._create_category_callback(category_name)
            self.add_item(btn)

        # Add Clear button on its own row if space allows, otherwise on the last row
        # Calculate which row categories fill: if 1-5 categories, they use row 0, so clear goes to row 1
        num_categories = len(sorted_categories)
        rows_used = (num_categories + 4) // 5  # ceiling division to get rows needed
        clear_role_row = min(rows_used, 4)  # put on its own row if possible (0-indexed, max 4)

        clear_btn = ui.Button(label="Clear Role", style=discord.ButtonStyle.danger, emoji="❌", row=clear_role_row)
        clear_btn.callback = self.on_clear_role
        self.add_item(clear_btn)

    def _create_category_callback(self, category_name: str):
        """Create a callback for a specific category button."""

        async def callback(interaction: discord.Interaction):
            await self.on_category_selected(interaction, category_name)

        return callback

    async def show(self):
        """Display the role selection view."""
        content = self._build_main_message()
        await self.interaction.response.send_message(content=content, view=self, ephemeral=True)

    async def refresh(self, interaction: discord.Interaction):
        """Refresh the view after a role change."""
        # Refresh the member object to get up-to-date role list
        self.member = await self.guild.fetch_member(self.member.id)

        # Rebuild the view with updated data
        user_role_ids = [role.id for role in self.member.roles]
        all_managed_roles = self.cog.get_all_managed_roles(self.guild.id)

        self.current_role_id = None
        for role_id in user_role_ids:
            if role_id in all_managed_roles:
                self.current_role_id = role_id
                break

        self.eligible_roles = self.cog.get_eligible_roles(self.guild.id, user_role_ids)

        # Rebuild roles by category
        self.roles_by_category = {}
        for role_config in self.eligible_roles:
            category = role_config["category"]
            if category not in self.roles_by_category:
                self.roles_by_category[category] = []
            self.roles_by_category[category].append(role_config)

        content = self._build_main_message()
        await interaction.response.edit_message(content=content, view=self)

    def _build_main_message(self) -> str:
        """Build the main message showing current role and available options."""
        content = "**🎨 Tourney Role Color Selection**\n\n"

        # Show current role
        if self.current_role_id:
            current_role = self.guild.get_role(self.current_role_id)
            if current_role:
                # Find the category for this role
                categories = self.cog.get_setting("categories", [], guild_id=self.guild.id)
                category_name = "Unknown"
                for cat in categories:
                    found = False
                    for role_config in cat.get("roles", []):
                        if role_config.get("role_id") == self.current_role_id:
                            category_name = cat.get("name")
                            found = True
                            break
                    if found:
                        break

                content += "**Current Selection:**\n"
                content += f"**{category_name}:** {current_role.mention}\n\n"
        else:
            content += "**Current Selection:** No role selected\n\n"

        # Show available roles by category
        if self.roles_by_category:
            content += "**Available Roles:**\n"
            for category_name in sorted(self.roles_by_category.keys()):
                roles = _sort_roles_by_inheritance(self.roles_by_category[category_name])
                role_mentions = ", ".join([f"<@&{r['role_id']}>" for r in roles])
                content += f"**{category_name}:** {role_mentions}\n"

            content += "\nSelect a category below to change your role, or click **Clear Role** to remove your current selection."
        return content

    async def on_category_selected(self, interaction: discord.Interaction, category_name: str):
        """Handle category button click."""
        roles = self.roles_by_category.get(category_name, [])
        if not roles:
            await interaction.response.send_message("No roles available in this category.", ephemeral=True)
            return

        # Show category selection view
        view = CategoryRoleSelectionView(self.cog, self, category_name, roles)
        await view.show(interaction)

    async def on_clear_role(self, interaction: discord.Interaction):
        """Handle clear role button click."""
        if not self.current_role_id:
            await interaction.response.send_message("You don't have a role to clear.", ephemeral=True)
            return

        # Remove the current role
        current_role = self.guild.get_role(self.current_role_id)
        if current_role and current_role in self.member.roles:
            try:
                await self.member.remove_roles(current_role, reason="Tourney role color cleared")
                # Refresh the main view
                await self.refresh(interaction)
            except discord.Forbidden:
                await interaction.response.send_message("Bot does not have permission to manage roles.", ephemeral=True)
            except discord.HTTPException as e:
                await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)
        else:
            # Role not found or user doesn't have it, just refresh
            await self.refresh(interaction)


class CategoryRoleSelectionView(ui.View):
    """View for selecting a specific role within a category."""

    def __init__(self, cog, parent_view: RoleSelectionView, category_name: str, roles: List[Dict]):
        super().__init__(timeout=300)
        self.cog = cog
        self.parent_view = parent_view
        self.category_name = category_name
        self.roles = roles

        # Add role buttons (one for each available role)
        for role_config in roles:
            role_id = role_config["role_id"]
            role_name = role_config["name"]

            btn = ui.Button(label=role_name, style=discord.ButtonStyle.success, emoji="✅")
            btn.callback = self._create_role_callback(role_id, role_name)
            self.add_item(btn)

        # Add back button
        back_btn = ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️")
        back_btn.callback = self.on_back
        self.add_item(back_btn)

    def _create_role_callback(self, role_id: int, role_name: str):
        """Create a callback for a specific role button."""

        async def callback(interaction: discord.Interaction):
            await self.on_role_selected(interaction, role_id, role_name)

        return callback

    async def show(self, interaction: discord.Interaction):
        """Display the category role selection view."""
        content = f"**🎨 Select {self.category_name} Role**\n\n"
        content += "**Available roles in this category:**\n"

        for role_config in self.roles:
            content += f"• <@&{role_config['role_id']}>\n"

        content += "\nClick a role to select it:"

        await interaction.response.edit_message(content=content, view=self)

    async def on_role_selected(self, interaction: discord.Interaction, role_id: int, role_name: str):
        """Handle role button click."""
        # Assign the role
        success, message = await self.cog.assign_role_to_user(self.parent_view.guild, self.parent_view.member, role_id)

        if success:
            # Refresh the main view
            await self.parent_view.refresh(interaction)
        else:
            # Show error message
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)

    async def on_back(self, interaction: discord.Interaction):
        """Handle back button click."""
        await self.parent_view.refresh(interaction)


class RoleSelectionButton(ui.Button):
    """Button that opens the role selection interface."""

    def __init__(self, cog):
        super().__init__(label="Select Role Color", style=discord.ButtonStyle.primary, emoji="🎨")
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        """Handle button click - open role selection view."""
        view = RoleSelectionView(self.cog, interaction)
        await view.show()
