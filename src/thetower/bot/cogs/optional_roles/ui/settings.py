"""Settings management views for Optional Roles cog."""

import discord
from discord import ui

from thetower.bot.ui.context import BaseSettingsView, SettingsViewContext


class OptionalRolesSettingsView(BaseSettingsView):
    """Settings view for Optional Roles cog."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(context)

        # Add main management buttons
        self.add_item(ManageCategoriesButton(self.cog, self.guild_id))

        # Add auto-enforcement toggle button
        self.add_item(AutoEnforceToggleButton(self.cog, self.guild_id))

        # Add removal notification toggle button
        self.add_item(RemovalNotifyToggleButton(self.cog, self.guild_id))

        # Add debounce configuration button (bot owner only)
        if context.is_bot_owner:
            self.add_item(ConfigureDebounceButton(self.cog))

        # Back button
        self.add_back_button()

    async def update_display(self, interaction: discord.Interaction):
        """Update the embed with current optional roles settings."""
        embed = discord.Embed(
            title="⚙️ Optional Roles Settings", description="Configure user-selectable roles with prerequisites", color=discord.Color.blue()
        )

        # Get current categories
        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)
        sorted_categories = sorted(categories, key=lambda c: c.get("name", "").lower())

        if sorted_categories:
            category_info = []
            for cat in sorted_categories:
                roles_count = len(cat.get("roles", []))
                mode = cat.get("selection_mode", "single")
                mode_emoji = "1️⃣" if mode == "single" else "🔢"
                category_info.append(f"{mode_emoji} **{cat.get('name')}**: {roles_count} roles")

            embed.add_field(name=f"Categories ({len(sorted_categories)})", value="\n".join(category_info[:10]), inline=False)
        else:
            embed.add_field(name="Categories", value="No categories configured. Click 'Manage Categories' to get started.", inline=False)

        # Show auto-enforcement status
        auto_enforce = self.cog.get_setting("auto_enforce_prerequisites", True, guild_id=self.guild_id)
        enforce_status = "✅ Enabled" if auto_enforce else "❌ Disabled"
        embed.add_field(name="Auto-Removal", value=enforce_status, inline=True)

        # Show removal notification status
        notify_removal = self.cog.get_setting("notify_on_removal", True, guild_id=self.guild_id)
        notify_status = "✅ Enabled" if notify_removal else "❌ Disabled"
        embed.add_field(name="DM Notifications", value=notify_status, inline=True)

        # Show debounce setting (global)
        debounce = self.cog.get_global_setting("debounce_seconds", 15)
        embed.add_field(name="Debounce Delay", value=f"{debounce}s (Bot Owner)", inline=True)

        await interaction.response.edit_message(embed=embed, view=self)


# === Management Buttons ===


class ManageCategoriesButton(ui.Button):
    """Button to manage role categories."""

    def __init__(self, cog, guild_id: int):
        super().__init__(label="Manage Categories", style=discord.ButtonStyle.primary, emoji="📋")
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Open category management view."""
        view = CategoryListView(self.cog, self.guild_id, interaction)
        await view.show()


class AutoEnforceToggleButton(ui.Button):
    """Button to toggle automatic prerequisite enforcement."""

    def __init__(self, cog, guild_id: int):
        super().__init__(label="Toggle Auto-Removal", style=discord.ButtonStyle.secondary, emoji="🔄")
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Toggle auto-enforcement setting."""
        current = self.cog.get_setting("auto_enforce_prerequisites", True, guild_id=self.guild_id)
        new_value = not current
        self.cog.set_setting("auto_enforce_prerequisites", new_value, guild_id=self.guild_id)

        status = "enabled" if new_value else "disabled"
        await interaction.response.send_message(f"✅ Auto-removal of roles when prerequisites are lost is now **{status}**", ephemeral=True)


class RemovalNotifyToggleButton(ui.Button):
    """Button to toggle DM notifications on role removal."""

    def __init__(self, cog, guild_id: int):
        super().__init__(label="Toggle Notifications", style=discord.ButtonStyle.secondary, emoji="📨")
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Toggle notification setting."""
        current = self.cog.get_setting("notify_on_removal", True, guild_id=self.guild_id)
        new_value = not current
        self.cog.set_setting("notify_on_removal", new_value, guild_id=self.guild_id)

        status = "enabled" if new_value else "disabled"
        await interaction.response.send_message(f"✅ DM notifications on role removal are now **{status}**", ephemeral=True)


