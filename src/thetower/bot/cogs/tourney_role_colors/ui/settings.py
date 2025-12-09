"""
Settings management views for the Tourney Role Colors cog.

This module contains:
- Settings views for configuring color categories and roles
- Admin interfaces for server owners
"""

from typing import Any, Dict, Optional

import discord
from discord import ui

from thetower.bot.basecog import BaseCog


class TourneyRoleColorsSettingsView(ui.View):
    """Main settings view for Tourney Role Colors cog."""

    def __init__(self, cog: BaseCog, guild_id: int):
        super().__init__(timeout=600)  # 10 minute timeout
        self.cog = cog
        self.guild_id = guild_id

        # Add buttons for different settings actions
        self.add_item(ManageCategoriesButton(cog, guild_id))
        self.add_item(ViewCurrentConfigButton(cog, guild_id))

    async def create_embed(self) -> discord.Embed:
        """Create the main settings embed."""
        embed = discord.Embed(
            title="🎨 Tourney Role Colors Settings",
            description="Configure color role categories and prerequisites for your server.",
            color=discord.Color.blue(),
        )

        # Show current categories count
        categories = self.cog.core.get_color_categories(self.guild_id)
        embed.add_field(name="Current Configuration", value=f"**{len(categories)}** categories configured", inline=True)

        return embed


class ManageCategoriesButton(ui.Button):
    """Button to manage color categories."""

    def __init__(self, cog: BaseCog, guild_id: int):
        super().__init__(label="📁 Manage Categories", style=discord.ButtonStyle.primary)
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Show category management interface."""
        categories = self.cog.core.get_color_categories(self.guild_id)

        if not categories:
            # No categories yet, show setup interface
            view = CreateFirstCategoryView(self.cog, self.guild_id)
            embed = discord.Embed(
                title="🎨 Setup Color Categories",
                description="You haven't configured any color categories yet.\n\n"
                "Color categories group related color roles together "
                "(e.g., 'Orange', 'Red', 'VIP').",
                color=discord.Color.blue(),
            )
        else:
            # Show existing categories
            view = CategoryManagementView(self.cog, self.guild_id, categories)
            embed = discord.Embed(
                title="🎨 Manage Color Categories", description="Select a category to manage or create a new one:", color=discord.Color.blue()
            )

            # List current categories
            category_list = []
            for cat_name, cat_data in categories.items():
                role_count = len(cat_data.get("roles", {}))
                category_list.append(f"• **{cat_name}** ({role_count} roles)")

            if category_list:
                embed.add_field(name="Current Categories", value="\n".join(category_list), inline=False)

        await interaction.response.edit_message(embed=embed, view=view)


class ViewCurrentConfigButton(ui.Button):
    """Button to view current configuration."""

    def __init__(self, cog: BaseCog, guild_id: int):
        super().__init__(label="👁️ View Configuration", style=discord.ButtonStyle.secondary)
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Show current configuration overview."""
        categories = self.cog.core.get_color_categories(self.guild_id)

        embed = discord.Embed(title="🎨 Current Configuration", color=discord.Color.blue())

        if not categories:
            embed.description = "No color categories configured yet."
        else:
            embed.description = f"**{len(categories)}** categories configured:"

            for cat_name, cat_data in categories.items():
                roles = cat_data.get("roles", {})
                role_list = []

                for role_id, role_config in roles.items():
                    role = interaction.guild.get_role(role_id)
                    role_name = role.name if role else f"Unknown Role ({role_id})"

                    prereqs = role_config.get("additional_prerequisites", [])
                    prereq_text = ", ".join(prereqs) if prereqs else "None"

                    inherits = role_config.get("inherits_from")
                    if inherits:
                        inherit_role = interaction.guild.get_role(inherits)
                        inherit_name = inherit_role.name if inherit_role else f"Role {inherits}"
                        prereq_text += f" (+ inherits from {inherit_name})"

                    role_list.append(f"• **{role_name}**: {prereq_text}")

                embed.add_field(
                    name=f"📁 {cat_name} ({len(roles)} roles)", value="\n".join(role_list) if role_list else "No roles configured", inline=False
                )

        # Add back button
        view = ui.View()
        view.add_item(BackToSettingsButton(self.cog, self.guild_id))

        await interaction.response.edit_message(embed=embed, view=view)


