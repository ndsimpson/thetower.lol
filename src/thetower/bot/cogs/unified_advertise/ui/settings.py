# Standard library imports
from typing import Optional

# Third-party imports
import discord
from discord.ui import Button, Modal, Select, TextInput, View

from thetower.bot.ui.context import BaseSettingsView, SettingsViewContext


class AdTypeSelectionView(View):
    """View for selecting advertisement types."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)  # 5 minute timeout
        self.cog = context.cog_instance
        self.context = context

    @discord.ui.select(
        placeholder="Select advertisement type",
        options=[
            discord.SelectOption(label="Guild Advertisement", value="guild", description="Advertise your server"),
            discord.SelectOption(label="Member Advertisement", value="member", description="Advertise yourself as a member"),
        ],
    )
    async def select_ad_type(self, interaction: discord.Interaction, select: Select):
        """Handle advertisement type selection."""
        ad_type = select.values[0]

        if ad_type == "guild":
            from .core import GuildAdvertisementForm

            modal = GuildAdvertisementForm(self.context)
            await interaction.response.send_modal(modal)
        elif ad_type == "member":
            from .core import MemberAdvertisementForm

            modal = MemberAdvertisementForm(self.context)
            await interaction.response.send_modal(modal)


class AdListView(View):
    """View for listing advertisements."""

    def __init__(self, context: SettingsViewContext, ads: list, page: int = 0):
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context
        self.ads = ads
        self.page = page
        self.per_page = 5

    async def update_view(self, interaction: discord.Interaction):
        """Update the view with current page."""
        start_idx = self.page * self.per_page
        end_idx = start_idx + self.per_page
        page_ads = self.ads[start_idx:end_idx]

        embed = discord.Embed(
            title="Advertisement List",
            description=f"Page {self.page + 1} of {(len(self.ads) + self.per_page - 1) // self.per_page}",
            color=discord.Color.blue(),
        )

        if page_ads:
            for ad in page_ads:
                embed.add_field(
                    name=ad.get("title", "Untitled"), value=f"Type: {ad.get('type', 'Unknown')}\nStatus: {ad.get('status', 'Unknown')}", inline=False
                )
        else:
            embed.add_field(name="No advertisements", value="No advertisements found", inline=False)

        # Update buttons
        self.clear_items()

        if self.page > 0:
            prev_btn = Button(label="Previous", style=discord.ButtonStyle.secondary, emoji="⬅️")
            prev_btn.callback = self.previous_page
            self.add_item(prev_btn)

        if end_idx < len(self.ads):
            next_btn = Button(label="Next", style=discord.ButtonStyle.secondary, emoji="➡️")
            next_btn.callback = self.next_page
            self.add_item(next_btn)

        return embed

    async def previous_page(self, interaction: discord.Interaction):
        """Go to previous page."""
        self.page -= 1
        embed = await self.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=self)

    async def next_page(self, interaction: discord.Interaction):
        """Go to next page."""
        self.page += 1
        embed = await self.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=self)


class AdDetailView(View):
    """View for displaying advertisement details."""

    def __init__(self, context: SettingsViewContext, ad_data: dict):
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context
        self.ad_data = ad_data

    async def update_view(self, interaction: discord.Interaction):
        """Update the view with advertisement details."""
        embed = discord.Embed(title=self.ad_data.get("title", "Advertisement Details"), color=discord.Color.blue())

        embed.add_field(name="Type", value=self.ad_data.get("type", "Unknown"), inline=True)
        embed.add_field(name="Status", value=self.ad_data.get("status", "Unknown"), inline=True)
        embed.add_field(name="Created", value=self.ad_data.get("created_at", "Unknown"), inline=True)

        if "description" in self.ad_data:
            embed.add_field(name="Description", value=self.ad_data["description"], inline=False)

        # Update buttons
        self.clear_items()

        # Add action buttons based on ad status and user permissions
        if self.ad_data.get("status") == "active":
            delete_btn = Button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️")
            delete_btn.callback = self.delete_ad
            self.add_item(delete_btn)

        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️")
        back_btn.callback = self.go_back
        self.add_item(back_btn)

        return embed

    async def delete_ad(self, interaction: discord.Interaction):
        """Delete the advertisement."""
        # Implementation would depend on how ads are stored
        await interaction.response.send_message("Delete functionality not yet implemented", ephemeral=True)

    async def go_back(self, interaction: discord.Interaction):
        """Go back to list view."""
        # This would need to be implemented based on the calling context
        await interaction.response.send_message("Back functionality not yet implemented", ephemeral=True)


class SettingsModal(Modal):
    """Modal for changing a setting value."""

    def __init__(self, context: SettingsViewContext, setting_name: str, title: str, placeholder: str):
        super().__init__(title=title, timeout=900)
        self.cog = context.cog_instance
        self.guild_id = context.guild_id
        self.setting_name = setting_name

        self.value_input = TextInput(label="Value", placeholder=placeholder, required=True, max_length=20)
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle setting update."""
        try:
            # Convert value to int
            value = int(self.value_input.value)

            # Handle special case: 0 means None for optional settings
            if value == 0 and self.setting_name in ["mod_channel_id", "testing_channel_id"]:
                value = None

            # Update setting
            self.cog.set_setting(self.setting_name, value, guild_id=self.guild_id)

            await interaction.response.send_message(f"✅ Updated {self.setting_name} to {value if value is not None else 'None'}", ephemeral=True)

        except ValueError:
            await interaction.response.send_message("❌ Invalid value. Please enter a number.", ephemeral=True)
        except Exception as e:
            self.cog.logger.error(f"Error updating setting: {e}")
            await interaction.response.send_message(f"❌ Error updating setting: {e}", ephemeral=True)


