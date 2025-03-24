# Standard library imports
import asyncio
import datetime
import re
from typing import Dict, List, Optional, Tuple, ClassVar

# Third-party imports
import discord
from discord.ext import commands, tasks
from discord.ui import Button, View, Modal, TextInput, Select

# Local application imports
from fish_bot.basecog import BaseCog
from fish_bot.utils.decorators import flexible_command


class AdvertisementType:
    """Constants for advertisement types."""
    GUILD: ClassVar[str] = "guild"
    MEMBER: ClassVar[str] = "member"


class AdTypeSelection(View):
    """View with buttons to select advertisement type."""

    def __init__(self, cog: 'UnifiedAdvertise') -> None:
        """Initialize the view with a reference to the cog.

        Args:
            cog: The UnifiedAdvertise cog instance
        """
        super().__init__(timeout=180)  # 3 minute timeout
        self.cog = cog

    @discord.ui.button(label="Guild Advertisement", style=discord.ButtonStyle.primary, emoji="🏰")
    async def guild_button(self, interaction: discord.Interaction, button: Button) -> None:
        await interaction.response.send_modal(GuildAdvertisementForm(self.cog))

    @discord.ui.button(label="Member Advertisement", style=discord.ButtonStyle.success, emoji="👤")
    async def member_button(self, interaction: discord.Interaction, button: Button) -> None:
        try:
            await interaction.response.send_modal(MemberAdvertisementForm(self.cog))
        except Exception as e:
            self.cog.logger.error(f"Error showing member advertisement form: {e}")
            await interaction.response.send_message(
                "There was an error showing the advertisement form. Please try again later.",
                ephemeral=True
            )

    async def on_timeout(self) -> None:
        # Disable all buttons when the view times out
        for item in self.children:
            item.disabled = True
        # Try to edit the original message with disabled buttons
        try:
            if hasattr(self, 'message'):
                await self.message.edit(view=self)
        except discord.NotFound:
            pass  # Message might have been deleted