class CreateFirstCategoryView(ui.View):
    """View for creating the first color category."""

    def __init__(self, cog: BaseCog, guild_id: int):
        super().__init__(timeout=600)
        self.cog = cog
        self.guild_id = guild_id

    @ui.button(label="➕ Create First Category", style=discord.ButtonStyle.success)
    async def create_first_category(self, interaction: discord.Interaction, button: ui.Button):
        """Start creating the first category."""
        modal = CreateCategoryModal(self.cog, self.guild_id, None)
        await interaction.response.send_modal(modal)


class CategoryManagementView(ui.View):
    """View for managing existing categories."""

    def __init__(self, cog: BaseCog, guild_id: int, categories: Dict[str, Any]):
        super().__init__(timeout=600)
        self.cog = cog
        self.guild_id = guild_id

        # Add buttons for each category
        for cat_name in categories.keys():
            self.add_item(CategoryButton(cat_name, cog, guild_id))

        # Add create new category button
        self.add_item(CreateCategoryButton(cog, guild_id))

        # Add back button
        self.add_item(BackToSettingsButton(cog, guild_id))


class CategoryButton(ui.Button):
    """Button for a specific category."""

    def __init__(self, category_name: str, cog: BaseCog, guild_id: int):
        super().__init__(label=category_name, style=discord.ButtonStyle.secondary)
        self.category_name = category_name
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Show category details and management options."""
        categories = self.cog.core.get_color_categories(self.guild_id)
        category_data = categories.get(self.category_name, {})

        embed = discord.Embed(title=f"🎨 {self.category_name} Category", color=discord.Color.blue())

        roles = category_data.get("roles", {})
        if roles:
            role_lines = []
            for role_id, role_config in roles.items():
                role = interaction.guild.get_role(int(role_id))
                role_name = role.name if role else f"Unknown Role ({role_id})"

                prereqs = role_config.get("additional_prerequisites", [])
                prereq_text = ", ".join(prereqs) if prereqs else "None"

                inherits = role_config.get("inherits_from")
                if inherits:
                    inherit_role = interaction.guild.get_role(inherits)
                    inherit_name = inherit_role.name if inherit_role else f"Role {inherits}"
                    prereq_text += f" (+ inherits from {inherit_name})"

                role_lines.append(f"• **{role_name}**: {prereq_text}")

            embed.description = f"**{len(roles)}** roles configured:"
            embed.add_field(name="Roles", value="\n".join(role_lines), inline=False)
        else:
            embed.description = "No roles configured in this category yet."

        # Create management view
        view = CategoryDetailView(self.cog, self.guild_id, self.category_name)
        await interaction.response.edit_message(embed=embed, view=view)


class CreateCategoryButton(ui.Button):
    """Button to create a new category."""

    def __init__(self, cog: BaseCog, guild_id: int):
        super().__init__(label="➕ New Category", style=discord.ButtonStyle.success)
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Create a new category."""
        # Create the categories view for callback
        categories = self.cog.core.get_color_categories(self.guild_id)
        callback_view = CategoryManagementView(self.cog, self.guild_id, categories)

        modal = CreateCategoryModal(self.cog, self.guild_id, callback_view)
        await interaction.response.send_modal(modal)


class BackToSettingsButton(ui.Button):
    """Button to go back to main settings."""

    def __init__(self, cog: BaseCog, guild_id: int):
        super().__init__(label="⬅️ Back to Settings", style=discord.ButtonStyle.secondary)
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Go back to main settings view."""
        view = TourneyRoleColorsSettingsView(self.cog, self.guild_id)
        embed = await view.create_embed()

        await interaction.response.edit_message(embed=embed, view=view)


class BackToCategoriesButton(ui.Button):
    """Button to go back to category management."""

    def __init__(self, cog: BaseCog, guild_id: int):
        super().__init__(label="⬅️ Back to Categories", style=discord.ButtonStyle.secondary)
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Go back to category management view."""
        categories = self.cog.core.get_color_categories(self.guild_id)
        view = CategoryManagementView(self.cog, self.guild_id, categories)

        embed = discord.Embed(
            title="🎨 Manage Color Categories", description="Select a category to manage or create a new one:", color=discord.Color.blue()
        )

        await interaction.response.edit_message(embed=embed, view=view)


class CategoryDetailView(ui.View):
    """View for managing a specific category."""

    def __init__(self, cog: BaseCog, guild_id: int, category_name: str):
        super().__init__(timeout=600)
        self.cog = cog
        self.guild_id = guild_id
        self.category_name = category_name

        # Add management buttons
        self.add_item(AddRoleButton(cog, guild_id, category_name))
        self.add_item(RemoveCategoryButton(cog, guild_id, category_name))
        self.add_item(BackToCategoriesButton(cog, guild_id))


