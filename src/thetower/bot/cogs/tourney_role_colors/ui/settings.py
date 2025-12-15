"""
Settings management views for the Tourney Role Colors cog.

This module contains:
- Settings views for configuring color categories and roles
- Admin interfaces for server owners
"""

from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import ui

from thetower.bot.basecog import BaseCog


class TourneyRoleColorsSettingsView(ui.View):
    """Main settings view for Tourney Role Colors cog."""

    def __init__(self, guild_id: int, cog: BaseCog):
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
                    role = interaction.guild.get_role(int(role_id))
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

                # Format prerequisites display
                prereq_parts = []

                # Direct prerequisites
                direct_prereqs = role_config.get("additional_prerequisites", [])
                if direct_prereqs:
                    # Convert role:RoleName to just RoleName
                    direct_names = []
                    for prereq in direct_prereqs:
                        if prereq.startswith("role:"):
                            direct_names.append(prereq[5:])  # Remove "role:" prefix
                        else:
                            direct_names.append(prereq)
                    prereq_parts.extend(direct_names)

                # Inherited prerequisites
                inherits = role_config.get("inherits_from")
                if inherits:
                    inherit_role = interaction.guild.get_role(inherits)
                    inherit_name = inherit_role.name if inherit_role else f"Role {inherits}"
                    prereq_parts.insert(0, f"[{inherit_name}]")  # Show inherited role in brackets at start

                prereq_text = ", ".join(prereq_parts) if prereq_parts else "None"
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
        view = TourneyRoleColorsSettingsView(self.guild_id, self.cog)
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
        self.add_item(RemoveRoleButton(cog, guild_id, category_name))
        self.add_item(EditRoleButton(cog, guild_id, category_name))
        self.add_item(RemoveCategoryButton(cog, guild_id, category_name))
        self.add_item(BackToCategoriesButton(cog, guild_id))


class SelectRoleView(ui.View):
    """View for selecting a role to add to a category."""

    def __init__(self, cog: BaseCog, guild_id: int, category_name: str, callback_view: ui.View):
        super().__init__(timeout=300)  # 5 minute timeout
        self.cog = cog
        self.guild_id = guild_id
        self.category_name = category_name
        self.callback_view = callback_view

        # Role selector
        self.role_select = ui.RoleSelect(placeholder="Select a role to add...", min_values=1, max_values=1, custom_id="role_select")
        self.role_select.callback = self.role_selected
        self.add_item(self.role_select)

        # Cancel button
        cancel_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.gray, custom_id="cancel")
        cancel_btn.callback = self.cancel
        self.add_item(cancel_btn)

    async def role_selected(self, interaction: discord.Interaction):
        """Handle role selection."""
        selected_role = self.role_select.values[0]

        # Check if role is already in this category
        categories = self.cog.core.get_color_categories(self.guild_id)
        category_data = categories.get(self.category_name, {})
        existing_roles = category_data.get("roles", {})

        if selected_role.id in existing_roles:
            embed = discord.Embed(
                title="❌ Role Already Added",
                description=f"**{selected_role.name}** is already in the **{self.category_name}** category.",
                color=discord.Color.red(),
            )
            await interaction.response.edit_message(embed=embed, view=self.callback_view)
            return

        # Move to prerequisite selection
        view = SelectPrerequisitesView(self.cog, self.guild_id, self.category_name, selected_role, self.callback_view)

        inheritance_text = ""
        if view.suggested_inheritance:
            inheritance_text = f"\n\n**🔗 Automatic Inheritance:** This role will automatically inherit prerequisites from **{view.suggested_inheritance.name}** (the highest existing role in this category below it in the hierarchy)."

        embed = discord.Embed(
            title="🎨 Select Prerequisites",
            description=f"Selected role: **{selected_role.name}**\n\n"
            f"Choose prerequisite roles that users must have before they can select **{selected_role.name}**.\n"
            "Users can only select roles that are below their current highest role in the hierarchy.\n\n"
            "**Leave empty if no additional prerequisites are required.**"
            f"{inheritance_text}",
            color=discord.Color.blue(),
        )

        await interaction.response.edit_message(embed=embed, view=view)

    async def cancel(self, interaction: discord.Interaction):
        """Cancel the role addition."""
        embed = discord.Embed(
            title="❌ Cancelled",
            description="Role addition cancelled.",
            color=discord.Color.gray(),
        )
        await interaction.response.edit_message(embed=embed, view=self.callback_view)