class ConfigureDebounceButton(ui.Button):
    """Button to configure debounce delay (bot owner only)."""

    def __init__(self, cog):
        super().__init__(label="Configure Debounce", style=discord.ButtonStyle.secondary, emoji="⏱️")
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        """Show modal to configure debounce."""
        modal = DebounceConfigModal(self.cog)
        await interaction.response.send_modal(modal)


class DebounceConfigModal(ui.Modal, title="Configure Debounce Delay"):
    """Modal to configure debounce delay."""

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

        current_value = cog.get_global_setting("debounce_seconds", 15)
        self.debounce_input = ui.TextInput(
            label="Debounce Delay (seconds)",
            placeholder="15",
            default=str(current_value),
            required=True,
            min_length=1,
            max_length=3,
        )
        self.add_item(self.debounce_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Save the debounce value."""
        try:
            value = int(self.debounce_input.value)
            if value < 0 or value > 300:
                await interaction.response.send_message("❌ Debounce must be between 0 and 300 seconds.", ephemeral=True)
                return

            self.cog.set_global_setting("debounce_seconds", value)
            await interaction.response.send_message(f"✅ Debounce delay set to {value} seconds", ephemeral=True)

        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number.", ephemeral=True)


# === Category Management Views ===


class CategoryListView(ui.View):
    """View for managing role categories."""

    def __init__(self, cog, guild_id: int, interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.interaction = interaction

        # Add category buttons
        categories = self.cog.get_setting("categories", [], guild_id=guild_id)
        sorted_categories = sorted(categories, key=lambda c: c.get("name", "").lower())

        for idx, category in enumerate(sorted_categories[:20]):  # Max 20 categories
            btn = ui.Button(label=category.get("name", "Unknown"), style=discord.ButtonStyle.secondary, row=idx // 5)
            btn.callback = self._create_category_callback(category)
            self.add_item(btn)

        # Add "Add Category" button
        add_btn = ui.Button(label="Add Category", style=discord.ButtonStyle.success, emoji="➕", row=4)
        add_btn.callback = self.on_add_category
        self.add_item(add_btn)

        # Add back button
        back_btn = ui.Button(label="← Back", style=discord.ButtonStyle.primary, row=4)
        back_btn.callback = self.on_back
        self.add_item(back_btn)

    def _create_category_callback(self, category: dict):
        """Create callback for category button."""

        async def callback(interaction: discord.Interaction):
            view = CategoryDetailView(self.cog, self.guild_id, category, interaction, parent=self)
            await view.show()

        return callback

    async def show(self):
        """Display the category list."""
        embed = discord.Embed(title="📋 Manage Categories", description="Select a category to edit or add a new one", color=discord.Color.blue())

        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)
        if categories:
            category_list = []
            for cat in sorted(categories, key=lambda c: c.get("name", "").lower()):
                mode = cat.get("selection_mode", "single")
                mode_text = "single" if mode == "single" else "multiple"
                roles_count = len(cat.get("roles", []))
                category_list.append(f"• **{cat.get('name')}** ({mode_text}, {roles_count} roles)")

            embed.add_field(name=f"Categories ({len(categories)})", value="\n".join(category_list[:20]), inline=False)
        else:
            embed.add_field(name="No Categories", value="Click 'Add Category' to create your first category", inline=False)

        await self.interaction.response.edit_message(embed=embed, view=self)

    async def refresh(self, interaction: discord.Interaction):
        """Refresh the view."""
        # Rebuild buttons
        self.clear_items()

        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)
        sorted_categories = sorted(categories, key=lambda c: c.get("name", "").lower())

        for idx, category in enumerate(sorted_categories[:20]):
            btn = ui.Button(label=category.get("name", "Unknown"), style=discord.ButtonStyle.secondary, row=idx // 5)
            btn.callback = self._create_category_callback(category)
            self.add_item(btn)

        add_btn = ui.Button(label="Add Category", style=discord.ButtonStyle.success, emoji="➕", row=4)
        add_btn.callback = self.on_add_category
        self.add_item(add_btn)

        back_btn = ui.Button(label="← Back", style=discord.ButtonStyle.primary, row=4)
        back_btn.callback = self.on_back
        self.add_item(back_btn)

        # Update embed
        embed = discord.Embed(title="📋 Manage Categories", description="Select a category to edit or add a new one", color=discord.Color.blue())

        if categories:
            category_list = []
            for cat in sorted_categories:
                mode = cat.get("selection_mode", "single")
                mode_text = "single" if mode == "single" else "multiple"
                roles_count = len(cat.get("roles", []))
                category_list.append(f"• **{cat.get('name')}** ({mode_text}, {roles_count} roles)")

            embed.add_field(name=f"Categories ({len(categories)})", value="\n".join(category_list[:20]), inline=False)
        else:
            embed.add_field(name="No Categories", value="Click 'Add Category' to create your first category", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

    async def on_add_category(self, interaction: discord.Interaction):
        """Show modal to add new category."""
        modal = AddCategoryModal(self.cog, self.guild_id, parent_view=self)
        await interaction.response.send_modal(modal)

    async def on_back(self, interaction: discord.Interaction):
        """Return to settings view."""
        # Re-create the main settings view
        from thetower.bot.ui.context import SettingsViewContext

        context = SettingsViewContext(cog=self.cog, guild_id=self.guild_id, is_bot_owner=interaction.user.id == self.cog.bot.owner_id)
        settings_view = OptionalRolesSettingsView(context)
        await settings_view.update_display(interaction)


class AddCategoryModal(ui.Modal, title="Add New Category"):
    """Modal to add a new category."""

    def __init__(self, cog, guild_id: int, parent_view):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.parent_view = parent_view

        self.name_input = ui.TextInput(label="Category Name", placeholder="Event Notifications", required=True, max_length=100)
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Save the new category."""
        name = self.name_input.value.strip()

        if not name:
            await interaction.response.send_message("❌ Category name cannot be empty.", ephemeral=True)
            return

        # Check for duplicate names
        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)
        if any(cat.get("name", "").lower() == name.lower() for cat in categories):
            await interaction.response.send_message(f"❌ A category named '{name}' already exists.", ephemeral=True)
            return

        # Add new category
        new_category = {"name": name, "selection_mode": "multiple", "roles": []}
        categories.append(new_category)
        self.cog.set_setting("categories", categories, guild_id=self.guild_id)

        await interaction.response.send_message(f"✅ Created category '{name}'", ephemeral=True)
        await self.parent_view.refresh(interaction)