class GuildSettingsView(View):
    """View for managing guild-specific advertisement settings."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)  # 10 minute timeout
        self.cog = context.cog_instance
        self.context = context
        self.guild_id = context.guild_id

    async def update_view(self, interaction: discord.Interaction):
        """Update the view with current guild settings."""
        # Get guild-specific settings
        cooldown_hours = self.cog._get_cooldown_hours(self.guild_id)
        advertise_channel_id = self.cog._get_advertise_channel_id(self.guild_id)
        mod_channel_id = self.cog._get_mod_channel_id(self.guild_id)
        testing_channel_id = self.cog._get_testing_channel_id(self.guild_id)
        debug_enabled = self.cog.get_setting("debug_enabled", default=False, guild_id=self.guild_id)
        custom_tags = self.cog._get_custom_tags(self.guild_id)

        # Get guild name
        guild = self.cog.bot.get_guild(self.guild_id)
        guild_name = guild.name if guild else f"Guild {self.guild_id}"

        embed = discord.Embed(title="⚙️ Guild Advertisement Settings", description=f"Configuration for {guild_name}", color=discord.Color.blue())

        # Time Settings
        embed.add_field(name="⏰ Advertisement Cooldown", value=f"{cooldown_hours} hours", inline=False)

        # Channel Settings
        advertise_channel = self.cog.bot.get_channel(advertise_channel_id) if advertise_channel_id else None
        channel_name = advertise_channel.mention if advertise_channel else f"ID: {advertise_channel_id}" if advertise_channel_id else "Not configured"
        embed.add_field(name="📢 Advertisement Channel", value=channel_name, inline=False)

        # Mod Channel Settings
        mod_channel = self.cog.bot.get_channel(mod_channel_id) if mod_channel_id else None
        mod_channel_name = mod_channel.mention if mod_channel else "Not configured"
        embed.add_field(name="🛡️ Moderation Channel", value=mod_channel_name, inline=False)

        # Testing/Debug Channel Settings
        testing_channel = self.cog.bot.get_channel(testing_channel_id) if testing_channel_id else None
        testing_channel_name = testing_channel.mention if testing_channel else "Not configured"
        debug_status = "✅ Enabled" if debug_enabled else "❌ Disabled"
        embed.add_field(name="🔧 Debug Settings", value=f"Testing Channel: {testing_channel_name}\nDebug Messages: {debug_status}", inline=False)

        # Custom Tags summary
        if custom_tags:
            tag_lines = []
            for group in custom_tags:
                type_label = "group" if group.get("type") == "group" else "solo"
                count = len(group.get("options", []))
                tag_lines.append(f"• **{group['label']}** [{type_label}, {count} option(s)]")
            embed.add_field(name="🏷️ Custom Tags", value="\n".join(tag_lines) or "None", inline=False)
        else:
            embed.add_field(name="🏷️ Custom Tags", value="No custom tags configured.", inline=False)

        # Stats
        guild_cooldowns = self.cog.cooldowns.get(self.guild_id, {"users": {}, "guilds": {}})
        guild_pending = sum(1 for _, _, _, _, gid, _, _ in self.cog.pending_deletions if gid == self.guild_id)

        embed.add_field(
            name="📊 Statistics",
            value=f"Active User Cooldowns: {len(guild_cooldowns.get('users', {}))}\n"
            f"Active Guild Cooldowns: {len(guild_cooldowns.get('guilds', {}))}\n"
            f"Pending Deletions: {guild_pending}",
            inline=False,
        )

        # Add buttons
        self.clear_items()

        # Change cooldown button
        cooldown_btn = Button(label="Set Cooldown", style=discord.ButtonStyle.primary, emoji="⏰")
        cooldown_btn.callback = self.set_cooldown
        self.add_item(cooldown_btn)

        # Set ad channel button
        channel_btn = Button(label="Set Ad Channel", style=discord.ButtonStyle.primary, emoji="📢")
        channel_btn.callback = self.set_ad_channel
        self.add_item(channel_btn)

        # Set mod channel button
        mod_btn = Button(label="Set Mod Channel", style=discord.ButtonStyle.primary, emoji="🛡️")
        mod_btn.callback = self.set_mod_channel
        self.add_item(mod_btn)

        # Set testing channel button
        testing_btn = Button(label="Set Testing Channel", style=discord.ButtonStyle.secondary, emoji="🔧")
        testing_btn.callback = self.set_testing_channel
        self.add_item(testing_btn)

        # Toggle debug button
        debug_btn = Button(
            label="Disable Debug" if debug_enabled else "Enable Debug",
            style=discord.ButtonStyle.danger if debug_enabled else discord.ButtonStyle.success,
            emoji="🔕" if debug_enabled else "🔔",
        )
        debug_btn.callback = self.toggle_debug
        self.add_item(debug_btn)

        # Custom tags management button
        custom_tags_btn = Button(label="Manage Custom Tags", style=discord.ButtonStyle.secondary, emoji="🏷️")
        custom_tags_btn.callback = self.manage_custom_tags
        self.add_item(custom_tags_btn)

        # Back button
        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️")
        back_btn.callback = self.go_back
        self.add_item(back_btn)

        return embed
        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️")
        back_btn.callback = self.go_back
        self.add_item(back_btn)

        return embed

    async def set_cooldown(self, interaction: discord.Interaction):
        """Show modal to set cooldown hours."""
        modal = SettingsModal(self.context, "cooldown_hours", "Set Cooldown Hours", "Enter cooldown hours (e.g., 168 for 7 days)")
        await interaction.response.send_modal(modal)

    async def set_ad_channel(self, interaction: discord.Interaction):
        """Show channel selector for advertisement channel."""
        view = View(timeout=900)

        # Create channel select for forum channels only
        channel_select = discord.ui.ChannelSelect(
            placeholder="Select advertisement forum channel", channel_types=[discord.ChannelType.forum], min_values=1, max_values=1
        )

        async def channel_callback(select_interaction: discord.Interaction):
            selected_channel = channel_select.values[0]
            self.cog.set_setting("advertise_channel_id", selected_channel.id, guild_id=self.guild_id)
            await select_interaction.response.send_message(f"✅ Set advertisement channel to {selected_channel.mention}", ephemeral=True)

        channel_select.callback = channel_callback
        view.add_item(channel_select)
        await interaction.response.send_message("Select the forum channel for advertisements:", view=view, ephemeral=True)

    async def set_mod_channel(self, interaction: discord.Interaction):
        """Show channel selector for moderation channel."""
        view = View(timeout=900)

        # Create channel select for text channels
        channel_select = discord.ui.ChannelSelect(
            placeholder="Select moderation notification channel", channel_types=[discord.ChannelType.text], min_values=0, max_values=1
        )

        async def channel_callback(select_interaction: discord.Interaction):
            if channel_select.values:
                selected_channel = channel_select.values[0]
                self.cog.set_setting("mod_channel_id", selected_channel.id, guild_id=self.guild_id)
                await select_interaction.response.send_message(f"✅ Set moderation channel to {selected_channel.mention}", ephemeral=True)
            else:
                self.cog.set_setting("mod_channel_id", None, guild_id=self.guild_id)
                await select_interaction.response.send_message("✅ Cleared moderation channel", ephemeral=True)

        channel_select.callback = channel_callback
        view.add_item(channel_select)

        # Add a clear button
        clear_btn = Button(label="Clear Channel", style=discord.ButtonStyle.secondary)

        async def clear_callback(clear_interaction: discord.Interaction):
            self.cog.set_setting("mod_channel_id", None, guild_id=self.guild_id)
            await clear_interaction.response.send_message("✅ Cleared moderation channel", ephemeral=True)

        clear_btn.callback = clear_callback
        view.add_item(clear_btn)

        await interaction.response.send_message("Select the text channel for moderation notifications (or click Clear):", view=view, ephemeral=True)

    async def manage_custom_tags(self, interaction: discord.Interaction):
        """Open the custom tag management view."""
        view = CustomTagsManagementView(self.context)
        embed = await view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    async def set_testing_channel(self, interaction: discord.Interaction):
        """Show channel selector for testing/debug channel."""
        view = View(timeout=900)

        # Create channel select for text channels only
        channel_select = discord.ui.ChannelSelect(placeholder="Select testing channel for debug messages", channel_types=[discord.ChannelType.text])

        async def channel_callback(select_interaction: discord.Interaction):
            channel_id = channel_select.values[0].id
            self.cog.set_setting("testing_channel_id", channel_id, guild_id=self.guild_id)
            await select_interaction.response.send_message(f"✅ Set testing channel to <#{channel_id}>", ephemeral=True)

        channel_select.callback = channel_callback
        view.add_item(channel_select)

        # Add a clear button
        clear_btn = Button(label="Clear Channel", style=discord.ButtonStyle.secondary)

        async def clear_callback(clear_interaction: discord.Interaction):
            self.cog.set_setting("testing_channel_id", None, guild_id=self.guild_id)
            await clear_interaction.response.send_message("✅ Cleared testing channel", ephemeral=True)

        clear_btn.callback = clear_callback
        view.add_item(clear_btn)

        await interaction.response.send_message("Select the text channel for debug messages (or click Clear):", view=view, ephemeral=True)

    async def toggle_debug(self, interaction: discord.Interaction):
        """Toggle debug messages on/off."""
        current_state = self.cog.get_setting("debug_enabled", default=False, guild_id=self.guild_id)
        new_state = not current_state

        self.cog.set_setting("debug_enabled", new_state, guild_id=self.guild_id)

        status = "enabled" if new_state else "disabled"
        await interaction.response.send_message(f"✅ Debug messages {status}", ephemeral=True)

        # Refresh the settings view to show updated state
        embed = await self.update_view(interaction)
        await interaction.message.edit(embed=embed, view=self)

    async def go_back(self, interaction: discord.Interaction):
        """Go back to main settings view."""
        main_view = UnifiedAdvertiseSettingsView(self.context)
        embed = await main_view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=main_view)


class SettingsView(View):
    """View for managing bot settings."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context

    async def update_view(self, interaction: discord.Interaction):
        """Update the view with current settings."""
        remember_last_ad = self.cog.get_global_setting("remember_last_ad", default=True)
        embed = discord.Embed(title="Bot Settings", description="Configure bot behavior and preferences", color=discord.Color.green())

        # Add current settings
        embed.add_field(name="Default Cooldown", value=f"{self.cog.guild_settings.get('cooldown_hours', 24)} hours", inline=True)

        # Global: remember last ad
        embed.add_field(
            name="💾 Remember Last Ad",
            value=(
                f"{'✅ Enabled' if remember_last_ad else '❌ Disabled'} — "
                "When enabled, users can re-use their last advertisement as a pre-filled template when posting a new one."
            ),
            inline=False,
        )

        embed.add_field(
            name="Default Settings", value="These are the default values used when no server-specific settings are configured.", inline=False
        )

        # Update buttons
        self.clear_items()

        # Toggle remember last ad — bot owner only
        if self.context.is_bot_owner:
            toggle_label = "Disable Remember Last Ad" if remember_last_ad else "Enable Remember Last Ad"
            toggle_style = discord.ButtonStyle.danger if remember_last_ad else discord.ButtonStyle.success
            toggle_btn = Button(label=toggle_label, style=toggle_style, emoji="💾")
            toggle_btn.callback = self.toggle_remember_last_ad
            self.add_item(toggle_btn)

        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️")
        back_btn.callback = self.go_back
        self.add_item(back_btn)

        return embed

    async def toggle_remember_last_ad(self, interaction: discord.Interaction):
        """Toggle the remember_last_ad global setting."""
        current = self.cog.get_global_setting("remember_last_ad", default=True)
        self.cog.set_global_setting("remember_last_ad", not current)
        status = "enabled" if not current else "disabled"
        await interaction.response.send_message(f"✅ Remember Last Ad has been {status}.", ephemeral=True)
        embed = await self.update_view(interaction)
        await interaction.message.edit(embed=embed, view=self)

    async def go_back(self, interaction: discord.Interaction):
        """Go back to main settings view."""
        main_view = UnifiedAdvertiseSettingsView(self.context)
        embed = await main_view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=main_view)


