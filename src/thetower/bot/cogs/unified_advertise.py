# Standard library imports
import asyncio
import datetime
import re
import time
from pathlib import Path
from typing import ClassVar, Dict, List, Optional, Tuple

# Third-party imports
import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import Button, Modal, Select, TextInput, View

# Local application imports
from thetower.bot.basecog import BaseCog


class AdvertisementType:
    """Constants for advertisement types."""

    GUILD: ClassVar[str] = "guild"
    MEMBER: ClassVar[str] = "member"


class AdTypeSelection(View):
    """View with buttons to select advertisement type."""

    def __init__(self, cog: "UnifiedAdvertise") -> None:
        """Initialize the view with a reference to the cog.

        Args:
            cog: The UnifiedAdvertise cog instance
        """
        super().__init__(timeout=900)  # 15 minute timeout
        self.cog = cog

    @discord.ui.button(label="Guild Advertisement", style=discord.ButtonStyle.primary, emoji="🏰")
    async def guild_button(self, interaction: discord.Interaction, button: Button) -> None:
        # Defer the response early to prevent timeouts
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        form = GuildAdvertisementForm(self.cog)
        view = NotificationView(form)

        if interaction.response.is_done():
            await interaction.followup.send("Please select your notification preference:", view=view, ephemeral=True)
        else:
            await interaction.response.send_message("Please select your notification preference:", view=view, ephemeral=True)

    @discord.ui.button(label="Member Advertisement", style=discord.ButtonStyle.success, emoji="👤")
    async def member_button(self, interaction: discord.Interaction, button: Button) -> None:
        # Defer the response early to prevent timeouts
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        form = MemberAdvertisementForm(self.cog)
        view = NotificationView(form)  # Reuse the same NotificationView

        if interaction.response.is_done():
            await interaction.followup.send("Please select your notification preference:", view=view, ephemeral=True)
        else:
            await interaction.response.send_message("Please select your notification preference:", view=view, ephemeral=True)

    async def on_timeout(self) -> None:
        # Disable all buttons when the view times out
        for item in self.children:
            item.disabled = True
        # Try to edit the original message with disabled buttons
        try:
            if hasattr(self, "message"):
                await self.message.edit(view=self)
        except discord.NotFound:
            pass  # Message might have been deleted