class SelectPrerequisitesView(ui.View):
    """View for selecting prerequisite roles."""

    def __init__(self, cog: BaseCog, guild_id: int, category_name: str, selected_role: discord.Role, callback_view: ui.View):
        super().__init__(timeout=300)  # 5 minute timeout
        self.cog = cog
        self.guild_id = guild_id
        self.category_name = category_name
        self.selected_role = selected_role
        self.callback_view = callback_view
        self.suggested_inheritance = None

        # Get eligible prerequisite roles (roles below the selected role in hierarchy)
        guild = cog.bot.get_guild(guild_id)
        eligible_roles = []

        # Sort roles by position (higher position = more powerful)
        sorted_roles = sorted(guild.roles, key=lambda r: r.position, reverse=True)

        # Find selected role position
        selected_position = selected_role.position

        # Get existing color role IDs to prevent circular references
        existing_color_role_ids = self.cog.core.get_all_color_role_ids(guild_id)

        # Get roles below the selected role
        for role in sorted_roles:
            if (
                role.position < selected_position
                and not role.is_default()
                and not role.managed
                and role.id != selected_role.id  # Explicitly exclude the selected role
                and role.id not in existing_color_role_ids
            ):  # Exclude existing color roles to prevent cycles
                eligible_roles.append(role)

        # Check for automatic inheritance suggestion
        categories = self.cog.core.get_color_categories(guild_id)
        category_data = categories.get(self.category_name, {})
        existing_role_ids = set(int(rid) for rid in category_data.get("roles", {}).keys())

        # Find the highest existing role in this category that's below the selected role
        suggested_inherit_role = None
        for role in sorted_roles:
            if role.id in existing_role_ids and role.position < selected_position:
                suggested_inherit_role = role
                break  # First one found is the highest due to sorting

        if suggested_inherit_role:
            self.suggested_inheritance = suggested_inherit_role

        # Prerequisite role selector (multi-select)
        if eligible_roles:
            self.prereq_select = ui.RoleSelect(
                placeholder="Select prerequisite roles (optional)...",
                min_values=0,
                max_values=min(len(eligible_roles), 25),  # Discord limit is 25
                custom_id=f"prereq_select_{selected_role.id}",
                default_values=[],
            )
            # Pre-populate with eligible roles only
            self.add_item(self.prereq_select)
            self.prereq_select.callback = self.prereq_selected
        else:
            # No eligible roles, add a note
            self.prereq_select = None

        # Confirm button
        confirm_btn = ui.Button(label="✅ Confirm", style=discord.ButtonStyle.success, custom_id="confirm")
        confirm_btn.callback = self.confirm
        self.add_item(confirm_btn)

        # Back button
        back_btn = ui.Button(label="⬅️ Back", style=discord.ButtonStyle.gray, custom_id="back")
        back_btn.callback = self.back
        self.add_item(back_btn)

    async def prereq_selected(self, interaction: discord.Interaction):
        """Handle prerequisite role selection (defer to prevent interaction failure)."""
        await interaction.response.defer()

    async def confirm(self, interaction: discord.Interaction):
        """Confirm the role addition with selected prerequisites."""
        try:
            prereq_roles = []
            if self.prereq_select and self.prereq_select.values:
                prereq_roles = [r for r in self.prereq_select.values if r.id != self.selected_role.id]
                self.cog.logger.info(f"Selected prereq roles: {[r.name for r in prereq_roles]}")

            # Convert to prerequisite format (role:role_name)
            prereq_list = [f"role:{role.name}" for role in prereq_roles]

            self.cog.logger.info(f"Adding role {self.selected_role.name} with prereqs: {prereq_list}")

            # Add the role
            success = await self.cog.core.add_color_role(self.guild_id, self.category_name, self.selected_role.id, prereq_list)

            if success:
                # Set inheritance if suggested
                if self.suggested_inheritance:
                    self.cog.logger.info(f"Setting inheritance for {self.selected_role.name} from {self.suggested_inheritance.name}")
                    inherit_success = await self.cog.core.set_role_inheritance(
                        self.guild_id, self.category_name, self.selected_role.id, self.suggested_inheritance.id
                    )
                    if not inherit_success:
                        # Log warning but don't fail the whole operation
                        self.cog.logger.warning(f"Failed to set inheritance for role {self.selected_role.id} from {self.suggested_inheritance.id}")

                prereq_text = ", ".join([role.name for role in prereq_roles]) if prereq_roles else "None"
                inheritance_note = f" (inherits from {self.suggested_inheritance.name})" if self.suggested_inheritance else ""

                embed = discord.Embed(
                    title="✅ Role Added",
                    description=f"Successfully added **{self.selected_role.name}** to category **{self.category_name}**\n"
                    f"Prerequisites: {prereq_text}{inheritance_note}",
                    color=discord.Color.green(),
                )
                await interaction.response.edit_message(embed=embed, view=RoleAddedView(self.callback_view))
            else:
                embed = discord.Embed(
                    title="❌ Addition Failed",
                    description=f"Failed to add **{self.selected_role.name}** to category **{self.category_name}**.",
                    color=discord.Color.red(),
                )
                await interaction.response.edit_message(embed=embed, view=self.callback_view)
        except Exception as e:
            self.cog.logger.error(f"Error in confirm method: {e}", exc_info=True)
            embed = discord.Embed(
                title="❌ Error",
                description="An error occurred while adding the role. Please try again.",
                color=discord.Color.red(),
            )
            await interaction.response.edit_message(embed=embed, view=self.callback_view)

    async def back(self, interaction: discord.Interaction):
        """Go back to role selection."""
        view = SelectRoleView(self.cog, self.guild_id, self.category_name, self.callback_view)
        embed = discord.Embed(
            title="🎨 Select Role to Add",
            description=f"Choose a role to add to the **{self.category_name}** category.\n\n"
            "The role will be available for users to select as a color role.",
            color=discord.Color.blue(),
        )

        await interaction.response.edit_message(embed=embed, view=view)