class UnifiedAdvertiseSettingsView(BaseSettingsView):
    """Main settings view for the unified advertise system."""

    def __init__(self, context: SettingsViewContext, guild_id: Optional[int] = None):
        super().__init__(context)
        self.guild_id = guild_id or context.guild_id

    async def update_view(self, interaction: discord.Interaction):
        """Update the main settings view."""
        # If we have a guild context and no specific guild_id was provided,
        # directly show the guild settings
        if interaction.guild and not self.guild_id:
            guild_settings_view = GuildSettingsView(
                SettingsViewContext(guild_id=interaction.guild.id, cog_instance=self.cog, interaction=interaction, is_bot_owner=self.ctx.is_bot_owner)
            )
            embed = await guild_settings_view.update_view(interaction)
            # Copy buttons from the guild settings view to this view
            self.clear_items()
            for item in guild_settings_view.children:
                self.add_item(item)
            return embed

        # If we have a specific guild_id, show that guild's settings
        if self.guild_id:
            guild_settings_view = GuildSettingsView(
                SettingsViewContext(guild_id=self.guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=self.ctx.is_bot_owner)
            )
            embed = await guild_settings_view.update_view(interaction)
            # Copy buttons from the guild settings view to this view
            self.clear_items()
            for item in guild_settings_view.children:
                self.add_item(item)
            return embed

        # Fallback: show the menu for choosing between server and default settings
        embed = discord.Embed(
            title="Unified Advertise Settings", description="Manage advertisement settings for this server", color=discord.Color.purple()
        )

        # Get current guild settings
        guild_id = interaction.guild.id if interaction.guild else None
        if guild_id:
            cooldown_hours = self.cog._get_cooldown_hours(guild_id)
            embed.add_field(name="Server Cooldown", value=f"{cooldown_hours} hours between advertisements", inline=True)

        embed.add_field(name="Default Settings", value=f"Default cooldown: {self.cog.guild_settings.get('cooldown_hours', 24)} hours", inline=False)

        # Update buttons
        self.clear_items()

        if interaction.guild:
            guild_settings_btn = Button(label="Server Settings", style=discord.ButtonStyle.primary, emoji="🏠")
            guild_settings_btn.callback = self.guild_settings
            self.add_item(guild_settings_btn)

        global_settings_btn = Button(label="Default Settings", style=discord.ButtonStyle.secondary, emoji="🌍")
        global_settings_btn.callback = self.default_settings
        self.add_item(global_settings_btn)

        return embed

    async def guild_settings(self, interaction: discord.Interaction):
        """Open guild-specific settings."""
        guild_id = interaction.guild.id
        settings_view = GuildSettingsView(
            SettingsViewContext(guild_id=guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=self.ctx.is_bot_owner)
        )
        embed = await settings_view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=settings_view)

    async def default_settings(self, interaction: discord.Interaction):
        """Open default settings."""
        settings_view = SettingsView(self.ctx)
        embed = await settings_view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=settings_view)


