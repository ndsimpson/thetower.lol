"""Settings management views for Tourney Role Colors cog."""

import re
from typing import Dict, List, Optional, Tuple

import discord
from discord import ui

from thetower.bot.ui.context import BaseSettingsView, SettingsViewContext


def _natural_sort_key(name: str) -> List:
    """Split a name into text and numeric parts for natural sorting.

    E.g. 'Pink 1000' -> ['pink ', 1000] so that numeric segments
    compare as integers rather than strings.
    """
    parts = re.split(r"(\d+)", (name or "").lower())
    return [int(p) if p.isdigit() else p for p in parts]


def _role_sort_key(role: Dict, all_roles: List[Dict]) -> Tuple:
    """Sort key for roles: by inheritance depth, then natural name order.

    Roles with no parent sort first, then children, grandchildren, etc.
    Falls back to natural name sort for tiebreaking.
    """
    depth = 0
    current = role
    seen: set = set()
    while current.get("inherits_from") and current["inherits_from"] not in seen:
        seen.add(current["inherits_from"])
        parent = next((r for r in all_roles if r.get("role_id") == current["inherits_from"]), None)
        if not parent:
            break
        depth += 1
        current = parent
    return (depth, _natural_sort_key(role.get("name", "")))


def _sort_roles_by_inheritance(roles: List[Dict]) -> List[Dict]:
    """Return a new list of roles sorted by inheritance depth, then natural name order."""
    return sorted(roles, key=lambda r: _role_sort_key(r, roles))


def _sort_role_ids_by_name(cog, guild_id: int, role_ids: List[int]) -> List[int]:
    """Return role IDs sorted by natural name order.

    Falls back to stringified ID when role lookup fails.
    """
    guild = None
    try:
        guild = getattr(cog, "bot", None).get_guild(guild_id) if getattr(cog, "bot", None) else None
    except Exception:
        guild = None

    def _name_key(role_id: int) -> List:
        if guild:
            role = guild.get_role(role_id)
            if role and role.name:
                return _natural_sort_key(role.name)
        return _natural_sort_key(str(role_id))

    return sorted(role_ids, key=_name_key)


class TourneyRoleColorsSettingsView(BaseSettingsView):
    """Settings view for Tourney Role Colors cog."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(context)

        # Add main management buttons
        self.add_item(ManageCategoriesButton(self.cog, self.guild_id))

        # Add logging channel button
        self.add_item(ConfigureLoggingChannelButton(self.cog, self.guild_id))

        # Add startup audit toggle button
        self.add_item(StartupAuditToggleButton(self.cog, self.guild_id))

        # Add auto-enforcement toggle button
        self.add_item(AutoEnforceToggleButton(self.cog, self.guild_id))

        # Add demotion notification toggle button
        self.add_item(DemotionNotifyToggleButton(self.cog, self.guild_id))

        # Add debounce configuration button (bot owner only)
        if context.is_bot_owner:
            self.add_item(ConfigureDebounceButton(self.cog))

        # Add logging channel select
        self.add_item(RoleColorLogChannelSelect(self.cog, self.guild_id))

        # Back button
        self.add_back_button()

    async def update_display(self, interaction: discord.Interaction):
        """Update the embed with current tourney role colors settings."""
        embed = discord.Embed(
            title="⚙️ Tourney Role Colors Settings", description="Configure role selection categories and prerequisites", color=discord.Color.blue()
        )

        # Get current categories
        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)
        # Sort categories for display
        sorted_categories = sorted(categories, key=lambda c: _natural_sort_key(c.get("name", "")))

        if sorted_categories:
            category_info = []
            for cat in sorted_categories:
                roles_count = len(cat.get("roles", []))
                category_info.append(f"**{cat.get('name')}**: {roles_count} roles")

            embed.add_field(name=f"Categories ({len(sorted_categories)})", value="\n".join(category_info[:10]), inline=False)
        else:
            embed.add_field(name="Categories", value="No categories configured. Click 'Manage Categories' to get started.", inline=False)

        # Show logging channel status
        log_channel_id = self.cog.get_setting("role_color_log_channel_id", guild_id=self.guild_id)
        if log_channel_id:
            guild = self.cog.bot.get_guild(self.guild_id)
            if guild:
                channel = guild.get_channel(log_channel_id)
                if channel:
                    embed.add_field(name="Logging Channel", value=f"Role changes logged to {channel.mention}", inline=False)
                else:
                    embed.add_field(name="Logging Channel", value="⚠️ Configured channel not found", inline=False)
        else:
            embed.add_field(name="Logging Channel", value="Not configured (changes not logged)", inline=False)

        # Show startup audit status
        startup_audit_enabled = self.cog.get_setting("enable_startup_audit", False, guild_id=self.guild_id)
        audit_status = "✅ Enabled" if startup_audit_enabled else "❌ Disabled"
        embed.add_field(name="Startup Audit", value=audit_status, inline=False)

        # Show auto-enforcement status
        auto_enforce = self.cog.get_setting("auto_enforce_prerequisites", True, guild_id=self.guild_id)
        enforce_status = "✅ Enabled" if auto_enforce else "❌ Disabled"
        embed.add_field(name="Auto-Demotion", value=enforce_status, inline=True)

        # Show demotion notification status
        notify_demotion = self.cog.get_setting("notify_on_demotion", False, guild_id=self.guild_id)
        notify_status = "✅ Enabled" if notify_demotion else "❌ Disabled"
        embed.add_field(name="DM Notifications", value=notify_status, inline=True)

        # Show debounce setting (global)
        debounce = self.cog.get_global_setting("debounce_seconds", 15)
        embed.add_field(name="Debounce Delay", value=f"{debounce}s (Bot Owner Only)", inline=True)

        embed.set_footer(text="Categories are mutually exclusive - users can only have one role at a time")

        await interaction.response.edit_message(embed=embed, view=self)


class StartupAuditToggleButton(ui.Button):
    """Button to toggle startup audit enabled/disabled."""

    def __init__(self, cog, guild_id: int):
        # Default to False if not set
        audit_enabled = cog.get_setting("enable_startup_audit", False, guild_id=guild_id)

        if audit_enabled:
            label = "Startup Audit: Enabled"
            style = discord.ButtonStyle.success
            emoji = "✅"
        else:
            label = "Startup Audit: Disabled"
            style = discord.ButtonStyle.danger
            emoji = "❌"

        super().__init__(label=label, style=style, emoji=emoji)
        self.cog = cog
        self.guild_id = guild_id
        self.audit_enabled = audit_enabled

    async def callback(self, interaction: discord.Interaction):
        """Toggle startup audit enabled/disabled."""
        new_state = not self.audit_enabled
        self.cog.set_setting("enable_startup_audit", new_state, self.guild_id)

        # Recreate the main settings view with updated value
        from thetower.bot.ui.context import SettingsViewContext

        context = SettingsViewContext(
            guild_id=interaction.guild.id, cog_instance=self.cog, interaction=interaction, is_bot_owner=await self.cog.bot.is_owner(interaction.user)
        )
        settings_view = TourneyRoleColorsSettingsView(context)
        await settings_view.update_display(interaction)


class ConfigureLoggingChannelButton(ui.Button):
    """Button to configure the logging channel."""

    def __init__(self, cog, guild_id: int):
        super().__init__(label="Configure Logging", style=discord.ButtonStyle.secondary, emoji="📝")
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Open logging channel configuration view."""
        view = LoggingChannelConfigView(self.cog, self.guild_id, interaction)

        # Get current channel
        log_channel_id = self.cog.get_setting("role_color_log_channel_id", guild_id=self.guild_id)

        embed = discord.Embed(
            title="📝 Configure Logging Channel",
            description="Select a channel to log role color changes, or clear to disable logging.",
            color=discord.Color.blue(),
        )

        if log_channel_id:
            guild = self.cog.bot.get_guild(self.guild_id)
            if guild:
                channel = guild.get_channel(log_channel_id)
                if channel:
                    embed.add_field(name="Current Channel", value=channel.mention, inline=False)
                else:
                    embed.add_field(name="Current Channel", value="⚠️ Channel not found", inline=False)
        else:
            embed.add_field(name="Current Channel", value="Not configured", inline=False)

        await interaction.response.edit_message(embed=embed, view=view)