class RoleAddedView(ui.View):
    """View shown after successfully adding a role."""

    def __init__(self, callback_view: ui.View):
        super().__init__(timeout=300)  # 5 minute timeout
        self.callback_view = callback_view

        # Back to category button
        back_btn = ui.Button(label="⬅️ Back to Category", style=discord.ButtonStyle.primary, custom_id="back_to_category")
        back_btn.callback = self.back_to_category
        self.add_item(back_btn)

    async def back_to_category(self, interaction: discord.Interaction):
        """Go back to the category view."""
        embed = discord.Embed(
            title="🎨 Category Management",
            description="Manage roles in this category.",
            color=discord.Color.blue(),
        )
        await interaction.response.edit_message(embed=embed, view=self.callback_view)


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

        # Start with role selection
        view = SelectRoleView(self.cog, self.guild_id, self.category_name, callback_view)
        embed = discord.Embed(
            title="🎨 Select Role to Add",
            description=f"Choose a role to add to the **{self.category_name}** category.\n\n"
            "The role will be available for users to select as a color role.",
            color=discord.Color.blue(),
        )

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class RemoveRoleButton(ui.Button):
    """Button to remove a role from a category."""

    def __init__(self, cog: BaseCog, guild_id: int, category_name: str):
        super().__init__(label="🗑️ Remove Role", style=discord.ButtonStyle.danger)
        self.cog = cog
        self.guild_id = guild_id
        self.category_name = category_name

    async def callback(self, interaction: discord.Interaction):
        """Remove a role from this category."""
        categories = self.cog.core.get_color_categories(self.guild_id)
        category_data = categories.get(self.category_name, {})
        roles = category_data.get("roles", {})

        if not roles:
            embed = discord.Embed(
                title="❌ No Roles to Remove",
                description=f"There are no roles configured in the **{self.category_name}** category.",
                color=discord.Color.red(),
            )
            await interaction.response.edit_message(embed=embed, view=CategoryDetailView(self.cog, self.guild_id, self.category_name))
            return

        # Show role selection for removal
        view = SelectRoleToRemoveView(self.cog, self.guild_id, self.category_name, roles)
        embed = discord.Embed(
            title="🗑️ Select Role to Remove",
            description=f"Choose a role to remove from the **{self.category_name}** category.",
            color=discord.Color.orange(),
        )

        await interaction.response.edit_message(embed=embed, view=view)


