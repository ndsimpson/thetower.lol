"""User-facing role selection views for Optional Roles cog."""

from typing import Dict, List

import discord
from discord import ui


class RoleSelectionView(ui.View):
    """Main view for users to select their optional roles."""

    def __init__(self, cog, interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.cog = cog
        self.interaction = interaction
        self.guild = interaction.guild
        self.member = interaction.user

        # Get user's current roles
        user_role_ids = [role.id for role in self.member.roles]

        # Get current managed roles
        self.current_role_ids = self.cog.get_user_managed_roles(self.guild.id, user_role_ids)

        # Get eligible roles grouped by category
        self.eligible_roles = self.cog.get_eligible_roles(self.guild.id, user_role_ids)

        # Group by category
        self.roles_by_category: Dict[str, List[Dict]] = {}
        for role_config in self.eligible_roles:
            category = role_config["category"]
            if category not in self.roles_by_category:
                self.roles_by_category[category] = []
            self.roles_by_category[category].append(role_config)

        # Add category buttons (sorted alphabetically)
        sorted_categories = sorted(self.roles_by_category.keys())
        for idx, category_name in enumerate(sorted_categories):
            # Check if user has any roles in this category
            category_roles = self.roles_by_category[category_name]
            has_role_in_category = any(r["role_id"] in self.current_role_ids for r in category_roles)

            # Use different style if user has a role in this category
            style = discord.ButtonStyle.success if has_role_in_category else discord.ButtonStyle.primary

            btn = ui.Button(label=category_name, style=style, row=idx // 5)
            btn.callback = self._create_category_callback(category_name)
            self.add_item(btn)

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

        # Rebuild current roles
        user_role_ids = [role.id for role in self.member.roles]
        self.current_role_ids = self.cog.get_user_managed_roles(self.guild.id, user_role_ids)

        # Rebuild eligible roles
        self.eligible_roles = self.cog.get_eligible_roles(self.guild.id, user_role_ids)

        # Rebuild roles by category
        self.roles_by_category = {}
        for role_config in self.eligible_roles:
            category = role_config["category"]
            if category not in self.roles_by_category:
                self.roles_by_category[category] = []
            self.roles_by_category[category].append(role_config)

        # Update category button styles
        self.clear_items()
        sorted_categories = sorted(self.roles_by_category.keys())
        for idx, category_name in enumerate(sorted_categories):
            category_roles = self.roles_by_category[category_name]
            has_role_in_category = any(r["role_id"] in self.current_role_ids for r in category_roles)
            style = discord.ButtonStyle.success if has_role_in_category else discord.ButtonStyle.primary

            btn = ui.Button(label=category_name, style=style, row=idx // 5)
            btn.callback = self._create_category_callback(category_name)
            self.add_item(btn)

        content = self._build_main_message()
        await interaction.response.edit_message(content=content, view=self)

    def _build_main_message(self) -> str:
        """Build the main selection message."""
        if not self.roles_by_category:
            return "**No Optional Roles Available**\n\nThere are no optional roles available for you at this time."

        # Build current roles list
        current_roles_text = ""
        if self.current_role_ids:
            role_objs = [self.guild.get_role(rid) for rid in self.current_role_ids]
            role_objs = [r for r in role_objs if r is not None]
            if role_objs:
                role_names = "\n".join(f"• {role.name}" for role in role_objs)
                current_roles_text = f"\n\n**Your Current Optional Roles:**\n{role_names}"

        return (
            f"**Optional Roles**\n\n"
            f"Select a category below to view and manage your optional roles.{current_roles_text}\n\n"
            f"💡 Categories marked green have roles you've already selected."
        )

    async def on_category_selected(self, interaction: discord.Interaction, category_name: str):
        """Handle category button click."""
        category_roles = self.roles_by_category.get(category_name, [])
        if not category_roles:
            await interaction.response.send_message("No roles available in this category.", ephemeral=True)
            return

        # Get category config to determine selection mode
        category_config = self.cog.get_category_config(self.guild.id, category_name)
        selection_mode = category_config.get("selection_mode", "single") if category_config else "single"

        # Show category view
        category_view = CategoryRoleView(self.cog, interaction, category_name, category_roles, selection_mode, self)
        await category_view.show()


class CategoryRoleView(ui.View):
    """View for selecting roles within a specific category."""

    def __init__(
        self, cog, interaction: discord.Interaction, category_name: str, roles: List[Dict], selection_mode: str, parent_view: RoleSelectionView
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.interaction = interaction
        self.guild = interaction.guild
        self.member = interaction.user
        self.category_name = category_name
        self.roles = roles
        self.selection_mode = selection_mode
        self.parent_view = parent_view

        # Get user's current roles in this category
        user_role_ids = [role.id for role in self.member.roles]
        self.current_role_ids = [r["role_id"] for r in roles if r["role_id"] in user_role_ids]

        # Add role buttons
        for idx, role_config in enumerate(self.roles):
            role_id = role_config["role_id"]
            role_obj = self.guild.get_role(role_id)
            if not role_obj:
                continue

            # Determine button style
            if role_id in self.current_role_ids:
                style = discord.ButtonStyle.success
                label = f"✓ {role_obj.name}"
            else:
                style = discord.ButtonStyle.secondary
                label = role_obj.name

            # Add emoji if configured
            emoji = role_config.get("emoji")

            btn = ui.Button(label=label, style=style, emoji=emoji, row=idx // 5)
            btn.callback = self._create_role_callback(role_config)
            self.add_item(btn)

        # Add back button
        back_btn = ui.Button(label="← Back", style=discord.ButtonStyle.primary, row=4)
        back_btn.callback = self.on_back
        self.add_item(back_btn)

        # Add clear all button if multi-select and user has roles
        if self.selection_mode == "multiple" and self.current_role_ids:
            clear_btn = ui.Button(label="Clear All", style=discord.ButtonStyle.danger, emoji="❌", row=4)
            clear_btn.callback = self.on_clear_all
            self.add_item(clear_btn)

    def _create_role_callback(self, role_config: Dict):
        """Create a callback for a specific role button."""

        async def callback(interaction: discord.Interaction):
            await self.on_role_selected(interaction, role_config)

        return callback

    async def show(self):
        """Display the category role view."""
        content = self._build_message()
        await self.interaction.response.edit_message(content=content, view=self)

    async def refresh(self, interaction: discord.Interaction):
        """Refresh the view after a role change."""
        # Refresh member
        self.member = await self.guild.fetch_member(self.member.id)
        user_role_ids = [role.id for role in self.member.roles]
        self.current_role_ids = [r["role_id"] for r in self.roles if r["role_id"] in user_role_ids]

        # Rebuild buttons
        self.clear_items()
        for idx, role_config in enumerate(self.roles):
            role_id = role_config["role_id"]
            role_obj = self.guild.get_role(role_id)
            if not role_obj:
                continue

            if role_id in self.current_role_ids:
                style = discord.ButtonStyle.success
                label = f"✓ {role_obj.name}"
            else:
                style = discord.ButtonStyle.secondary
                label = role_obj.name

            emoji = role_config.get("emoji")
            btn = ui.Button(label=label, style=style, emoji=emoji, row=idx // 5)
            btn.callback = self._create_role_callback(role_config)
            self.add_item(btn)

        # Add back button
        back_btn = ui.Button(label="← Back", style=discord.ButtonStyle.primary, row=4)
        back_btn.callback = self.on_back
        self.add_item(back_btn)

        # Add clear all button if applicable
        if self.selection_mode == "multiple" and self.current_role_ids:
            clear_btn = ui.Button(label="Clear All", style=discord.ButtonStyle.danger, emoji="❌", row=4)
            clear_btn.callback = self.on_clear_all
            self.add_item(clear_btn)

        content = self._build_message()
        await interaction.response.edit_message(content=content, view=self)

    def _build_message(self) -> str:
        """Build the category selection message."""
        mode_text = "multiple roles" if self.selection_mode == "multiple" else "one role"

        current_text = ""
        if self.current_role_ids:
            role_objs = [self.guild.get_role(rid) for rid in self.current_role_ids]
            role_objs = [r for r in role_objs if r is not None]
            if role_objs:
                role_names = ", ".join(r.name for r in role_objs)
                current_text = f"\n\n**Currently selected:** {role_names}"

        return f"**{self.category_name}**\n\nYou can select {mode_text} from this category.{current_text}\n\n" f"Click a role to toggle it on or off."

    async def on_role_selected(self, interaction: discord.Interaction, role_config: Dict):
        """Handle role selection."""
        role_id = role_config["role_id"]
        role_obj = self.guild.get_role(role_id)

        if not role_obj:
            await interaction.response.send_message("❌ This role no longer exists.", ephemeral=True)
            return

        try:
            # Check if user already has this role
            if role_id in self.current_role_ids:
                # Remove the role
                await self.member.remove_roles(role_obj, reason="User opted out of optional role")
                await interaction.response.send_message(f"✓ Removed **{role_obj.name}**", ephemeral=True, delete_after=3)
            else:
                # Add the role
                # If single-selection mode, remove other roles in category first
                if self.selection_mode == "single" and self.current_role_ids:
                    roles_to_remove = [self.guild.get_role(rid) for rid in self.current_role_ids]
                    roles_to_remove = [r for r in roles_to_remove if r is not None]
                    if roles_to_remove:
                        await self.member.remove_roles(*roles_to_remove, reason="Replacing with different optional role")

                await self.member.add_roles(role_obj, reason="User opted into optional role")
                await interaction.response.send_message(f"✓ Added **{role_obj.name}**", ephemeral=True, delete_after=3)

            # Refresh the view
            await self.refresh(interaction)

            # Also refresh parent view to update category button colors
            user_role_ids = [role.id for role in self.member.roles]
            self.parent_view.current_role_ids = self.cog.get_user_managed_roles(self.guild.id, user_role_ids)

        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to manage this role.", ephemeral=True)
        except Exception as e:
            self.cog.logger.error(f"Error toggling role {role_obj.name}: {e}", exc_info=True)
            await interaction.response.send_message("❌ An error occurred. Please try again.", ephemeral=True)

    async def on_clear_all(self, interaction: discord.Interaction):
        """Clear all roles in this category."""
        if not self.current_role_ids:
            await interaction.response.send_message("You don't have any roles to clear.", ephemeral=True)
            return

        try:
            roles_to_remove = [self.guild.get_role(rid) for rid in self.current_role_ids]
            roles_to_remove = [r for r in roles_to_remove if r is not None]

            if roles_to_remove:
                await self.member.remove_roles(*roles_to_remove, reason="User cleared all optional roles in category")
                role_names = ", ".join(r.name for r in roles_to_remove)
                await interaction.response.send_message(f"✓ Removed all roles: {role_names}", ephemeral=True, delete_after=5)
                await self.refresh(interaction)

                # Update parent view
                user_role_ids = [role.id for role in self.member.roles]
                self.parent_view.current_role_ids = self.cog.get_user_managed_roles(self.guild.id, user_role_ids)

        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to manage these roles.", ephemeral=True)
        except Exception as e:
            self.cog.logger.error(f"Error clearing roles: {e}", exc_info=True)
            await interaction.response.send_message("❌ An error occurred. Please try again.", ephemeral=True)

    async def on_back(self, interaction: discord.Interaction):
        """Return to main category view."""
        await self.parent_view.refresh(interaction)


class RoleSelectionButton(ui.Button):
    """Button that opens the role selection interface from player profiles."""

    def __init__(self, cog):
        super().__init__(
            label="Manage Optional Roles",
            style=discord.ButtonStyle.primary,
            emoji="⚙️",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        """Handle button click."""
        # Create and show the role selection view
        view = RoleSelectionView(self.cog, interaction)
        await view.show()


class PostVerificationRoleView(ui.View):
    """View for post-verification role selection within ephemeral verification message."""

    def __init__(self, cog, member: discord.Member, guild_id: int, eligible_roles: List[Dict]):
        super().__init__(timeout=300)  # 5 minute timeout for ephemeral message
        self.cog = cog
        self.member = member
        self.guild_id = guild_id
        self.eligible_roles = eligible_roles

        # Add buttons for each eligible role (up to 25)
        for idx, role_config in enumerate(eligible_roles[:25]):
            guild = cog.bot.get_guild(guild_id)
            if not guild:
                continue

            role_obj = guild.get_role(role_config["role_id"])
            if not role_obj:
                continue

            emoji = role_config.get("emoji")
            btn = ui.Button(
                label=role_obj.name,
                style=discord.ButtonStyle.secondary,
                emoji=emoji,
                custom_id=f"post_verify_role_{role_config['role_id']}",
                row=idx // 5,
            )
            btn.callback = self._create_role_callback(role_config)
            self.add_item(btn)

        # Add "Skip" button
        skip_btn = ui.Button(label="Skip for Now", style=discord.ButtonStyle.secondary, emoji="⏭️", row=4, custom_id="post_verify_skip")
        skip_btn.callback = self.on_skip
        self.add_item(skip_btn)

    def _create_role_callback(self, role_config: Dict):
        """Create callback for role button."""

        async def callback(interaction: discord.Interaction):
            await self.on_role_selected(interaction, role_config)

        return callback

    async def on_role_selected(self, interaction: discord.Interaction, role_config: Dict):
        """Handle role selection."""
        guild = self.cog.bot.get_guild(self.guild_id)
        if not guild:
            await interaction.response.send_message("❌ Server not found.", ephemeral=True)
            return

        member = guild.get_member(self.member.id)
        if not member:
            await interaction.response.send_message("❌ You are no longer in the server.", ephemeral=True)
            return

        role_obj = guild.get_role(role_config["role_id"])
        if not role_obj:
            await interaction.response.send_message("❌ Role not found.", ephemeral=True)
            return

        try:
            # Check if user already has this role
            if role_obj in member.roles:
                await interaction.response.send_message(f"✅ You already have the **{role_obj.name}** role!", ephemeral=True)
                return

            # If single-selection mode in this category, remove other roles
            category_name = role_config["category"]
            selection_mode = role_config["selection_mode"]

            if selection_mode == "single":
                # Get all roles in this category
                categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)
                category = next((cat for cat in categories if cat.get("name") == category_name), None)

                if category:
                    category_role_ids = [r["role_id"] for r in category.get("roles", [])]
                    current_category_roles = [r for r in member.roles if r.id in category_role_ids]

                    if current_category_roles:
                        await member.remove_roles(*current_category_roles, reason="Replacing with different optional role")

            # Add the selected role
            await member.add_roles(role_obj, reason="User opted into optional role (post-verification)")
            await interaction.response.send_message(f"✅ You've been given the **{role_obj.name}** role!", ephemeral=True)

            # Update button to show selection
            for child in self.children:
                if isinstance(child, ui.Button) and child.label == role_obj.name:
                    child.style = discord.ButtonStyle.success
                    child.label = f"✓ {role_obj.name}"
                    break

            await interaction.message.edit(view=self)

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to manage this role. Please contact a server administrator.", ephemeral=True
            )
        except Exception as e:
            self.cog.logger.error(f"Error assigning post-verification role: {e}", exc_info=True)
            await interaction.response.send_message("❌ An error occurred. Please try again or contact a server administrator.", ephemeral=True)

    async def on_skip(self, interaction: discord.Interaction):
        """Handle skip button."""
        await interaction.response.send_message("👍 You can manage your optional roles anytime via `/profile`!", ephemeral=True)
        # Disable all buttons
        for child in self.children:
            if isinstance(child, ui.Button):
                child.disabled = True
        await interaction.message.edit(view=self)