class LoggingChannelConfigView(ui.View):
    """View for configuring the logging channel."""

    def __init__(self, cog, guild_id: int, original_interaction: discord.Interaction):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild_id = guild_id
        self.original_interaction = original_interaction

        # Add channel select
        self.add_item(RoleColorLogChannelSelect(cog, guild_id))

        # Add back button
        self.add_item(LoggingChannelBackButton(cog, original_interaction))


class LoggingChannelBackButton(ui.Button):
    """Back button to return to main Tourney Role Colors settings."""

    def __init__(self, cog, original_interaction: discord.Interaction):
        super().__init__(label="Back to Settings", style=discord.ButtonStyle.secondary, emoji="⬅️")
        self.cog = cog
        self.original_interaction = original_interaction

    async def callback(self, interaction: discord.Interaction):
        # Recreate the main settings view
        from thetower.bot.ui.context import SettingsViewContext

        context = SettingsViewContext(
            guild_id=interaction.guild.id,
            cog_instance=self.cog,
            interaction=self.original_interaction,
            is_bot_owner=await self.cog.bot.is_owner(interaction.user),
        )
        settings_view = TourneyRoleColorsSettingsView(context)
        await settings_view.update_display(interaction)


class CategoryManagementBackButton(ui.Button):
    """Back button to return to main Tourney Role Colors settings."""

    def __init__(self, cog, original_interaction: discord.Interaction):
        super().__init__(label="Back to Settings", style=discord.ButtonStyle.secondary, emoji="⬅️")
        self.cog = cog
        self.original_interaction = original_interaction

    async def callback(self, interaction: discord.Interaction):
        # Recreate the main settings view
        from thetower.bot.ui.context import SettingsViewContext

        context = SettingsViewContext(
            guild_id=interaction.guild.id,
            cog_instance=self.cog,
            interaction=self.original_interaction,
            is_bot_owner=await self.cog.bot.is_owner(interaction.user),
        )
        settings_view = TourneyRoleColorsSettingsView(context)
        await settings_view.update_display(interaction)


class AutoEnforceToggleButton(ui.Button):
    """Button to toggle auto-enforcement of prerequisites."""

    def __init__(self, cog, guild_id: int):
        # Default to True if not set
        auto_enforce = cog.get_setting("auto_enforce_prerequisites", True, guild_id=guild_id)

        if auto_enforce:
            label = "Auto-Demotion: Enabled"
            style = discord.ButtonStyle.success
            emoji = "✅"
        else:
            label = "Auto-Demotion: Disabled"
            style = discord.ButtonStyle.danger
            emoji = "❌"

        super().__init__(label=label, style=style, emoji=emoji)
        self.cog = cog
        self.guild_id = guild_id
        self.auto_enforce = auto_enforce

    async def callback(self, interaction: discord.Interaction):
        """Toggle auto-enforcement enabled/disabled."""
        new_state = not self.auto_enforce
        self.cog.set_setting("auto_enforce_prerequisites", new_state, self.guild_id)

        status = "enabled" if new_state else "disabled"
        emoji = "✅" if new_state else "❌"

        await interaction.response.send_message(
            f"{emoji} Auto-demotion has been **{status}**. "
            f"{'Users will be automatically demoted to qualifying roles when prerequisites are lost.' if new_state else 'Users will keep their roles even if prerequisites are lost.'}",
            ephemeral=True,
        )


class DemotionNotifyToggleButton(ui.Button):
    """Button to toggle DM notifications for demotions."""

    def __init__(self, cog, guild_id: int):
        # Default to False if not set
        notify_enabled = cog.get_setting("notify_on_demotion", False, guild_id=guild_id)

        if notify_enabled:
            label = "DM Notifications: Enabled"
            style = discord.ButtonStyle.success
            emoji = "✅"
        else:
            label = "DM Notifications: Disabled"
            style = discord.ButtonStyle.danger
            emoji = "❌"

        super().__init__(label=label, style=style, emoji=emoji)
        self.cog = cog
        self.guild_id = guild_id
        self.notify_enabled = notify_enabled

    async def callback(self, interaction: discord.Interaction):
        """Toggle DM notifications enabled/disabled."""
        new_state = not self.notify_enabled
        self.cog.set_setting("notify_on_demotion", new_state, self.guild_id)

        status = "enabled" if new_state else "disabled"
        emoji = "✅" if new_state else "❌"

        await interaction.response.send_message(
            f"{emoji} DM notifications have been **{status}**. "
            f"{'Users will receive a DM when their color role is auto-demoted.' if new_state else 'Users will not be notified of auto-demotions.'}",
            ephemeral=True,
        )