class SelectRoleToRemoveView(ui.View):
    """View for selecting a role to remove from a category."""

    def __init__(self, cog: BaseCog, guild_id: int, category_name: str, roles: Dict[str, Any]):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.category_name = category_name

        # Create role select dropdown
        options = []
        for role_id, role_config in roles.items():
            role = cog.bot.get_guild(guild_id).get_role(int(role_id))
            role_name = role.name if role else f"Unknown Role ({role_id})"
            options.append(discord.SelectOption(label=role_name, value=role_id))

        if options:
            self.role_select = ui.Select(placeholder="Select a role to remove...", options=options, custom_id="remove_role_select")
            self.role_select.callback = self.role_selected
            self.add_item(self.role_select)

        # Back button
        back_btn = ui.Button(label="⬅️ Back", style=discord.ButtonStyle.gray, custom_id="back")
        back_btn.callback = self.back
        self.add_item(back_btn)

    async def role_selected(self, interaction: discord.Interaction):
        """Handle role selection for removal."""
        selected_role_id = self.role_select.values[0]
        role = interaction.guild.get_role(int(selected_role_id))
        role_name = role.name if role else f"Unknown Role ({selected_role_id})"

        # Check for inheritance dependencies
        inheriting_roles = self.cog.core.get_roles_inheriting_from(self.guild_id, int(selected_role_id))

        if inheriting_roles:
            # Show warning about inheritance
            inheriting_names = []
            for cat_name, inherit_role_id in inheriting_roles:
                inherit_role = interaction.guild.get_role(inherit_role_id)
                inherit_name = inherit_role.name if inherit_role else f"Role {inherit_role_id}"
                inheriting_names.append(f"**{inherit_name}**")

            view = ConfirmRemoveRoleView(self.cog, self.guild_id, self.category_name, int(selected_role_id), inheriting_roles)
            embed = discord.Embed(
                title="⚠️ Warning: Breaking Inheritance",
                description=f"**{role_name}** is currently inherited by:\n" + "\n".join(f"• {name}" for name in inheriting_names) + "\n\n"
                f"If you remove **{role_name}**, these prerequisites will no longer be followed unless you manually add them back in.",
                color=discord.Color.orange(),
            )
        else:
            # No inheritance dependencies, show direct confirmation
            view = ConfirmRemoveRoleView(self.cog, self.guild_id, self.category_name, int(selected_role_id), [])
            embed = discord.Embed(
                title="🗑️ Confirm Role Removal",
                description=f"Are you sure you want to remove **{role_name}** from the **{self.category_name}** category?",
                color=discord.Color.red(),
            )

        await interaction.response.edit_message(embed=embed, view=view)

    async def back(self, interaction: discord.Interaction):
        """Go back to category detail view."""
        view = CategoryDetailView(self.cog, self.guild_id, self.category_name)
        embed = discord.Embed(title=f"🎨 {self.category_name} Category", color=discord.Color.blue())
        await interaction.response.edit_message(embed=embed, view=view)