class CategoryDetailView(ui.View):
    """View for editing a specific category."""

    def __init__(self, cog, guild_id: int, category: dict, interaction: discord.Interaction, parent):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.category = category
        self.interaction = interaction
        self.parent = parent

        # Mode toggle button
        mode_btn = ui.Button(
            label=f"Mode: {category.get('selection_mode', 'single').title()}", style=discord.ButtonStyle.secondary, emoji="🔀", row=0
        )
        mode_btn.callback = self.on_toggle_mode
        self.add_item(mode_btn)

        # Post-verification toggle button
        show_on_verify = category.get("show_on_verification", False)
        verify_btn = ui.Button(
            label=f"Verification Prompt: {'On' if show_on_verify else 'Off'}", style=discord.ButtonStyle.secondary, emoji="🆕", row=0
        )
        verify_btn.callback = self.on_toggle_verification
        self.add_item(verify_btn)

        # Manage roles button
        roles_btn = ui.Button(label="Manage Roles", style=discord.ButtonStyle.primary, emoji="👥", row=1)
        roles_btn.callback = self.on_manage_roles
        self.add_item(roles_btn)

        # Delete category button
        delete_btn = ui.Button(label="Delete Category", style=discord.ButtonStyle.danger, emoji="🗑️", row=2)
        delete_btn.callback = self.on_delete_category
        self.add_item(delete_btn)

        # Back button
        back_btn = ui.Button(label="← Back", style=discord.ButtonStyle.primary, row=2)
        back_btn.callback = self.on_back
        self.add_item(back_btn)

    async def show(self):
        """Display category details."""
        embed = self._build_embed()
        await self.interaction.response.edit_message(embed=embed, view=self)

    def _build_embed(self) -> discord.Embed:
        """Build the category detail embed."""
        embed = discord.Embed(title=f"📋 {self.category.get('name')}", color=discord.Color.blue())

        mode = self.category.get("selection_mode", "single")
        mode_text = "Users can select **one role**" if mode == "single" else "Users can select **multiple roles**"
        embed.add_field(name="Selection Mode", value=mode_text, inline=False)

        # Show post-verification status
        show_on_verify = self.category.get("show_on_verification", False)
        verify_text = "✅ Enabled" if show_on_verify else "❌ Disabled"
        embed.add_field(name="Post-Verification Prompt", value=verify_text, inline=False)
        if show_on_verify:
            embed.add_field(name="ℹ️ Info", value="Roles from this category will be offered to users immediately after they verify.", inline=False)

        roles = self.category.get("roles", [])
        if roles:
            guild = self.cog.bot.get_guild(self.guild_id)
            role_list = []
            for role_config in roles:
                role_obj = guild.get_role(role_config["role_id"]) if guild else None
                role_name = role_obj.name if role_obj else f"Unknown ({role_config['role_id']})"
                prereq_count = len(role_config.get("prerequisite_roles", []))
                role_list.append(f"• {role_name} ({prereq_count} prereqs)")

            embed.add_field(name=f"Roles ({len(roles)})", value="\n".join(role_list[:10]), inline=False)
        else:
            embed.add_field(name="Roles", value="No roles configured", inline=False)

        return embed

    async def on_toggle_mode(self, interaction: discord.Interaction):
        """Toggle selection mode."""
        current_mode = self.category.get("selection_mode", "single")
        new_mode = "multiple" if current_mode == "single" else "single"

        # Update category in settings
        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)
        for cat in categories:
            if cat.get("name") == self.category.get("name"):
                cat["selection_mode"] = new_mode
                break

        self.cog.set_setting("categories", categories, guild_id=self.guild_id)
        self.category["selection_mode"] = new_mode

        # Refresh view
        embed = self._build_embed()
        # Update button label
        self.children[0].label = f"Mode: {new_mode.title()}"
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_toggle_verification(self, interaction: discord.Interaction):
        """Toggle post-verification prompt."""
        current = self.category.get("show_on_verification", False)
        new_value = not current

        # Update category in settings
        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)
        for cat in categories:
            if cat.get("name") == self.category.get("name"):
                cat["show_on_verification"] = new_value
                break

        self.cog.set_setting("categories", categories, guild_id=self.guild_id)
        self.category["show_on_verification"] = new_value

        # Refresh view
        embed = self._build_embed()
        # Update button label
        self.children[1].label = f"Verification Prompt: {'On' if new_value else 'Off'}"
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_manage_roles(self, interaction: discord.Interaction):
        """Open role management view."""
        view = CategoryRoleManagementView(self.cog, self.guild_id, self.category, interaction, parent=self)
        await view.show()

    async def on_delete_category(self, interaction: discord.Interaction):
        """Delete this category."""
        # Remove category from settings
        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)
        categories = [cat for cat in categories if cat.get("name") != self.category.get("name")]
        self.cog.set_setting("categories", categories, guild_id=self.guild_id)

        await interaction.response.send_message(f"✅ Deleted category '{self.category.get('name')}'", ephemeral=True)
        await self.parent.refresh(interaction)

    async def on_back(self, interaction: discord.Interaction):
        """Return to category list."""
        await self.parent.refresh(interaction)