class ConfigureDebounceButton(ui.Button):
    """Button to configure debounce delay (bot owner only)."""

    def __init__(self, cog):
        current_value = cog.get_global_setting("debounce_seconds", 15)
        super().__init__(label=f"Set Debounce: {current_value}s", style=discord.ButtonStyle.secondary, emoji="⏱️")
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        """Open modal to configure debounce."""
        # Double-check bot owner (should already be enforced by /settings)
        is_bot_owner = await self.cog.bot.is_owner(interaction.user)
        if not is_bot_owner:
            await interaction.response.send_message("❌ Only the bot owner can change this setting.", ephemeral=True)
            return

        modal = ConfigureDebounceModal(self.cog)
        await interaction.response.send_modal(modal)


class ManageCategoriesButton(ui.Button):
    """Button to manage categories."""

    def __init__(self, cog, guild_id: int):
        super().__init__(label="Manage Categories", style=discord.ButtonStyle.primary, emoji="📁")
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        # Get current categories
        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)

        # Sort categories for display purposes
        sorted_categories = sorted(categories, key=lambda cat: _natural_sort_key(cat.get("name", "")))

        # Show category management view
        view = CategoryManagementView(self.cog, self.guild_id, categories, interaction)

        if categories:
            category_list = "\n".join(
                [f"**{idx + 1}.** {cat.get('name')} ({len(cat.get('roles', []))} roles)" for idx, cat in enumerate(sorted_categories[:10])]
            )
            message = f"**Current Categories:**\n\n{category_list}\n\nSelect an action below:"
        else:
            message = "**No categories configured**\n\nClick 'Create Category' to add your first category."

        await interaction.response.edit_message(content=message, view=view, embed=None)


class CategoryManagementView(ui.View):
    """View for managing categories."""

    def __init__(self, cog, guild_id: int, categories: List[Dict], original_interaction: discord.Interaction = None):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild_id = guild_id
        self.categories = categories
        self.original_interaction = original_interaction

        # Add buttons
        self.add_item(CreateCategoryButton(self.cog, self.guild_id))
        if categories:
            self.add_item(EditCategoryButton(self.cog, self.guild_id, categories))
            self.add_item(DeleteCategoryButton(self.cog, self.guild_id, categories))

        # Add back button if we have the original interaction
        if original_interaction:
            self.add_item(CategoryManagementBackButton(cog, original_interaction))


class CreateCategoryButton(ui.Button):
    """Button to create a new category."""

    def __init__(self, cog, guild_id: int):
        super().__init__(label="Create Category", style=discord.ButtonStyle.success, emoji="➕")
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        # Show modal to create category
        modal = CreateCategoryModal(self.cog, self.guild_id)
        await interaction.response.send_modal(modal)


class CreateCategoryModal(ui.Modal, title="Create New Category"):
    """Modal for creating a new category."""

    category_name = ui.TextInput(label="Category Name", placeholder="e.g., Orange, Yellow, Profile Icons", required=True, max_length=50)

    def __init__(self, cog, guild_id: int):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        # Get current categories
        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)

        # Check if category name already exists
        if any(cat.get("name") == self.category_name.value for cat in categories):
            await interaction.response.send_message(f"❌ A category named '{self.category_name.value}' already exists.", ephemeral=True)
            return

        # Create new category
        new_category = {"name": self.category_name.value, "roles": []}

        categories.append(new_category)
        # Persist categories sorted by name
        categories.sort(key=lambda c: _natural_sort_key(c.get("name", "")))
        self.cog.set_setting("categories", categories, guild_id=self.guild_id)

        # Refresh the category management view
        view = CategoryManagementView(self.cog, self.guild_id, categories)
        category_list = "\n".join(
            [f"**{idx + 1}.** {cat.get('name')} ({len(cat.get('roles', []))} roles)" for idx, cat in enumerate(categories[:10])]
        )
        message = f"✅ Created category: **{self.category_name.value}**\n\n**Current Categories:**\n\n{category_list}\n\nSelect an action below:"

        await interaction.response.edit_message(content=message, view=view)