# ====================
# Custom Tag Management
# ====================


class AddGroupTagModal(Modal, title="Add Tag Group"):
    """Modal for creating a new group-type custom tag (pick-one from multiple options)."""

    group_label = TextInput(
        label="Label (shown to users)",
        placeholder="e.g. How many members are in your guild?",
        required=True,
        max_length=100,
    )

    def __init__(self, context: SettingsViewContext) -> None:
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.guild_id = context.guild_id
        self.context = context

    async def on_submit(self, interaction: discord.Interaction) -> None:
        import uuid

        existing = list(self.cog._get_custom_tags(self.guild_id))
        new_group = {
            "id": str(uuid.uuid4())[:8],
            "label": self.group_label.value.strip(),
            "type": "group",
            "options": [],
        }
        existing.append(new_group)
        self.cog.set_setting("custom_tags", existing, guild_id=self.guild_id)
        view = TagGroupOptionsView(self.context, new_group["id"])
        embed = await view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=view)


class AddSoloTagModal(Modal, title="Add Solo Tag"):
    """Modal for creating a new solo-type custom tag (independent on/off toggle)."""

    tag_name = TextInput(
        label="Display Name (shown to users)",
        placeholder="e.g. Looking for members",
        required=True,
        max_length=100,
    )
    tag_id_input = TextInput(
        label="Discord Forum Tag ID",
        placeholder="Paste the integer tag ID from developer mode",
        required=True,
        max_length=20,
    )

    def __init__(self, context: SettingsViewContext) -> None:
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.guild_id = context.guild_id
        self.context = context

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            tag_id = int(self.tag_id_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Tag ID must be a number (integer).", ephemeral=True)
            return

        import uuid

        name = self.tag_name.value.strip()
        existing = list(self.cog._get_custom_tags(self.guild_id))
        new_entry = {
            "id": str(uuid.uuid4())[:8],
            "label": name,
            "type": "solo",
            "options": [{"tag_id": tag_id, "name": name}],
        }
        existing.append(new_entry)
        self.cog.set_setting("custom_tags", existing, guild_id=self.guild_id)
        view = CustomTagsManagementView(self.context)
        embed = await view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=view)