class AddRoleButton(ui.Button):
    """Button to add a role to a category."""

    def __init__(self, cog: BaseCog, guild_id: int, category_name: str):
        super().__init__(label="➕ Add Role", style=discord.ButtonStyle.success)
        self.cog = cog
        self.guild_id = guild_id
        self.category_name = category_name

    async def callback(self, interaction: discord.Interaction):
        """Add a role to this category."""
        # Create the category detail view for callback
        callback_view = CategoryDetailView(self.cog, self.guild_id, self.category_name)

        modal = AddRoleModal(self.cog, self.guild_id, self.category_name, callback_view)
        await interaction.response.send_modal(modal)


class RemoveCategoryButton(ui.Button):
    """Button to remove a category."""

    def __init__(self, cog: BaseCog, guild_id: int, category_name: str):
        super().__init__(label="🗑️ Delete Category", style=discord.ButtonStyle.danger)
        self.cog = cog
        self.guild_id = guild_id
        self.category_name = category_name

    async def callback(self, interaction: discord.Interaction):
        """Remove this category."""
        # Create confirmation view
        view = ui.View()
        view.add_item(ConfirmDeleteCategoryButton(self.cog, self.guild_id, self.category_name))
        view.add_item(CancelDeleteButton(self.cog, self.guild_id, self.category_name))

        embed = discord.Embed(
            title="⚠️ Confirm Deletion",
            description=f"Are you sure you want to delete the category **{self.category_name}**?\n\n"
            "This will remove all role configurations in this category.",
            color=discord.Color.red(),
        )

        await interaction.response.edit_message(embed=embed, view=view)


class ConfirmDeleteCategoryButton(ui.Button):
    """Button to confirm category deletion."""

    def __init__(self, cog: BaseCog, guild_id: int, category_name: str):
        super().__init__(label="✅ Yes, Delete", style=discord.ButtonStyle.danger)
        self.cog = cog
        self.guild_id = guild_id
        self.category_name = category_name

    async def callback(self, interaction: discord.Interaction):
        """Confirm and delete the category."""
        try:
            success = await self.cog.core.remove_color_category(self.guild_id, self.category_name)

            if success:
                embed = discord.Embed(
                    title="✅ Category Deleted", description=f"Successfully deleted category **{self.category_name}**", color=discord.Color.green()
                )

                # Return to categories view
                categories = self.cog.core.get_color_categories(self.guild_id)
                if categories:
                    view = CategoryManagementView(self.cog, self.guild_id, categories)
                else:
                    # No categories left, go back to settings
                    view = TourneyRoleColorsSettingsView(self.cog, self.guild_id)
                    embed = await view.create_embed()

            else:
                embed = discord.Embed(
                    title="❌ Deletion Failed", description=f"Category **{self.category_name}** not found.", color=discord.Color.red()
                )
                view = CategoryDetailView(self.cog, self.guild_id, self.category_name)

            await interaction.response.edit_message(embed=embed, view=view)

        except Exception as e:
            embed = discord.Embed(title="❌ Error", description=f"Failed to delete category: {str(e)}", color=discord.Color.red())
            view = CategoryDetailView(self.cog, self.guild_id, self.category_name)
            await interaction.response.edit_message(embed=embed, view=view)


class CancelDeleteButton(ui.Button):
    """Button to cancel category deletion."""

    def __init__(self, cog: BaseCog, guild_id: int, category_name: str):
        super().__init__(label="❌ Cancel", style=discord.ButtonStyle.secondary)
        self.cog = cog
        self.guild_id = guild_id
        self.category_name = category_name

    async def callback(self, interaction: discord.Interaction):
        """Cancel deletion and return to category detail."""
        categories = self.cog.core.get_color_categories(self.guild_id)
        category_data = categories.get(self.category_name, {})

        embed = discord.Embed(title=f"🎨 {self.category_name} Category", color=discord.Color.blue())

        roles = category_data.get("roles", {})
        if roles:
            role_lines = []
            for role_id, role_config in roles.items():
                role = interaction.guild.get_role(int(role_id))
                role_name = role.name if role else f"Unknown Role ({role_id})"

                prereqs = role_config.get("additional_prerequisites", [])
                prereq_text = ", ".join(prereqs) if prereqs else "None"

                inherits = role_config.get("inherits_from")
                if inherits:
                    inherit_role = interaction.guild.get_role(inherits)
                    inherit_name = inherit_role.name if inherit_role else f"Role {inherits}"
                    prereq_text += f" (+ inherits from {inherit_name})"

                role_lines.append(f"• **{role_name}**: {prereq_text}")

            embed.description = f"**{len(roles)}** roles configured:"
            embed.add_field(name="Roles", value="\n".join(role_lines), inline=False)
        else:
            embed.description = "No roles configured in this category yet."

        view = CategoryDetailView(self.cog, self.guild_id, self.category_name)
        await interaction.response.edit_message(embed=embed, view=view)