class ConfigureDebounceModal(ui.Modal, title="Configure Debounce Delay"):
    """Modal for configuring the debounce delay."""

    debounce_input = ui.TextInput(
        label="Debounce Delay (seconds)",
        placeholder="Enter a value between 1 and 30",
        required=True,
        min_length=1,
        max_length=2,
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog
        # Set current value as default
        current_value = cog.get_global_setting("debounce_seconds", 15)
        self.debounce_input.default = str(current_value)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(self.debounce_input.value)

            # Validate range
            if value < 1 or value > 30:
                await interaction.response.send_message("❌ Debounce delay must be between 1 and 30 seconds.", ephemeral=True)
                return

            # Save the setting
            self.cog.set_global_setting("debounce_seconds", value)

            await interaction.response.send_message(
                f"✅ Debounce delay set to **{value} seconds**. "
                f"This controls how long the bot waits after a prerequisite role change before enforcing color role prerequisites.",
                ephemeral=True,
            )

        except ValueError:
            await interaction.response.send_message("❌ Invalid input. Please enter a number between 1 and 30.", ephemeral=True)


class EditCategoryButton(ui.Button):
    """Button to edit a category."""

    def __init__(self, cog, guild_id: int, categories: List[Dict]):
        super().__init__(label="Edit Category", style=discord.ButtonStyle.primary, emoji="✏️")
        self.cog = cog
        self.guild_id = guild_id
        self.categories = categories

    async def callback(self, interaction: discord.Interaction):
        # Show select menu to choose category
        view = ui.View(timeout=900)
        select = CategorySelectMenu(self.cog, self.guild_id, self.categories, "edit")
        view.add_item(select)
        # Add back button
        view.add_item(BackToCategoriesButton(self.cog, self.guild_id))

        await interaction.response.edit_message(content="Select a category to edit:", view=view, embed=None)


class DeleteCategoryButton(ui.Button):
    """Button to delete a category."""

    def __init__(self, cog, guild_id: int, categories: List[Dict]):
        super().__init__(label="Delete Category", style=discord.ButtonStyle.danger, emoji="🗑️")
        self.cog = cog
        self.guild_id = guild_id
        self.categories = categories

    async def callback(self, interaction: discord.Interaction):
        # Show select menu to choose category
        view = ui.View(timeout=900)
        select = CategorySelectMenu(self.cog, self.guild_id, self.categories, "delete")
        view.add_item(select)
        # Add back button
        view.add_item(BackToCategoriesButton(self.cog, self.guild_id))

        await interaction.response.edit_message(content="⚠️ Select a category to DELETE:", view=view, embed=None)


class CategorySelectMenu(ui.Select):
    """Select menu for choosing a category."""

    def __init__(self, cog, guild_id: int, categories: List[Dict], action: str):
        self.cog = cog
        self.guild_id = guild_id
        self.action = action

        # Create options from categories, sorted alphabetically but retaining original index values
        indexed_categories = list(enumerate(categories[:25]))
        indexed_categories.sort(key=lambda pair: _natural_sort_key(pair[1].get("name", "")))

        options = [
            discord.SelectOption(label=cat.get("name"), value=str(orig_idx), description=f"{len(cat.get('roles', []))} roles configured")
            for orig_idx, cat in indexed_categories
        ]

        super().__init__(placeholder="Select a category...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        category_idx = int(self.values[0])
        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)

        if category_idx >= len(categories):
            await interaction.response.send_message("❌ Invalid category.", ephemeral=True)
            return

        category = categories[category_idx]

        if self.action == "delete":
            # Delete the category
            deleted_name = category.get("name")
            categories.pop(category_idx)
            # Persist categories sorted by name
            categories.sort(key=lambda c: _natural_sort_key(c.get("name", "")))
            self.cog.set_setting("categories", categories, guild_id=self.guild_id)

            # Refresh the category management view
            view = CategoryManagementView(self.cog, self.guild_id, categories)
            if categories:
                category_list = "\n".join(
                    [f"**{idx + 1}.** {cat.get('name')} ({len(cat.get('roles', []))} roles)" for idx, cat in enumerate(categories[:10])]
                )
                message = f"✅ Deleted category: **{deleted_name}**\n\n**Current Categories:**\n\n{category_list}\n\nSelect an action below:"
            else:
                message = (
                    f"✅ Deleted category: **{deleted_name}**\n\n**No categories configured**\n\nClick 'Create Category' to add your first category."
                )

            await interaction.response.edit_message(content=message, view=view)
        elif self.action == "edit":
            # Show role management for this category
            view = RoleManagementView(self.cog, self.guild_id, category_idx, category)

            roles = category.get("roles", [])
            # Sort roles by inheritance depth for display
            display_roles = _sort_roles_by_inheritance(roles)
            if display_roles:
                role_list = "\n".join(
                    [
                        f"**{idx + 1}.** <@&{role.get('role_id')}> - "
                        f"{len(role.get('prerequisite_roles', []))} prereqs"
                        + (f", inherits from <@&{role.get('inherits_from')}>" if role.get("inherits_from") else "")
                        for idx, role in enumerate(display_roles[:10])
                    ]
                )
                message = f"**Category: {category.get('name')}**\n\n{role_list}\n\nSelect an action:"
            else:
                message = f"**Category: {category.get('name')}**\n\nNo roles configured. Click 'Add Role' to get started."

            await interaction.response.edit_message(content=message, view=view, embed=None)


class BackToCategoriesButton(ui.Button):
    """Button to return to the category selection screen."""

    def __init__(self, cog, guild_id: int):
        super().__init__(label="Back to Categories", style=discord.ButtonStyle.secondary, emoji="⬅️")
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)
        view = CategoryManagementView(self.cog, self.guild_id, categories)

        if categories:
            sorted_categories = sorted(categories, key=lambda cat: _natural_sort_key(cat.get("name", "")))
            category_list = "\n".join(
                [f"**{idx + 1}.** {cat.get('name')} ({len(cat.get('roles', []))} roles)" for idx, cat in enumerate(sorted_categories[:10])]
            )
            message = f"**Current Categories:**\n\n{category_list}\n\nSelect an action below:"
        else:
            message = "**No categories configured**\n\nClick 'Create Category' to add your first category."

        await interaction.response.edit_message(content=message, view=view, embed=None)


class RoleManagementView(ui.View):
    """View for managing roles within a category."""

    def __init__(self, cog, guild_id: int, category_idx: int, category: Dict):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild_id = guild_id
        self.category_idx = category_idx
        self.category = category

        # Back to categories
        self.add_item(BackToCategoriesButton(self.cog, self.guild_id))

        # Add buttons
        self.add_item(AddRoleButton(self.cog, self.guild_id, self.category_idx, category))
        if category.get("roles"):
            self.add_item(EditRoleButton(self.cog, self.guild_id, self.category_idx, category))
            self.add_item(DeleteRoleButton(self.cog, self.guild_id, self.category_idx, category))


class AddRoleButton(ui.Button):
    """Button to add a role to a category."""

    def __init__(self, cog, guild_id: int, category_idx: int, category: Dict):
        super().__init__(label="Add Role", style=discord.ButtonStyle.success, emoji="➕")
        self.cog = cog
        self.guild_id = guild_id
        self.category_idx = category_idx
        self.category = category

    async def callback(self, interaction: discord.Interaction):
        # Step 1: Show role select view
        view = AddRoleStep1SelectRoleView(self.cog, self.guild_id, self.category_idx, self.category)
        await interaction.response.edit_message(
            content=f"**Add Role to {self.category.get('name')}**\n\n" f"**Step 1 of 3:** Select the role users will be able to pick:",
            view=view,
            embed=None,
        )