class AddTagOptionModal(Modal, title="Add Tag Option"):
    """Modal for adding a tag option to an existing tag group."""

    tag_id_input = TextInput(
        label="Discord Forum Tag ID",
        placeholder="Paste the integer tag ID from developer mode",
        required=True,
        max_length=20,
    )
    tag_name = TextInput(
        label="Display Name (shown to users)",
        placeholder="e.g. 1-10 members",
        required=True,
        max_length=80,
    )

    def __init__(self, context: SettingsViewContext, group_id: str) -> None:
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.guild_id = context.guild_id
        self.group_id = group_id
        self.context = context

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            tag_id = int(self.tag_id_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Tag ID must be a number (integer).", ephemeral=True)
            return

        custom_tags = list(self.cog._get_custom_tags(self.guild_id))
        found = False
        for group in custom_tags:
            if group["id"] == self.group_id:
                group["options"].append({"tag_id": tag_id, "name": self.tag_name.value.strip()})
                found = True
                break

        if not found:
            await interaction.response.send_message("❌ Tag group not found.", ephemeral=True)
            return

        self.cog.set_setting("custom_tags", custom_tags, guild_id=self.guild_id)
        await interaction.response.send_message(f"✅ Added option **{self.tag_name.value.strip()}** (Tag ID: `{tag_id}`).", ephemeral=True)


class TagGroupOptionsView(View):
    """View for managing options within a single tag group."""

    def __init__(self, context: SettingsViewContext, group_id: str) -> None:
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context
        self.guild_id = context.guild_id
        self.group_id = group_id

    async def update_view(self, interaction: discord.Interaction) -> discord.Embed:
        """Build and return the embed for this view."""
        custom_tags = self.cog._get_custom_tags(self.guild_id)
        group = next((g for g in custom_tags if g["id"] == self.group_id), None)

        if not group:
            return discord.Embed(title="❌ Group not found", color=discord.Color.red())

        type_label = "Group (pick one)" if group["type"] == "group" else "Solo (on/off toggle)"
        embed = discord.Embed(
            title=f"🏷️ Options: {group['label']}",
            description=f"**Type:** {type_label}",
            color=discord.Color.gold(),
        )

        if group.get("options"):
            lines = [f"• **{opt['name']}** — Tag ID: `{opt['tag_id']}`" for opt in group["options"]]
            embed.add_field(name="Current Options", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Options", value="No options yet. Add some below!", inline=False)

        self.clear_items()

        add_btn = Button(label="Add Option", style=discord.ButtonStyle.success, emoji="➕")
        add_btn.callback = self.add_option
        self.add_item(add_btn)

        if group.get("options"):
            remove_btn = Button(label="Remove Option", style=discord.ButtonStyle.danger, emoji="🗑️")
            remove_btn.callback = self.remove_option
            self.add_item(remove_btn)

        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️")
        back_btn.callback = self.go_back
        self.add_item(back_btn)

        return embed

    async def add_option(self, interaction: discord.Interaction) -> None:
        modal = AddTagOptionModal(self.context, self.group_id)
        await interaction.response.send_modal(modal)

    async def remove_option(self, interaction: discord.Interaction) -> None:
        custom_tags = self.cog._get_custom_tags(self.guild_id)
        group = next((g for g in custom_tags if g["id"] == self.group_id), None)
        if not group or not group.get("options"):
            await interaction.response.send_message("No options to remove.", ephemeral=True)
            return

        options = [discord.SelectOption(label=f"{opt['name']} (ID: {opt['tag_id']})"[:100], value=str(opt["tag_id"])) for opt in group["options"]]
        select = Select(placeholder="Select option to remove", options=options)

        async def select_callback(select_interaction: discord.Interaction) -> None:
            tag_id_to_remove = int(select.values[0])
            tags_list = list(self.cog._get_custom_tags(self.guild_id))
            for g in tags_list:
                if g["id"] == self.group_id:
                    g["options"] = [o for o in g["options"] if o["tag_id"] != tag_id_to_remove]
                    break
            self.cog.set_setting("custom_tags", tags_list, guild_id=self.guild_id)
            await select_interaction.response.send_message("✅ Option removed.", ephemeral=True)

        select.callback = select_callback
        view = View(timeout=900)
        view.add_item(select)
        await interaction.response.send_message("Select the option to remove:", view=view, ephemeral=True)

    async def go_back(self, interaction: discord.Interaction) -> None:
        view = CustomTagsManagementView(self.context)
        embed = await view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=view)


class TagEditSelectorView(View):
    """Inline selector view for choosing which tag to edit."""

    def __init__(self, context: SettingsViewContext) -> None:
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context
        self.guild_id = context.guild_id

    async def update_view(self, interaction: discord.Interaction) -> discord.Embed:
        custom_tags = self.cog._get_custom_tags(self.guild_id)

        embed = discord.Embed(
            title="✏️ Edit Tags — Select a Tag",
            description="Choose a tag group or solo tag to edit its options.",
            color=discord.Color.blurple(),
        )

        self.clear_items()

        options = []
        for g in custom_tags:
            type_indicator = "[Group]" if g.get("type") == "group" else "[Solo]"
            options.append(discord.SelectOption(label=f"{g['label']} {type_indicator}"[:100], value=g["id"]))

        select = Select(placeholder="Select a tag to edit…", options=options)

        async def select_callback(select_interaction: discord.Interaction) -> None:
            group_id = select.values[0]
            view = TagGroupOptionsView(self.context, group_id)
            edit_embed = await view.update_view(select_interaction)
            await select_interaction.response.edit_message(embed=edit_embed, view=view)

        select.callback = select_callback
        self.add_item(select)

        cancel_btn = Button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")

        async def cancel_callback(cancel_interaction: discord.Interaction) -> None:
            back_view = CustomTagsManagementView(self.context)
            back_embed = await back_view.update_view(cancel_interaction)
            await cancel_interaction.response.edit_message(embed=back_embed, view=back_view)

        cancel_btn.callback = cancel_callback
        self.add_item(cancel_btn)

        return embed


class TagDeleteSelectorView(View):
    """Inline selector view for choosing which tag to delete."""

    def __init__(self, context: SettingsViewContext) -> None:
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context
        self.guild_id = context.guild_id

    async def update_view(self, interaction: discord.Interaction) -> discord.Embed:
        custom_tags = self.cog._get_custom_tags(self.guild_id)

        embed = discord.Embed(
            title="🗑️ Delete Tag — Select a Tag",
            description="Choose a tag group or solo tag to delete.",
            color=discord.Color.red(),
        )

        self.clear_items()

        options = []
        for g in custom_tags:
            type_indicator = "[Group]" if g.get("type") == "group" else "[Solo]"
            options.append(discord.SelectOption(label=f"{g['label']} {type_indicator}"[:100], value=g["id"]))

        select = Select(placeholder="Select a tag to delete…", options=options)

        async def select_callback(select_interaction: discord.Interaction) -> None:
            group_id = select.values[0]
            remaining = [g for g in self.cog._get_custom_tags(self.guild_id) if g["id"] != group_id]
            self.cog.set_setting("custom_tags", remaining, guild_id=self.guild_id)
            back_view = CustomTagsManagementView(self.context)
            back_embed = await back_view.update_view(select_interaction)
            await select_interaction.response.edit_message(content="✅ Tag deleted.", embed=back_embed, view=back_view)

        select.callback = select_callback
        self.add_item(select)

        cancel_btn = Button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")

        async def cancel_callback(cancel_interaction: discord.Interaction) -> None:
            back_view = CustomTagsManagementView(self.context)
            back_embed = await back_view.update_view(cancel_interaction)
            await cancel_interaction.response.edit_message(embed=back_embed, view=back_view)

        cancel_btn.callback = cancel_callback
        self.add_item(cancel_btn)

        return embed


class CustomTagsManagementView(View):
    """View for listing, adding, and deleting custom tag groups for a guild."""

    def __init__(self, context: SettingsViewContext) -> None:
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context
        self.guild_id = context.guild_id

    async def update_view(self, interaction: discord.Interaction) -> discord.Embed:
        """Build and return the embed for this view."""
        custom_tags = self.cog._get_custom_tags(self.guild_id)

        embed = discord.Embed(
            title="🏷️ Custom Tag Management",
            description=(
                "Configure tags that users can apply to their guild advertisements.\n\n"
                "**Group** tags let users pick exactly one option from a list.\n"
                "**Solo** tags are independent on/off toggles."
            ),
            color=discord.Color.gold(),
        )

        if custom_tags:
            # Group tags — one field each
            for group in custom_tags:
                if group.get("type") != "solo":
                    opts = group.get("options", [])
                    opts_text = "\n".join(f"  • {o['name']} (ID: `{o['tag_id']}`)" for o in opts) if opts else "  *(no options yet)*"
                    embed.add_field(name=f"{group['label']} [Group]", value=opts_text, inline=False)

            # Solo tags — all in one field
            solo_tags = [g for g in custom_tags if g.get("type") == "solo"]
            if solo_tags:
                solo_lines = []
                for g in solo_tags:
                    opts = g.get("options", [])
                    tag_id = opts[0]["tag_id"] if opts else "*(no tag ID set)*"
                    solo_lines.append(f"{g['label']}: {tag_id}")
                embed.add_field(name="Solo Tags", value="\n".join(solo_lines), inline=False)
        else:
            embed.add_field(name="No custom tags", value="No tag groups have been configured yet.", inline=False)

        self.clear_items()

        refresh_btn = Button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄")
        refresh_btn.callback = self.refresh
        self.add_item(refresh_btn)

        add_group_btn = Button(label="Add Tag Group", style=discord.ButtonStyle.success, emoji="📦")
        add_group_btn.callback = self.add_tag_group
        self.add_item(add_group_btn)

        add_solo_btn = Button(label="Add Solo Tag", style=discord.ButtonStyle.success, emoji="🏷️")
        add_solo_btn.callback = self.add_solo_tag
        self.add_item(add_solo_btn)

        if custom_tags:
            edit_btn = Button(label="Edit Tags", style=discord.ButtonStyle.primary, emoji="⚙️")
            edit_btn.callback = self.edit_tags
            self.add_item(edit_btn)

            delete_group_btn = Button(label="Delete Tag", style=discord.ButtonStyle.danger, emoji="🗑️")
            delete_group_btn.callback = self.delete_tag_group
            self.add_item(delete_group_btn)

        back_btn = Button(label="Back to Settings", style=discord.ButtonStyle.secondary, emoji="⬅️")
        back_btn.callback = self.go_back
        self.add_item(back_btn)

        return embed

    async def add_tag_group(self, interaction: discord.Interaction) -> None:
        modal = AddGroupTagModal(self.context)
        await interaction.response.send_modal(modal)

    async def add_solo_tag(self, interaction: discord.Interaction) -> None:
        modal = AddSoloTagModal(self.context)
        await interaction.response.send_modal(modal)

    async def refresh(self, interaction: discord.Interaction) -> None:
        embed = await self.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=self)

    async def delete_tag_group(self, interaction: discord.Interaction) -> None:
        custom_tags = self.cog._get_custom_tags(self.guild_id)
        if not custom_tags:
            await interaction.response.send_message("No tags to delete.", ephemeral=True)
            return

        view = TagDeleteSelectorView(self.context)
        embed = await view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    async def edit_tags(self, interaction: discord.Interaction) -> None:
        custom_tags = self.cog._get_custom_tags(self.guild_id)
        if not custom_tags:
            await interaction.response.send_message("No tags to edit.", ephemeral=True)
            return

        if len(custom_tags) == 1:
            # Only one tag — open it directly
            view = TagGroupOptionsView(self.context, custom_tags[0]["id"])
            embed = await view.update_view(interaction)
            await interaction.response.edit_message(embed=embed, view=view)
            return

        view = TagEditSelectorView(self.context)
        embed = await view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=view)

    async def go_back(self, interaction: discord.Interaction) -> None:
        from .settings import GuildSettingsView

        guild_settings_view = GuildSettingsView(self.context)
        embed = await guild_settings_view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=guild_settings_view)