# Modal dialogs for configuration


class CreateCategoryModal(ui.Modal, title="Create Color Category"):
    """Modal for creating a new color category."""

    def __init__(self, cog: BaseCog, guild_id: int, callback_view: Optional[ui.View]):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.callback_view = callback_view

    category_name = ui.TextInput(label="Category Name", placeholder="e.g., VIP Colors, Tournament Ranks", required=True, max_length=50)

    description = ui.TextInput(
        label="Description (Optional)",
        placeholder="Brief description of this category",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=200,
    )

    async def on_submit(self, interaction: discord.Interaction):
        """Handle category creation."""
        try:
            success = await self.cog.core.add_color_category(self.guild_id, self.category_name.value, self.description.value or "")

            if success:
                embed = discord.Embed(
                    title="✅ Category Created",
                    description=f"Successfully created category **{self.category_name.value}**",
                    color=discord.Color.green(),
                )

                # Return to settings view
                view = TourneyRoleColorsSettingsView(self.cog, self.guild_id)
                embed = await view.create_embed()

                await interaction.response.edit_message(embed=embed, view=view)
            else:
                embed = discord.Embed(
                    title="❌ Creation Failed",
                    description=f"A category named **{self.category_name.value}** already exists.",
                    color=discord.Color.red(),
                )

                # Return to the callback view or create a new one
                if self.callback_view:
                    view = self.callback_view
                else:
                    view = TourneyRoleColorsSettingsView(self.cog, self.guild_id)
                    embed = await view.create_embed()

                await interaction.response.edit_message(embed=embed, view=view)

        except Exception as e:
            embed = discord.Embed(title="❌ Error", description=f"Failed to create category: {str(e)}", color=discord.Color.red())

            if self.callback_view:
                view = self.callback_view
            else:
                view = TourneyRoleColorsSettingsView(self.cog, self.guild_id)
                embed = await view.create_embed()

            await interaction.response.edit_message(embed=embed, view=view)


class AddRoleModal(ui.Modal, title="Add Color Role"):
    """Modal for adding a role to a category."""

    def __init__(self, cog: BaseCog, guild_id: int, category_name: str, callback_view: Optional[ui.View]):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.category_name = category_name
        self.callback_view = callback_view

    role_name = ui.TextInput(label="Role Name", placeholder="Exact role name (case-sensitive)", required=True, max_length=50)

    prerequisites = ui.TextInput(
        label="Prerequisites (Optional)",
        placeholder="rank:gold, tournament:winner (comma-separated)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=200,
    )

    async def on_submit(self, interaction: discord.Interaction):
        """Handle role addition."""
        try:
            # Find the role by name
            role = discord.utils.get(interaction.guild.roles, name=self.role_name.value)
            if not role:
                embed = discord.Embed(
                    title="❌ Role Not Found",
                    description=f"Could not find a role named **{self.role_name.value}** in this server.",
                    color=discord.Color.red(),
                )
                await interaction.response.edit_message(embed=embed, view=self.callback_view)
                return

            # Parse prerequisites
            prereq_list = []
            if self.prerequisites.value:
                prereq_list = [p.strip() for p in self.prerequisites.value.split(",")]

            success = await self.cog.core.add_color_role(self.guild_id, self.category_name, role.id, prereq_list)

            if success:
                prereq_text = ", ".join(prereq_list) if prereq_list else "None"
                embed = discord.Embed(
                    title="✅ Role Added",
                    description=f"Successfully added **{role.name}** to category **{self.category_name}**\n" f"Prerequisites: {prereq_text}",
                    color=discord.Color.green(),
                )
            else:
                embed = discord.Embed(
                    title="❌ Addition Failed",
                    description=f"**{role.name}** is already in category **{self.category_name}** or category doesn't exist.",
                    color=discord.Color.red(),
                )

            await interaction.response.edit_message(embed=embed, view=self.callback_view)

        except Exception as e:
            embed = discord.Embed(title="❌ Error", description=f"Failed to add role: {str(e)}", color=discord.Color.red())
            await interaction.response.edit_message(embed=embed, view=self.callback_view)