class AddRoleStep1SelectRoleView(ui.View):
    """Step 1: Select the role to add."""

    def __init__(self, cog, guild_id: int, category_idx: int, category: Dict):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild_id = guild_id
        self.category_idx = category_idx
        self.category = category

        # Add role select
        self.role_select = ui.RoleSelect(placeholder="Select a role...", min_values=1, max_values=1)
        self.role_select.callback = self.on_role_selected
        self.add_item(self.role_select)

    async def on_role_selected(self, interaction: discord.Interaction):
        selected_role = self.role_select.values[0]
        role_id = selected_role.id
        role_name = selected_role.name

        # Check if role already exists in this category
        if any(r.get("role_id") == role_id for r in self.category.get("roles", [])):
            await interaction.response.send_message(f"❌ {role_name} is already in this category.", ephemeral=True)
            return

        # Move to Step 2: Select inheritance
        # Sort existing roles by name for display
        existing_roles = _sort_roles_by_inheritance(self.category.get("roles", []))

        if existing_roles:
            view = AddRoleStep2SelectInheritanceView(self.cog, self.guild_id, self.category_idx, self.category, role_id, role_name)

            role_list = "\n".join([f"• **{r.get('name')}** (<@&{r.get('role_id')}>)" for r in existing_roles[:10]])

            await interaction.response.edit_message(
                content=f"**Add Role to {self.category.get('name')}**\n\n"
                f"Selected: **{role_name}**\n\n"
                f"**Step 2 of 3:** Select ONE role to inherit prerequisites from\n\n"
                f"Available roles:\n{role_list}\n\n"
                f"If this role inherits from another, users with ANY prerequisite from "
                f"the inherited role (and its chain) can select this role:",
                view=view,
            )
        else:
            # No existing roles, skip to Step 3
            view = AddRoleStep3SelectPrerequisitesView(self.cog, self.guild_id, self.category_idx, self.category, role_id, role_name, None)

            await interaction.response.edit_message(
                content=f"**Add Role to {self.category.get('name')}**\n\n"
                f"Selected: **{role_name}**\n\n"
                f"No existing roles to inherit from.\n\n"
                f"**Step 3 of 3:** Select additional prerequisite roles:",
                view=view,
            )


class AddRoleStep2SelectInheritanceView(ui.View):
    """Step 2: Select single role to inherit from."""

    def __init__(self, cog, guild_id: int, category_idx: int, category: Dict, role_id: int, role_name: str):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild_id = guild_id
        self.category_idx = category_idx
        self.category = category
        self.role_id = role_id
        self.role_name = role_name

        # Create select menu with existing roles (single selection)
        # Sort roles alphabetically for display
        existing_roles = _sort_roles_by_inheritance(category.get("roles", []))
        options = [
            discord.SelectOption(label=role.get("name", "Unknown"), value=str(role.get("role_id")), description="Inherits its prerequisites")
            for role in existing_roles[:25]
        ]

        self.inherit_select = ui.Select(placeholder="Select ONE role to inherit from...", min_values=1, max_values=1, options=options)
        self.inherit_select.callback = self.on_inheritance_selected
        self.add_item(self.inherit_select)

        # Add skip button
        skip_btn = ui.Button(label="Skip (No Inheritance)", style=discord.ButtonStyle.secondary)
        skip_btn.callback = self.on_skip_inheritance
        self.add_item(skip_btn)

    async def on_inheritance_selected(self, interaction: discord.Interaction):
        inherits_from_id = int(self.inherit_select.values[0])

        # Get the inherited role name
        inherited_role = next((r for r in self.category.get("roles", []) if r.get("role_id") == inherits_from_id), None)
        inherited_name = inherited_role.get("name", "Unknown") if inherited_role else "Unknown"

        # Move to Step 3
        await self.show_prerequisites_step(interaction, inherits_from_id, inherited_name)

    async def on_skip_inheritance(self, interaction: discord.Interaction):
        # Move to Step 3 without inheritance
        await self.show_prerequisites_step(interaction, None, None)

    async def show_prerequisites_step(self, interaction: discord.Interaction, inherits_from_id: Optional[int], inherited_name: Optional[str]):
        view = AddRoleStep3SelectPrerequisitesView(
            self.cog, self.guild_id, self.category_idx, self.category, self.role_id, self.role_name, inherits_from_id
        )

        inheritance_text = ""
        if inherited_name:
            inheritance_text = f"\n🔗 Inherits from: **{inherited_name}**\n"

        await interaction.response.edit_message(
            content=f"**Add Role to {self.category.get('name')}**\n\n"
            f"Selected: **{self.role_name}**{inheritance_text}\n"
            f"**Step 3 of 3:** Select ADDITIONAL prerequisite roles\n\n"
            f"Users must have at least ONE prerequisite (including inherited ones) "
            f"to select **{self.role_name}**:",
            view=view,
        )


