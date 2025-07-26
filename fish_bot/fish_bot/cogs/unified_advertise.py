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
        self.notify = True
        self.interaction = None  # Store interaction object

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

    async def on_submit(self, interaction: discord.Interaction) -> None:
        import time
        start_time = time.time()
        self.interaction = interaction  # Store interaction when form is submitted
        await self.cog._send_debug_message(f"Guild advertisement form submitted by user {interaction.user.id} ({interaction.user.name})")

        # Check if guild ID is valid (only A-Z, 0-9, exactly 6 chars)
        guild_id = self.guild_id.value.upper()
        if not re.match(r'^[A-Z0-9]{6}$', guild_id):
            await self.cog._send_debug_message(f"Invalid guild ID format from user {interaction.user.id}: {guild_id}")
            await interaction.response.send_message(
                "Guild ID must be exactly 6 characters and only contain letters A-Z and numbers 0-9.",
                ephemeral=True
            )
            return

        # Process notification preference
        notify = self.notify

        # Check cooldowns before processing
        user_id = interaction.user.id
        cooldown_start = time.time()

        cooldown_check = await self.cog.check_cooldowns(
            interaction,
            user_id,
            guild_id,
            AdvertisementType.GUILD
        )
        cooldown_time = time.time() - cooldown_start
        await self.cog._send_debug_message(f"Cooldown check completed in {cooldown_time:.2f}s for user {interaction.user.id}")

        # Warn if cooldown check took too long
        if cooldown_time > 1.0:
            await self.cog._send_debug_message(f"⚠️ Cooldown check took {cooldown_time:.2f}s - potential timeout risk for user {interaction.user.id}")

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

        # CRITICAL: Respond to interaction IMMEDIATELY before heavy work
        await interaction.response.send_message(
            f"Thank you! Your {AdvertisementType.GUILD} advertisement is being posted. "
            f"It will remain visible for {self.cog.cooldown_hours} hours.",
            ephemeral=True
        )

        # Post advertisement and update cooldowns
        thread_title = f"[Guild] {self.guild_name.value} ({guild_id})"
        total_time = time.time() - start_time
        await self.cog._send_debug_message(f"Guild form processing completed in {total_time:.2f}s, posting advertisement for user {interaction.user.id}")
        await self.cog.post_advertisement(interaction, embed, thread_title, AdvertisementType.GUILD, guild_id, notify)

    async def on_timeout(self) -> None:
        """Handle form timeout."""
        try:
            if self.interaction:  # Only try to send message if we have an interaction
                await self.interaction.response.send_message(
                    "The form timed out. Please try submitting your advertisement again.",
                    ephemeral=True
                )
        except (discord.NotFound, discord.HTTPException):
            pass


class NotificationView(View):
    def __init__(self, form: GuildAdvertisementForm):
        super().__init__(timeout=180)
        self.form = form

    @discord.ui.select(
        placeholder="Would you like to be notified when your ad expires?",
        options=[
            discord.SelectOption(label="Yes", value="yes", emoji="✉️"),
            discord.SelectOption(label="No", value="no", emoji="🔕")
        ],
        min_values=1,
        max_values=1
    )
    async def notify_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.form.notify = select.values[0] == "yes"
        await interaction.response.send_modal(self.form)


class MemberAdvertisementForm(Modal, title="Member Advertisement Form"):
    """Modal form for collecting member advertisement information."""

    def __init__(self, cog: 'UnifiedAdvertise') -> None:
        """Initialize the view with a reference to the cog.

        Args:
            cog: The UnifiedAdvertise cog instance
        """
        super().__init__(timeout=180)  # 3 minute timeout
        self.cog = cog
        self.notify = True
        self.interaction = None  # Store interaction object

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

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.interaction = interaction  # Store interaction when form is submitted
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
        notify = self.notify

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

        # CRITICAL: Respond to interaction IMMEDIATELY before heavy work
        await interaction.response.send_message(
            f"Thank you! Your {AdvertisementType.MEMBER} advertisement is being posted. "
            f"It will remain visible for {self.cog.cooldown_hours} hours.",
            ephemeral=True
        )

        # Post advertisement and update cooldowns
        thread_title = f"[Member] {interaction.user.name} ({player_id})"
        await self.cog.post_advertisement(interaction, embed, thread_title, AdvertisementType.MEMBER, None, notify)

    async def on_timeout(self) -> None:
        """Handle form timeout."""
        try:
            if self.interaction:  # Only try to send message if we have an interaction
                await self.interaction.response.send_message(
                    "The form timed out. Please try submitting your advertisement again.",
                    ephemeral=True
                )
        except (discord.NotFound, discord.HTTPException):
            pass