class CategoryRoleManagementView(ui.View):
    """View for managing roles within a category."""

    def __init__(self, cog, guild_id: int, category: dict, interaction: discord.Interaction, parent):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.category = category
        self.interaction = interaction
        self.parent = parent

        # Add role select dropdown
        self.add_item(AddRoleSelect(self.cog, self.guild_id, self.category, self))

        # Add role buttons
        roles = category.get("roles", [])
        guild = cog.bot.get_guild(guild_id)

        for idx, role_config in enumerate(roles[:20]):
            role_obj = guild.get_role(role_config["role_id"]) if guild else None
            label = role_obj.name if role_obj else f"Unknown ({role_config['role_id']})"

            btn = ui.Button(label=label, style=discord.ButtonStyle.secondary, row=(idx // 5) + 1)
            btn.callback = self._create_role_callback(role_config)
            self.add_item(btn)

        # Back button
        back_btn = ui.Button(label="← Back", style=discord.ButtonStyle.primary, row=4)
        back_btn.callback = self.on_back
        self.add_item(back_btn)

    def _create_role_callback(self, role_config: dict):
        """Create callback for role button."""

        async def callback(interaction: discord.Interaction):
            view = RoleDetailView(self.cog, self.guild_id, self.category, role_config, interaction, parent=self)
            await view.show()

        return callback

    async def show(self):
        """Display role management view."""
        embed = self._build_embed()
        await self.interaction.response.edit_message(embed=embed, view=self)

    async def refresh(self, interaction: discord.Interaction):
        """Refresh the view."""
        # Rebuild view
        self.clear_items()

        # Re-add role select
        self.add_item(AddRoleSelect(self.cog, self.guild_id, self.category, self))

        # Re-add role buttons
        roles = self.category.get("roles", [])
        guild = self.cog.bot.get_guild(self.guild_id)

        for idx, role_config in enumerate(roles[:20]):
            role_obj = guild.get_role(role_config["role_id"]) if guild else None
            label = role_obj.name if role_obj else f"Unknown ({role_config['role_id']})"

            btn = ui.Button(label=label, style=discord.ButtonStyle.secondary, row=(idx // 5) + 1)
            btn.callback = self._create_role_callback(role_config)
            self.add_item(btn)

        # Back button
        back_btn = ui.Button(label="← Back", style=discord.ButtonStyle.primary, row=4)
        back_btn.callback = self.on_back
        self.add_item(back_btn)

        # Update display
        embed = self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    def _build_embed(self) -> discord.Embed:
        """Build the role management embed."""
        embed = discord.Embed(title=f"👥 Manage Roles - {self.category.get('name')}", color=discord.Color.blue())

        roles = self.category.get("roles", [])
        if roles:
            embed.add_field(
                name="Instructions", value="Select a role below to edit its prerequisites, or use the dropdown to add a new role.", inline=False
            )

            guild = self.cog.bot.get_guild(self.guild_id)
            role_list = []
            for role_config in roles:
                role_obj = guild.get_role(role_config["role_id"]) if guild else None
                role_name = role_obj.name if role_obj else f"Unknown ({role_config['role_id']})"
                prereq_count = len(role_config.get("prerequisite_roles", []))
                role_list.append(f"• {role_name} ({prereq_count} prereqs)")

            embed.add_field(name=f"Roles ({len(roles)})", value="\n".join(role_list[:10]), inline=False)
        else:
            embed.add_field(name="No Roles", value="Use the dropdown to add roles to this category", inline=False)

        return embed

    async def on_back(self, interaction: discord.Interaction):
        """Return to category detail view."""
        await self.parent.show()


class AddRoleSelect(ui.RoleSelect):
    """Role select dropdown to add roles to category."""

    def __init__(self, cog, guild_id: int, category: dict, parent_view):
        super().__init__(placeholder="Add a role to this category", min_values=1, max_values=1, row=0)
        self.cog = cog
        self.guild_id = guild_id
        self.category = category
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        """Add selected role to category."""
        role = self.values[0]

        # Check if role already exists in category
        if any(r["role_id"] == role.id for r in self.category.get("roles", [])):
            await interaction.response.send_message(f"❌ {role.name} is already in this category", ephemeral=True)
            return

        # Add role to category
        new_role_config = {"role_id": role.id, "name": role.name, "prerequisite_roles": [], "emoji": None, "description": None}

        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)
        for cat in categories:
            if cat.get("name") == self.category.get("name"):
                if "roles" not in cat:
                    cat["roles"] = []
                cat["roles"].append(new_role_config)
                self.category["roles"] = cat["roles"]  # Update local reference
                break

        self.cog.set_setting("categories", categories, guild_id=self.guild_id)

        await interaction.response.send_message(f"✅ Added {role.name} to category", ephemeral=True)
        await self.parent_view.refresh(interaction)


class RoleDetailView(ui.View):
    """View for editing a specific role's settings."""

    def __init__(self, cog, guild_id: int, category: dict, role_config: dict, interaction: discord.Interaction, parent):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.category = category
        self.role_config = role_config
        self.interaction = interaction
        self.parent = parent

        # Add prerequisite role select
        self.add_item(PrerequisiteRoleSelect(self.cog, self.guild_id, self.category, self.role_config, self))

        # Remove role button
        remove_btn = ui.Button(label="Remove from Category", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
        remove_btn.callback = self.on_remove_role
        self.add_item(remove_btn)

        # Back button
        back_btn = ui.Button(label="← Back", style=discord.ButtonStyle.primary, row=1)
        back_btn.callback = self.on_back
        self.add_item(back_btn)

    async def show(self):
        """Display role detail view."""
        embed = self._build_embed()
        await self.interaction.response.edit_message(embed=embed, view=self)

    async def refresh(self, interaction: discord.Interaction):
        """Refresh the view."""
        embed = self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    def _build_embed(self) -> discord.Embed:
        """Build the role detail embed."""
        guild = self.cog.bot.get_guild(self.guild_id)
        role_obj = guild.get_role(self.role_config["role_id"]) if guild else None
        role_name = role_obj.name if role_obj else f"Unknown ({self.role_config['role_id']})"

        embed = discord.Embed(title=f"⚙️ {role_name}", color=discord.Color.blue())
        embed.add_field(name="Category", value=self.category.get("name"), inline=False)

        # Show prerequisites
        prereq_ids = self.role_config.get("prerequisite_roles", [])
        if prereq_ids:
            prereq_roles = [guild.get_role(pid) for pid in prereq_ids] if guild else []
            prereq_names = [r.mention for r in prereq_roles if r is not None]
            if prereq_names:
                embed.add_field(name="Prerequisites (user needs ANY one)", value="\n".join(prereq_names), inline=False)
            else:
                embed.add_field(name="Prerequisites", value="⚠️ Configured roles not found", inline=False)
        else:
            embed.add_field(name="Prerequisites", value="None (anyone can select this role)", inline=False)

        embed.add_field(
            name="Instructions",
            value="Use the dropdown to add prerequisite roles. Users will need at least ONE of the prerequisite roles to select this role.",
            inline=False,
        )

        return embed

    async def on_remove_role(self, interaction: discord.Interaction):
        """Remove this role from the category."""
        # Remove role from category
        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)
        for cat in categories:
            if cat.get("name") == self.category.get("name"):
                cat["roles"] = [r for r in cat.get("roles", []) if r["role_id"] != self.role_config["role_id"]]
                self.category["roles"] = cat["roles"]
                break

        self.cog.set_setting("categories", categories, guild_id=self.guild_id)

        guild = self.cog.bot.get_guild(self.guild_id)
        role_obj = guild.get_role(self.role_config["role_id"]) if guild else None
        role_name = role_obj.name if role_obj else "Role"

        await interaction.response.send_message(f"✅ Removed {role_name} from category", ephemeral=True)
        await self.parent.refresh(interaction)

    async def on_back(self, interaction: discord.Interaction):
        """Return to role management view."""
        await self.parent.refresh(interaction)


class PrerequisiteRoleSelect(ui.RoleSelect):
    """Role select dropdown to manage prerequisite roles."""

    def __init__(self, cog, guild_id: int, category: dict, role_config: dict, parent_view):
        super().__init__(placeholder="Add/remove prerequisite roles", min_values=0, max_values=25, row=0)
        self.cog = cog
        self.guild_id = guild_id
        self.category = category
        self.role_config = role_config
        self.parent_view = parent_view

        # Pre-select current prerequisites
        current_prereqs = role_config.get("prerequisite_roles", [])
        if current_prereqs:
            self.default_values = []
            guild = cog.bot.get_guild(guild_id)
            if guild:
                for prereq_id in current_prereqs:
                    role_obj = guild.get_role(prereq_id)
                    if role_obj:
                        self.default_values.append(discord.Object(id=prereq_id))

    async def callback(self, interaction: discord.Interaction):
        """Update prerequisite roles."""
        # Get selected role IDs
        new_prereq_ids = [role.id for role in self.values]

        # Prevent role from being its own prerequisite
        if self.role_config["role_id"] in new_prereq_ids:
            await interaction.response.send_message("❌ A role cannot be a prerequisite for itself", ephemeral=True)
            return

        # Update role config
        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)
        for cat in categories:
            if cat.get("name") == self.category.get("name"):
                for role in cat.get("roles", []):
                    if role["role_id"] == self.role_config["role_id"]:
                        role["prerequisite_roles"] = new_prereq_ids
                        self.role_config["prerequisite_roles"] = new_prereq_ids
                        break
                break

        self.cog.set_setting("categories", categories, guild_id=self.guild_id)

        count = len(new_prereq_ids)
        await interaction.response.send_message(f"✅ Updated prerequisites ({count} role{'s' if count != 1 else ''})", ephemeral=True)
        await self.parent_view.refresh(interaction)