class GuildAdvertisementForm(Modal, title="Guild Advertisement Form"):
    """Modal form for collecting guild advertisement information."""

    def __init__(self, cog: "UnifiedAdvertise") -> None:
        """Initialize the view with a reference to the cog.

        Args:
            cog: The UnifiedAdvertise cog instance
        """
        super().__init__(timeout=900)  # 15 minute timeout
        self.cog = cog
        self.notify = True
        self.interaction = None  # Store interaction object

    guild_name = TextInput(label="Guild Name", placeholder="Enter your guild's name", required=True, max_length=100)

    guild_id = TextInput(label="Guild ID", placeholder="Enter your guild's ID (e.g. A1B2C3)", required=True, min_length=6, max_length=6)

    guild_leader = TextInput(label="Guild Leader", placeholder="Enter guild leader's name", required=True, max_length=100)

    member_count = TextInput(label="Member Count", placeholder="How many active members?", required=True, max_length=10)

    description = TextInput(
        label="Guild Description", placeholder="Tell us about your guild...", required=True, max_length=1000, style=discord.TextStyle.paragraph
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        import time

        start_time = time.time()
        self.interaction = interaction  # Store interaction when form is submitted
        await self.cog._send_debug_message(f"Guild advertisement form submitted by user {interaction.user.id} ({interaction.user.name})")

        # Normalize and validate guild ID
        guild_id = self.cog._normalize_guild_id(self.guild_id.value)
        if not re.match(r"^[A-Z0-9]{6}$", guild_id):
            await self.cog._send_debug_message(f"Invalid guild ID format from user {interaction.user.id}: {guild_id}")
            await interaction.response.send_message(
                "Guild ID must be exactly 6 characters and only contain letters A-Z and numbers 0-9.", ephemeral=True
            )
            return

        # Process notification preference
        notify = self.notify

        # Check cooldowns before processing
        user_id = interaction.user.id
        cooldown_start = time.time()

        cooldown_check = await self.cog.check_cooldowns(interaction, user_id, guild_id, AdvertisementType.GUILD)
        cooldown_time = time.time() - cooldown_start
        await self.cog._send_debug_message(f"Cooldown check completed in {cooldown_time:.2f}s for user {interaction.user.id}")

        # Warn if cooldown check took too long
        if cooldown_time > 1.0:
            await self.cog._send_debug_message(f"⚠️ Cooldown check took {cooldown_time:.2f}s - potential timeout risk for user {interaction.user.id}")

        if not cooldown_check:
            return

        # Create guild advertisement embed
        embed = discord.Embed(
            title=self.guild_name.value, description=self.description.value, color=discord.Color.blue(), timestamp=discord.utils.utcnow()
        )

        embed.set_author(name=f"Guild Ad by {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        embed.add_field(name="Guild ID", value=guild_id, inline=True)  # Display uppercase ID
        embed.add_field(name="Leader", value=self.guild_leader.value, inline=True)
        embed.add_field(name="Member Count", value=self.member_count.value, inline=True)
        embed.add_field(name="Posted by", value=f"<@{interaction.user.id}>", inline=True)
        embed.set_footer(text="Use /advertise to submit your own advertisement")

        # CRITICAL: Respond to interaction IMMEDIATELY before heavy work
        discord_guild_id = interaction.guild.id if interaction.guild else None
        cooldown_hours = self.cog._get_cooldown_hours(discord_guild_id) if discord_guild_id else 168

        await interaction.response.send_message(
            f"Thank you! Your {AdvertisementType.GUILD} advertisement is being posted. "
            f"It will remain visible for {cooldown_hours} hours.",
            ephemeral=True,
        )

        # Post advertisement and update cooldowns
        thread_title = f"[Guild] {self.guild_name.value} ({guild_id})"
        total_time = time.time() - start_time
        await self.cog._send_debug_message(
            f"Guild form processing completed in {total_time:.2f}s, posting advertisement for user {interaction.user.id}"
        )
        await self.cog.post_advertisement(interaction, embed, thread_title, AdvertisementType.GUILD, guild_id, notify)

    async def on_timeout(self) -> None:
        """Handle form timeout."""
        try:
            if self.interaction:  # Only try to send message if we have an interaction
                await self.interaction.response.send_message("The form timed out. Please try submitting your advertisement again.", ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            pass


class NotificationView(View):
    def __init__(self, form: GuildAdvertisementForm):
        super().__init__(timeout=900)
        self.form = form

    @discord.ui.select(
        placeholder="Would you like to be notified when your ad expires?",
        options=[discord.SelectOption(label="Yes", value="yes", emoji="✉️"), discord.SelectOption(label="No", value="no", emoji="🔕")],
        min_values=1,
        max_values=1,
    )
    async def notify_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.form.notify = select.values[0] == "yes"
        await interaction.response.send_modal(self.form)


class MemberAdvertisementForm(Modal, title="Member Advertisement Form"):
    """Modal form for collecting member advertisement information."""

    def __init__(self, cog: "UnifiedAdvertise") -> None:
        """Initialize the view with a reference to the cog.

        Args:
            cog: The UnifiedAdvertise cog instance
        """
        super().__init__(timeout=900)  # 15 minute timeout
        self.cog = cog
        self.notify = True
        self.interaction = None  # Store interaction object

    player_id = TextInput(label="Player ID", placeholder="Your player ID", required=True, max_length=50)

    weekly_boxes = TextInput(
        label="Weekly Box Count", placeholder="How many weekly boxes do you usually clear? (out of 7)", required=True, max_length=10
    )

    additional_info = TextInput(
        label="Additional Information",
        placeholder="What else should we know about you?",
        required=True,
        max_length=1000,
        style=discord.TextStyle.paragraph,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.interaction = interaction  # Store interaction when form is submitted
        # Check if player ID is valid (only A-Z, 0-9)
        player_id = self.player_id.value.upper()
        if not re.match(r"^[A-Z0-9]+$", player_id):
            self.cog.logger.warning(f"User {interaction.user.id} provided invalid player ID format: {player_id}")
            await interaction.response.send_message("Player ID can only contain letters A-Z and numbers 0-9.", ephemeral=True)
            return

        # Process notification preference
        notify = self.notify

        # Check cooldowns before processing
        user_id = interaction.user.id

        cooldown_check = await self.cog.check_cooldowns(interaction, user_id, None, AdvertisementType.MEMBER)

        if not cooldown_check:
            return

        # Create member advertisement embed
        embed = discord.Embed(title=f"Player: {interaction.user.name}", color=discord.Color.green(), timestamp=discord.utils.utcnow())

        embed.set_author(name=f"Submitted by {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)

        # Make the Player ID a clickable link (uppercase)
        url_value = f"[{player_id}](https://thetower.lol/player?player={player_id})"
        embed.add_field(name="Player ID", value=url_value, inline=True)
        embed.add_field(name="Weekly Box Count", value=self.weekly_boxes.value, inline=True)
        embed.add_field(name="Posted by", value=f"<@{interaction.user.id}>", inline=True)
        embed.add_field(name="Additional Info", value=self.additional_info.value, inline=False)
        embed.set_footer(text="Use /advertise to submit your own advertisement")

        # CRITICAL: Respond to interaction IMMEDIATELY before heavy work
        discord_guild_id = interaction.guild.id if interaction.guild else None
        cooldown_hours = self.cog._get_cooldown_hours(discord_guild_id) if discord_guild_id else 168

        await interaction.response.send_message(
            f"Thank you! Your {AdvertisementType.MEMBER} advertisement is being posted. "
            f"It will remain visible for {cooldown_hours} hours.",
            ephemeral=True,
        )

        # Post advertisement and update cooldowns
        thread_title = f"[Member] {interaction.user.name} ({player_id})"
        await self.cog.post_advertisement(interaction, embed, thread_title, AdvertisementType.MEMBER, None, notify)

    async def on_timeout(self) -> None:
        """Handle form timeout."""
        try:
            if self.interaction:  # Only try to send message if we have an interaction
                await self.interaction.response.send_message("The form timed out. Please try submitting your advertisement again.", ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            pass


# ====================
# UI Components for Advertisement Management
# ====================


class AdManagementView(View):
    """View for users to manage their advertisements."""

    def __init__(self, cog: "UnifiedAdvertise", user_id: int, guild_id: int):
        super().__init__(timeout=300)  # 5 minute timeout
        self.cog = cog
        self.user_id = user_id
        self.guild_id = guild_id

    async def update_view(self, interaction: discord.Interaction):
        """Update the view with current advertisement status."""
        # Get user's active advertisements in this guild
        user_ads = []
        for thread_id, deletion_time, author_id, notify, ad_guild_id in self.cog.pending_deletions:
            if author_id == self.user_id and ad_guild_id == self.guild_id:
                try:
                    thread = await self.cog.bot.fetch_channel(thread_id)
                    if thread:
                        time_left = deletion_time - datetime.datetime.now()
                        hours_left = time_left.total_seconds() / 3600
                        user_ads.append((thread_id, thread.name, hours_left, notify))
                except Exception:
                    continue

        # Check cooldown status
        cooldown_hours = self.cog._get_cooldown_hours(self.guild_id)
        guild_cooldowns = self.cog.cooldowns.get(self.guild_id, {"users": {}, "guilds": {}})
        user_cooldown_str = guild_cooldowns["users"].get(str(self.user_id))

        on_cooldown = False
        cooldown_hours_left = 0

        if user_cooldown_str:
            stored_time = datetime.datetime.fromisoformat(user_cooldown_str)
            if stored_time.tzinfo is None:
                stored_time = stored_time.replace(tzinfo=datetime.timezone.utc)
            current_time = datetime.datetime.now(datetime.timezone.utc)
            elapsed = (current_time - stored_time).total_seconds()

            if elapsed < cooldown_hours * 3600:
                on_cooldown = True
                cooldown_hours_left = cooldown_hours - (elapsed / 3600)

        # Build embed
        embed = discord.Embed(
            title="Advertisement Management",
            description="Manage your advertisements in this server",
            color=discord.Color.blue()
        )

        if user_ads:
            ads_text = []
            for thread_id, name, hours_left, notify in user_ads:
                notify_icon = "🔔" if notify else "🔕"
                ads_text.append(f"**{name}**\n{notify_icon} Expires in {hours_left:.1f} hours")
            embed.add_field(name="Your Active Advertisements", value="\n\n".join(ads_text), inline=False)
        else:
            embed.add_field(name="Active Advertisements", value="You have no active advertisements", inline=False)

        if on_cooldown:
            embed.add_field(
                name="Cooldown Status",
                value=f"⏳ You can post a new advertisement in {cooldown_hours_left:.1f} hours",
                inline=False
            )
        else:
            embed.add_field(
                name="Cooldown Status",
                value="✅ You can post a new advertisement now!",
                inline=False
            )

        # Update buttons
        self.clear_items()

        if user_ads:
            # Add delete button if user has ads
            delete_btn = Button(label="Delete Advertisement", style=discord.ButtonStyle.danger, emoji="🗑️")
            delete_btn.callback = self.delete_advertisement
            self.add_item(delete_btn)

            # Add toggle notification button
            toggle_btn = Button(label="Toggle Notifications", style=discord.ButtonStyle.secondary, emoji="🔔")
            toggle_btn.callback = self.toggle_notifications
            self.add_item(toggle_btn)

        if not on_cooldown:
            # Add create new ad button
            create_btn = Button(label="Create Advertisement", style=discord.ButtonStyle.success, emoji="✨")
            create_btn.callback = self.create_advertisement
            self.add_item(create_btn)

        # Always add refresh button
        refresh_btn = Button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄")
        refresh_btn.callback = self.refresh_view
        self.add_item(refresh_btn)

        return embed

    async def delete_advertisement(self, interaction: discord.Interaction):
        """Handle deleting an advertisement."""
        # Get user's ads
        user_ads = []
        for thread_id, deletion_time, author_id, notify, ad_guild_id in self.cog.pending_deletions:
            if author_id == self.user_id and ad_guild_id == self.guild_id:
                try:
                    thread = await self.cog.bot.fetch_channel(thread_id)
                    if thread:
                        user_ads.append((thread_id, thread.name))
                except Exception:
                    continue

        if len(user_ads) == 1:
            # Only one ad, delete it directly
            thread_id = user_ads[0][0]
            await self._delete_ad(interaction, thread_id)
        else:
            # Multiple ads, show selection dropdown
            options = [discord.SelectOption(label=name[:100], value=str(tid)) for tid, name in user_ads]
            select = Select(placeholder="Select advertisement to delete", options=options)

            async def select_callback(select_interaction: discord.Interaction):
                thread_id = int(select.values[0])
                await self._delete_ad(select_interaction, thread_id)

            select.callback = select_callback
            view = View()
            view.add_item(select)
            await interaction.response.send_message("Select the advertisement you want to delete:", view=view, ephemeral=True)

    async def _delete_ad(self, interaction: discord.Interaction, thread_id: int):
        """Delete a specific advertisement."""
        try:
            thread = await self.cog.bot.fetch_channel(thread_id)
            await thread.delete()

            # Remove from pending deletions
            self.cog.pending_deletions = [
                entry for entry in self.cog.pending_deletions if entry[0] != thread_id
            ]
            await self.cog._save_pending_deletions()

            await interaction.response.send_message("✅ Advertisement deleted successfully.", ephemeral=True)

            # Refresh the main view
            embed = await self.update_view(interaction)
            await interaction.message.edit(embed=embed, view=self)
        except Exception as e:
            self.cog.logger.error(f"Error deleting advertisement: {e}")
            await interaction.response.send_message("❌ Failed to delete advertisement.", ephemeral=True)

    async def toggle_notifications(self, interaction: discord.Interaction):
        """Toggle notification settings."""
        # Get user's ads
        user_ads = []
        for entry in self.cog.pending_deletions:
            thread_id, deletion_time, author_id, notify, ad_guild_id = entry
            if author_id == self.user_id and ad_guild_id == self.guild_id:
                try:
                    thread = await self.cog.bot.fetch_channel(thread_id)
                    if thread:
                        user_ads.append((thread_id, thread.name, notify))
                except Exception:
                    continue

        if len(user_ads) == 1:
            # Only one ad, toggle it directly
            thread_id, name, current_notify = user_ads[0]
            await self._toggle_notify(interaction, thread_id, not current_notify)
        else:
            # Multiple ads, show selection dropdown
            options = [
                discord.SelectOption(
                    label=name[:80],
                    value=str(tid),
                    description=f"Notifications {'ON' if notify else 'OFF'}",
                    emoji="🔔" if notify else "🔕"
                )
                for tid, name, notify in user_ads
            ]
            select = Select(placeholder="Select advertisement", options=options)

            async def select_callback(select_interaction: discord.Interaction):
                thread_id = int(select.values[0])
                # Find current notify state
                current_notify = False
                for tid, _, notify in user_ads:
                    if tid == thread_id:
                        current_notify = notify
                        break
                await self._toggle_notify(select_interaction, thread_id, not current_notify)

            select.callback = select_callback
            view = View()
            view.add_item(select)
            await interaction.response.send_message("Select advertisement to toggle notifications:", view=view, ephemeral=True)

    async def _toggle_notify(self, interaction: discord.Interaction, thread_id: int, new_state: bool):
        """Toggle notification for a specific ad."""
        updated_deletions = []
        for t_id, t_time, t_author, t_notify, t_guild_id in self.cog.pending_deletions:
            if t_id == thread_id:
                updated_deletions.append((t_id, t_time, t_author, new_state, t_guild_id))
            else:
                updated_deletions.append((t_id, t_time, t_author, t_notify, t_guild_id))

        self.cog.pending_deletions = updated_deletions
        await self.cog._save_pending_deletions()

        state_text = "enabled" if new_state else "disabled"
        await interaction.response.send_message(f"✅ Notifications have been {state_text}.", ephemeral=True)

        # Refresh the main view
        embed = await self.update_view(interaction)
        await interaction.message.edit(embed=embed, view=self)

    async def create_advertisement(self, interaction: discord.Interaction):
        """Launch the advertisement creation flow."""
        view = AdTypeSelection(self.cog)
        await interaction.response.send_message("What type of advertisement would you like to post?", view=view, ephemeral=True)

    async def refresh_view(self, interaction: discord.Interaction):
        """Refresh the view."""
        embed = await self.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=self)


class AdminAdManagementView(View):
    """View for server owners/admins to manage all advertisements."""

    def __init__(self, cog: "UnifiedAdvertise", guild_id: int, is_bot_owner: bool = False):
        super().__init__(timeout=600)  # 10 minute timeout
        self.cog = cog
        self.guild_id = guild_id
        self.is_bot_owner = is_bot_owner

    async def update_view(self, interaction: discord.Interaction):
        """Update the view with current advertisement statistics."""
        # Get all advertisements in this guild
        guild_ads_count = 0
        member_ads_count = 0

        # Get tag IDs for this guild
        guild_tag_id = self.cog._get_guild_tag_id(self.guild_id)
        member_tag_id = self.cog._get_member_tag_id(self.guild_id)

        for thread_id, deletion_time, author_id, notify, ad_guild_id in self.cog.pending_deletions:
            if ad_guild_id == self.guild_id:
                try:
                    thread = await self.cog.bot.fetch_channel(thread_id)
                    if thread:
                        # Check tags to determine type
                        thread_tag_ids = [tag.id for tag in thread.applied_tags]
                        if guild_tag_id and guild_tag_id in thread_tag_ids:
                            guild_ads_count += 1
                        elif member_tag_id and member_tag_id in thread_tag_ids:
                            member_ads_count += 1
                except Exception:
                    continue

        total_ads = guild_ads_count + member_ads_count

        # Build embed
        embed = discord.Embed(
            title="🛡️ Advertisement Management (Admin)",
            description="Manage advertisements for this server",
            color=discord.Color.gold()
        )

        embed.add_field(name="📊 Statistics", value=f"**Total Active:** {total_ads}\n**Guild Ads:** {guild_ads_count}\n**Member Ads:** {member_ads_count}", inline=False)

        # Update buttons
        self.clear_items()

        # Add manage ads button
        manage_btn = Button(label="Manage Ads", style=discord.ButtonStyle.primary, emoji="📋")
        manage_btn.callback = self.show_manage_ads
        self.add_item(manage_btn)

        # Add settings button (for admins)
        settings_btn = Button(label="Settings", style=discord.ButtonStyle.primary, emoji="⚙️")
        settings_btn.callback = self.show_settings
        self.add_item(settings_btn)

        # Add "My Ads" button to access regular user view
        my_ads_btn = Button(label="My Ads", style=discord.ButtonStyle.success, emoji="📝")
        my_ads_btn.callback = self.show_my_ads
        self.add_item(my_ads_btn)

        # Add refresh button
        refresh_btn = Button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄")
        refresh_btn.callback = self.refresh_view
        self.add_item(refresh_btn)

        return embed

    async def show_manage_ads(self, interaction: discord.Interaction):
        """Show ad type selection view."""
        type_view = AdTypeSelectionView(self.cog, self.guild_id)
        embed = type_view.build_embed()
        await interaction.response.send_message(embed=embed, view=type_view, ephemeral=True)

    async def show_settings(self, interaction: discord.Interaction):
        """Show settings management UI."""
        settings_view = SettingsView(self.cog, self.guild_id)
        embed = await settings_view.build_embed()
        await interaction.response.send_message(embed=embed, view=settings_view, ephemeral=True)

    async def show_my_ads(self, interaction: discord.Interaction):
        """Show the regular user ad management view."""
        user_view = AdManagementView(self.cog, interaction.user.id, interaction.guild.id)
        embed = await user_view.update_view(interaction)
        await interaction.response.send_message(embed=embed, view=user_view, ephemeral=True)

    async def refresh_view(self, interaction: discord.Interaction):
        """Refresh the view."""
        embed = await self.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=self)


class AdTypeSelectionView(View):
    """View for selecting which type of ads to manage (Guild or Member)."""

    def __init__(self, cog: "UnifiedAdvertise", guild_id: int):
        super().__init__(timeout=600)
        self.cog = cog
        self.guild_id = guild_id

        # Add buttons
        guild_btn = Button(label="Guild Ads", style=discord.ButtonStyle.primary, emoji="🏰")
        guild_btn.callback = self.show_guild_ads
        self.add_item(guild_btn)

        member_btn = Button(label="Member Ads", style=discord.ButtonStyle.primary, emoji="👤")
        member_btn.callback = self.show_member_ads
        self.add_item(member_btn)

        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, emoji="◀️")
        back_btn.callback = self.go_back
        self.add_item(back_btn)

    def build_embed(self):
        """Build the ad type selection embed."""
        embed = discord.Embed(
            title="📋 Select Advertisement Type",
            description="Choose which type of advertisements to manage",
            color=discord.Color.blue()
        )
        return embed

    async def show_guild_ads(self, interaction: discord.Interaction):
        """Show guild advertisement list."""
        list_view = AdListView(self.cog, self.guild_id, AdvertisementType.GUILD)
        embed = await list_view.build_embed()
        await interaction.response.edit_message(embed=embed, view=list_view)

    async def show_member_ads(self, interaction: discord.Interaction):
        """Show member advertisement list."""
        list_view = AdListView(self.cog, self.guild_id, AdvertisementType.MEMBER)
        embed = await list_view.build_embed()
        await interaction.response.edit_message(embed=embed, view=list_view)

    async def go_back(self, interaction: discord.Interaction):
        """Go back to admin main view."""
        admin_view = AdminAdManagementView(self.cog, self.guild_id)
        embed = await admin_view.update_view(interaction)
        await interaction.response.edit_message(embed=embed, view=admin_view)


class AdListView(View):
    """View for listing and selecting specific advertisements."""

    def __init__(self, cog: "UnifiedAdvertise", guild_id: int, ad_type: str):
        super().__init__(timeout=600)
        self.cog = cog
        self.guild_id = guild_id
        self.ad_type = ad_type

    async def build_embed(self):
        """Build the ad list embed with selection dropdown."""
        # Get tag ID for this ad type
        if self.ad_type == AdvertisementType.GUILD:
            tag_id = self.cog._get_guild_tag_id(self.guild_id)
            type_emoji = "🏰"
            type_name = "Guild"
        else:
            tag_id = self.cog._get_member_tag_id(self.guild_id)
            type_emoji = "👤"
            type_name = "Member"

        # Get all advertisements of this type
        ads = []
        for thread_id, deletion_time, author_id, notify, ad_guild_id in self.cog.pending_deletions:
            if ad_guild_id == self.guild_id:
                try:
                    thread = await self.cog.bot.fetch_channel(thread_id)
                    if thread:
                        # Check if this thread has the correct tag
                        thread_tag_ids = [tag.id for tag in thread.applied_tags]
                        if tag_id and tag_id in thread_tag_ids:
                            time_left = deletion_time - datetime.datetime.now()
                            hours_left = time_left.total_seconds() / 3600
                            ads.append((thread_id, thread.name, author_id, hours_left, notify))
                except Exception:
                    continue

        embed = discord.Embed(
            title=f"{type_emoji} {type_name} Advertisements",
            description=f"Total: {len(ads)} active",
            color=discord.Color.green() if ads else discord.Color.greyple()
        )

        if ads:
            # Add selection dropdown
            options = [
                discord.SelectOption(
                    label=name[:80] if len(name) <= 80 else name[:77] + "...",
                    value=str(thread_id),
                    description=f"By user {author_id} - {hours_left:.1f}h left"[:100]
                )
                for thread_id, name, author_id, hours_left, notify in ads[:25]  # Discord limit
            ]
            select = Select(placeholder="Select an advertisement to view details", options=options)
            select.callback = self.show_ad_details
            self.add_item(select)

        # Add back button
        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, emoji="◀️")
        back_btn.callback = self.go_back
        self.add_item(back_btn)

        return embed

    async def show_ad_details(self, interaction: discord.Interaction):
        """Show details for selected advertisement."""
        thread_id = int(interaction.data['values'][0])
        detail_view = AdDetailView(self.cog, self.guild_id, thread_id, self.ad_type)
        embed = await detail_view.build_embed()
        await interaction.response.edit_message(embed=embed, view=detail_view)

    async def go_back(self, interaction: discord.Interaction):
        """Go back to ad type selection."""
        type_view = AdTypeSelectionView(self.cog, self.guild_id)
        embed = type_view.build_embed()
        await interaction.response.edit_message(embed=embed, view=type_view)


class AdDetailView(View):
    """View for displaying advertisement details with action buttons."""

    def __init__(self, cog: "UnifiedAdvertise", guild_id: int, thread_id: int, ad_type: str):
        super().__init__(timeout=600)
        self.cog = cog
        self.guild_id = guild_id
        self.thread_id = thread_id
        self.ad_type = ad_type

    async def build_embed(self):
        """Build the ad detail embed."""
        # Find the ad in pending_deletions
        ad_data = None
        for t_id, deletion_time, author_id, notify, ad_guild_id in self.cog.pending_deletions:
            if t_id == self.thread_id and ad_guild_id == self.guild_id:
                ad_data = (t_id, deletion_time, author_id, notify)
                break

        if not ad_data:
            embed = discord.Embed(
                title="❌ Advertisement Not Found",
                description="This advertisement may have been deleted.",
                color=discord.Color.red()
            )
            return embed

        thread_id, deletion_time, author_id, notify = ad_data

        # Fetch thread details
        try:
            thread = await self.cog.bot.fetch_channel(thread_id)
            time_left = deletion_time - datetime.datetime.now()
            hours_left = time_left.total_seconds() / 3600

            type_emoji = "🏰" if self.ad_type == AdvertisementType.GUILD else "👤"
            type_name = "Guild" if self.ad_type == AdvertisementType.GUILD else "Member"

            embed = discord.Embed(
                title=f"{type_emoji} {thread.name}",
                description=f"**Type:** {type_name} Advertisement\n**Thread ID:** {thread_id}",
                color=discord.Color.blue()
            )

            embed.add_field(name="Posted By", value=f"<@{author_id}>", inline=True)
            embed.add_field(name="Expires In", value=f"{hours_left:.1f} hours", inline=True)
            embed.add_field(name="Notifications", value="🔔 Enabled" if notify else "🔕 Disabled", inline=True)
            embed.add_field(name="Thread", value=thread.mention if hasattr(thread, 'mention') else f"Thread {thread_id}", inline=False)

            # Add action buttons
            reset_btn = Button(label="Reset Timeout", style=discord.ButtonStyle.primary, emoji="⏰")
            reset_btn.callback = self.reset_timeout
            self.add_item(reset_btn)

            delete_btn = Button(label="Delete Ad", style=discord.ButtonStyle.danger, emoji="🗑️")
            delete_btn.callback = self.delete_ad
            self.add_item(delete_btn)

            ban_btn = Button(label="Ban & Delete", style=discord.ButtonStyle.danger, emoji="🚫")
            ban_btn.callback = self.ban_and_delete
            self.add_item(ban_btn)

            back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, emoji="◀️")
            back_btn.callback = self.go_back
            self.add_item(back_btn)

        except Exception as e:
            self.cog.logger.error(f"Error fetching thread {thread_id}: {e}")
            embed = discord.Embed(
                title="❌ Error Loading Advertisement",
                description=f"Could not load advertisement details: {str(e)}",
                color=discord.Color.red()
            )

        return embed

    async def reset_timeout(self, interaction: discord.Interaction):
        """Reset the advertisement timeout."""
        # Find and update the deletion time
        updated_deletions = []
        for t_id, deletion_time, author_id, notify, ad_guild_id in self.cog.pending_deletions:
            if t_id == self.thread_id:
                # Reset to full cooldown
                cooldown_hours = self.cog._get_cooldown_hours(self.guild_id)
                new_deletion_time = datetime.datetime.now() + datetime.timedelta(hours=cooldown_hours)
                updated_deletions.append((t_id, new_deletion_time, author_id, notify, ad_guild_id))
            else:
                updated_deletions.append((t_id, deletion_time, author_id, notify, ad_guild_id))

        self.cog.pending_deletions = updated_deletions
        await self.cog._save_pending_deletions()

        await interaction.response.send_message("✅ Advertisement timeout reset successfully.", ephemeral=True)

        # Refresh the view
        embed = await self.build_embed()
        await interaction.message.edit(embed=embed, view=self)

    async def delete_ad(self, interaction: discord.Interaction):
        """Delete the advertisement."""
        try:
            thread = await self.cog.bot.fetch_channel(self.thread_id)
            await thread.delete()

            # Remove from pending deletions
            self.cog.pending_deletions = [
                entry for entry in self.cog.pending_deletions if entry[0] != self.thread_id
            ]
            await self.cog._save_pending_deletions()

            await interaction.response.send_message("✅ Advertisement deleted successfully.", ephemeral=True)

            # Go back to list
            list_view = AdListView(self.cog, self.guild_id, self.ad_type)
            embed = await list_view.build_embed()
            await interaction.message.edit(embed=embed, view=list_view)

        except Exception as e:
            self.cog.logger.error(f"Error deleting thread {self.thread_id}: {e}")
            await interaction.response.send_message(f"❌ Failed to delete advertisement: {str(e)}", ephemeral=True)

    async def ban_and_delete(self, interaction: discord.Interaction):
        """Ban the user/guild and delete the advertisement."""
        # Get author ID from pending_deletions
        author_id = None
        for t_id, _, a_id, _, ad_guild_id in self.cog.pending_deletions:
            if t_id == self.thread_id:
                author_id = a_id
                break

        if not author_id:
            await interaction.response.send_message("❌ Could not find advertisement author.", ephemeral=True)
            return

        # Add to banned list
        banned_key = f"banned_{'guilds' if self.ad_type == AdvertisementType.GUILD else 'users'}"
        banned_list = self.cog.get_setting(banned_key, default=[], guild_id=self.guild_id)
        if isinstance(banned_list, list):
            if author_id not in banned_list:
                banned_list.append(author_id)
                self.cog.set_setting(banned_key, banned_list, guild_id=self.guild_id)

        # Delete the ad
        try:
            thread = await self.cog.bot.fetch_channel(self.thread_id)
            await thread.delete()

            # Remove from pending deletions
            self.cog.pending_deletions = [
                entry for entry in self.cog.pending_deletions if entry[0] != self.thread_id
            ]
            await self.cog._save_pending_deletions()

            type_name = "guild" if self.ad_type == AdvertisementType.GUILD else "user"
            await interaction.response.send_message(
                f"✅ Banned {type_name} {author_id} and deleted advertisement.",
                ephemeral=True
            )

            # Go back to list
            list_view = AdListView(self.cog, self.guild_id, self.ad_type)
            embed = await list_view.build_embed()
            await interaction.message.edit(embed=embed, view=list_view)

        except Exception as e:
            self.cog.logger.error(f"Error in ban_and_delete for thread {self.thread_id}: {e}")
            await interaction.response.send_message(f"❌ Failed to ban and delete: {str(e)}", ephemeral=True)

    async def go_back(self, interaction: discord.Interaction):
        """Go back to ad list."""
        list_view = AdListView(self.cog, self.guild_id, self.ad_type)
        embed = await list_view.build_embed()
        await interaction.response.edit_message(embed=embed, view=list_view)


class SettingsView(View):
    """View for managing advertisement settings."""

    def __init__(self, cog: "UnifiedAdvertise", guild_id: int):
        super().__init__(timeout=600)  # 10 minute timeout
        self.cog = cog
        self.guild_id = guild_id

    async def build_embed(self):
        """Build settings display embed."""
        # Get guild-specific settings
        cooldown_hours = self.cog._get_cooldown_hours(self.guild_id)
        advertise_channel_id = self.cog._get_advertise_channel_id(self.guild_id)
        mod_channel_id = self.cog._get_mod_channel_id(self.guild_id)
        testing_channel_id = self.cog._get_testing_channel_id(self.guild_id)
        debug_enabled = self.cog.get_setting('debug_enabled', default=False, guild_id=self.guild_id)
        guild_tag_id = self.cog._get_guild_tag_id(self.guild_id)
        member_tag_id = self.cog._get_member_tag_id(self.guild_id)

        embed = discord.Embed(
            title="⚙️ Advertisement Settings",
            description=f"Configuration for Guild {self.guild_id}",
            color=discord.Color.blue()
        )

        # Time Settings
        embed.add_field(
            name="⏰ Advertisement Cooldown",
            value=f"{cooldown_hours} hours",
            inline=False
        )

        # Channel Settings
        advertise_channel = self.cog.bot.get_channel(advertise_channel_id) if advertise_channel_id else None
        channel_name = advertise_channel.mention if advertise_channel else f"ID: {advertise_channel_id}" if advertise_channel_id else "Not configured"
        embed.add_field(
            name="📢 Advertisement Channel",
            value=channel_name,
            inline=False
        )

        # Mod Channel Settings
        mod_channel = self.cog.bot.get_channel(mod_channel_id) if mod_channel_id else None
        mod_channel_name = mod_channel.mention if mod_channel else "Not configured"
        embed.add_field(
            name="🛡️ Moderation Channel",
            value=mod_channel_name,
            inline=False
        )

        # Testing/Debug Channel Settings
        testing_channel = self.cog.bot.get_channel(testing_channel_id) if testing_channel_id else None
        testing_channel_name = testing_channel.mention if testing_channel else "Not configured"
        debug_status = "✅ Enabled" if debug_enabled else "❌ Disabled"
        embed.add_field(
            name="🔧 Debug Settings",
            value=f"Testing Channel: {testing_channel_name}\nDebug Messages: {debug_status}",
            inline=False
        )

        # Tag Settings
        guild_tag = f"ID: {guild_tag_id}" if guild_tag_id else "Not configured"
        member_tag = f"ID: {member_tag_id}" if member_tag_id else "Not configured"
        embed.add_field(
            name="🏷️ Forum Tags",
            value=f"Guild Tag: {guild_tag}\nMember Tag: {member_tag}",
            inline=False
        )

        # Stats
        guild_cooldowns = self.cog.cooldowns.get(self.guild_id, {"users": {}, "guilds": {}})
        guild_pending = sum(1 for _, _, _, _, gid in self.cog.pending_deletions if gid == self.guild_id)

        embed.add_field(
            name="📊 Statistics",
            value=f"Active User Cooldowns: {len(guild_cooldowns.get('users', {}))}\n"
                  f"Active Guild Cooldowns: {len(guild_cooldowns.get('guilds', {}))}\n"
                  f"Pending Deletions: {guild_pending}",
            inline=False
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
            emoji="🔕" if debug_enabled else "🔔"
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

        return embed

    async def set_cooldown(self, interaction: discord.Interaction):
        """Show modal to set cooldown hours."""
        modal = SettingModal(self.cog, self.guild_id, "cooldown_hours", "Set Cooldown Hours", "Enter cooldown hours (e.g., 168 for 7 days)")
        modal.parent_view = self
        await interaction.response.send_modal(modal)

    async def set_ad_channel(self, interaction: discord.Interaction):
        """Show channel selector for advertisement channel."""
        view = View(timeout=60)

        # Create channel select for forum channels only
        channel_select = discord.ui.ChannelSelect(
            placeholder="Select advertisement forum channel",
            channel_types=[discord.ChannelType.forum],
            min_values=1,
            max_values=1
        )

        async def channel_callback(select_interaction: discord.Interaction):
            selected_channel = channel_select.values[0]
            self.cog.set_setting(
                "advertise_channel_id",
                selected_channel.id,
                guild_id=self.guild_id
            )
            await select_interaction.response.send_message(
                f"✅ Set advertisement channel to {selected_channel.mention}",
                ephemeral=True
            )

        channel_select.callback = channel_callback
        view.add_item(channel_select)
        await interaction.response.send_message("Select the forum channel for advertisements:", view=view, ephemeral=True)

    async def set_mod_channel(self, interaction: discord.Interaction):
        """Show channel selector for moderation channel."""
        view = View(timeout=60)

        # Create channel select for text channels
        channel_select = discord.ui.ChannelSelect(
            placeholder="Select moderation notification channel",
            channel_types=[discord.ChannelType.text],
            min_values=0,
            max_values=1
        )

        async def channel_callback(select_interaction: discord.Interaction):
            if channel_select.values:
                selected_channel = channel_select.values[0]
                self.cog.set_setting(
                    "mod_channel_id",
                    selected_channel.id,
                    guild_id=self.guild_id
                )
                await select_interaction.response.send_message(
                    f"✅ Set moderation channel to {selected_channel.mention}",
                    ephemeral=True
                )
            else:
                self.cog.set_setting(
                    "mod_channel_id",
                    None,
                    guild_id=self.guild_id
                )
                await select_interaction.response.send_message(
                    "✅ Cleared moderation channel",
                    ephemeral=True
                )

        channel_select.callback = channel_callback
        view.add_item(channel_select)

        # Add a clear button
        clear_btn = Button(label="Clear Channel", style=discord.ButtonStyle.secondary)

        async def clear_callback(clear_interaction: discord.Interaction):
            self.cog.set_setting(
                "mod_channel_id",
                None,
                guild_id=self.guild_id
            )
            await clear_interaction.response.send_message(
                "✅ Cleared moderation channel",
                ephemeral=True
            )

        clear_btn.callback = clear_callback
        view.add_item(clear_btn)

        await interaction.response.send_message("Select the text channel for moderation notifications (or click Clear):", view=view, ephemeral=True)

    async def set_guild_tag(self, interaction: discord.Interaction):
        """Show modal to set guild tag."""
        modal = SettingModal(self.cog, self.guild_id, "guild_tag_id", "Set Guild Tag ID", "Enter forum tag ID (0 to clear)")
        modal.parent_view = self
        await interaction.response.send_modal(modal)

    async def set_member_tag(self, interaction: discord.Interaction):
        """Show modal to set member tag."""
        modal = SettingModal(self.cog, self.guild_id, "member_tag_id", "Set Member Tag ID", "Enter forum tag ID (0 to clear)")
        modal.parent_view = self
        await interaction.response.send_modal(modal)

    async def set_testing_channel(self, interaction: discord.Interaction):
        """Show channel selector for testing/debug channel."""
        view = View(timeout=60)

        # Create channel select for text channels only
        channel_select = discord.ui.ChannelSelect(
            placeholder="Select testing channel for debug messages",
            channel_types=[discord.ChannelType.text]
        )

        async def channel_callback(select_interaction: discord.Interaction):
            channel_id = channel_select.values[0].id
            self.cog.set_setting(
                "testing_channel_id",
                channel_id,
                guild_id=self.guild_id
            )
            await select_interaction.response.send_message(
                f"✅ Set testing channel to <#{channel_id}>",
                ephemeral=True
            )

        channel_select.callback = channel_callback
        view.add_item(channel_select)

        # Add a clear button
        clear_btn = Button(label="Clear Channel", style=discord.ButtonStyle.secondary)

        async def clear_callback(clear_interaction: discord.Interaction):
            self.cog.set_setting(
                "testing_channel_id",
                None,
                guild_id=self.guild_id
            )
            await clear_interaction.response.send_message(
                "✅ Cleared testing channel",
                ephemeral=True
            )

        clear_btn.callback = clear_callback
        view.add_item(clear_btn)

        await interaction.response.send_message("Select the text channel for debug messages (or click Clear):", view=view, ephemeral=True)

    async def toggle_debug(self, interaction: discord.Interaction):
        """Toggle debug messages on/off."""
        current_state = self.cog.get_setting('debug_enabled', default=False, guild_id=self.guild_id)
        new_state = not current_state

        self.cog.set_setting('debug_enabled', new_state, guild_id=self.guild_id)

        status = "enabled" if new_state else "disabled"
        await interaction.response.send_message(
            f"✅ Debug messages {status}",
            ephemeral=True
        )

        # Refresh the settings view to show updated state
        embed = await self.build_embed()
        await interaction.message.edit(embed=embed, view=self)


class SettingModal(Modal):
    """Modal for changing a setting value."""

    def __init__(self, cog: "UnifiedAdvertise", guild_id: int, setting_name: str, title: str, placeholder: str):
        super().__init__(title=title, timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.setting_name = setting_name
        self.parent_view = None

        self.value_input = TextInput(
            label="Value",
            placeholder=placeholder,
            required=True,
            max_length=20
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle setting update."""
        try:
            # Convert value to int
            value = int(self.value_input.value)

            # Handle special case: 0 means None for optional settings
            if value == 0 and self.setting_name in ["mod_channel_id", "guild_tag_id", "member_tag_id"]:
                value = None

            # Update setting
            self.cog.set_setting(
                self.setting_name,
                value,
                guild_id=self.guild_id
            )

            await interaction.response.send_message(
                f"✅ Updated {self.setting_name} to {value if value is not None else 'None'}",
                ephemeral=True
            )

            # Refresh parent view if available
            if self.parent_view:
                # Wait a moment for the setting to save
                await asyncio.sleep(0.5)
                # We can't directly edit the original message, so we'll just notify the user
                # They can click refresh on the settings view

        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid value. Please enter a number.",
                ephemeral=True
            )
        except Exception as e:
            self.cog.logger.error(f"Error updating setting: {e}")
            await interaction.response.send_message(
                f"❌ Error updating setting: {e}",
                ephemeral=True
            )


class UnifiedAdvertise(BaseCog, name="Unified Advertise"):
    @tasks.loop(hours=1)
    async def orphaned_post_scan(self) -> None:
        """Scan for orphaned advertisement posts and add them to pending deletions if not already tracked."""
        await self._send_debug_message("Starting orphaned post scan.")

        # Skip if paused
        if self.is_paused:
            return

        try:
            # Scan each guild's advertisement channel
            for guild in self.bot.guilds:
                guild_id = guild.id

                # Only process guilds where this cog is enabled
                if not self.bot.cog_manager.can_guild_use_cog(self.qualified_name, guild_id):
                    continue

                self._ensure_guild_initialized(guild_id)

                advertise_channel_id = self._get_advertise_channel_id(guild_id)
                if not advertise_channel_id:
                    continue  # Skip guilds without configured ad channel

                channel = self.bot.get_channel(advertise_channel_id)
                if not channel:
                    await self._send_debug_message(f"Orphan scan: Advertisement channel not found for guild {guild_id}: {advertise_channel_id}", guild_id)
                    continue

                # Fetch all active threads in the forum channel
                threads = []
                try:
                    # For forum channels, threads is a list property, not a method
                    threads = channel.threads
                except Exception as e:
                    await self._send_debug_message(f"Orphan scan: Failed to fetch threads for guild {guild_id}: {e}", guild_id)
                    continue

                tracked_ids = {t_id for t_id, _, _, _, _ in self.pending_deletions}
                new_orphans = 0
                cooldown_hours = self._get_cooldown_hours(guild_id)

                for thread in threads:
                    if thread.id not in tracked_ids:
                        # Extract actual user and guild information from embed
                        user_id, ad_guild_id, ad_type = await self._extract_user_and_guild_info(thread)

                        # Add all orphans regardless of pin status
                        deletion_time = datetime.datetime.now() + datetime.timedelta(hours=cooldown_hours)
                        notify = False
                        self.pending_deletions.append((thread.id, deletion_time, user_id, notify, guild_id))
                        new_orphans += 1

                        # Update cooldown timestamps to match this thread's creation time
                        thread_creation_timestamp = thread.created_at.isoformat()

                        # Get guild-specific cooldowns
                        guild_cooldowns = self.cooldowns.get(guild_id, {"users": {}, "guilds": {}})

                        if user_id != 0:
                            guild_cooldowns["users"][str(user_id)] = thread_creation_timestamp
                            await self._send_debug_message(f"Updated user {user_id} cooldown to match orphaned thread {thread.id} creation time", guild_id)

                        # For guild advertisements, also update guild cooldown
                        if ad_type == "guild" and ad_guild_id:
                            guild_cooldowns["guilds"][ad_guild_id] = thread_creation_timestamp
                            await self._send_debug_message(f"Updated guild {ad_guild_id} cooldown to match orphaned thread {thread.id} creation time", guild_id)

                        # Save back to main cooldowns
                        self.cooldowns[guild_id] = guild_cooldowns

                if new_orphans:
                    await self._save_pending_deletions()
                    await self._save_cooldowns(guild_id)  # Save updated cooldown timestamps
                    await self._send_debug_message(f"Orphan scan: Added {new_orphans} orphaned threads to pending deletions.", guild_id)
                else:
                    await self._send_debug_message("Orphan scan: No new orphaned threads found.", guild_id)

                # After handling orphans, check for duplicates
                await self._check_and_remove_duplicates(threads, guild_id)

        except Exception as e:
            await self._send_debug_message(f"Orphan scan: Error: {e}")

    async def _check_and_remove_duplicates(self, threads: list, guild_id: int) -> None:
        """Check for duplicate posts and remove all but the oldest one.

        Args:
            threads: List of threads to check
            guild_id: Discord guild ID
        """
        await self._send_debug_message("Starting duplicate detection scan.", guild_id)

        cooldown_hours = self._get_cooldown_hours(guild_id)
        guild_cooldowns = self.cooldowns.get(guild_id, {"users": {}, "guilds": {}})

        try:
            # Group threads by author to check for duplicates from same user
            author_threads = {}

            for thread in threads:
                user_id, guild_id, ad_type = await self._extract_user_and_guild_info(thread)
                if user_id == 0:
                    continue  # Skip threads with no identifiable user

                if user_id not in author_threads:
                    author_threads[user_id] = []
                author_threads[user_id].append((thread, guild_id, ad_type))

            duplicates_removed = 0

            # Check each author's threads for duplicates
            for user_id, user_thread_data in author_threads.items():
                if len(user_thread_data) <= 1:
                    continue  # No duplicates possible with only one thread

                # Extract just the threads for sorting
                user_threads = [thread_data[0] for thread_data in user_thread_data]

                # Sort threads by creation time (oldest first)
                user_threads.sort(key=lambda t: t.created_at)

                # Group similar threads (could be duplicates)
                duplicate_groups = []
                processed_threads = set()

                for i, thread1 in enumerate(user_threads):
                    if thread1.id in processed_threads:
                        continue

                    similar_threads = [thread1]
                    processed_threads.add(thread1.id)

                    # Check if other threads are similar to this one
                    for j, thread2 in enumerate(user_threads[i + 1 :], i + 1):
                        if thread2.id in processed_threads:
                            continue

                        if await self._are_threads_similar(thread1, thread2):
                            similar_threads.append(thread2)
                            processed_threads.add(thread2.id)

                    if len(similar_threads) > 1:
                        duplicate_groups.append(similar_threads)

                # Remove duplicates, keeping only the oldest or any pinned thread
                for duplicate_group in duplicate_groups:
                    # Check if any threads in the group are pinned
                    pinned_threads = [t for t in duplicate_group if hasattr(t, "pinned") and t.pinned]
                    unpinned_threads = [t for t in duplicate_group if not (hasattr(t, "pinned") and t.pinned)]

                    if pinned_threads:
                        # If there are pinned threads, keep all pinned threads and delete all unpinned ones
                        keep_threads = pinned_threads
                        delete_threads = unpinned_threads
                        await self._send_debug_message(
                            f"Found duplicates with {len(pinned_threads)} pinned thread(s) from user {user_id}, keeping pinned, deleting {len(delete_threads)} unpinned"
                        )
                    else:
                        # No pinned threads, keep the oldest (first in sorted list)
                        keep_threads = [duplicate_group[0]]
                        delete_threads = duplicate_group[1:]
                        await self._send_debug_message(
                            f"Found {len(delete_threads)} duplicate threads from user {user_id}, keeping oldest: {keep_threads[0].id}"
                        )

                    for thread in delete_threads:
                        try:
                            await thread.delete()
                            duplicates_removed += 1
                            await self._send_debug_message(f"Deleted duplicate thread {thread.id}", guild_id)

                            # Remove from pending deletions if it was there
                            self.pending_deletions = [entry for entry in self.pending_deletions if entry[0] != thread.id]

                        except Exception as e:
                            await self._send_debug_message(f"Error deleting duplicate thread {thread.id}: {e}", guild_id)

                    # Ensure all kept threads are properly tracked and update cooldowns
                    tracked_ids = {t_id for t_id, _, _, _, _ in self.pending_deletions}
                    for keep_thread in keep_threads:
                        # Get the thread's actual user and guild info
                        thread_user_id, thread_guild_id, thread_ad_type = await self._extract_user_and_guild_info(keep_thread)

                        if keep_thread.id not in tracked_ids:
                            deletion_time = datetime.datetime.now() + datetime.timedelta(hours=cooldown_hours)
                            notify = False  # Don't notify for duplicate cleanup
                            self.pending_deletions.append((keep_thread.id, deletion_time, thread_user_id, notify, guild_id))
                            await self._send_debug_message(f"Added kept thread {keep_thread.id} to pending deletions tracking", guild_id)

                        # Update cooldown timestamps to match the kept thread's creation time
                        thread_creation_timestamp = keep_thread.created_at.isoformat()

                        # Update user cooldown
                        if thread_user_id != 0:
                            guild_cooldowns["users"][str(thread_user_id)] = thread_creation_timestamp
                            await self._send_debug_message(
                                f"Updated user {thread_user_id} cooldown to match kept thread {keep_thread.id} creation time",
                                guild_id
                            )

                        # Update guild cooldown for guild advertisements
                        if thread_ad_type == "guild" and thread_guild_id:
                            guild_cooldowns["guilds"][thread_guild_id] = thread_creation_timestamp
                            await self._send_debug_message(
                                f"Updated guild {thread_guild_id} cooldown to match kept thread {keep_thread.id} creation time",
                                guild_id
                            )

                    # Save updated guild cooldowns
                    self.cooldowns[guild_id] = guild_cooldowns

            if duplicates_removed > 0:
                await self._save_pending_deletions()
                await self._save_cooldowns(guild_id)  # Save updated cooldown timestamps
                await self._send_debug_message(f"Duplicate scan complete: Removed {duplicates_removed} duplicate threads.", guild_id)
            else:
                await self._send_debug_message("Duplicate scan complete: No duplicates found.", guild_id)

        except Exception as e:
            await self._send_debug_message(f"Duplicate detection error: {e}", guild_id)

    async def _are_threads_similar(self, thread1, thread2) -> bool:
        """Determine if two threads are similar enough to be considered duplicates.

        Since all posts are created by the bot via forms, we can be more precise
        in duplicate detection by comparing the structured embed content.
        """
        try:
            # First check: if threads are from the same author and created very close together
            time_diff = abs((thread1.created_at - thread2.created_at).total_seconds())

            # If created within 2 minutes, likely a duplicate submission
            if time_diff <= 120:  # 2 minutes
                # Get the embed content from both threads to compare
                try:
                    embed1_data = None
                    embed2_data = None

                    # Get the first message from each thread (the bot's embed post)
                    async for msg1 in thread1.history(limit=1):
                        if msg1.author == self.bot.user and msg1.embeds:
                            embed1_data = msg1.embeds[0]
                        break

                    async for msg2 in thread2.history(limit=1):
                        if msg2.author == self.bot.user and msg2.embeds:
                            embed2_data = msg2.embeds[0]
                        break

                    if embed1_data and embed2_data:
                        return self._are_embeds_similar(embed1_data, embed2_data)

                except Exception:
                    pass  # If we can't fetch messages, fall back to title comparison

            # Fallback: Check if titles are very similar (for bot-generated titles)
            title1 = thread1.name.lower().strip()
            title2 = thread2.name.lower().strip()

            # Remove common bot-generated prefixes
            for prefix in ["[guild]", "[member]"]:
                title1 = title1.replace(prefix, "").strip()
                title2 = title2.replace(prefix, "").strip()

            # If titles are identical after cleaning, they're likely duplicates
            if title1 == title2:
                return True

            # Check for very similar titles (for cases where user name might vary slightly)
            if len(title1) > 10 and len(title2) > 10:
                # Extract key parts (like guild names or player IDs from titles)
                # Guild format: "[Guild] GuildName (ID)"
                # Member format: "[Member] PlayerName (PlayerID)"

                # Look for parentheses content (IDs)
                import re

                id_pattern = r"\(([^)]+)\)"

                id1_match = re.search(id_pattern, title1)
                id2_match = re.search(id_pattern, title2)

                if id1_match and id2_match:
                    id1 = id1_match.group(1).strip()
                    id2 = id2_match.group(1).strip()

                    # If the IDs are the same, likely duplicate
                    if id1 == id2:
                        return True

            return False

        except Exception as e:
            await self._send_debug_message(f"Error comparing threads {thread1.id} and {thread2.id}: {e}")
            return False

    def _are_embeds_similar(self, embed1, embed2) -> bool:
        """Compare two bot-generated embeds to see if they're duplicates.

        Since these are bot-generated embeds with consistent structure,
        we can be more precise in our comparison.
        """
        try:
            # Compare embed titles (should be very similar for duplicates)
            if embed1.title and embed2.title:
                title1 = embed1.title.lower().strip()
                title2 = embed2.title.lower().strip()
                if title1 == title2:
                    return True

            # Compare field values (the most reliable indicator for bot-generated content)
            if embed1.fields and embed2.fields:
                # Create dictionaries of field name -> value for easier comparison
                fields1 = {field.name.lower().strip(): field.value.lower().strip() for field in embed1.fields if field.name and field.value}
                fields2 = {field.name.lower().strip(): field.value.lower().strip() for field in embed2.fields if field.name and field.value}

                # Check for key identifying fields
                key_fields = ["player id", "guild id", "guild name"]

                for key_field in key_fields:
                    if key_field in fields1 and key_field in fields2:
                        value1 = fields1[key_field]
                        value2 = fields2[key_field]

                        # Remove markdown links if present: [TEXT](URL) -> TEXT
                        import re

                        link_pattern = r"\[([^\]]+)\]\([^)]+\)"
                        value1 = re.sub(link_pattern, r"\1", value1)
                        value2 = re.sub(link_pattern, r"\1", value2)

                        # If key identifying fields match, it's a duplicate
                        if value1 == value2 and len(value1) > 0:
                            return True

                # Additional check: if most fields match, likely duplicate
                matching_fields = 0
                total_fields = len(fields1)

                if total_fields > 0:
                    for field_name, value1 in fields1.items():
                        if field_name in fields2:
                            value2 = fields2[field_name]
                            if value1 == value2:
                                matching_fields += 1

                    # If 80% or more fields match, consider it a duplicate
                    if matching_fields / total_fields >= 0.8:
                        return True

            return False

        except Exception:
            return False

    """Combined cog for both guild and member advertisements.

    Provides functionality for posting, managing and moderating
    guild and member advertisements in a Discord forum channel.
    """

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.logger.info("Initializing UnifiedAdvertise")

        # Define default settings (per-guild)
        self.default_settings = {
            "cooldown_hours": 24,
            "advertise_channel_id": None,
            "mod_channel_id": None,
            "guild_tag_id": None,
            "member_tag_id": None,
            "testing_channel_id": None,
            "debug_enabled": False,
        }

        # Multi-guild data structures (will be populated in cog_initialize)
        # Format: {guild_id: {"users": {}, "guilds": {}}}
        self.cooldowns = {}
        # Format: [(thread_id, deletion_time, author_id, notify, guild_id), ...]
        self.pending_deletions = []

        # Store a reference to this cog
        self.bot.unified_advertise = self

    # === Settings Helper Methods ===

    def _ensure_guild_initialized(self, guild_id: int) -> None:
        """Ensure settings and data structures are initialized for a guild."""
        if guild_id:
            self.ensure_settings_initialized(guild_id=guild_id, default_settings=self.default_settings)

            # Initialize cooldowns for this guild if not present
            if guild_id not in self.cooldowns:
                self.cooldowns[guild_id] = {"users": {}, "guilds": {}}

    def _get_cooldown_hours(self, guild_id: int) -> int:
        """Get cooldown hours setting for a guild."""
        return self.get_setting('cooldown_hours', default=24, guild_id=guild_id)

    def _get_advertise_channel_id(self, guild_id: int) -> Optional[int]:
        """Get advertise channel ID setting for a guild."""
        return self.get_setting('advertise_channel_id', default=None, guild_id=guild_id)

    def _get_mod_channel_id(self, guild_id: int) -> Optional[int]:
        """Get mod channel ID setting for a guild."""
        return self.get_setting('mod_channel_id', default=None, guild_id=guild_id)

    def _get_guild_tag_id(self, guild_id: int) -> Optional[int]:
        """Get guild tag ID setting for a guild."""
        return self.get_setting('guild_tag_id', default=None, guild_id=guild_id)

    def _get_member_tag_id(self, guild_id: int) -> Optional[int]:
        """Get member tag ID setting for a guild."""
        return self.get_setting('member_tag_id', default=None, guild_id=guild_id)

    def _get_testing_channel_id(self, guild_id: int) -> Optional[int]:
        """Get testing channel ID setting for a guild."""
        return self.get_setting('testing_channel_id', default=None, guild_id=guild_id)

    def _get_cooldown_filename(self, guild_id: int) -> str:
        """Get cooldown filename for a guild."""
        return f'advertisement_cooldowns_{guild_id}.json'

    def _get_pending_deletions_filename(self, guild_id: int) -> str:
        """Get pending deletions filename for a guild."""
        return f'advertisement_pending_deletions_{guild_id}.pkl'

    async def cog_initialize(self) -> None:
        """Initialize the cog - called by BaseCog during ready process."""
        self.logger.info("Initializing Advertisement module...")

        try:
            async with self.task_tracker.task_context("Initialization") as tracker:
                # Initialize parent
                self.logger.debug("Initializing parent cog")
                await super().cog_initialize()

                # 1. Load data (multi-guild support will load for all configured guilds)
                self.logger.debug("Loading cached data")
                tracker.update_status("Loading data")
                await self._load_all_guild_data()

                # 2. Start scheduled tasks
                self.logger.debug("Starting scheduled tasks")
                tracker.update_status("Starting tasks")
                if not self.check_deletions.is_running():
                    self.check_deletions.start()
                if not self.weekly_cleanup.is_running():
                    self.weekly_cleanup.start()
                if not hasattr(self, "orphaned_post_scan") or not self.orphaned_post_scan.is_running():
                    self.orphaned_post_scan.start()

                # 3. Update status variables
                self._last_operation_time = datetime.datetime.utcnow()
                self._operation_count = 0

                # 4. Mark as ready
                self.set_ready(True)
                self.logger.info("Advertisement initialization complete")

                # 5. Sync slash commands for all guilds where this cog is enabled
                tracker.update_status("Syncing slash commands")
                await self._sync_commands_for_enabled_guilds()

        except Exception as e:
            self._has_errors = True
            self.logger.error(f"Failed to initialize Advertisement module: {e}", exc_info=True)
            raise

    async def _sync_commands_for_enabled_guilds(self) -> None:
        """Sync slash commands for all guilds where this cog is enabled."""
        try:
            # Normalize the cog name for config lookups (e.g., "Unified Advertise" -> "unified_advertise")
            normalized_cog_name = self.bot.cog_manager.class_name_to_filename(self.qualified_name.replace(' ', ''))
            self.logger.info(f"Checking cog enablement using qualified_name: '{self.qualified_name}' (normalized: '{normalized_cog_name}')")

            # Debug: Log what commands are in the tree
            all_commands = self.bot.tree.get_commands()
            self.logger.info(f"DEBUG: Bot tree has {len(all_commands)} global commands")
            for cmd in all_commands:
                self.logger.info(f"  - {cmd.name}: {cmd.description}")

            self.logger.info(f"Starting slash command sync for {len(self.bot.guilds)} guilds...")
            synced_count = 0
            skipped_count = 0
            for guild in self.bot.guilds:
                can_use = self.bot.cog_manager.can_guild_use_cog(normalized_cog_name, guild.id)
                self.logger.debug(f"Guild {guild.id} ({guild.name}): can_guild_use_cog('{normalized_cog_name}') = {can_use}")
                if can_use:
                    try:
                        self.logger.info(f"Syncing slash commands for guild {guild.id} ({guild.name})...")
                        # Copy global commands to this guild, then sync
                        self.bot.tree.copy_global_to(guild=guild)
                        synced = await self.bot.tree.sync(guild=guild)
                        synced_count += 1
                        self.logger.info(f"✓ Successfully synced {len(synced)} slash commands for guild {guild.id} ({guild.name})")
                        for cmd in synced:
                            self.logger.info(f"  - Synced: {cmd.name}")
                    except Exception as e:
                        self.logger.warning(f"✗ Failed to sync slash commands for guild {guild.id}: {e}")
                else:
                    skipped_count += 1
                    # self.logger.info(f"⊘ Skipping guild {guild.id} ({guild.name}) - cog not enabled")
            self.logger.info(f"Slash command sync complete: {synced_count} synced, {skipped_count} skipped out of {len(self.bot.guilds)} guilds")
        except Exception as e:
            self.logger.error(f"Error syncing commands for enabled guilds: {e}")

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded."""
        # Cancel scheduled tasks
        if hasattr(self, "check_deletions"):
            self.check_deletions.cancel()
        if hasattr(self, "weekly_cleanup"):
            self.weekly_cleanup.cancel()
        if hasattr(self, "orphaned_post_scan"):
            self.orphaned_post_scan.cancel()

        # Force save any modified data
        if self.is_data_modified():
            await self._save_cooldowns()
            await self._save_pending_deletions()

        # Clear tasks by invalidating the tracker
        if hasattr(self.task_tracker, "clear_error_state"):
            self.task_tracker.clear_error_state()

        # Call parent implementation
        await super().cog_unload()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Override interaction check for slash commands.

        For the unified_advertise cog:
        - The /advertise command is for managing user's own ads (ephemeral UI), so no channel restrictions
        - Future commands that post to channels should respect permission manager
        """
        # For now, /advertise is just for personal ad management (ephemeral)
        # If we add slash commands that post to channels, we'll check permissions for those
        return True

    # ====================
    # Standard Commands
    # ====================

    # ====================
    # Advertisement Commands
    # ====================

    @app_commands.command(name="advertise", description="Manage your advertisements")
    @app_commands.guild_only()
    async def advertise_slash(self, interaction: discord.Interaction) -> None:
        """Slash command for managing advertisements."""
        # Send response immediately to avoid timeout
        if not await self.wait_until_ready():
            await interaction.response.send_message("⏳ System is still initializing, please try again later.", ephemeral=True)
            return

        # Check if system is paused
        if self.is_paused:
            await interaction.response.send_message("⏸️ The advertisement system is currently paused. Please try again later.", ephemeral=True)
            return

        # Check permissions
        if not await self.interaction_check(interaction):
            return

        # Ensure we're in a guild
        if not interaction.guild:
            await interaction.response.send_message("❌ This command must be used in a server.", ephemeral=True)
            return

        guild_id = interaction.guild.id
        user_id = interaction.user.id

        # Initialize settings for this guild
        self._ensure_guild_initialized(guild_id)

        # Check if user is admin/owner for admin view
        is_admin = interaction.user.guild_permissions.administrator
        is_bot_owner = await self.bot.is_owner(interaction.user)

        if is_admin or is_bot_owner:
            # Show admin view
            view = AdminAdManagementView(self, guild_id, is_bot_owner)
            embed = await view.update_view(interaction)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            # Show user view
            view = AdManagementView(self, user_id, guild_id)
            embed = await view.update_view(interaction)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # ====================
    # Owner Commands
    # ====================
    # Task Loops
    # ====================

    @tasks.loop(hours=168)  # 168 hours = 1 week
    async def weekly_cleanup(self) -> None:
        """Weekly task to clean up expired cooldowns."""
        await self._cleanup_cooldowns()

    @tasks.loop(minutes=1)  # Check for threads to delete every minute
    async def check_deletions(self) -> None:
        """Check for threads that need to be deleted."""
        # Skip if paused
        if self.is_paused:
            return

        async with self.task_tracker.task_context("Advertisement Deletion Check"):
            current_time = datetime.datetime.now()
            to_remove = []  # Track entries to remove

            for thread_id, deletion_time, author_id, notify, guild_id in self.pending_deletions:
                if current_time >= deletion_time:
                    try:
                        # Try to get the thread
                        thread = await self.bot.fetch_channel(thread_id)
                        # Skip deletion if thread is pinned
                        if hasattr(thread, "pinned") and thread.pinned:
                            self.logger.info(f"Skipping deletion for pinned thread {thread_id}")
                            continue

                        # Send notification if requested
                        if notify and author_id:
                            try:
                                user = await self.bot.fetch_user(author_id)
                                if user:
                                    await user.send(f"Your advertisement in {thread.name} has expired and been removed.")
                            except Exception as e:
                                self.logger.warning(f"Failed to send notification to user {author_id}: {e}")

                        # Delete the thread
                        await thread.delete()
                        self.logger.info(f"Deleted advertisement thread {thread_id} for guild {guild_id}")
                        self._operation_count += 1

                    except discord.NotFound:
                        # Thread already deleted or doesn't exist
                        self.logger.info(f"Thread {thread_id} no longer exists, removing from tracking")

                    except Exception as e:
                        self.logger.error(f"Error processing thread {thread_id}: {e}")
                        self._has_errors = True
                        # Don't remove from list if there's an unexpected error
                        continue

                    # Mark for removal if deleted or not found
                    to_remove.append(thread_id)
                    self._last_operation_time = datetime.datetime.now()

            # Remove processed entries
            if to_remove:
                self.pending_deletions = [entry for entry in self.pending_deletions if entry[0] not in to_remove]
                await self._save_pending_deletions()

    @check_deletions.before_loop
    async def before_check_deletions(self) -> None:
        """Wait until the bot is ready before starting the deletion check task."""
        await self.bot.wait_until_ready()

    @weekly_cleanup.before_loop
    async def before_weekly_cleanup(self) -> None:
        """Wait until the bot is ready before starting the task."""
        await self.bot.wait_until_ready()

        # Calculate time until next midnight
        now = datetime.datetime.now()
        tomorrow = now + datetime.timedelta(days=1)
        midnight = datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0)
        seconds_until_midnight = (midnight - now).total_seconds()

        # Wait until midnight to start the first run
        await asyncio.sleep(seconds_until_midnight)

    @orphaned_post_scan.before_loop
    async def before_orphaned_post_scan(self) -> None:
        """Wait until the bot is ready before starting the orphaned post scan."""
        await self.bot.wait_until_ready()

    # ====================
    # Helper Methods
    # ====================

    async def _load_all_guild_data(self) -> None:
        """Load data for all configured guilds."""
        try:
            # Get all guilds the bot is in
            for guild in self.bot.guilds:
                guild_id = guild.id

                # Only load data for guilds where this cog is enabled
                if not self.bot.cog_manager.can_guild_use_cog(self.qualified_name, guild_id):
                    continue

                self._ensure_guild_initialized(guild_id)

                # Load cooldowns for this guild
                cooldowns_file = self.data_directory / self._get_cooldown_filename(guild_id)
                guild_cooldowns = await self.load_data(cooldowns_file, default={"users": {}, "guilds": {}})
                self.cooldowns[guild_id] = guild_cooldowns

                self.logger.info(f"Loaded cooldowns for guild {guild_id}: {len(guild_cooldowns.get('users', {}))} users, {len(guild_cooldowns.get('guilds', {}))} guilds")

            # Load all pending deletions (global, but we'll track guild_id in the tuple)
            deletions_file = self.data_directory / "advertisement_pending_deletions_all.pkl"
            self.pending_deletions = await self._load_pending_deletions_multi_guild(deletions_file)

            self.logger.info(f"Loaded {len(self.pending_deletions)} total pending deletions across all guilds")

        except Exception as e:
            self.logger.error(f"Error loading guild data: {e}", exc_info=True)

    async def _load_pending_deletions_multi_guild(self, file_path: Path) -> List[Tuple[int, datetime.datetime, int, bool, int]]:
        """Load pending deletions with multi-guild support.

        Returns:
            List of tuples: (thread_id, deletion_time, author_id, notify, guild_id)
        """
        try:
            data = await self.load_data(file_path, default=[])
            converted_data = []

            for entry in data:
                if len(entry) == 5:  # New format with guild_id
                    thread_id, del_time, author_id, notify, guild_id = entry
                    if isinstance(del_time, str):
                        del_time = datetime.datetime.fromisoformat(del_time)
                    converted_data.append((int(thread_id), del_time, int(author_id), bool(notify), int(guild_id)))
                elif len(entry) == 4:  # Old format without guild_id (thread_id, time, author_id, notify)
                    thread_id, del_time, author_id, notify = entry
                    if isinstance(del_time, str):
                        del_time = datetime.datetime.fromisoformat(del_time)
                    # Try to determine guild_id from thread
                    guild_id = await self._get_thread_guild_id(thread_id)
                    converted_data.append((int(thread_id), del_time, int(author_id), bool(notify), guild_id))
                    self.logger.info(f"Migrated deletion entry for thread {thread_id} to include guild_id {guild_id}")
                else:
                    self.logger.warning(f"Invalid deletion entry format: {entry}")
                    continue

            return converted_data
        except Exception as e:
            self.logger.error(f"Error loading pending deletions: {e}")
            return []

    async def _get_thread_guild_id(self, thread_id: int) -> int:
        """Try to determine guild_id from a thread."""
        try:
            thread = await self.bot.fetch_channel(thread_id)
            if thread and hasattr(thread, 'guild'):
                return thread.guild.id
        except Exception:
            pass
        # Default to first guild if we can't determine
        if self.bot.guilds:
            return self.bot.guilds[0].id
        return 0

    async def _save_all_guild_cooldowns(self) -> None:
        """Save cooldowns for all guilds."""
        try:
            for guild_id, cooldowns in self.cooldowns.items():
                cooldowns_file = self.data_directory / self._get_cooldown_filename(guild_id)
                await self.save_data_if_modified(cooldowns, cooldowns_file)
            self.mark_data_modified()
        except Exception as e:
            self.logger.error(f"Error saving all guild cooldowns: {e}")

    async def _save_pending_deletions_multi_guild(self) -> None:
        """Save pending deletions with multi-guild support."""
        try:
            deletions_file = self.data_directory / "advertisement_pending_deletions_all.pkl"

            # Convert datetime objects to ISO strings for serialization
            serializable_data = [
                (thread_id, deletion_time.isoformat() if isinstance(deletion_time, datetime.datetime) else deletion_time,
                 author_id, notify, guild_id)
                for thread_id, deletion_time, author_id, notify, guild_id in self.pending_deletions
            ]

            await self.save_data_if_modified(serializable_data, deletions_file)
            self.mark_data_modified()
        except Exception as e:
            self.logger.error(f"Error saving pending deletions: {e}")

    async def _cleanup_cooldowns(self) -> None:
        """Remove expired cooldowns from the cooldowns dictionary."""
        try:
            current_time = datetime.datetime.now()
            total_expired = 0

            # Iterate through all guilds
            for guild_id in list(self.cooldowns.keys()):
                cooldown_hours = await self._get_cooldown_hours(guild_id)
                sections = ["users", "guilds"]
                guild_expired = 0

                for section in sections:
                    expired_items = []
                    guild_cooldowns = self.cooldowns[guild_id].get(section, {})

                    for item_id, timestamp in list(guild_cooldowns.items()):
                        timestamp_dt = datetime.datetime.fromisoformat(timestamp)
                        elapsed = current_time - timestamp_dt
                        if elapsed.total_seconds() > cooldown_hours * 3600:
                            expired_items.append(item_id)

                    for item_id in expired_items:
                        del self.cooldowns[guild_id][section][item_id]
                        guild_expired += 1

                if guild_expired > 0:
                    self.logger.info(f"Weekly cleanup: Removed {guild_expired} expired cooldowns for guild {guild_id}")
                    total_expired += guild_expired

            if total_expired > 0:
                await self._save_all_guild_cooldowns()
                self.logger.info(f"Weekly cleanup: Removed {total_expired} total expired cooldowns across all guilds")
                self._last_operation_time = datetime.datetime.now()
        except Exception as e:
            self.logger.error(f"Error during cooldown cleanup: {e}")
            self._has_errors = True

    async def _load_cooldowns(self) -> Dict[str, Dict[str, str]]:
        """Deprecated: Load cooldowns for single guild. Use _load_all_guild_data instead."""
        self.logger.warning("_load_cooldowns is deprecated, use _load_all_guild_data instead")
        return {"users": {}, "guilds": {}}

    async def _save_cooldowns(self, guild_id: int = None) -> None:
        """Save cooldowns - updated for multi-guild support."""
        if guild_id:
            # Save for specific guild
            try:
                cooldowns_file = self.data_directory / self._get_cooldown_filename(guild_id)
                await self.save_data_if_modified(self.cooldowns.get(guild_id, {"users": {}, "guilds": {}}), cooldowns_file)
                self.mark_data_modified()
            except Exception as e:
                self.logger.error(f"Error saving cooldowns for guild {guild_id}: {e}")
        else:
            # Save for all guilds
            await self._save_all_guild_cooldowns()

    async def _load_pending_deletions(self) -> List[Tuple[int, datetime.datetime, int, bool]]:
        """Deprecated: Use _load_pending_deletions_multi_guild instead."""
        self.logger.warning("_load_pending_deletions is deprecated, use _load_pending_deletions_multi_guild instead")
        return []

    async def _save_pending_deletions(self) -> None:
        """Save pending deletions - updated for multi-guild support."""
        await self._save_pending_deletions_multi_guild()

    async def _resume_deletion_tasks(self) -> None:
        """Check for threads that were scheduled for deletion before restart."""
        self.logger.info(f"Resumed tracking {len(self.pending_deletions)} pending thread deletions")

    async def _extract_user_and_guild_info(self, thread) -> tuple[int, str, str]:
        """Extract the actual user ID and guild ID from the thread's embed data.

        Returns:
            tuple: (user_id, guild_id, ad_type) where user_id is the Discord user who submitted the form,
                   guild_id is the guild ID for guild ads (or empty for member ads),
                   and ad_type is either 'guild' or 'member'
        """
        try:
            # Get the first message from the thread (the bot's embed post)
            async for message in thread.history(limit=1):
                if message.author == self.bot.user and message.embeds:
                    embed = message.embeds[0]

                    # Create a dictionary of field names to values for easier lookup
                    fields = {field.name.lower().strip(): field.value.strip() for field in embed.fields if field.name and field.value}

                    # Determine advertisement type from embed title or fields
                    ad_type = "member"
                    guild_id = ""

                    if embed.title and "[guild]" in embed.title.lower():
                        ad_type = "guild"
                        # Extract guild ID from embed fields
                        if "guild id" in fields:
                            guild_id = self._normalize_guild_id(fields["guild id"])
                    elif "guild id" in fields:
                        ad_type = "guild"
                        guild_id = self._normalize_guild_id(fields["guild id"])

                    # Extract user ID from embed fields
                    user_id = 0
                    if "posted by" in fields:
                        # Extract Discord user ID from "Posted by" field
                        posted_by = fields["posted by"]
                        # Format is typically "<@user_id>" or "username (user_id)"
                        user_match = re.search(r"<@(\d+)>|(\d{17,19})", posted_by)
                        if user_match:
                            user_id = int(user_match.group(1) or user_match.group(2))
                    elif "player id" in fields:
                        # For member ads, we might need to cross-reference the player ID
                        # But for now, fall back to thread owner
                        user_id = getattr(thread, "owner_id", 0) or 0

                    if user_id == 0:
                        # Fallback to thread owner if we can't extract from embed
                        user_id = getattr(thread, "owner_id", 0) or 0

                    return user_id, guild_id, ad_type
                break
        except Exception as e:
            await self._send_debug_message(f"Error extracting user/guild info from thread {thread.id}: {e}")

        # Fallback values
        return getattr(thread, "owner_id", 0) or 0, "", "member"

    def _normalize_guild_id(self, guild_id: str) -> str:
        """Normalize guild ID to ensure consistent handling.

        Args:
            guild_id: Raw guild ID string

        Returns:
            str: Normalized guild ID (uppercase, stripped)
        """
        if not guild_id:
            return ""
        return str(guild_id).upper().strip()

    async def _send_debug_message(self, message: str, guild_id: Optional[int] = None) -> None:
        """Send debug message to testing channel if configured and debug is enabled.

        Args:
            message: The debug message to send
            guild_id: Optional guild ID to send to that guild's testing channel
        """
        # Check if debug is enabled for this guild
        if guild_id:
            debug_enabled = self.get_setting('debug_enabled', default=False, guild_id=guild_id)
            testing_channel_id = self._get_testing_channel_id(guild_id)
        else:
            # Try to get from first configured guild as fallback
            debug_enabled = False
            testing_channel_id = None
            for gid in self.cooldowns.keys():
                debug_enabled = self.get_setting('debug_enabled', default=False, guild_id=gid)
                testing_channel_id = self._get_testing_channel_id(gid)
                if testing_channel_id and debug_enabled:
                    break

        # Only send to Discord if debug is enabled
        if debug_enabled and testing_channel_id:
            try:
                channel = self.bot.get_channel(testing_channel_id)
                if channel:
                    # Add UTC timestamp to debug message
                    utc_timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                    await channel.send(f"🔧 **[{utc_timestamp}] Advertise Debug**: {message}")
            except Exception as e:
                self.logger.error(f"Failed to send debug message to testing channel: {e}")

    async def check_cooldowns(
        self, interaction: discord.Interaction, user_id: int, ad_guild_id: Optional[str] = None, ad_type: Optional[str] = None
    ) -> bool:
        """Check if user or guild is on cooldown and handle the response.

        Args:
            interaction: The discord interaction
            user_id: Discord user ID
            ad_guild_id: In-game Guild ID for guild advertisements (optional) - will be normalized for consistent checking
            ad_type: Type of advertisement (guild or member)

        Returns:
            bool: True if not on cooldown, False if on cooldown
        """
        # Get the Discord guild ID (server ID)
        discord_guild_id = interaction.guild.id if interaction.guild else None
        if not discord_guild_id:
            return False

        # Check if user or guild is banned
        if ad_type == AdvertisementType.GUILD and ad_guild_id:
            # Normalize the guild ID
            normalized_guild_id = self._normalize_guild_id(ad_guild_id)
            banned_guilds = self.get_setting("banned_guilds", default=[], guild_id=discord_guild_id)
            if isinstance(banned_guilds, list) and normalized_guild_id in banned_guilds:
                await interaction.response.send_message(
                    "❌ This guild has been banned from posting advertisements in this server.",
                    ephemeral=True
                )
                return False

        if ad_type == AdvertisementType.MEMBER:
            banned_users = self.get_setting("banned_users", default=[], guild_id=discord_guild_id)
            if isinstance(banned_users, list) and user_id in banned_users:
                await interaction.response.send_message(
                    "❌ You have been banned from posting member advertisements in this server.",
                    ephemeral=True
                )
                return False

        # Ensure guild is initialized
        self._ensure_guild_initialized(discord_guild_id)

        # Get cooldown settings for this guild
        cooldown_hours = self._get_cooldown_hours(discord_guild_id)
        mod_channel_id = self._get_mod_channel_id(discord_guild_id)

        # Get guild-specific cooldowns
        guild_cooldowns = self.cooldowns.get(discord_guild_id, {"users": {}, "guilds": {}})

        # Normalize ad_guild_id if provided (for in-game guild ads)
        if ad_guild_id:
            ad_guild_id = self._normalize_guild_id(ad_guild_id)

        # Check user cooldown
        if str(user_id) in guild_cooldowns["users"]:
            timestamp = guild_cooldowns["users"][str(user_id)]
            # Parse the stored timestamp
            stored_time = datetime.datetime.fromisoformat(timestamp)
            # Convert to UTC if needed and make timezone-aware for consistent comparison
            if stored_time.tzinfo is None:
                # Assume naive timestamps are UTC
                stored_time = stored_time.replace(tzinfo=datetime.timezone.utc)
            current_time = datetime.datetime.now(datetime.timezone.utc)
            elapsed = (current_time - stored_time).total_seconds()

            if elapsed < cooldown_hours * 3600:
                hours_left = cooldown_hours - (elapsed / 3600)

                # Send notification to mod channel about bypass attempt
                if mod_channel_id:
                    mod_channel = self.bot.get_channel(mod_channel_id)
                    if mod_channel:
                        await mod_channel.send(
                            f"⚠️ **Advertisement Cooldown Bypass Attempt**\n"
                            f"User: {interaction.user.name} (ID: {interaction.user.id})\n"
                            f"Type: User cooldown ({ad_type})\n"
                            f"Time remaining: {hours_left:.1f} hours"
                        )

                await interaction.response.send_message(
                    f"You can only post one advertisement every {cooldown_hours} hours. "
                    f"Please try again in {hours_left:.1f} hours.\n"
                    f"If you attempt to bypass this limit, you will be banned from advertising.",
                    ephemeral=True,
                )
                return False

        # Check in-game guild cooldown if applicable
        if ad_guild_id and ad_guild_id in guild_cooldowns["guilds"]:
            timestamp = guild_cooldowns["guilds"][ad_guild_id]
            # Parse the stored timestamp
            stored_time = datetime.datetime.fromisoformat(timestamp)
            # Convert to UTC if needed and make timezone-aware for consistent comparison
            if stored_time.tzinfo is None:
                # Assume naive timestamps are UTC
                stored_time = stored_time.replace(tzinfo=datetime.timezone.utc)
            current_time = datetime.datetime.now(datetime.timezone.utc)
            elapsed = (current_time - stored_time).total_seconds()

            if elapsed < cooldown_hours * 3600:
                hours_left = cooldown_hours - (elapsed / 3600)

                # Send notification to mod channel about guild cooldown bypass attempt
                if mod_channel_id:
                    mod_channel = self.bot.get_channel(mod_channel_id)
                    if mod_channel:
                        await mod_channel.send(
                            f"⚠️ **Guild Advertisement Cooldown Bypass Attempt**\n"
                            f"User: {interaction.user.name} (ID: {interaction.user.id})\n"
                            f"Guild ID: {ad_guild_id}\n"
                            f"Time remaining: {hours_left:.1f} hours"
                        )

                await interaction.response.send_message(
                    f"This guild was already advertised in the past {cooldown_hours} hours. "
                    f"Please try again in {hours_left:.1f} hours.\n"
                    f"If you attempt to bypass this limit, your guild will be banned from advertising.",
                    ephemeral=True,
                )
                return False

        return True

    async def post_advertisement(
        self, interaction: discord.Interaction, embed: discord.Embed, thread_title: str, ad_type: str, ad_guild_id: Optional[str], notify: bool
    ) -> None:
        """Post the advertisement as a thread in the forum channel.

        Args:
            interaction: Discord interaction object (response already sent)
            embed: Embed to post
            thread_title: Title for the forum thread
            ad_type: Type of advertisement (guild or member)
            ad_guild_id: In-game Guild ID (optional, for guild advertisements)
            notify: Whether to notify the user when the ad expires
        """
        start_time = time.time()

        # Get Discord guild ID
        discord_guild_id = interaction.guild.id if interaction.guild else None
        if not discord_guild_id:
            await interaction.followup.send("❌ This command must be used in a server.", ephemeral=True)
            return

        await self._send_debug_message(f"Starting post_advertisement for user {interaction.user.id} ({interaction.user.name}), type: {ad_type}")

        try:
            # Ensure guild is initialized
            self._ensure_guild_initialized(discord_guild_id)

            # Get guild-specific settings
            advertise_channel_id = self._get_advertise_channel_id(discord_guild_id)
            guild_tag_id = self._get_guild_tag_id(discord_guild_id)
            member_tag_id = self._get_member_tag_id(discord_guild_id)
            cooldown_hours = self._get_cooldown_hours(discord_guild_id)

            # Get the forum channel first (quick check)
            channel_fetch_start = time.time()
            channel = self.bot.get_channel(advertise_channel_id)
            channel_fetch_time = time.time() - channel_fetch_start
            await self._send_debug_message(f"Channel fetch took {channel_fetch_time:.2f}s for user {interaction.user.id}")

            if not channel:
                await self._send_debug_message(f"❌ Advertisement channel not found: {advertise_channel_id}")
                await interaction.followup.send("There was an error posting your advertisement. Please contact a server administrator.", ephemeral=True)
                return

            # Now do the heavy work (initial response already sent by form)
            async with self.task_tracker.task_context("Posting Advertisement"):
                # Determine which tag to apply based on advertisement type
                applied_tags = []
                if ad_type == AdvertisementType.GUILD and guild_tag_id:
                    try:
                        # Find the tag object by ID
                        for tag in channel.available_tags:
                            if tag.id == guild_tag_id:
                                applied_tags.append(tag)
                                break
                    except Exception as e:
                        self.logger.error(f"Error finding guild tag: {e}")
                        self._has_errors = True

                elif ad_type == AdvertisementType.MEMBER and member_tag_id:
                    try:
                        # Find the tag object by ID
                        for tag in channel.available_tags:
                            if tag.id == member_tag_id:
                                applied_tags.append(tag)
                                break
                    except Exception as e:
                        self.logger.error(f"Error finding member tag: {e}")
                        self._has_errors = True

                # Create the forum thread with tags
                thread_create_start = time.time()
                thread_with_message = await channel.create_thread(
                    name=thread_title,
                    content="",  # Empty content
                    embed=embed,
                    applied_tags=applied_tags,  # Apply the tags
                    auto_archive_duration=1440,  # Auto-archive after 24 hours
                )
                thread_create_time = time.time() - thread_create_start
                await self._send_debug_message(f"Thread creation took {thread_create_time:.2f}s for user {interaction.user.id}")

                thread = thread_with_message.thread
                await self._send_debug_message(
                    f"✅ Created advertisement thread: {thread.id} for user {interaction.user.id} ({interaction.user.name}), type: {ad_type}"
                )
                self._operation_count += 1
                self._last_operation_time = datetime.datetime.now()

                # Update cooldowns for this guild
                cooldown_start = time.time()
                current_time = datetime.datetime.now(datetime.timezone.utc).isoformat()

                # Get guild-specific cooldowns
                guild_cooldowns = self.cooldowns.get(discord_guild_id, {"users": {}, "guilds": {}})
                guild_cooldowns["users"][str(interaction.user.id)] = current_time

                # If it's a guild advertisement, also add in-game guild cooldown
                if ad_guild_id:
                    guild_cooldowns["guilds"][ad_guild_id] = current_time

                self.cooldowns[discord_guild_id] = guild_cooldowns
                await self._save_cooldowns(discord_guild_id)
                cooldown_time = time.time() - cooldown_start
                await self._send_debug_message(f"Cooldown update took {cooldown_time:.2f}s for user {interaction.user.id}")

                # Schedule thread for deletion with author ID, notification preference, and guild ID
                schedule_start = time.time()
                deletion_time = datetime.datetime.now() + datetime.timedelta(hours=cooldown_hours)
                self.pending_deletions.append((thread.id, deletion_time, interaction.user.id, notify, discord_guild_id))
                await self._save_pending_deletions()
                schedule_time = time.time() - schedule_start
                await self._send_debug_message(f"Deletion scheduling took {schedule_time:.2f}s for user {interaction.user.id}")

                total_time = time.time() - start_time
                await self._send_debug_message(
                    f"✅ Advertisement posting completed in {total_time:.2f}s for user {interaction.user.id} ({interaction.user.name})"
                )

        except Exception as e:
            total_time = time.time() - start_time
            await self._send_debug_message(f"❌ Error in post_advertisement after {total_time:.2f}s for user {interaction.user.id}: {str(e)}")
            self.logger.error(f"Error in post_advertisement after {total_time:.2f}s: {e}", exc_info=True)
            self._has_errors = True

            # Try to send error message - use followup since initial response was already sent in form
            try:
                await interaction.followup.send("There was an error posting your advertisement. Please contact a server administrator.", ephemeral=True)
            except Exception as response_error:
                await self._send_debug_message(f"❌ Failed to send error response to user {interaction.user.id}: {str(response_error)}")


# ====================
# Cog Setup
# ====================


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UnifiedAdvertise(bot))

    # Note: Slash command syncing is now handled automatically by CogManager
    # when cogs are enabled/disabled for guilds
    bot.logger.info("UnifiedAdvertise cog loaded - slash commands will sync per-guild via CogManager")