class ConfirmRemoveRoleView(ui.View):
    """View for confirming role removal with inheritance warning."""

    def __init__(self, cog: BaseCog, guild_id: int, category_name: str, role_id: int, inheriting_roles: List[Tuple[str, int]]):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.category_name = category_name
        self.role_id = role_id
        self.inheriting_roles = inheriting_roles

        # Confirm button
        confirm_btn = ui.Button(label="🗑️ Remove Role", style=discord.ButtonStyle.danger, custom_id="confirm_remove")
        confirm_btn.callback = self.confirm_remove
        self.add_item(confirm_btn)

        # Cancel button
        cancel_btn = ui.Button(label="❌ Cancel", style=discord.ButtonStyle.gray, custom_id="cancel_remove")
        cancel_btn.callback = self.cancel_remove
        self.add_item(cancel_btn)

    async def confirm_remove(self, interaction: discord.Interaction):
        """Confirm and perform the role removal."""
        success = await self.cog.core.remove_color_role_from_category(self.guild_id, self.category_name, self.role_id)

        if success:
            role = interaction.guild.get_role(self.role_id)
            role_name = role.name if role else f"Role {self.role_id}"

            embed = discord.Embed(
                title="✅ Role Removed",
                description=f"Successfully removed **{role_name}** from category **{self.category_name}**.",
                color=discord.Color.green(),
            )
        else:
            embed = discord.Embed(
                title="❌ Removal Failed",
                description="Failed to remove the role. It may no longer exist or the category may have been modified.",
                color=discord.Color.red(),
            )

        view = CategoryDetailView(self.cog, self.guild_id, self.category_name)
        await interaction.response.edit_message(embed=embed, view=view)

    async def cancel_remove(self, interaction: discord.Interaction):
        """Cancel the removal and go back."""
        view = CategoryDetailView(self.cog, self.guild_id, self.category_name)
        embed = discord.Embed(title=f"🎨 {self.category_name} Category", color=discord.Color.blue())
        await interaction.response.edit_message(embed=embed, view=view)

        await interaction.response.edit_message(embed=embed, view=view)


class EditRoleButton(ui.Button):
    """Button to edit a role in a category."""

    def __init__(self, cog: BaseCog, guild_id: int, category_name: str):
        super().__init__(label="✏️ Edit Role", style=discord.ButtonStyle.primary)
        self.cog = cog
        self.guild_id = guild_id
        self.category_name = category_name

    async def callback(self, interaction: discord.Interaction):
        """Edit a role in this category."""
        categories = self.cog.core.get_color_categories(self.guild_id)
        category_data = categories.get(self.category_name, {})
        roles = category_data.get("roles", {})

        if not roles:
            embed = discord.Embed(
                title="❌ No Roles to Edit",
                description=f"There are no roles configured in the **{self.category_name}** category.",
                color=discord.Color.red(),
            )
            await interaction.response.edit_message(embed=embed, view=CategoryDetailView(self.cog, self.guild_id, self.category_name))
            return

        # Show role selection for editing
        view = SelectRoleToEditView(self.cog, self.guild_id, self.category_name, roles)
        embed = discord.Embed(
            title="✏️ Select Role to Edit",
            description=f"Choose a role to edit in the **{self.category_name}** category.",
            color=discord.Color.blue(),
        )

        await interaction.response.edit_message(embed=embed, view=view)


class SelectRoleToEditView(ui.View):
    """View for selecting a role to edit in a category."""

    def __init__(self, cog: BaseCog, guild_id: int, category_name: str, roles: Dict[str, Any]):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.category_name = category_name

        # Create role select dropdown
        options = []
        for role_id, role_config in roles.items():
            role = cog.bot.get_guild(guild_id).get_role(int(role_id))
            role_name = role.name if role else f"Unknown Role ({role_id})"
            options.append(discord.SelectOption(label=role_name, value=role_id))

        if options:
            self.role_select = ui.Select(placeholder="Select a role to edit...", options=options, custom_id="edit_role_select")
            self.role_select.callback = self.role_selected
            self.add_item(self.role_select)

        # Back button
        back_btn = ui.Button(label="⬅️ Back", style=discord.ButtonStyle.gray, custom_id="back")
        back_btn.callback = self.back
        self.add_item(back_btn)

    async def role_selected(self, interaction: discord.Interaction):
        """Handle role selection for editing."""
        selected_role_id = self.role_select.values[0]
        role = interaction.guild.get_role(int(selected_role_id))
        role_name = role.name if role else f"Unknown Role ({selected_role_id})"

        # Get current role configuration
        categories = self.cog.core.get_color_categories(self.guild_id)
        category_data = categories.get(self.category_name, {})
        role_config = category_data.get("roles", {}).get(selected_role_id, {})
        current_prereqs = role_config.get("additional_prerequisites", [])

        # Start the edit wizard (same as add wizard but prepopulated)
        view = EditRoleWizardView(self.cog, self.guild_id, self.category_name, int(selected_role_id), current_prereqs)
        embed = discord.Embed(
            title="✏️ Edit Role",
            description=f"Editing **{role_name}** in category **{self.category_name}**\n\n" "You can change the role and/or its prerequisites.",
            color=discord.Color.blue(),
        )

        await interaction.response.edit_message(embed=embed, view=view)

    async def back(self, interaction: discord.Interaction):
        """Go back to category detail view."""
        view = CategoryDetailView(self.cog, self.guild_id, self.category_name)
        embed = discord.Embed(title=f"🎨 {self.category_name} Category", color=discord.Color.blue())
        await interaction.response.edit_message(embed=embed, view=view)


