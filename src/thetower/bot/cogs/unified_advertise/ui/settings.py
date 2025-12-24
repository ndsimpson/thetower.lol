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
            if value == 0 and self.setting_name in ["mod_channel_id", "guild_tag_id", "member_tag_id", "testing_channel_id"]:
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
        guild_tag_id = self.cog._get_guild_tag_id(self.guild_id)
        member_tag_id = self.cog._get_member_tag_id(self.guild_id)

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

        # Tag Settings - Get tag names
        guild_tag_name = "Not configured"
        member_tag_name = "Not configured"

        if guild_tag_id and advertise_channel and hasattr(advertise_channel, "available_tags"):
            guild_tag = next((tag for tag in advertise_channel.available_tags if tag.id == guild_tag_id), None)
            if guild_tag:
                guild_tag_name = f"{guild_tag.name} (ID: {guild_tag_id})"
            else:
                guild_tag_name = f"ID: {guild_tag_id}"

        if member_tag_id and advertise_channel and hasattr(advertise_channel, "available_tags"):
            member_tag = next((tag for tag in advertise_channel.available_tags if tag.id == member_tag_id), None)
            if member_tag:
                member_tag_name = f"{member_tag.name} (ID: {member_tag_id})"
            else:
                member_tag_name = f"ID: {member_tag_id}"

        embed.add_field(name="🏷️ Forum Tags", value=f"Guild Tag: {guild_tag_name}\nMember Tag: {member_tag_name}", inline=False)

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

        # Set guild tag button
        guild_tag_btn = Button(label="Set Guild Tag", style=discord.ButtonStyle.secondary, emoji="🏰")
        guild_tag_btn.callback = self.set_guild_tag
        self.add_item(guild_tag_btn)

        # Set member tag button
        member_tag_btn = Button(label="Set Member Tag", style=discord.ButtonStyle.secondary, emoji="👤")
        member_tag_btn.callback = self.set_member_tag
        self.add_item(member_tag_btn)

        # Back button
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

    async def set_guild_tag(self, interaction: discord.Interaction):
        """Show modal to set guild tag."""
        modal = SettingsModal(self.context, "guild_tag_id", "Set Guild Tag ID", "Enter forum tag ID (0 to clear)")
        await interaction.response.send_modal(modal)

    async def set_member_tag(self, interaction: discord.Interaction):
        """Show modal to set member tag."""
        modal = SettingsModal(self.context, "member_tag_id", "Set Member Tag ID", "Enter forum tag ID (0 to clear)")
        await interaction.response.send_modal(modal)

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
        embed = discord.Embed(title="Bot Settings", description="Configure bot behavior and preferences", color=discord.Color.green())

        # Add current settings
        embed.add_field(name="Default Cooldown", value=f"{self.cog.guild_settings.get('cooldown_hours', 24)} hours", inline=True)

        embed.add_field(
            name="Default Settings", value="These are the default values used when no server-specific settings are configured.", inline=False
        )

        # Update buttons
        self.clear_items()

        # No edit functionality for default settings - they are configured in code
        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️")
        back_btn.callback = self.go_back
        self.add_item(back_btn)

        return embed

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
                self.cog.SettingsViewContext(
                    guild_id=interaction.guild.id, cog_instance=self.cog, interaction=interaction, is_bot_owner=self.context.is_bot_owner
                )
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
                self.cog.SettingsViewContext(
                    guild_id=self.guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=self.context.is_bot_owner
                )
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
            self.cog.SettingsViewContext(guild_id=guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=self.context.is_bot_owner)
        )
        embed = await settings_view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=settings_view)

    async def default_settings(self, interaction: discord.Interaction):
        """Open default settings."""
        settings_view = SettingsView(self.context)
        embed = await settings_view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=settings_view)