class AddRoleStep3SelectPrerequisitesView(ui.View):
    """Step 3: Select additional prerequisite roles."""

    def __init__(self, cog, guild_id: int, category_idx: int, category: Dict, role_id: int, role_name: str, inherits_from: Optional[int]):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild_id = guild_id
        self.category_idx = category_idx
        self.category = category
        self.role_id = role_id
        self.role_name = role_name
        self.inherits_from = inherits_from
        self.prerequisite_role_ids: List[int] = []

        # Add prerequisite role select
        self.prereq_select = ui.RoleSelect(placeholder="Select additional prerequisite roles...", min_values=0, max_values=25)
        self.prereq_select.callback = self.on_prereqs_selected
        self.add_item(self.prereq_select)

        # Add save button
        save_btn = ui.Button(label="💾 Save Role", style=discord.ButtonStyle.success)
        save_btn.callback = self.on_save
        self.add_item(save_btn)

    async def on_prereqs_selected(self, interaction: discord.Interaction):
        self.prerequisite_role_ids = [role.id for role in self.prereq_select.values]

        # Build preview of what will be saved
        content = f"**Add Role to {self.category.get('name')}**\n\n"
        content += f"Selected: **{self.role_name}**\n\n"

        # Show inheritance
        if self.inherits_from:
            inherited_role = next((r for r in self.category.get("roles", []) if r.get("role_id") == self.inherits_from), None)
            if inherited_role:
                content += f"🔗 **Inherits from:** {inherited_role.get('name')} (<@&{self.inherits_from}>)\n"

                # Resolve inherited prerequisites
                inherited_prereqs = self._resolve_inherited_prereqs(self.inherits_from)
                if inherited_prereqs:
                    inherited_mentions = ", ".join([f"<@&{rid}>" for rid in inherited_prereqs])
                    content += f"   ↳ Inherited prerequisites: {inherited_mentions}\n"

        content += "\n"

        # Show additional prerequisites (alphabetically by role name)
        if self.prerequisite_role_ids:
            sorted_addl = _sort_role_ids_by_name(self.cog, self.guild_id, list(self.prerequisite_role_ids))
            prereq_mentions = ", ".join([f"<@&{rid}>" for rid in sorted_addl])
            content += f"📋 **Additional Prerequisites:** {prereq_mentions}\n\n"
        else:
            content += "📋 **Additional Prerequisites:** None\n\n"

        # Show full computed prerequisite set
        all_prereqs = set(self.prerequisite_role_ids)
        if self.inherits_from:
            all_prereqs.update(self._resolve_inherited_prereqs(self.inherits_from))

        if all_prereqs:
            sorted_all = _sort_role_ids_by_name(self.cog, self.guild_id, list(all_prereqs))
            all_mentions = ", ".join([f"<@&{rid}>" for rid in sorted_all])
            content += f"✅ **Full Prerequisite Set:** {all_mentions}\n"
            content += f"   (Users need ANY of these roles to select **{self.role_name}**)\n"
        else:
            content += "⚠️ **No prerequisites** - anyone can select this role!\n"

        content += "\nClick **💾 Save Role** to confirm."

        await interaction.response.edit_message(content=content, view=self)

    def _resolve_inherited_prereqs(self, inherits_from_id: int) -> set:
        """Recursively resolve all prerequisites from inherited role chain."""
        prereqs = set()
        visited = set()

        def resolve(role_id: int):
            if role_id in visited:
                return
            visited.add(role_id)

            # Find the role in the category
            role = next((r for r in self.category.get("roles", []) if r.get("role_id") == role_id), None)
            if not role:
                return

            # Add this role's direct prerequisites
            prereqs.update(role.get("prerequisite_roles", []))

            # Recursively resolve if it inherits from another role
            inherits_from = role.get("inherits_from")
            if inherits_from:
                prereqs.update(role.get("prerequisite_roles", []))
                resolve(inherits_from)

        resolve(inherits_from_id)
        return prereqs

    async def on_save(self, interaction: discord.Interaction):
        # Get categories and add role
        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)

        if self.category_idx >= len(categories):
            await interaction.response.send_message("❌ Category not found.", ephemeral=True)
            return

        category = categories[self.category_idx]

        # Create the role configuration
        new_role = {
            "role_id": self.role_id,
            "name": self.role_name,
            "prerequisite_roles": self.prerequisite_role_ids,
            "inherits_from": self.inherits_from,  # Single role ID or None
        }

        category["roles"].append(new_role)
        # Persist roles sorted by inheritance depth, categories by name
        category["roles"] = _sort_roles_by_inheritance(category["roles"])
        categories.sort(key=lambda c: _natural_sort_key(c.get("name", "")))
        self.cog.set_setting("categories", categories, guild_id=self.guild_id)

        # Build summary message
        summary = f"✅ Added <@&{self.role_id}> to **{category.get('name')}**\n\n"

        if self.inherits_from:
            inherited_role = next((r for r in category.get("roles", []) if r.get("role_id") == self.inherits_from), None)
            inherited_name = inherited_role.get("name", "Unknown") if inherited_role else "Unknown"
            summary += f"🔗 Inherits from: **{inherited_name}** (<@&{self.inherits_from}>)\n"

        if self.prerequisite_role_ids:
            prereq_mentions = ", ".join([f"<@&{rid}>" for rid in self.prerequisite_role_ids])
            summary += f"📋 Additional Prerequisites: {prereq_mentions}\n"
        else:
            summary += "📋 No additional prerequisites\n"

        if not self.inherits_from and not self.prerequisite_role_ids:
            summary += "\n⚠️ This role has no prerequisites - anyone can select it!"

        # After saving, return to the category management view for this category
        view = RoleManagementView(self.cog, self.guild_id, self.category_idx, category)

        roles = category.get("roles", [])
        display_roles = _sort_roles_by_inheritance(roles)
        if display_roles:
            role_list = "\n".join(
                [
                    f"**{idx + 1}.** <@&{role.get('role_id')}> - "
                    f"{len(role.get('prerequisite_roles', []))} prereqs"
                    + (f", inherits from <@&{role.get('inherits_from')}>" if role.get("inherits_from") else "")
                    for idx, role in enumerate(display_roles[:10])
                ]
            )
            summary += f"\n\n**Category: {category.get('name')}**\n\n{role_list}\n\nSelect an action:"
        else:
            summary += f"\n\n**Category: {category.get('name')}**\n\n" "No roles configured. Click 'Add Role' to get started."

        await interaction.response.edit_message(content=summary, view=view)