class EditRoleWizardView(ui.View):
    """Wizard view for editing a role (prepopulated version of add wizard)."""

    def __init__(self, cog: BaseCog, guild_id: int, category_name: str, current_role_id: int, current_prereqs: List[str]):
        super().__init__(timeout=600)
        self.cog = cog
        self.guild_id = guild_id
        self.category_name = category_name
        self.current_role_id = current_role_id
        self.current_prereqs = current_prereqs
        self.selected_role = None
        self.selected_prereqs = current_prereqs.copy()

        # Step 1: Role selection (prepopulated)
        self.current_step = "role"
        self.setup_role_step()

    def setup_role_step(self):
        """Setup the role selection step."""
        self.clear_items()

        # Get available roles (exclude already used roles)
        guild = self.cog.bot.get_guild(self.guild_id)
        existing_color_role_ids = self.cog.core.get_all_color_role_ids(self.guild_id)

        available_roles = []
        for role in guild.roles:
            if (
                not role.is_default() and not role.managed and (role.id not in existing_color_role_ids or role.id == self.current_role_id)
            ):  # Allow current role
                available_roles.append(role)

        if available_roles:
            options = []
            for role in available_roles:
                # Pre-select current role
                default = role.id == self.current_role_id
                options.append(discord.SelectOption(label=role.name, value=str(role.id), default=default))

            self.role_select = ui.Select(placeholder="Select the role...", options=options[:25], custom_id="edit_role_select")  # Discord limit
            self.role_select.callback = self.role_selected
            self.add_item(self.role_select)

        # Next button
        next_btn = ui.Button(label="Next: Prerequisites", style=discord.ButtonStyle.primary, custom_id="next_to_prereqs")
        next_btn.callback = self.next_to_prereqs
        self.add_item(next_btn)

        # Cancel button
        cancel_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.gray, custom_id="cancel_edit")
        cancel_btn.callback = self.cancel_edit
        self.add_item(cancel_btn)

    def setup_prereq_step(self):
        """Setup the prerequisite selection step."""
        self.clear_items()
        self.current_step = "prereqs"

        # Get eligible prerequisite roles (same category + non-category roles)
        guild = self.cog.bot.get_guild(self.guild_id)
        eligible_roles = []

        # Get all roles in this category (for inheritance)
        categories = self.cog.core.get_color_categories(self.guild_id)
        category_data = categories.get(self.category_name, {})
        category_role_ids = set(int(rid) for rid in category_data.get("roles", {}).keys())

        # Get existing color role IDs to exclude
        existing_color_role_ids = self.cog.core.get_all_color_role_ids(self.guild_id)

        for role in guild.roles:
            if (
                not role.is_default() and not role.managed and (role.id in category_role_ids or role.id not in existing_color_role_ids)
            ):  # Same category OR non-category
                eligible_roles.append(role)

        # Create options with inheritance info
        options = []
        for role in eligible_roles[:24]:  # Leave room for inheritance display
            # Check if this role has prerequisites that would be inherited
            inherited_prereqs = []
            if str(role.id) in category_data.get("roles", {}):
                inherited_prereqs = self.cog.core.get_all_prerequisites(self.guild_id, role.id)

            # Pre-select current prerequisites
            default = any(prereq.endswith(f":{role.name}") for prereq in self.selected_prereqs)

            label = role.name
            if inherited_prereqs:
                inherited_names = []
                for prereq in inherited_prereqs:
                    if prereq.startswith("role:"):
                        inherited_names.append(prereq[5:])  # Remove "role:" prefix
                if inherited_names:
                    label += f" (+inherits: {', '.join(inherited_names[:3])}"
                    if len(inherited_names) > 3:
                        label += f" +{len(inherited_names) - 3} more"
                    label += ")"

            if len(label) > 100:  # Discord limit
                label = label[:97] + "..."

            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(role.id),
                    description=f"Inherits {len(inherited_prereqs)} prerequisites" if inherited_prereqs else None,
                    default=default,
                )
            )

        if options:
            self.prereq_select = ui.Select(
                placeholder="Select prerequisite roles...", options=options, max_values=len(options), custom_id="edit_prereq_select"
            )
            self.prereq_select.callback = self.prereq_selected
            self.add_item(self.prereq_select)

        # Save button
        save_btn = ui.Button(label="💾 Save Changes", style=discord.ButtonStyle.success, custom_id="save_edit")
        save_btn.callback = self.save_edit
        self.add_item(save_btn)

        # Back button
        back_btn = ui.Button(label="⬅️ Back", style=discord.ButtonStyle.gray, custom_id="back_to_role")
        back_btn.callback = self.back_to_role
        self.add_item(back_btn)

        # Cancel button
        cancel_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.gray, custom_id="cancel_edit")
        cancel_btn.callback = self.cancel_edit
        self.add_item(cancel_btn)

    async def role_selected(self, interaction: discord.Interaction):
        """Handle role selection."""
        selected_role_id = int(self.role_select.values[0])
        self.selected_role = self.cog.bot.get_guild(self.guild_id).get_role(selected_role_id)

        # Update embed to show selected role
        embed = interaction.message.embeds[0]
        embed.description = f"Editing role in category **{self.category_name}**\n\n**Selected Role:** {self.selected_role.name}"

        await interaction.response.edit_message(embed=embed, view=self)

    async def next_to_prereqs(self, interaction: discord.Interaction):
        """Move to prerequisite selection step."""
        if not self.selected_role:
            # Find selected role from dropdown
            if self.role_select.values:
                selected_role_id = int(self.role_select.values[0])
                self.selected_role = self.cog.bot.get_guild(self.guild_id).get_role(selected_role_id)

        if not self.selected_role:
            embed = discord.Embed(
                title="❌ No Role Selected",
                description="Please select a role to edit.",
                color=discord.Color.red(),
            )
            await interaction.response.edit_message(embed=embed, view=self)
            return

        self.setup_prereq_step()
        embed = discord.Embed(
            title="✏️ Edit Prerequisites",
            description=f"Editing **{self.selected_role.name}** in category **{self.category_name}**\n\n"
            "Select which roles are required as prerequisites. Roles from the same category will show inheritance information.",
            color=discord.Color.blue(),
        )

        await interaction.response.edit_message(embed=embed, view=self)

    async def prereq_selected(self, interaction: discord.Interaction):
        """Handle prerequisite selection."""
        selected_prereq_ids = [int(v) for v in self.prereq_select.values]

        # Convert to prerequisite format
        self.selected_prereqs = []
        for prereq_id in selected_prereq_ids:
            prereq_role = self.cog.bot.get_guild(self.guild_id).get_role(prereq_id)
            if prereq_role:
                self.selected_prereqs.append(f"role:{prereq_role.name}")

        # Update embed to show selected prerequisites
        embed = interaction.message.embeds[0]
        prereq_text = ", ".join([p[5:] for p in self.selected_prereqs]) if self.selected_prereqs else "None"
        embed.description = f"Editing **{self.selected_role.name}** in category **{self.category_name}**\n\n**Selected Prerequisites:** {prereq_text}"

        await interaction.response.edit_message(embed=embed, view=self)

    async def save_edit(self, interaction: discord.Interaction):
        """Save the role edits."""
        try:
            # Get final selections
            if not self.selected_role:
                if self.role_select.values:
                    selected_role_id = int(self.role_select.values[0])
                    self.selected_role = self.cog.bot.get_guild(self.guild_id).get_role(selected_role_id)

            if self.current_step == "prereqs" and self.prereq_select.values:
                selected_prereq_ids = [int(v) for v in self.prereq_select.values]
                self.selected_prereqs = []
                for prereq_id in selected_prereq_ids:
                    prereq_role = self.cog.bot.get_guild(self.guild_id).get_role(prereq_id)
                    if prereq_role:
                        self.selected_prereqs.append(f"role:{prereq_role.name}")

            # Check if role changed
            role_changed = self.selected_role.id != self.current_role_id

            if role_changed:
                # Remove old role and add new one
                await self.cog.core.remove_color_role_from_category(self.guild_id, self.category_name, self.current_role_id)
                success = await self.cog.core.add_color_role(self.guild_id, self.category_name, self.selected_role.id, self.selected_prereqs)
            else:
                # Update existing role's prerequisites
                categories = self.cog.core.get_color_categories(self.guild_id)
                if self.category_name in categories:
                    category = categories[self.category_name]
                    if str(self.current_role_id) in category["roles"]:
                        category["roles"][str(self.current_role_id)]["additional_prerequisites"] = self.selected_prereqs
                        self.cog.core.set_color_categories(self.guild_id, categories)
                        success = True
                    else:
                        success = False
                else:
                    success = False

            if success:
                embed = discord.Embed(
                    title="✅ Role Updated",
                    description=f"Successfully updated **{self.selected_role.name}** in category **{self.category_name}**.",
                    color=discord.Color.green(),
                )
            else:
                embed = discord.Embed(
                    title="❌ Update Failed",
                    description="Failed to update the role. It may no longer exist or the category may have been modified.",
                    color=discord.Color.red(),
                )

            view = CategoryDetailView(self.cog, self.guild_id, self.category_name)
            await interaction.response.edit_message(embed=embed, view=view)

        except Exception as e:
            self.cog.logger.error(f"Error in save_edit: {e}", exc_info=True)
            embed = discord.Embed(
                title="❌ Error",
                description="An error occurred while saving the role changes.",
                color=discord.Color.red(),
            )
            view = CategoryDetailView(self.cog, self.guild_id, self.category_name)
            await interaction.response.edit_message(embed=embed, view=view)

    async def back_to_role(self, interaction: discord.Interaction):
        """Go back to role selection step."""
        self.setup_role_step()
        embed = discord.Embed(
            title="✏️ Edit Role",
            description=f"Editing role in category **{self.category_name}**\n\nSelect the role to edit.",
            color=discord.Color.blue(),
        )

        await interaction.response.edit_message(embed=embed, view=self)

    async def cancel_edit(self, interaction: discord.Interaction):
        """Cancel the edit and go back."""
        view = CategoryDetailView(self.cog, self.guild_id, self.category_name)
        embed = discord.Embed(title=f"🎨 {self.category_name} Category", color=discord.Color.blue())
        await interaction.response.edit_message(embed=embed, view=view)


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
                    view = TourneyRoleColorsSettingsView(self.guild_id, self.cog)
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
                view = TourneyRoleColorsSettingsView(self.guild_id, self.cog)
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
                    view = TourneyRoleColorsSettingsView(self.guild_id, self.cog)
                    embed = await view.create_embed()

                await interaction.response.edit_message(embed=embed, view=view)

        except Exception as e:
            embed = discord.Embed(title="❌ Error", description=f"Failed to create category: {str(e)}", color=discord.Color.red())

            if self.callback_view:
                view = self.callback_view
            else:
                view = TourneyRoleColorsSettingsView(self.guild_id, self.cog)
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