class GuildAdvertisementForm(Modal, title="Guild Advertisement Form"):
    """Modal form for collecting guild advertisement information."""

    def __init__(self, cog: 'UnifiedAdvertise') -> None:
        """Initialize the view with a reference to the cog.

        Args:
            cog: The UnifiedAdvertise cog instance
        """
        super().__init__(timeout=180)  # 3 minute timeout
        self.cog = cog

    guild_name = TextInput(
        label="Guild Name",
        placeholder="Enter your guild's name",
        required=True,
        max_length=100
    )

    guild_id = TextInput(
        label="Guild ID",
        placeholder="Enter your guild's ID (e.g. A1B2C3)",
        required=True,
        min_length=6,
        max_length=6
    )

    guild_leader = TextInput(
        label="Guild Leader",
        placeholder="Enter guild leader's name",
        required=True,
        max_length=100
    )

    member_count = TextInput(
        label="Member Count",
        placeholder="How many active members?",
        required=True,
        max_length=10
    )

    description = TextInput(
        label="Guild Description",
        placeholder="Tell us about your guild...",
        required=True,
        max_length=1000,
        style=discord.TextStyle.paragraph
    )

    # Remove the notify_on_expire TextInput and replace with Select
    notify_on_expire = Select(
        placeholder="Would you like to be notified when your ad expires?",
        options=[
            discord.SelectOption(label="Yes", value="yes", emoji="✉️"),
            discord.SelectOption(label="No", value="no", emoji="🔕")
        ],
        min_values=1,
        max_values=1,
        custom_id="notify_select"  # Add custom ID for component handling
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        # Check if guild ID is valid (only A-Z, 0-9, exactly 6 chars)
        guild_id = self.guild_id.value.upper()
        if not re.match(r'^[A-Z0-9]{6}$', guild_id):
            await interaction.response.send_message(
                "Guild ID must be exactly 6 characters and only contain letters A-Z and numbers 0-9.",
                ephemeral=True
            )
            return

        # Process notification preference
        notify = self.notify_on_expire.values[0] == "yes"

        # Check cooldowns before processing
        user_id = interaction.user.id

        cooldown_check = await self.cog.check_cooldowns(
            interaction,
            user_id,
            guild_id,
            AdvertisementType.GUILD
        )

        if not cooldown_check:
            return

        # Create guild advertisement embed
        embed = discord.Embed(
            title=self.guild_name.value,
            description=self.description.value,
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )

        embed.set_author(name=f"Guild Ad by {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        embed.add_field(name="Guild ID", value=guild_id, inline=True)  # Display uppercase ID
        embed.add_field(name="Leader", value=self.guild_leader.value, inline=True)
        embed.add_field(name="Member Count", value=self.member_count.value, inline=True)
        embed.set_footer(text="Use /advertise to submit your own advertisement")

        # Post advertisement and update cooldowns
        thread_title = f"[Guild] {self.guild_name.value} ({guild_id})"
        await self.cog.post_advertisement(interaction, embed, thread_title, AdvertisementType.GUILD, guild_id, notify)

    async def on_timeout(self) -> None:
        """Handle form timeout."""
        try:
            await self.interaction.response.send_message(
                "The form timed out. Please try submitting your advertisement again.",
                ephemeral=True
            )
        except (discord.NotFound, discord.HTTPException):
            pass


class MemberAdvertisementForm(Modal, title="Member Advertisement Form"):
    """Modal form for collecting member advertisement information."""

    def __init__(self, cog: 'UnifiedAdvertise') -> None:
        """Initialize the view with a reference to the cog.

        Args:
            cog: The UnifiedAdvertise cog instance
        """
        super().__init__(timeout=180)  # 3 minute timeout
        self.logger.info("Initializing UnifiedAdvertise")
        self.cog = cog

    player_id = TextInput(
        label="Player ID",
        placeholder="Your player ID",
        required=True,
        max_length=50
    )

    weekly_boxes = TextInput(
        label="Weekly Box Count",
        placeholder="How many weekly boxes do you usually clear? (out of 7)",
        required=True,
        max_length=10
    )

    additional_info = TextInput(
        label="Additional Information",
        placeholder="What else should we know about you?",
        required=True,
        max_length=1000,
        style=discord.TextStyle.paragraph
    )

    # Remove the notify_on_expire TextInput and replace with Select
    notify_on_expire = Select(
        placeholder="Would you like to be notified when your ad expires?",
        options=[
            discord.SelectOption(label="Yes", value="yes", emoji="✉️"),
            discord.SelectOption(label="No", value="no", emoji="🔕")
        ],
        min_values=1,
        max_values=1,
        custom_id="notify_select"  # Add custom ID for component handling
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        # Check if player ID is valid (only A-Z, 0-9)
        player_id = self.player_id.value.upper()
        if not re.match(r'^[A-Z0-9]+$', player_id):
            self.cog.logger.warning(f"User {interaction.user.id} provided invalid player ID format: {player_id}")
            await interaction.response.send_message(
                "Player ID can only contain letters A-Z and numbers 0-9.",
                ephemeral=True
            )
            return

        # Process notification preference
        notify = self.notify_on_expire.values[0] == "yes"

        # Check cooldowns before processing
        user_id = interaction.user.id

        cooldown_check = await self.cog.check_cooldowns(
            interaction,
            user_id,
            None,
            AdvertisementType.MEMBER
        )

        if not cooldown_check:
            return

        # Create member advertisement embed
        embed = discord.Embed(
            title=f"Player: {interaction.user.name}",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )

        embed.set_author(name=f"Submitted by {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)

        # Make the Player ID a clickable link (uppercase)
        url_value = f"[{player_id}](https://thetower.lol/player?player={player_id})"
        embed.add_field(name="Player ID", value=url_value, inline=True)
        embed.add_field(name="Weekly Box Count", value=self.weekly_boxes.value, inline=True)
        embed.add_field(name="Additional Info", value=self.additional_info.value, inline=False)
        embed.set_footer(text="Use /advertise to submit your own advertisement")

        # Post advertisement and update cooldowns
        thread_title = f"[Member] {interaction.user.name} ({player_id})"
        await self.cog.post_advertisement(interaction, embed, thread_title, AdvertisementType.MEMBER, None, notify)

    async def on_timeout(self) -> None:
        """Handle form timeout."""
        try:
            await self.interaction.response.send_message(
                "The form timed out. Please try submitting your advertisement again.",
                ephemeral=True
            )
        except (discord.NotFound, discord.HTTPException):
            pass


class UnifiedAdvertise(BaseCog, name="Unified Advertise"):
    """Combined cog for both guild and member advertisements.

    Provides functionality for posting, managing and moderating
    guild and member advertisements in a Discord forum channel.
    """

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.logger.info("Initializing UnifiedAdvertise")

        # Define settings with descriptions
        settings_config = {
            "cooldown_hours": (24, "Default cooldown period in hours"),
            "advertise_channel_id": (None, "Forum channel for advertisements"),
            "mod_channel_id": (None, "Channel for moderator notifications"),
            "guild_tag_id": (None, "Tag ID for guild advertisements"),
            "member_tag_id": (None, "Tag ID for member advertisements"),
            "guild_id": (None, "Guild ID for slash command registration"),
            "cooldown_filename": ("advertisement_cooldowns.json", "Filename for cooldown data"),
            "pending_deletions_filename": ("advertisement_pending_deletions.pkl", "Filename for pending deletions")
        }

        # Initialize settings using BaseCog method
        for name, (value, description) in settings_config.items():
            if not self.has_setting(name):
                self.set_setting(name, value)

        # Load settings into instance variables
        self._load_settings()

        # Initialize empty data structures (will be populated in cog_initialize)
        self.cooldowns = {'users': {}, 'guilds': {}}
        self.pending_deletions = []

        # Add standard pause commands to the unifiedadvertise group
        self.create_pause_commands(self.unifiedadvertise_group)

        # Store a reference to this cog
        self.bot.unified_advertise = self

    def _load_settings(self) -> None:
        """Load settings into instance variables."""
        self.cooldown_hours: int = self.get_setting("cooldown_hours")
        self.advertise_channel_id: Optional[int] = self.get_setting("advertise_channel_id")
        self.mod_channel_id: Optional[int] = self.get_setting("mod_channel_id")
        self.guild_tag_id: Optional[int] = self.get_setting("guild_tag_id")
        self.member_tag_id: Optional[int] = self.get_setting("member_tag_id")
        self.guild_id: Optional[int] = self.get_setting("guild_id")
        self.cooldown_filename: str = self.get_setting("cooldown_filename", "advertisement_cooldowns.json")
        self.pending_deletions_filename: str = self.get_setting("pending_deletions_filename", "advertisement_pending_deletions.pkl")

    async def cog_initialize(self) -> None:
        """Initialize the cog - called by BaseCog during ready process."""
        self.logger.info("Initializing Advertisement module...")

        try:
            async with self.task_tracker.task_context("Initialization"):
                await super().cog_initialize()

                # Load data
                self.cooldowns = await self._load_cooldowns()
                self.pending_deletions = await self._load_pending_deletions()

                # Start the scheduled tasks
                self.check_deletions.start()
                self.weekly_cleanup.start()

                # Update status variables
                self._last_operation_time = datetime.datetime.utcnow()

                # Set ready state
                self.set_ready(True)

                self.logger.info("Advertisement initialization complete")

        except Exception as e:
            self._has_errors = True
            self.logger.error(f"Failed to initialize Advertisement module: {e}", exc_info=True)
            raise

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded."""
        # Cancel scheduled tasks
        if hasattr(self, 'check_deletions'):
            self.check_deletions.cancel()
        if hasattr(self, 'weekly_cleanup'):
            self.weekly_cleanup.cancel()

        # Force save any modified data
        if self.is_data_modified():
            self._save_cooldowns()
            self._save_pending_deletions()

        # Clear tasks by invalidating the tracker
        if hasattr(self, 'task_tracker'):
            self.task_tracker.invalidate()

        # Call parent implementation
        await super().cog_unload()

    # ====================
    # Standard Commands
    # ====================

    @commands.group(name="unifiedadvertise", aliases=["uad"], invoke_without_command=True)
    async def unifiedadvertise_group(self, ctx):
        """Unified advertisement management commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @unifiedadvertise_group.command(name="status")
    async def status_command(self, ctx: commands.Context) -> None:
        """Display current operational status of the advertisement system."""
        if not await self.wait_until_ready():
            await ctx.send("⏳ Still initializing, please try again later.")
            return

        # Determine overall status
        if self.is_paused:
            status_emoji = "⏸️"
            status_text = "Paused"
            embed_color = discord.Color.orange()
        elif self._has_errors:
            status_emoji = "⚠️"
            status_text = "Degraded"
            embed_color = discord.Color.orange()
        else:
            status_emoji = "✅"
            status_text = "Operational"
            embed_color = discord.Color.blue()

        # Create status embed
        embed = discord.Embed(
            title="Advertisement System Status",
            description=f"Current status: {status_emoji} {status_text}",
            color=embed_color
        )

        # Add dependency information
        channel = self.bot.get_channel(self.advertise_channel_id)
        dependencies = [f"Advertisement Channel: {'✅ Available' if channel else '❌ Unavailable'}"]
        embed.add_field(name="Dependencies", value="\n".join(dependencies), inline=False)

        # Add task tracking status
        self.add_task_status_fields(embed)

        # Add statistics
        embed.add_field(
            name="Statistics",
            value=f"Operations completed: {self._operation_count}\n"
            f"Pending deletions: {len(self.pending_deletions)}",
            inline=False
        )

        # Add last activity
        if self._last_operation_time:
            embed.add_field(
                name="Last Activity",
                value=f"Last operation: {self.format_relative_time(self._last_operation_time)} ago",
                inline=False
            )

        await ctx.send(embed=embed)

    @unifiedadvertise_group.command(name="settings")
    async def settings_command(self, ctx: commands.Context) -> None:
        """Display current advertisement settings."""
        if not await self.wait_until_ready():
            await ctx.send("⏳ System is still initializing, please try again later.")
            return

        embed = discord.Embed(
            title="Advertisement Settings",
            description="Current configuration for advertisement system",
            color=discord.Color.blue()
        )

        # Time Settings
        embed.add_field(
            name="Time Settings",
            value=f"Advertisement Cooldown: {self.format_time_value(self.cooldown_hours * 3600)}",
            inline=False
        )

        # Channel Settings
        advertise_channel = self.bot.get_channel(self.advertise_channel_id)
        channel_name = advertise_channel.name if advertise_channel else "Unknown"
        embed.add_field(
            name="Channel Settings",
            value=f"Advertisement Channel: {channel_name} (ID: {self.advertise_channel_id})",
            inline=False
        )

        # Tag Settings
        guild_tag = "Not configured" if self.guild_tag_id is None else f"ID: {self.guild_tag_id}"
        member_tag = "Not configured" if self.member_tag_id is None else f"ID: {self.member_tag_id}"

        embed.add_field(
            name="Tag Settings",
            value=f"Guild Tag: {guild_tag}\nMember Tag: {member_tag}",
            inline=False
        )

        # Stats
        embed.add_field(
            name="Statistics",
            value=f"Active User Cooldowns: {len(self.cooldowns['users'])}\n"
            f"Active Guild Cooldowns: {len(self.cooldowns['guilds'])}\n"
            f"Pending Deletions: {len(self.pending_deletions)}",
            inline=False
        )

        await ctx.send(embed=embed)

    @unifiedadvertise_group.command(name="set")
    async def set_setting(self, ctx: commands.Context, setting_name: str, value: str) -> None:
        """Change a cog setting.

        Args:
            setting_name: Name of setting to change
            value: New value for setting
        """
        try:
            valid_settings = {
                "cooldown_hours": ("Cooldown period in hours", int),
                "advertise_channel_id": ("Forum channel for advertisements", int),
                "mod_channel_id": ("Channel for moderator notifications", int),
                "guild_tag_id": ("Tag ID for guild advertisements", int),
                "member_tag_id": ("Tag ID for member advertisements", int),
                "guild_id": ("Guild ID for slash command registration", int)
            }

            if setting_name not in valid_settings:
                return await ctx.send(
                    "❌ Invalid setting. Valid options:\n" +
                    "\n".join([f"• `{k}` - {v[0]}" for k, v in valid_settings.items()])
                )

            # Convert value to correct type
            try:
                value = valid_settings[setting_name][1](value)
            except ValueError:
                return await ctx.send(f"❌ Invalid value format for {setting_name}")

            # Update the setting
            self.set_setting(setting_name, value)

            # Reload settings into instance variables
            self._load_settings()

            await ctx.send(f"✅ Set `{setting_name}` to `{value}`")
            self.logger.info(f"Setting changed by {ctx.author}: {setting_name} = {value}")

        except Exception as e:
            self.logger.error(f"Error changing setting: {e}")
            await ctx.send("❌ An error occurred changing the setting")

    # ====================
    # Advertisement Commands
    # ====================

    @flexible_command(name="advertise", command_type="slash")
    async def advertise_slash(self, interaction: discord.Interaction) -> None:
        """Slash command for creating an advertisement."""
        # Check permissions first
        if not await self.interaction_check(interaction):
            return

        if not await self.wait_until_ready():
            await interaction.response.send_message("⏳ System is still initializing, please try again later.", ephemeral=True)
            return

        # Create the selection view
        view = AdTypeSelection(self)

        # Show the advertisement type selection
        await interaction.response.send_message(
            "What type of advertisement would you like to post?",
            view=view,
            ephemeral=True
        )

    @flexible_command(name="advertisedelete", command_type="slash")
    async def delete_ad_slash(self, interaction: discord.Interaction) -> None:
        """Slash command to delete your own advertisement early."""
        if not await self.wait_until_ready():
            await interaction.response.send_message("⏳ System is still initializing, please try again later.", ephemeral=True)
            return

        # Find user's active advertisements
        user_threads = []
        for thread_id, deletion_time, author_id, notify in self.pending_deletions:
            try:
                thread = await self.bot.fetch_channel(thread_id)
                if thread and thread.owner_id == interaction.user.id:
                    user_threads.append((thread_id, thread.name))
            except Exception:
                continue

        if not user_threads:
            await interaction.response.send_message("You don't have any active advertisements.", ephemeral=True)
            return

        # Create selection menu
        options = [discord.SelectOption(label=name[:100], value=str(id)) for id, name in user_threads]

        class DeleteSelect(Select):
            def __init__(self):
                super().__init__(
                    placeholder="Select an advertisement to delete",
                    options=options,
                    min_values=1,
                    max_values=1
                )

            async def callback(self, select_interaction: discord.Interaction):
                thread_id = int(self.values[0])
                try:
                    thread = await self.bot.fetch_channel(thread_id)
                    await thread.delete()

                    # Update tracking with new tuple structure
                    self.view.cog.pending_deletions = [(t_id, t_time, t_author, t_notify)
                                                       for t_id, t_time, t_author, t_notify
                                                       in self.view.cog.pending_deletions
                                                       if t_id != thread_id]
                    self.view.cog._save_pending_deletions()

                    await select_interaction.response.send_message("Advertisement deleted successfully.", ephemeral=True)
                except Exception as e:
                    self.view.cog.logger.error(f"Error deleting advertisement: {e}")
                    await select_interaction.response.send_message("Failed to delete advertisement.", ephemeral=True)

        class DeleteView(View):
            def __init__(self, cog: UnifiedAdvertise):
                super().__init__()
                self.cog = cog
                self.add_item(DeleteSelect())

        await interaction.response.send_message("Select the advertisement you want to delete:",
                                                view=DeleteView(self),
                                                ephemeral=True)

    @flexible_command(name="advertisenotify", command_type="slash")
    async def notify_ad_slash(self, interaction: discord.Interaction) -> None:
        """Slash command to toggle notification settings for your advertisement."""
        if not await self.wait_until_ready():
            await interaction.response.send_message("⏳ System is still initializing, please try again later.", ephemeral=True)
            return

        # Find user's active advertisements
        user_threads = []
        for thread_id, deletion_time, author_id, notify in self.pending_deletions:
            if author_id == interaction.user.id:
                try:
                    thread = await self.bot.fetch_channel(thread_id)
                    if thread:
                        user_threads.append((thread_id, thread.name, notify))
                except Exception:
                    continue

        if not user_threads:
            await interaction.response.send_message("You don't have any active advertisements.", ephemeral=True)
            return

        # Create selection menu options with current notification status
        options = [
            discord.SelectOption(
                label=name[:80],  # Shorter label to accommodate notification status
                value=str(id),
                description=f"Notifications {'enabled' if notify else 'disabled'}",
                emoji="✉️" if notify else "🔕"
            ) for id, name, notify in user_threads
        ]

        class NotifySelect(Select):
            def __init__(self):
                super().__init__(
                    placeholder="Select an advertisement to modify notifications",
                    options=options,
                    min_values=1,
                    max_values=1
                )

            async def callback(self, select_interaction: discord.Interaction):
                thread_id = int(self.values[0])

                # Find current notification state
                current_notify = False
                for t_id, t_time, t_author, t_notify in self.view.cog.pending_deletions:
                    if t_id == thread_id:
                        current_notify = t_notify
                        break

                # Toggle notification state
                updated_deletions = []
                for t_id, t_time, t_author, t_notify in self.view.cog.pending_deletions:
                    if t_id == thread_id:
                        # Flip the notification setting
                        updated_deletions.append((t_id, t_time, t_author, not t_notify))
                    else:
                        updated_deletions.append((t_id, t_time, t_author, t_notify))

                self.view.cog.pending_deletions = updated_deletions
                self.view.cog._save_pending_deletions()

                # Confirm the change
                new_state = "enabled" if not current_notify else "disabled"
                await select_interaction.response.send_message(
                    f"Notifications have been {new_state} for your advertisement.",
                    ephemeral=True
                )

        class NotifyView(View):
            def __init__(self, cog: UnifiedAdvertise):
                super().__init__()
                self.cog = cog
                self.add_item(NotifySelect())

        await interaction.response.send_message(
            "Select an advertisement to toggle notifications:",
            view=NotifyView(self),
            ephemeral=True
        )

    # ====================
    # Owner Commands
    # ====================

    @flexible_command(name="owner_delete_post")
    async def owner_delete_post(self, ctx: commands.Context, message_url: str) -> None:
        """Delete a post based on message URL and remove it from pending deletions.

        Only works for the bot owner in DMs.

        Args:
            message_url: URL of the message/thread to delete
        """
        # Check if command is used by bot owner in DMs
        if not await self._check_owner_dm(ctx):
            return

        try:
            # Extract channel and message IDs from URL
            parts = message_url.split('/')
            if len(parts) < 7:
                await ctx.send("Invalid message URL format. Expected: https://discord.com/channels/guild_id/channel_id/message_id")
                return

            channel_id = int(parts[-2])

            # Try to fetch the channel (should be a thread)
            try:
                thread = await self.bot.fetch_channel(channel_id)

                # Delete the thread
                await thread.delete()

                # Remove from pending deletions and notify author if needed
                updated_list = []
                deleted = False

                for t_id, t_time, t_author, t_notify in self.pending_deletions:
                    if t_id == channel_id:
                        deleted = True
                        # Try to notify the author if notifications were enabled
                        if t_notify and t_author:
                            try:
                                user = await self.bot.fetch_user(t_author)
                                if user:
                                    await user.send(f"Your advertisement in {thread.name} has been removed by a moderator.")
                            except Exception as e:
                                self.logger.error(f"Failed to send notification to user {t_author}: {e}")
                    else:
                        updated_list.append((t_id, t_time, t_author, t_notify))

                if deleted:
                    self.pending_deletions = updated_list
                    self._save_pending_deletions()
                    self.logger.info(f"Owner manually deleted thread {channel_id} and removed from pending deletions")
                    await ctx.send("Successfully deleted thread and removed from pending deletions.")
                else:
                    self.logger.info(f"Owner manually deleted thread {channel_id} (not in pending deletions)")
                    await ctx.send("Successfully deleted thread, but it wasn't in the pending deletions list.")

            except discord.NotFound:
                self.logger.warning(f"Owner tried to delete non-existent thread {channel_id}")
                await ctx.send("Thread not found. It might have been already deleted.")
            except discord.Forbidden:
                self.logger.error(f"No permission to delete thread {channel_id}")
                await ctx.send("I don't have permission to delete that thread.")
            except Exception as e:
                self.logger.error(f"Error deleting thread {channel_id}: {str(e)}")
                await ctx.send(f"Error deleting thread: {str(e)}")

        except Exception as e:
            self.logger.error(f"Error processing owner_delete_post command: {str(e)}")
            await ctx.send(f"Error processing command: {str(e)}")

    @flexible_command(name="owner_reset_timeout")
    async def owner_reset_timeout(self, ctx: commands.Context, timeout_type: str, identifier: str) -> None:
        """Reset a timeout for a user or guild.

        timeout_type: 'user' or 'guild'
        identifier: Discord user ID or Guild ID
        Only works for the bot owner in DMs.
        """
        # Check if command is used by bot owner in DMs
        if not await self._check_owner_dm(ctx):
            return

        try:
            timeout_type = timeout_type.lower()

            if timeout_type not in ['user', 'guild']:
                await ctx.send("Invalid timeout type. Use 'user' or 'guild'.")
                return

            # Map timeout type to the cooldowns dictionary key
            cooldown_key = 'users' if timeout_type == 'user' else 'guilds'

            # Check if the identifier exists in the cooldowns
            if identifier in self.cooldowns[cooldown_key]:
                # Remove the timeout
                del self.cooldowns[cooldown_key][identifier]
                self._save_cooldowns()
                await ctx.send(f"Successfully reset {timeout_type} timeout for {identifier}.")
            else:
                await ctx.send(f"No timeout found for {timeout_type} {identifier}.")

        except Exception as e:
            await ctx.send(f"Error processing command: {str(e)}")

    @flexible_command(name="owner_list_timeouts")
    async def owner_list_timeouts(self, ctx: commands.Context, timeout_type: Optional[str] = None) -> None:
        """List all active timeouts.

        Args:
            timeout_type: Optional 'user' or 'guild' to filter results

        Only works for the bot owner in DMs.
        """
        # Check if command is used by the bot owner in DMs
        if not await self._check_owner_dm(ctx):
            return

        try:
            now = datetime.datetime.now()
            sections = []

            # Determine which sections to show
            if timeout_type:
                timeout_type = timeout_type.lower()
                if timeout_type not in ['user', 'guild']:
                    await ctx.send("Invalid timeout type. Use 'user', 'guild' or omit for all.")
                    return

                if timeout_type == 'user':
                    sections = ['users']
                else:
                    sections = ['guilds']
            else:
                # Show all sections if no type specified
                sections = ['users', 'guilds']

            # Build the message
            result = []

            for section in sections:
                if not self.cooldowns[section]:
                    result.append(f"No active {section} timeouts.")
                    continue

                result.append(f"**{section.capitalize()} Timeouts:**")

                for item_id, timestamp in list(self.cooldowns[section].items()):
                    timestamp_dt = datetime.datetime.fromisoformat(timestamp)
                    elapsed = now - timestamp_dt
                    hours_left = self.cooldown_hours - (elapsed.total_seconds() / 3600)

                    if hours_left > 0:
                        result.append(f"- ID: `{item_id}`, Time left: {hours_left:.1f} hours")
                    else:
                        # Updated to use consistent emoji
                        result.append(f"- ID: `{item_id}`, **⚠️ EXPIRED** ({abs(hours_left):.1f} hours ago)")

                result.append("")  # Add a blank line between sections

            # Send the message
            if result:
                await ctx.send("\n".join(result))
            else:
                await ctx.send("No active timeouts found.")

        except Exception as e:
            self.logger.error(f"Error in owner_list_timeouts: {e}", exc_info=True)
            await ctx.send(f"Error processing command: {str(e)}")

    @flexible_command(name="owner_list_pending")
    async def owner_list_pending(self, ctx: commands.Context) -> None:
        """List all pending deletions.

        Only works for the bot owner in DMs.
        """
        # Check if command is used by the bot owner in DMs
        if not await self._check_owner_dm(ctx):
            return

        try:
            now = datetime.datetime.now()

            if not self.pending_deletions:
                await ctx.send("No pending thread deletions.")
                return

            result = ["**Pending Thread Deletions:**"]

            for thread_id, deletion_time, author_id, notify in self.pending_deletions:
                time_left = deletion_time - now
                hours_left = time_left.total_seconds() / 3600

                if self.guild_id:
                    thread_url = f"https://discord.com/channels/{self.guild_id}/{thread_id}"
                else:
                    thread_url = f"Thread ID: {thread_id} (Guild ID not configured)"

                if hours_left > 0:
                    result.append(f"- Thread ID: `{thread_id}`, Time left: {hours_left:.1f} hours\n  URL: {thread_url}")
                else:
                    # Updated to use consistent emoji
                    result.append(f"- Thread ID: `{thread_id}`, **⚠️ OVERDUE** by {abs(hours_left):.1f} hours\n  URL: {thread_url}")

            # Send the message(s) - discord has a 2000 char limit
            messages = []
            current_msg = ""

            for line in result:
                if len(current_msg) + len(line) + 1 > 1990:  # Leave some buffer
                    messages.append(current_msg)
                    current_msg = line
                else:
                    if current_msg:
                        current_msg += "\n" + line
                    else:
                        current_msg = line

            if current_msg:
                messages.append(current_msg)

            for msg in messages:
                await ctx.send(msg)

        except Exception as e:
            self.logger.error(f"Error in owner_list_pending: {e}", exc_info=True)
            await ctx.send(f"Error processing command: {str(e)}")

    async def _check_owner_dm(self, ctx: commands.Context) -> bool:
        """Check if the command is being used by the bot owner in DMs.

        Args:
            ctx: The command context

        Returns:
            bool: True if the user is the bot owner and in DMs, False otherwise
        """
        # Check if command is in DMs
        if not isinstance(ctx.channel, discord.DMChannel):
            self.logger.warning(f"Non-DM attempt to use owner command from {ctx.author.id}")
            return False

        # Check if user is bot owner
        if ctx.author.id != self.bot.owner_id:
            self.logger.warning(f"Non-owner {ctx.author.id} attempted to use owner command")
            await ctx.send("This command is only available to the bot owner.")
            return False

        return True

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
            threads_to_delete = []

            for thread_id, deletion_time, author_id, notify in self.pending_deletions:
                if current_time >= deletion_time:
                    threads_to_delete.append((thread_id, author_id, notify))

            # Delete threads that have reached their time
            for thread_id, author_id, notify in threads_to_delete:
                try:
                    # Send notification if requested
                    if notify and author_id:
                        try:
                            user = await self.bot.fetch_user(author_id)
                            if user:
                                thread = await self.bot.fetch_channel(thread_id)
                                await user.send(f"Your advertisement in {thread.name} has expired and been removed.")
                        except Exception as e:
                            self.logger.error(f"Failed to send notification to user {author_id}: {e}")

                    thread = await self.bot.fetch_channel(thread_id)
                    await thread.delete()
                    self.logger.info(f"Deleted advertisement thread {thread_id} (scheduled for {deletion_time})")
                    self._operation_count += 1
                    self._last_operation_time = datetime.datetime.now()
                except (discord.NotFound, discord.HTTPException) as e:
                    self.logger.error(f"Error deleting thread {thread_id}: {e}")
                    self._has_errors = True

                # Remove from pending deletions
                self.pending_deletions = [(t_id, t_time, t_author, t_notify)
                                          for t_id, t_time, t_author, t_notify in self.pending_deletions
                                          if t_id != thread_id]

            if threads_to_delete:
                self._save_pending_deletions()

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

    # ====================
    # Helper Methods
    # ====================

    async def _cleanup_cooldowns(self) -> None:
        """Remove expired cooldowns from the cooldowns dictionary."""
        try:
            current_time = datetime.datetime.now()
            sections = ['users', 'guilds']
            expired_count = 0

            for section in sections:
                expired_items = []

                for item_id, timestamp in list(self.cooldowns[section].items()):
                    timestamp_dt = datetime.datetime.fromisoformat(timestamp)
                    elapsed = current_time - timestamp_dt
                    if elapsed.total_seconds() > self.cooldown_hours * 3600:
                        expired_items.append(item_id)

                for item_id in expired_items:
                    del self.cooldowns[section][item_id]
                    expired_count += 1

            if expired_count > 0:
                self._save_cooldowns()
                self.logger.info(f"Weekly cleanup: Removed {expired_count} expired cooldowns")
                self._last_operation_time = datetime.datetime.now()
        except Exception as e:
            self.logger.error(f"Error during cooldown cleanup: {e}")
            self._has_errors = True

    async def _load_cooldowns(self) -> Dict[str, Dict[str, str]]:
        """Load cooldowns using BaseCog data management."""
        try:
            cooldowns_file = self.data_directory / self.cooldown_filename
            data = await self.load_data(cooldowns_file, default={
                'users': {},
                'guilds': {}
            })
            return data
        except Exception as e:
            self.logger.error(f"Error loading cooldowns: {e}")
            return {'users': {}, 'guilds': {}}

    async def _save_cooldowns(self) -> None:
        """Save cooldowns using BaseCog data management."""
        try:
            cooldowns_file = self.data_directory / self.cooldown_filename
            await self.save_data_if_modified(self.cooldowns, cooldowns_file)
            self.mark_data_modified()
        except Exception as e:
            self.logger.error(f"Error saving cooldowns: {e}")

    async def _load_pending_deletions(self) -> List[Tuple[int, datetime.datetime, int, bool]]:
        """Load pending deletions using BaseCog data management."""
        try:
            deletions_file = self.data_directory / self.pending_deletions_filename
            data = await self.load_data(deletions_file, default=[])

            # Convert timestamps to datetime if needed
            converted_data = []
            for entry in data:
                if len(entry) == 4:  # Current format (thread_id, time, author_id, notify)
                    thread_id, del_time, author_id, notify = entry
                    if isinstance(del_time, str):
                        del_time = datetime.datetime.fromisoformat(del_time)
                    converted_data.append((int(thread_id), del_time, int(author_id), bool(notify)))
                elif len(entry) == 2:  # Old format (thread_id, time)
                    thread_id, del_time = entry
                    if isinstance(del_time, str):
                        del_time = datetime.datetime.fromisoformat(del_time)
                    # Add default values for author_id (None) and notify (False)
                    converted_data.append((int(thread_id), del_time, 0, False))
                    self.logger.info(f"Migrated old deletion entry format for thread {thread_id}")
                else:
                    self.logger.warning(f"Invalid deletion entry format: {entry}")
                    continue

            return converted_data
        except Exception as e:
            self.logger.error(f"Error loading pending deletions: {e}")
            return []

    async def _save_pending_deletions(self) -> None:
        """Save pending deletions using BaseCog data management."""
        try:
            deletions_file = self.data_directory / self.pending_deletions_filename

            # Convert datetime objects to ISO strings for serialization
            serializable_data = [
                (thread_id, deletion_time.isoformat() if isinstance(deletion_time, datetime.datetime) else deletion_time,
                 author_id, notify)
                for thread_id, deletion_time, author_id, notify in self.pending_deletions
            ]

            await self.save_data_if_modified(serializable_data, deletions_file)
            self.mark_data_modified()
        except Exception as e:
            self.logger.error(f"Error saving pending deletions: {e}")

    async def _resume_deletion_tasks(self) -> None:
        """Check for threads that were scheduled for deletion before restart."""
        self.logger.info(f"Resumed tracking {len(self.pending_deletions)} pending thread deletions")

    async def check_cooldowns(self, interaction: discord.Interaction, user_id: int, guild_id: Optional[str] = None,
                              ad_type: Optional[str] = None) -> bool:
        """Check if user or guild is on cooldown and handle the response.

        Args:
            interaction: The discord interaction
            user_id: Discord user ID
            guild_id: Guild ID (optional)
            ad_type: Type of advertisement (guild or member)

        Returns:
            bool: True if not on cooldown, False if on cooldown
        """
        # Check user cooldown
        if str(user_id) in self.cooldowns['users']:
            timestamp = self.cooldowns['users'][str(user_id)]
            elapsed = (datetime.datetime.now() - datetime.datetime.fromisoformat(timestamp)).total_seconds()

            if elapsed < self.cooldown_hours * 3600:
                hours_left = self.cooldown_hours - (elapsed / 3600)

                # Send notification to mod channel about bypass attempt
                mod_channel = self.bot.get_channel(self.mod_channel_id)
                if mod_channel:
                    await mod_channel.send(f"⚠️ **Advertisement Cooldown Bypass Attempt**\n"
                                           f"User: {interaction.user.name} (ID: {interaction.user.id})\n"
                                           f"Type: User cooldown ({ad_type})\n"
                                           f"Time remaining: {hours_left:.1f} hours")

                await interaction.response.send_message(
                    f"You can only post one advertisement every {self.cooldown_hours} hours. "
                    f"Please try again in {hours_left:.1f} hours.\n"
                    f"If you attempt to bypass this limit, you will be banned from advertising.",
                    ephemeral=True
                )
                return False

        # Check guild cooldown if applicable
        if guild_id and str(guild_id) in self.cooldowns['guilds']:
            timestamp = self.cooldowns['guilds'][str(guild_id)]
            elapsed = (datetime.datetime.now() - datetime.datetime.fromisoformat(timestamp)).total_seconds()

            if elapsed < self.cooldown_hours * 3600:
                hours_left = self.cooldown_hours - (elapsed / 3600)

                # Send notification to mod channel about guild cooldown bypass attempt
                mod_channel = self.bot.get_channel(self.mod_channel_id)
                if mod_channel:
                    await mod_channel.send(f"⚠️ **Guild Advertisement Cooldown Bypass Attempt**\n"
                                           f"User: {interaction.user.name} (ID: {interaction.user.id})\n"
                                           f"Guild ID: {guild_id}\n"
                                           f"Time remaining: {hours_left:.1f} hours")

                await interaction.response.send_message(
                    f"This guild was already advertised in the past {self.cooldown_hours} hours. "
                    f"Please try again in {hours_left:.1f} hours.\n"
                    f"If you attempt to bypass this limit, your guild will be banned from advertising.",
                    ephemeral=True
                )
                return False

        return True

    async def post_advertisement(self, interaction: discord.Interaction, embed: discord.Embed, thread_title: str,
                                 ad_type: str, guild_id: Optional[str], notify: bool) -> None:
        """Post the advertisement as a thread in the forum channel.

        Args:
            interaction: Discord interaction object
            embed: Embed to post
            thread_title: Title for the forum thread
            ad_type: Type of advertisement (guild or member)
            guild_id: Guild ID (optional, for guild advertisements)
            notify: Whether to notify the user when the ad expires
        """
        try:
            # Track operation with BaseCog's task tracker
            async with self.task_tracker.task_context("Posting Advertisement"):
                # Get the forum channel
                channel = self.bot.get_channel(self.advertise_channel_id)

                if not channel:
                    self.logger.error(f"Advertisement channel not found: {self.advertise_channel_id}")
                    await interaction.response.send_message(
                        "There was an error posting your advertisement. Please contact @thedisasterfish.",
                        ephemeral=True
                    )
                    return

                # Determine which tag to apply based on advertisement type
                applied_tags = []
                if (ad_type == AdvertisementType.GUILD and self.guild_tag_id):
                    try:
                        # Find the tag object by ID
                        for tag in channel.available_tags:
                            if tag.id == self.guild_tag_id:
                                applied_tags.append(tag)
                                break
                    except Exception as e:
                        self.logger.error(f"Error finding guild tag: {e}")
                        self._has_errors = True

                elif (ad_type == AdvertisementType.MEMBER and self.member_tag_id):
                    try:
                        # Find the tag object by ID
                        for tag in channel.available_tags:
                            if tag.id == self.member_tag_id:
                                applied_tags.append(tag)
                                break
                    except Exception as e:
                        self.logger.error(f"Error finding member tag: {e}")
                        self._has_errors = True

                # Create the forum thread with tags
                thread_with_message = await channel.create_thread(
                    name=thread_title,
                    content="",  # Empty content
                    embed=embed,
                    applied_tags=applied_tags,  # Apply the tags
                    auto_archive_duration=1440  # Auto-archive after 24 hours
                )

                thread = thread_with_message.thread
                self.logger.info(f"Created new advertisement thread: {thread.id} for user {interaction.user.id} (type: {ad_type})")
                self._operation_count += 1
                self._last_operation_time = datetime.datetime.now()

                # Confirm to the user
                if interaction.response.is_done():
                    await interaction.followup.send(
                        f"Thank you! Your {ad_type} advertisement has been posted. "
                        f"It will remain visible for {self.cooldown_hours} hours.",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        f"Thank you! Your {ad_type} advertisement has been posted. "
                        f"It will remain visible for {self.cooldown_hours} hours.",
                        ephemeral=True
                    )

                # Update cooldowns
                current_time = datetime.datetime.now().isoformat()
                self.cooldowns['users'][str(interaction.user.id)] = current_time

                # If it's a guild advertisement, also add guild cooldown
                if guild_id:
                    self.cooldowns['guilds'][str(guild_id)] = current_time

                self._save_cooldowns()

                # Schedule thread for deletion with author ID and notification preference
                deletion_time = datetime.datetime.now() + datetime.timedelta(hours=self.cooldown_hours)
                self.pending_deletions.append((thread.id, deletion_time, interaction.user.id, notify))
                self._save_pending_deletions()
                self.logger.info(f"Scheduled thread {thread.id} for deletion at {deletion_time} "
                                 f"with notify={notify}, author={interaction.user.id}")

        except Exception as e:
            self.logger.error(f"Error in post_advertisement: {e}", exc_info=True)
            self._has_errors = True
            if interaction.response.is_done():
                await interaction.followup.send(
                    "There was an error posting your advertisement. Please contact @thedisasterfish.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "There was an error posting your advertisement. Please contact @thedisasterfish.",
                    ephemeral=True
                )

# ====================
# Cog Setup
# ====================


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UnifiedAdvertise(bot))

    # Sync the slash commands
    try:
        cog = bot.get_cog("UnifiedAdvertise")
        if cog and cog.guild_id:
            guild = discord.Object(id=cog.guild_id)
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            cog.logger.info(f"Synced commands to guild {cog.guild_id}")
        else:
            cog.logger.warning("Guild ID not configured, using global sync")
            await bot.tree.sync()
    except Exception as e:
        if cog:
            cog.logger.error(f"Error syncing app commands: {e}")
        print(f"Error syncing app commands: {e}")