class UnifiedAdvertise(BaseCog, name="Unified Advertise"):
    @tasks.loop(hours=1)
    async def orphaned_post_scan(self) -> None:
        """Scan for orphaned advertisement posts and add them to pending deletions if not already tracked."""
        await self._send_debug_message("Starting orphaned post scan.")
        try:
            channel = self.bot.get_channel(self.advertise_channel_id)
            if not channel:
                await self._send_debug_message(f"Orphan scan: Advertisement channel not found: {self.advertise_channel_id}")
                return

            # Fetch all active threads in the forum channel
            threads = []
            try:
                # For forum channels, threads is a list property, not a method
                threads = channel.threads
            except Exception as e:
                await self._send_debug_message(f"Orphan scan: Failed to fetch threads: {e}")
                return

            tracked_ids = {t_id for t_id, _, _, _ in self.pending_deletions}
            new_orphans = 0
            for thread in threads:
                if thread.id not in tracked_ids:
                    # Add all orphans regardless of pin status
                    deletion_time = datetime.datetime.now() + datetime.timedelta(hours=self.cooldown_hours)
                    author_id = getattr(thread, 'owner_id', 0) or 0
                    notify = False
                    self.pending_deletions.append((thread.id, deletion_time, author_id, notify))
                    new_orphans += 1

                    # Update cooldown timestamp to match this thread's creation time
                    if author_id != 0:
                        thread_creation_timestamp = thread.created_at.isoformat()
                        self.cooldowns['users'][str(author_id)] = thread_creation_timestamp
                        await self._send_debug_message(f"Updated user {author_id} cooldown to match orphaned thread {thread.id} creation time")
            if new_orphans:
                await self._save_pending_deletions()
                await self._save_cooldowns()  # Save updated cooldown timestamps
                await self._send_debug_message(f"Orphan scan: Added {new_orphans} orphaned threads to pending deletions.")
            else:
                await self._send_debug_message("Orphan scan: No new orphaned threads found.")

            # After handling orphans, check for duplicates
            await self._check_and_remove_duplicates(threads)
        except Exception as e:
            await self._send_debug_message(f"Orphan scan: Error: {e}")

    async def _check_and_remove_duplicates(self, threads: list) -> None:
        """Check for duplicate posts and remove all but the oldest one."""
        await self._send_debug_message("Starting duplicate detection scan.")
        try:
            # Group threads by author to check for duplicates from same user
            author_threads = {}

            for thread in threads:
                author_id = getattr(thread, 'owner_id', 0) or 0
                if author_id == 0:
                    continue  # Skip threads with no owner

                if author_id not in author_threads:
                    author_threads[author_id] = []
                author_threads[author_id].append(thread)

            duplicates_removed = 0

            # Check each author's threads for duplicates
            for author_id, user_threads in author_threads.items():
                if len(user_threads) <= 1:
                    continue  # No duplicates possible with only one thread

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
                    for j, thread2 in enumerate(user_threads[i + 1:], i + 1):
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
                    pinned_threads = [t for t in duplicate_group if hasattr(t, 'pinned') and t.pinned]
                    unpinned_threads = [t for t in duplicate_group if not (hasattr(t, 'pinned') and t.pinned)]

                    if pinned_threads:
                        # If there are pinned threads, keep all pinned threads and delete all unpinned ones
                        keep_threads = pinned_threads
                        delete_threads = unpinned_threads
                        await self._send_debug_message(f"Found duplicates with {len(pinned_threads)} pinned thread(s) from user {author_id}, keeping pinned, deleting {len(delete_threads)} unpinned")
                    else:
                        # No pinned threads, keep the oldest (first in sorted list)
                        keep_threads = [duplicate_group[0]]
                        delete_threads = duplicate_group[1:]
                        await self._send_debug_message(f"Found {len(delete_threads)} duplicate threads from user {author_id}, keeping oldest: {keep_threads[0].id}")

                    for thread in delete_threads:
                        try:
                            await thread.delete()
                            duplicates_removed += 1
                            await self._send_debug_message(f"Deleted duplicate thread {thread.id}")

                            # Remove from pending deletions if it was there
                            self.pending_deletions = [
                                entry for entry in self.pending_deletions
                                if entry[0] != thread.id
                            ]

                        except Exception as e:
                            await self._send_debug_message(f"Error deleting duplicate thread {thread.id}: {e}")

                    # Ensure all kept threads are properly tracked
                    tracked_ids = {t_id for t_id, _, _, _ in self.pending_deletions}
                    for keep_thread in keep_threads:
                        if keep_thread.id not in tracked_ids:
                            deletion_time = datetime.datetime.now() + datetime.timedelta(hours=self.cooldown_hours)
                            notify = False  # Don't notify for duplicate cleanup
                            self.pending_deletions.append((keep_thread.id, deletion_time, author_id, notify))
                            await self._send_debug_message(f"Added kept thread {keep_thread.id} to pending deletions tracking")

                        # Update cooldown timestamp to match the kept thread's creation time
                        # This ensures the timeout aligns with the actual remaining post
                        thread_creation_timestamp = keep_thread.created_at.isoformat()
                        self.cooldowns['users'][str(author_id)] = thread_creation_timestamp
                        await self._send_debug_message(f"Updated user {author_id} cooldown to match kept thread {keep_thread.id} creation time")

            if duplicates_removed > 0:
                await self._save_pending_deletions()
                await self._save_cooldowns()  # Save updated cooldown timestamps
                await self._send_debug_message(f"Duplicate scan complete: Removed {duplicates_removed} duplicate threads.")
            else:
                await self._send_debug_message("Duplicate scan complete: No duplicates found.")

        except Exception as e:
            await self._send_debug_message(f"Duplicate detection error: {e}")

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
            for prefix in ['[guild]', '[member]']:
                title1 = title1.replace(prefix, '').strip()
                title2 = title2.replace(prefix, '').strip()

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
                id_pattern = r'\(([^)]+)\)'

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
                fields1 = {field.name.lower().strip(): field.value.lower().strip()
                           for field in embed1.fields if field.name and field.value}
                fields2 = {field.name.lower().strip(): field.value.lower().strip()
                           for field in embed2.fields if field.name and field.value}

                # Check for key identifying fields
                key_fields = ['player id', 'guild id', 'guild name']

                for key_field in key_fields:
                    if key_field in fields1 and key_field in fields2:
                        value1 = fields1[key_field]
                        value2 = fields2[key_field]

                        # Remove markdown links if present: [TEXT](URL) -> TEXT
                        import re
                        link_pattern = r'\[([^\]]+)\]\([^)]+\)'
                        value1 = re.sub(link_pattern, r'\1', value1)
                        value2 = re.sub(link_pattern, r'\1', value2)

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

        # Initialize settings
        for name, (value, description) in settings_config.items():
            if not self.has_setting(name):
                self.set_setting(name, value)

        # Initialize empty data structures (will be populated in cog_initialize)
        self.cooldowns = {'users': {}, 'guilds': {}}
        self.pending_deletions = []

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

        # Get testing channel from config for debug messages
        self.testing_channel_id: Optional[int] = self.config.get_channel_id("testing") if self.config else None

    async def cog_initialize(self) -> None:
        """Initialize the cog - called by BaseCog during ready process."""
        self.logger.info("Initializing Advertisement module...")

        try:
            async with self.task_tracker.task_context("Initialization") as tracker:
                # Initialize parent
                self.logger.debug("Initializing parent cog")
                await super().cog_initialize()

                # 0. Create inherited commands
                self.create_pause_commands(self.unifiedadvertise_group)

                # 1. Load settings
                self.logger.debug("Loading settings")
                tracker.update_status("Loading settings")
                self._load_settings()

                # 2. Load data
                self.logger.debug("Loading cached data")
                tracker.update_status("Loading data")
                self.cooldowns = await self._load_cooldowns()
                self.pending_deletions = await self._load_pending_deletions()

                # 3. Start scheduled tasks
                self.logger.debug("Starting scheduled tasks")
                tracker.update_status("Starting tasks")
                if not self.check_deletions.is_running():
                    self.check_deletions.start()
                if not self.weekly_cleanup.is_running():
                    self.weekly_cleanup.start()
                if not hasattr(self, 'orphaned_post_scan') or not self.orphaned_post_scan.is_running():
                    self.orphaned_post_scan.start()

                # 4. Update status variables
                self._last_operation_time = datetime.datetime.utcnow()
                self._operation_count = 0

                # 5. Mark as ready
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
        if hasattr(self, 'orphaned_post_scan'):
            self.orphaned_post_scan.cancel()

        # Force save any modified data
        if self.is_data_modified():
            await self._save_cooldowns()
            await self._save_pending_deletions()

        # Clear tasks by invalidating the tracker
        if hasattr(self.task_tracker, 'clear_error_state'):
            self.task_tracker.clear_error_state()

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
    async def set_setting_command(self, ctx: commands.Context, setting_name: str, value: str) -> None:
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

    @discord.app_commands.command(name="advertise", description="Create a new advertisement")
    async def advertise_slash(self, interaction: discord.Interaction) -> None:
        """Slash command for creating an advertisement."""
        import time
        start_time = time.time()
        await self._send_debug_message(f"Advertise command started by user {interaction.user.id} ({interaction.user.name})")

        if not await self.wait_until_ready():
            await self._send_debug_message(f"System not ready for user {interaction.user.id}")
            await interaction.response.send_message("⏳ System is still initializing, please try again later.", ephemeral=True)
            return

        # Check if system is paused
        if self.is_paused:
            await self._send_debug_message(f"System paused when user {interaction.user.id} tried to advertise")
            await interaction.response.send_message("⏸️ The advertisement system is currently paused. Please try again later.", ephemeral=True)
            return

        # Check permissions
        permission_start = time.time()
        if not await self.interaction_check(interaction):
            await self._send_debug_message(f"Permission check failed for user {interaction.user.id} after {time.time() - permission_start:.2f}s")
            return
        permission_time = time.time() - permission_start
        await self._send_debug_message(f"Permission check completed in {permission_time:.2f}s for user {interaction.user.id}")

        # Create the selection view
        view = AdTypeSelection(self)

        # Show the advertisement type selection
        total_time = time.time() - start_time
        await self._send_debug_message(f"Advertise command setup completed in {total_time:.2f}s for user {interaction.user.id}")
        await interaction.response.send_message(
            "What type of advertisement would you like to post?",
            view=view,
            ephemeral=True
        )

    @discord.app_commands.command(name="advertisedelete", description="Delete your active advertisement")
    async def delete_ad_slash(self, interaction: discord.Interaction) -> None:
        """Slash command to delete your own advertisement early."""
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

        # Find user's active advertisements
        user_threads = []
        for thread_id, deletion_time, author_id, notify in self.pending_deletions:
            # Changed: Check author_id instead of thread.owner_id
            if author_id == interaction.user.id:
                try:
                    thread = await self.bot.fetch_channel(thread_id)
                    if thread:
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
                    thread = await self.view.cog.bot.fetch_channel(thread_id)
                    await thread.delete()

                    # Update tracking with new tuple structure
                    self.view.cog.pending_deletions = [(t_id, t_time, t_author, t_notify)
                                                       for t_id, t_time, t_author, t_notify
                                                       in self.view.cog.pending_deletions
                                                       if t_id != thread_id]
                    await self.view.cog._save_pending_deletions()

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

    @discord.app_commands.command(name="advertisenotify", description="Toggle notification settings for your advertisement")
    async def notify_ad_slash(self, interaction: discord.Interaction) -> None:
        """Slash command to toggle notification settings for your advertisement."""
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
                await self._save_cooldowns()
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
        """
        if not await self._check_owner_dm(ctx):
            return

        try:
            now = datetime.datetime.now()
            if timeout_type and timeout_type.lower() in ['user', 'guild']:
                sections = [f"{timeout_type.lower()}s"]
            else:
                sections = ['users', 'guilds']
            messages = []
            current_msg = []

            for section in sections:
                if not self.cooldowns[section]:
                    current_msg.append(f"No active {section} timeouts.")
                    continue

                current_msg.append(f"**{section.capitalize()} Timeouts:**")

                for item_id, timestamp in list(self.cooldowns[section].items()):
                    timestamp_dt = datetime.datetime.fromisoformat(timestamp)
                    elapsed = now - timestamp_dt
                    hours_left = self.cooldown_hours - (elapsed.total_seconds() / 3600)

                    line = (f"- ID: `{item_id}`, " +
                            (f"Time left: {hours_left:.1f} hours" if hours_left > 0
                            else f"**⚠️ EXPIRED** ({abs(hours_left):.1f} hours ago)"))

                    # Check if adding this line would exceed Discord's limit
                    if sum(len(x) for x in current_msg) + len(line) > 1900:
                        messages.append("\n".join(current_msg))
                        current_msg = [line]
                    else:
                        current_msg.append(line)

                current_msg.append("")  # Add separator between sections

            # Add any remaining content
            if current_msg:
                messages.append("\n".join(current_msg))

            # Send messages
            if not messages:
                await ctx.send("No active timeouts found.")
            else:
                for msg in messages:
                    await ctx.send(msg)

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

    @flexible_command(name="owner_delete_all_ads")
    async def owner_delete_all_ads(self, ctx: commands.Context, confirm: str = None) -> None:
        """Delete all active advertisements and clear pending deletions.

        Args:
            confirm: Type 'confirm' to execute the deletion

        Only works for the bot owner in DMs.
        """
        if not await self._check_owner_dm(ctx):
            return

        if not confirm or confirm.lower() != 'confirm':
            await ctx.send("⚠️ This will delete ALL active advertisements and clear the pending deletions list.\n"
                           "To confirm, use: `owner_delete_all_ads confirm`")
            return

        try:
            deleted_count = 0
            errors_count = 0

            # Process each pending deletion
            for thread_id, _, author_id, notify in self.pending_deletions:
                try:
                    thread = await self.bot.fetch_channel(thread_id)
                    if thread:
                        await thread.delete()
                        deleted_count += 1

                        # Try to notify the author if notifications were enabled
                        if notify and author_id:
                            try:
                                user = await self.bot.fetch_user(author_id)
                                if user:
                                    await user.send("Your advertisement has been removed by a moderator.")
                            except Exception as e:
                                self.logger.warning(f"Failed to send notification to user {author_id}: {e}")
                except discord.NotFound:
                    # Thread already deleted
                    deleted_count += 1
                except Exception as e:
                    self.logger.error(f"Error deleting thread {thread_id}: {e}")
                    errors_count += 1

            # Clear the pending deletions list
            old_count = len(self.pending_deletions)
            self.pending_deletions = []
            await self._save_pending_deletions()

            # Send summary
            await ctx.send(f"Operation complete:\n"
                           f"• Processed {old_count} pending deletions\n"
                           f"• Successfully deleted: {deleted_count} threads\n"
                           f"• Errors encountered: {errors_count}\n"
                           f"• Pending deletions list cleared")

        except Exception as e:
            self.logger.error(f"Error in owner_delete_all_ads: {e}", exc_info=True)
            await ctx.send(f"Error processing command: {str(e)}")

    @flexible_command(name="owner_clear_all_timeouts")
    async def owner_clear_all_timeouts(self, ctx: commands.Context, confirm: str = None) -> None:
        """Clear all advertisement timeouts.

        Args:
            confirm: Type 'confirm' to execute the clearing

        Only works for the bot owner in DMs.
        """
        if not await self._check_owner_dm(ctx):
            return

        if not confirm or confirm.lower() != 'confirm':
            await ctx.send("⚠️ This will clear ALL advertisement cooldowns for both users and guilds.\n"
                           "To confirm, use: `owner_clear_all_timeouts confirm`")
            return

        try:
            # Store counts for reporting
            user_count = len(self.cooldowns['users'])
            guild_count = len(self.cooldowns['guilds'])

            # Clear both cooldown dictionaries
            self.cooldowns = {'users': {}, 'guilds': {}}
            await self._save_cooldowns()

            await ctx.send(f"Successfully cleared all timeouts:\n"
                           f"• Users cleared: {user_count}\n"
                           f"• Guilds cleared: {guild_count}")

        except Exception as e:
            self.logger.error(f"Error in owner_clear_all_timeouts: {e}", exc_info=True)
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
            to_remove = []  # Track entries to remove

            for thread_id, deletion_time, author_id, notify in self.pending_deletions:
                if current_time >= deletion_time:
                    try:
                        # Try to get the thread
                        thread = await self.bot.fetch_channel(thread_id)
                        # Skip deletion if thread is pinned
                        if hasattr(thread, 'pinned') and thread.pinned:
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
                        self.logger.info(f"Deleted advertisement thread {thread_id}")
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
                self.pending_deletions = [
                    entry for entry in self.pending_deletions
                    if entry[0] not in to_remove
                ]
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
                await self._save_cooldowns()
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

    async def _send_debug_message(self, message: str) -> None:
        """Send debug message to testing channel if configured."""
        if self.testing_channel_id:
            try:
                channel = self.bot.get_channel(self.testing_channel_id)
                if channel:
                    # Add UTC timestamp to debug message
                    utc_timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                    await channel.send(f"🔧 **[{utc_timestamp}] Advertise Debug**: {message}")
            except Exception as e:
                self.logger.error(f"Failed to send debug message to testing channel: {e}")
        # Always log to console as backup
        self.logger.info(message)

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
            interaction: Discord interaction object (response already sent)
            embed: Embed to post
            thread_title: Title for the forum thread
            ad_type: Type of advertisement (guild or member)
            guild_id: Guild ID (optional, for guild advertisements)
            notify: Whether to notify the user when the ad expires
        """
        import time
        start_time = time.time()
        await self._send_debug_message(f"Starting post_advertisement for user {interaction.user.id} ({interaction.user.name}), type: {ad_type}")

        try:
            # Get the forum channel first (quick check)
            channel_fetch_start = time.time()
            channel = self.bot.get_channel(self.advertise_channel_id)
            channel_fetch_time = time.time() - channel_fetch_start
            await self._send_debug_message(f"Channel fetch took {channel_fetch_time:.2f}s for user {interaction.user.id}")

            if not channel:
                await self._send_debug_message(f"❌ Advertisement channel not found: {self.advertise_channel_id}")
                await interaction.followup.send(
                    "There was an error posting your advertisement. Please contact @thedisasterfish.",
                    ephemeral=True
                )
                return

            # Now do the heavy work (initial response already sent by form)
            async with self.task_tracker.task_context("Posting Advertisement"):
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
                thread_create_start = time.time()
                thread_with_message = await channel.create_thread(
                    name=thread_title,
                    content="",  # Empty content
                    embed=embed,
                    applied_tags=applied_tags,  # Apply the tags
                    auto_archive_duration=1440  # Auto-archive after 24 hours
                )
                thread_create_time = time.time() - thread_create_start
                await self._send_debug_message(f"Thread creation took {thread_create_time:.2f}s for user {interaction.user.id}")

                thread = thread_with_message.thread
                await self._send_debug_message(f"✅ Created advertisement thread: {thread.id} for user {interaction.user.id} ({interaction.user.name}), type: {ad_type}")
                self._operation_count += 1
                self._last_operation_time = datetime.datetime.now()

                # Update cooldowns
                cooldown_start = time.time()
                current_time = datetime.datetime.now().isoformat()
                self.cooldowns['users'][str(interaction.user.id)] = current_time

                # If it's a guild advertisement, also add guild cooldown
                if guild_id:
                    self.cooldowns['guilds'][str(guild_id)] = current_time

                await self._save_cooldowns()
                cooldown_time = time.time() - cooldown_start
                await self._send_debug_message(f"Cooldown update took {cooldown_time:.2f}s for user {interaction.user.id}")

                # Schedule thread for deletion with author ID and notification preference
                schedule_start = time.time()
                deletion_time = datetime.datetime.now() + datetime.timedelta(hours=self.cooldown_hours)
                self.pending_deletions.append((thread.id, deletion_time, interaction.user.id, notify))
                await self._save_pending_deletions()
                schedule_time = time.time() - schedule_start
                await self._send_debug_message(f"Deletion scheduling took {schedule_time:.2f}s for user {interaction.user.id}")

                total_time = time.time() - start_time
                await self._send_debug_message(f"✅ Advertisement posting completed in {total_time:.2f}s for user {interaction.user.id} ({interaction.user.name})")

        except Exception as e:
            total_time = time.time() - start_time
            await self._send_debug_message(f"❌ Error in post_advertisement after {total_time:.2f}s for user {interaction.user.id}: {str(e)}")
            self.logger.error(f"Error in post_advertisement after {total_time:.2f}s: {e}", exc_info=True)
            self._has_errors = True

            # Try to send error message - use followup since initial response was already sent in form
            try:
                await interaction.followup.send(
                    "There was an error posting your advertisement. Please contact @thedisasterfish.",
                    ephemeral=True
                )
            except Exception as response_error:
                await self._send_debug_message(f"❌ Failed to send error response to user {interaction.user.id}: {str(response_error)}")

# ====================
# Cog Setup
# ====================


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UnifiedAdvertise(bot))

    # Sync the slash commands
    try:
        cog = bot.get_cog("Unified Advertise")
        bot.logger.debug("Waiting for UnifiedAdvertise cog to be ready")
        await cog.wait_until_ready()
        bot.logger.debug("UnifiedAdvertise Cog is ready")
        if cog.guild_id:
            guild = discord.Object(id=cog.guild_id)
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            bot.logger.info(f"Synced commands to guild {cog.guild_id}")
        else:
            bot.logger.warning("Guild ID not configured, using global sync")
            await bot.tree.sync()
    except Exception as e:
        if cog:
            bot.logger.error(f"Error syncing app commands: {e}")
        print(f"Error syncing app commands: {e}")