class EditRoleView(ui.View):
    """View for editing an existing role's configuration."""

    def __init__(self, cog, guild_id: int, category_idx: int, category: Dict, role_idx: int, role_config: Dict):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild_id = guild_id
        self.category_idx = category_idx
        self.category = category
        self.role_idx = role_idx
        self.role_config = role_config
        self.role_id = role_config.get("role_id")
        self.role_name = role_config.get("name")

        # Track current values (will be updated by callbacks)
        self.inherits_from = role_config.get("inherits_from")
        self.prerequisite_role_ids = list(role_config.get("prerequisite_roles", []))

        # Build inheritance select (single selection)
        existing_roles = [r for r in category.get("roles", []) if r.get("role_id") != self.role_id]
        # Sort for display
        existing_roles = _sort_roles_by_inheritance(existing_roles)
        if existing_roles:
            options = [
                discord.SelectOption(
                    label=role.get("name", "Unknown"),
                    value=str(role.get("role_id")),
                    description="Inherits its prerequisites",
                    default=(role.get("role_id") == self.inherits_from),
                )
                for role in existing_roles[:25]
            ]

            self.inherit_select = ui.Select(placeholder="Select ONE role to inherit from (or none)...", min_values=0, max_values=1, options=options)
            self.inherit_select.callback = self.on_inheritance_changed
            self.add_item(self.inherit_select)

        # Build prerequisites select (multi-selection with pre-population)
        default_prereq_roles = [discord.Object(id=rid) for rid in self.prerequisite_role_ids]
        self.prereq_select = ui.RoleSelect(
            placeholder="Select additional prerequisite roles...", min_values=0, max_values=25, default_values=default_prereq_roles
        )
        self.prereq_select.callback = self.on_prereqs_changed
        self.add_item(self.prereq_select)

        # Add save button
        save_btn = ui.Button(label="💾 Save Changes", style=discord.ButtonStyle.success)
        save_btn.callback = self.on_save
        self.add_item(save_btn)

        # Add cancel button
        cancel_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self.on_cancel
        self.add_item(cancel_btn)

    async def show(self, interaction: discord.Interaction):
        """Display the edit view with current configuration."""
        content = self._build_preview_message()
        await interaction.response.edit_message(content=content, view=self, embed=None)

    def _build_preview_message(self) -> str:
        """Build preview message showing current and computed configuration."""
        content = f"**Edit Role: {self.role_name}** (<@&{self.role_id}>)\n"
        content += f"**Category:** {self.category.get('name')}\n\n"

        # Show inheritance
        if self.inherits_from:
            inherited_role = next((r for r in self.category.get("roles", []) if r.get("role_id") == self.inherits_from), None)
            if inherited_role:
                content += f"🔗 **Inherits from:** {inherited_role.get('name')} (<@&{self.inherits_from}>)\n"

                # Resolve inherited prerequisites (alphabetically by role name)
                inherited_prereqs = self._resolve_inherited_prereqs(self.inherits_from)
                if inherited_prereqs:
                    sorted_inherited = _sort_role_ids_by_name(self.cog, self.guild_id, list(inherited_prereqs))
                    inherited_mentions = ", ".join([f"<@&{rid}>" for rid in sorted_inherited])
                    content += f"   ↳ Inherited prerequisites: {inherited_mentions}\n"
        else:
            content += "🔗 **Inherits from:** None\n"

        content += "\n"

        # Show additional prerequisites (alphabetically by role name)
        if self.prerequisite_role_ids:
            sorted_addl = _sort_role_ids_by_name(self.cog, self.guild_id, list(self.prerequisite_role_ids))
            prereq_mentions = ", ".join([f"<@&{rid}>" for rid in sorted_addl])
            content += f"📋 **Additional Prerequisites:** {prereq_mentions}\n\n"
        else:
            content += "📋 **Additional Prerequisites:** None\n\n"

        # Show full computed prerequisite set
        all_prereqs = set(self.prerequisite_role_ids)
        if self.inherits_from:
            all_prereqs.update(self._resolve_inherited_prereqs(self.inherits_from))

        if all_prereqs:
            sorted_all = _sort_role_ids_by_name(self.cog, self.guild_id, list(all_prereqs))
            all_mentions = ", ".join([f"<@&{rid}>" for rid in sorted_all])
            content += f"✅ **Full Prerequisite Set:** {all_mentions}\n"
            content += f"   (Users need ANY of these roles to select **{self.role_name}**)\n"
        else:
            content += "⚠️ **No prerequisites** - anyone can select this role!\n"

        content += "\nModify selections above, then click **💾 Save Changes** to confirm."

        return content

    async def on_inheritance_changed(self, interaction: discord.Interaction):
        """Handle inheritance selection change."""
        if self.inherit_select.values:
            self.inherits_from = int(self.inherit_select.values[0])
        else:
            self.inherits_from = None

        # Update the message with new preview
        content = self._build_preview_message()
        await interaction.response.edit_message(content=content, view=self)

    async def on_prereqs_changed(self, interaction: discord.Interaction):
        """Handle prerequisites selection change."""
        self.prerequisite_role_ids = [role.id for role in self.prereq_select.values]

        # Update the message with new preview
        content = self._build_preview_message()
        await interaction.response.edit_message(content=content, view=self)

    async def on_save(self, interaction: discord.Interaction):
        """Save the edited configuration."""
        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)

        if self.category_idx >= len(categories):
            await interaction.response.edit_message(content="❌ Category not found.", view=None)
            return

        category = categories[self.category_idx]
        roles = category.get("roles", [])

        if self.role_idx >= len(roles):
            await interaction.response.edit_message(content="❌ Role not found.", view=None)
            return

        # Update the role configuration
        roles[self.role_idx] = {
            "role_id": self.role_id,
            "name": self.role_name,
            "prerequisite_roles": self.prerequisite_role_ids,
            "inherits_from": self.inherits_from,
        }

        # Persist roles sorted by inheritance depth, categories by name
        categories[self.category_idx]["roles"] = _sort_roles_by_inheritance(roles)
        categories.sort(key=lambda c: _natural_sort_key(c.get("name", "")))
        self.cog.set_setting("categories", categories, guild_id=self.guild_id)

        # Build summary message
        summary = f"✅ Updated <@&{self.role_id}> in **{category.get('name')}**\n\n"

        if self.inherits_from:
            inherited_role = next((r for r in category.get("roles", []) if r.get("role_id") == self.inherits_from), None)
            inherited_name = inherited_role.get("name", "Unknown") if inherited_role else "Unknown"
            summary += f"🔗 Inherits from: **{inherited_name}** (<@&{self.inherits_from}>)\n"

        if self.prerequisite_role_ids:
            prereq_mentions = ", ".join([f"<@&{rid}>" for rid in self.prerequisite_role_ids])
            summary += f"📋 Additional Prerequisites: {prereq_mentions}\n"
        else:
            summary += "📋 No additional prerequisites\n"

        if not self.inherits_from and not self.prerequisite_role_ids:
            summary += "\n⚠️ This role has no prerequisites - anyone can select it!"

        await interaction.response.edit_message(content=summary, view=None)

    async def on_cancel(self, interaction: discord.Interaction):
        """Cancel editing and return to role management."""
        view = RoleManagementView(self.cog, self.guild_id, self.category_idx, self.category)

        roles = self.category.get("roles", [])
        display_roles = _sort_roles_by_inheritance(roles)
        role_list = "\n".join(
            [
                f"**{idx + 1}.** <@&{role.get('role_id')}> - "
                f"{len(role.get('prerequisite_roles', []))} prereqs"
                + (f", inherits from <@&{role.get('inherits_from')}>" if role.get("inherits_from") else "")
                for idx, role in enumerate(display_roles[:10])
            ]
        )
        message = f"**Category: {self.category.get('name')}**\n\n{role_list}\n\nSelect an action:"

        await interaction.response.edit_message(content=message, view=view, embed=None)

    def _resolve_inherited_prereqs(self, inherits_from_id: int) -> set:
        """Recursively resolve all prerequisites from inherited role chain."""
        prereqs = set()
        visited = set()

        def resolve(role_id: int):
            if role_id in visited:
                return
            visited.add(role_id)

            # Find the role in the category
            role = next((r for r in self.category.get("roles", []) if r.get("role_id") == role_id), None)
            if not role:
                return

            # Add this role's direct prerequisites
            prereqs.update(role.get("prerequisite_roles", []))

            # Recursively resolve if it inherits from another role
            inherits_from = role.get("inherits_from")
            if inherits_from:
                prereqs.update(role.get("prerequisite_roles", []))
                resolve(inherits_from)

        resolve(inherits_from_id)
        return prereqs


class EditRoleButton(ui.Button):
    """Button to edit a role in a category."""

    def __init__(self, cog, guild_id: int, category_idx: int, category: Dict):
        super().__init__(label="Edit Role", style=discord.ButtonStyle.primary, emoji="✏️")
        self.cog = cog
        self.guild_id = guild_id
        self.category_idx = category_idx
        self.category = category

    async def callback(self, interaction: discord.Interaction):
        # Show select menu to choose role
        view = ui.View(timeout=900)
        select = RoleSelectMenu(self.cog, self.guild_id, self.category_idx, self.category, "edit")
        view.add_item(select)

        await interaction.response.edit_message(content="Select a role to edit:", view=view, embed=None)


class DeleteRoleButton(ui.Button):
    """Button to delete a role from a category."""

    def __init__(self, cog, guild_id: int, category_idx: int, category: Dict):
        super().__init__(label="Delete Role", style=discord.ButtonStyle.danger, emoji="🗑️")
        self.cog = cog
        self.guild_id = guild_id
        self.category_idx = category_idx
        self.category = category

    async def callback(self, interaction: discord.Interaction):
        # Show select menu to choose role
        view = ui.View(timeout=900)
        select = RoleSelectMenu(self.cog, self.guild_id, self.category_idx, self.category, "delete")
        view.add_item(select)

        await interaction.response.edit_message(content="⚠️ Select a role to DELETE:", view=view, embed=None)


class RoleSelectMenu(ui.Select):
    """Select menu for choosing a role within a category."""

    def __init__(self, cog, guild_id: int, category_idx: int, category: Dict, action: str):
        self.cog = cog
        self.guild_id = guild_id
        self.category_idx = category_idx
        self.action = action

        # Create options from roles, sorted by name for display while retaining original indices
        indexed_roles = list(enumerate(category.get("roles", [])[:25]))
        all_roles = [pair[1] for pair in indexed_roles]
        indexed_roles.sort(key=lambda pair: _role_sort_key(pair[1], all_roles))

        options = [
            discord.SelectOption(
                label=f"{role.get('name', 'Unknown')}",
                value=str(orig_idx),
                description=f"{len(role.get('prerequisite_roles', []))} prereqs" + (", inherits" if role.get("inherits_from") else ""),
            )
            for orig_idx, role in indexed_roles
        ]

        super().__init__(placeholder="Select a role...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        role_idx = int(self.values[0])
        categories = self.cog.get_setting("categories", [], guild_id=self.guild_id)

        if self.category_idx >= len(categories):
            await interaction.response.send_message("❌ Category not found.", ephemeral=True)
            return

        category = categories[self.category_idx]
        roles = category.get("roles", [])

        if role_idx >= len(roles):
            await interaction.response.send_message("❌ Role not found.", ephemeral=True)
            return

        role_config = roles[role_idx]

        if self.action == "delete":
            # Delete the role
            deleted_name = role_config.get("name")
            roles.pop(role_idx)
            # Persist roles sorted by inheritance depth, categories by name
            category["roles"] = _sort_roles_by_inheritance(roles)
            categories.sort(key=lambda c: _natural_sort_key(c.get("name", "")))
            self.cog.set_setting("categories", categories, guild_id=self.guild_id)

            # Refresh the role management view
            view = RoleManagementView(self.cog, self.guild_id, self.category_idx, category)
            roles = category.get("roles", [])
            display_roles = _sort_roles_by_inheritance(roles)
            if display_roles:
                role_list = "\n".join(
                    [
                        f"**{idx + 1}.** <@&{role.get('role_id')}> - "
                        f"{len(role.get('prerequisite_roles', []))} prereqs"
                        + (f", inherits from <@&{role.get('inherits_from')}>" if role.get("inherits_from") else "")
                        for idx, role in enumerate(display_roles[:10])
                    ]
                )
                message = f"✅ Removed {deleted_name}\n\n**Category: {category.get('name')}**\n\n{role_list}\n\nSelect an action:"
            else:
                message = (
                    f"✅ Removed {deleted_name}\n\n**Category: {category.get('name')}**\n\nNo roles configured. Click 'Add Role' to get started."
                )

            await interaction.response.edit_message(content=message, view=view)
        elif self.action == "edit":
            # Show edit view with current values
            view = EditRoleView(self.cog, self.guild_id, self.category_idx, category, role_idx, role_config)
            await view.show(interaction)


class RoleColorLogChannelSelect(ui.ChannelSelect):
    """Channel select for choosing the role color logging channel."""

    def __init__(self, cog, guild_id: int):
        current_channel_id = cog.get_setting("role_color_log_channel_id", guild_id=guild_id)
        placeholder = "Select role color logging channel..."
        if current_channel_id:
            guild = cog.bot.get_guild(guild_id)
            if guild:
                channel = guild.get_channel(current_channel_id)
                if channel:
                    placeholder = f"Current: {channel.name}"

        super().__init__(placeholder=placeholder, min_values=0, max_values=1, channel_types=[discord.ChannelType.text])
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Handle channel selection."""
        if not self.values:
            # Clear the setting
            self.cog.set_setting("role_color_log_channel_id", None, self.guild_id)
        else:
            channel = self.values[0]
            self.cog.set_setting("role_color_log_channel_id", channel.id, self.guild_id)

        # Update the logging config view to show new channel
        log_channel_id = self.cog.get_setting("role_color_log_channel_id", guild_id=self.guild_id)

        embed = discord.Embed(
            title="📝 Configure Logging Channel",
            description="Select a channel to log role color changes, or clear to disable logging.",
            color=discord.Color.blue(),
        )

        if log_channel_id:
            guild = self.cog.bot.get_guild(self.guild_id)
            if guild:
                channel = guild.get_channel(log_channel_id)
                if channel:
                    embed.add_field(name="Current Channel", value=channel.mention, inline=False)
                else:
                    embed.add_field(name="Current Channel", value="⚠️ Channel not found", inline=False)
        else:
            embed.add_field(name="Current Channel", value="Not configured", inline=False)

        await interaction.response.edit_message(embed=embed)
