# Standard library imports
import asyncio
import datetime
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple

# Third-party imports
import discord
from discord import app_commands
from discord.ext import commands, tasks

# Local application imports
from thetower.bot.basecog import BaseCog

# UI imports
from .ui import (
    AdManagementView,
    AdminAdManagementView,
    AdvertisementType,
    UnifiedAdvertiseSettingsView,
)


class UnifiedAdvertise(BaseCog, name="Unified Advertise"):
    """Combined cog for both guild and member advertisements.

    Provides functionality for posting, managing and moderating
    guild and member advertisements in a Discord forum channel.
    """

    # Settings view class for the cog manager
    settings_view_class = UnifiedAdvertiseSettingsView

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
                    await self._send_debug_message(
                        f"Orphan scan: Advertisement channel not found for guild {guild_id}: {advertise_channel_id}", guild_id
                    )
                    continue

                # Fetch all active threads in the forum channel
                threads = []
                try:
                    # For forum channels, threads is a list property, not a method
                    threads = channel.threads
                except Exception as e:
                    await self._send_debug_message(f"Orphan scan: Failed to fetch threads for guild {guild_id}: {e}", guild_id)
                    continue

                tracked_ids = {t_id for t_id, _, _, _, _, _, _ in self.pending_deletions}
                new_orphans = 0
                cooldown_hours = self._get_cooldown_hours(guild_id)

                for thread in threads:
                    if thread.id not in tracked_ids:
                        # Extract actual user and guild information from embed
                        user_id, ad_guild_id, ad_type = await self._extract_user_and_guild_info(thread)

                        # Get names
                        thread_name = thread.name
                        try:
                            author = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                            author_name = author.name if author else f"User {user_id}"
                        except Exception:
                            author_name = f"User {user_id}"

                        # Add all orphans regardless of pin status
                        deletion_time = datetime.datetime.now() + datetime.timedelta(hours=cooldown_hours)
                        notify = False
                        self.pending_deletions.append((thread.id, deletion_time, user_id, notify, guild_id, thread_name, author_name))
                        new_orphans += 1

                        # Update cooldown timestamps to match this thread's creation time
                        thread_creation_timestamp = thread.created_at.isoformat()

                        # Get guild-specific cooldowns
                        guild_cooldowns = self.cooldowns.get(guild_id, {"users": {}, "guilds": {}})

                        if user_id != 0:
                            guild_cooldowns["users"][str(user_id)] = thread_creation_timestamp
                            await self._send_debug_message(
                                f"Updated user {user_id} cooldown to match orphaned thread {thread.id} creation time", guild_id
                            )

                        # For guild advertisements, also update guild cooldown
                        if ad_type == "guild" and ad_guild_id:
                            guild_cooldowns["guilds"][ad_guild_id] = thread_creation_timestamp
                            await self._send_debug_message(
                                f"Updated guild {ad_guild_id} cooldown to match orphaned thread {thread.id} creation time", guild_id
                            )

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

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.logger.info("Initializing UnifiedAdvertise")

        # Store a reference to this cog
        self.bot.unified_advertise = self

        # Global settings (bot-wide) - none for this cog currently
        self.global_settings = {}

        # Guild-specific settings
        self.guild_settings = {
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

    # === Settings Helper Methods ===

    def _ensure_guild_initialized(self, guild_id: int) -> None:
        """Ensure settings and data structures are initialized for a guild."""
        if guild_id:
            self.ensure_settings_initialized(guild_id=guild_id, default_settings=self.guild_settings)

            # Initialize cooldowns for this guild if not present
            if guild_id not in self.cooldowns:
                self.cooldowns[guild_id] = {"users": {}, "guilds": {}}

    def _get_cooldown_hours(self, guild_id: int) -> int:
        """Get cooldown hours setting for a guild."""
        return self.get_setting("cooldown_hours", default=24, guild_id=guild_id)

    def _get_advertise_channel_id(self, guild_id: int) -> Optional[int]:
        """Get advertise channel ID setting for a guild."""
        return self.get_setting("advertise_channel_id", default=None, guild_id=guild_id)

    def _get_mod_channel_id(self, guild_id: int) -> Optional[int]:
        """Get mod channel ID setting for a guild."""
        return self.get_setting("mod_channel_id", default=None, guild_id=guild_id)

    def _get_guild_tag_id(self, guild_id: int) -> Optional[int]:
        """Get guild tag ID setting for a guild."""
        return self.get_setting("guild_tag_id", default=None, guild_id=guild_id)

    def _get_member_tag_id(self, guild_id: int) -> Optional[int]:
        """Get member tag ID setting for a guild."""
        return self.get_setting("member_tag_id", default=None, guild_id=guild_id)

    def _get_testing_channel_id(self, guild_id: int) -> Optional[int]:
        """Get testing channel ID setting for a guild."""
        return self.get_setting("testing_channel_id", default=None, guild_id=guild_id)

    def _get_cooldown_filename(self, guild_id: int) -> str:
        """Get cooldown filename for a guild."""
        return f"advertisement_cooldowns_{guild_id}.json"

    async def cog_initialize(self) -> None:
        """Initialize the cog - called by BaseCog during ready process."""
        self.logger.info("Initializing Advertisement module...")

        try:
            async with self.task_tracker.task_context("Initialization") as tracker:
                # Initialize parent
                self.logger.debug("Initializing parent cog")
                tracker.update_status("Loading data")
                await super().cog_initialize()

                # 1. Load data (multi-guild support will load for all configured guilds)
                self.logger.debug("Loading cached data")
                tracker.update_status("Loading data")
                await self._load_all_guild_data()

                # Clean up non-existent threads from pending deletions
                self.logger.debug("Cleaning up non-existent threads")
                tracker.update_status("Cleaning up threads")
                await self._cleanup_nonexistent_threads()

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

        except Exception as e:
            self._has_errors = True
            self.logger.error(f"Failed to initialize Advertisement module: {e}", exc_info=True)
            raise

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

    async def _check_additional_interaction_permissions(self, interaction: discord.Interaction) -> bool:
        """Override additional interaction permissions for slash commands.

        For the unified_advertise cog:
        - The /advertise command is for managing user's own ads (ephemeral UI), so no channel restrictions
        - Future commands that post to channels should respect permission manager
        """
        # For now, /advertise is just for personal ad management (ephemeral)
        # If we add slash commands that post to channels, we'll check permissions for those
        return True

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
        if not await self._check_additional_interaction_permissions(interaction):
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

        # Defer response immediately to prevent timeout
        await interaction.response.defer(ephemeral=True)

        if is_admin or is_bot_owner:
            # Show admin view
            view = AdminAdManagementView(self, guild_id)
            embed = await view.update_view(interaction)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            # Show user view
            view = AdManagementView(self, user_id, guild_id)
            embed = await view.update_view(interaction)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

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

            for thread_id, deletion_time, author_id, notify, guild_id, thread_name, author_name in self.pending_deletions:
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
                        self.logger.debug(f"Thread {thread_id} no longer exists, removing from tracking")

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

                self.logger.info(
                    f"Loaded cooldowns for guild {guild_id}: {len(guild_cooldowns.get('users', {}))} users, {len(guild_cooldowns.get('guilds', {}))} guilds"
                )

            # Load all pending deletions (global, but we'll track guild_id in the tuple)
            deletions_file = self.data_directory / "advertisement_pending_deletions_all.pkl"
            self.pending_deletions = await self._load_pending_deletions_multi_guild(deletions_file)

            self.logger.info(f"Loaded {len(self.pending_deletions)} total pending deletions across all guilds")

        except Exception as e:
            self.logger.error(f"Error loading guild data: {e}", exc_info=True)

    async def _load_pending_deletions_multi_guild(self, file_path: Path) -> List[Tuple[int, datetime.datetime, int, bool, int, str, str]]:
        """Load pending deletions with multi-guild support.

        Returns:
            List of tuples: (thread_id, deletion_time, author_id, notify, guild_id, thread_name, author_name)
        """
        try:
            data = await self.load_data(file_path, default=[])
            converted_data = []

            for entry in data:
                if len(entry) == 7:  # New format with names
                    thread_id, del_time, author_id, notify, guild_id, thread_name, author_name = entry
                    if isinstance(del_time, str):
                        del_time = datetime.datetime.fromisoformat(del_time)
                    converted_data.append((int(thread_id), del_time, int(author_id), bool(notify), int(guild_id), str(thread_name), str(author_name)))
                elif len(entry) == 5:  # Old format with guild_id but no names
                    thread_id, del_time, author_id, notify, guild_id = entry
                    if isinstance(del_time, str):
                        del_time = datetime.datetime.fromisoformat(del_time)
                    # Fetch names for migration
                    thread_name, author_name = await self._fetch_names_for_migration(thread_id, author_id)
                    converted_data.append((int(thread_id), del_time, int(author_id), bool(notify), int(guild_id), thread_name, author_name))
                    self.logger.info(f"Migrated deletion entry for thread {thread_id} to include names")
                elif len(entry) == 4:  # Old format without guild_id (thread_id, time, author_id, notify)
                    thread_id, del_time, author_id, notify = entry
                    if isinstance(del_time, str):
                        del_time = datetime.datetime.fromisoformat(del_time)
                    # Try to determine guild_id from thread and fetch names
                    guild_id = await self._get_thread_guild_id(thread_id)
                    thread_name, author_name = await self._fetch_names_for_migration(thread_id, author_id)
                    converted_data.append((int(thread_id), del_time, int(author_id), bool(notify), guild_id, thread_name, author_name))
                    self.logger.info(f"Migrated deletion entry for thread {thread_id} to include guild_id {guild_id} and names")
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
            if thread and hasattr(thread, "guild"):
                return thread.guild.id
        except Exception:
            pass
        # Default to first guild if we can't determine
        if self.bot.guilds:
            return self.bot.guilds[0].id
        return 0

    async def _fetch_names_for_migration(self, thread_id: int, author_id: int) -> Tuple[str, str]:
        """Fetch thread and author names for migration."""
        thread_name = f"Thread {thread_id}"
        author_name = f"User {author_id}"

        try:
            thread = self.bot.get_channel(thread_id)
            if not thread:
                thread = await self.bot.fetch_channel(thread_id)
            if thread:
                thread_name = thread.name
        except Exception as e:
            self.logger.warning(f"Could not fetch thread name for {thread_id}: {e}")

        try:
            author = self.bot.get_user(author_id)
            if not author:
                author = await self.bot.fetch_user(author_id)
            if author:
                author_name = author.name
        except Exception as e:
            self.logger.warning(f"Could not fetch author name for {author_id}: {e}")

        return thread_name, author_name

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
                (
                    thread_id,
                    deletion_time.isoformat() if isinstance(deletion_time, datetime.datetime) else deletion_time,
                    author_id,
                    notify,
                    guild_id,
                    thread_name,
                    author_name,
                )
                for thread_id, deletion_time, author_id, notify, guild_id, thread_name, author_name in self.pending_deletions
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

    async def _save_pending_deletions(self) -> None:
        """Save pending deletions - updated for multi-guild support."""
        await self._save_pending_deletions_multi_guild()

    async def _cleanup_nonexistent_threads(self) -> None:
        """Clean up threads that no longer exist from pending deletions list during startup.

        This prevents logging messages about non-existent threads every time the bot loads.
        """
        if not self.pending_deletions:
            return

        to_remove = []
        for thread_id, deletion_time, author_id, notify, guild_id, thread_name, author_name in self.pending_deletions:
            try:
                # Try to fetch the thread - if it doesn't exist, mark for removal
                await self.bot.fetch_channel(thread_id)
            except discord.NotFound:
                # Thread no longer exists, mark for removal
                to_remove.append(thread_id)
            except Exception:
                # Other errors (network issues, etc.) - leave in list for now
                pass

        # Remove non-existent threads
        if to_remove:
            original_count = len(self.pending_deletions)
            self.pending_deletions = [entry for entry in self.pending_deletions if entry[0] not in to_remove]
            removed_count = original_count - len(self.pending_deletions)

            if removed_count > 0:
                self.logger.debug(f"Cleaned up {removed_count} non-existent threads from pending deletions")
                await self._save_pending_deletions()

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
            debug_enabled = self.get_setting("debug_enabled", default=False, guild_id=guild_id)
            testing_channel_id = self._get_testing_channel_id(guild_id)
        else:
            # Try to get from first configured guild as fallback
            debug_enabled = False
            testing_channel_id = None
            for gid in self.cooldowns.keys():
                debug_enabled = self.get_setting("debug_enabled", default=False, guild_id=gid)
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
                await interaction.response.send_message("❌ This guild has been banned from posting advertisements in this server.", ephemeral=True)
                return False

        if ad_type == AdvertisementType.MEMBER:
            banned_users = self.get_setting("banned_users", default=[], guild_id=discord_guild_id)
            if isinstance(banned_users, list) and user_id in banned_users:
                await interaction.response.send_message("❌ You have been banned from posting member advertisements in this server.", ephemeral=True)
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
                await interaction.followup.send(
                    "There was an error posting your advertisement. Please contact a server administrator.", ephemeral=True
                )
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
                thread_name = thread.name
                author_name = interaction.user.name
                self.pending_deletions.append((thread.id, deletion_time, interaction.user.id, notify, discord_guild_id, thread_name, author_name))
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
                await interaction.followup.send(
                    "There was an error posting your advertisement. Please contact a server administrator.", ephemeral=True
                )
            except Exception as response_error:
                await self._send_debug_message(f"❌ Failed to send error response to user {interaction.user.id}: {str(response_error)}")

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
                    tracked_ids = {t_id for t_id, _, _, _, _, _, _ in self.pending_deletions}
                    for keep_thread in keep_threads:
                        # Get the thread's actual user and guild info
                        thread_user_id, thread_guild_id, thread_ad_type = await self._extract_user_and_guild_info(keep_thread)

                        if keep_thread.id not in tracked_ids:
                            deletion_time = datetime.datetime.now() + datetime.timedelta(hours=cooldown_hours)
                            notify = False  # Don't notify for duplicate cleanup
                            thread_name = keep_thread.name
                            try:
                                author = self.bot.get_user(thread_user_id) or await self.bot.fetch_user(thread_user_id)
                                author_name = author.name if author else f"User {thread_user_id}"
                            except Exception:
                                author_name = f"User {thread_user_id}"
                            self.pending_deletions.append((keep_thread.id, deletion_time, thread_user_id, notify, guild_id, thread_name, author_name))
                            await self._send_debug_message(f"Added kept thread {keep_thread.id} to pending deletions tracking", guild_id)

                        # Update cooldown timestamps to match the kept thread's creation time
                        thread_creation_timestamp = keep_thread.created_at.isoformat()

                        # Update user cooldown
                        if thread_user_id != 0:
                            guild_cooldowns["users"][str(thread_user_id)] = thread_creation_timestamp
                            await self._send_debug_message(
                                f"Updated user {thread_user_id} cooldown to match kept thread {keep_thread.id} creation time", guild_id
                            )

                        # Update guild cooldown for guild advertisements
                        if thread_ad_type == "guild" and thread_guild_id:
                            guild_cooldowns["guilds"][thread_guild_id] = thread_creation_timestamp
                            await self._send_debug_message(
                                f"Updated guild {thread_guild_id} cooldown to match kept thread {keep_thread.id} creation time", guild_id
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
                # Create dictionaries of field name -> value for easier lookup
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


# ====================
# Cog Setup
# ====================


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UnifiedAdvertise(bot))

    # Note: Slash command syncing is now handled automatically by CogManager
    # when cogs are enabled/disabled for guilds
    bot.logger.info("UnifiedAdvertise cog loaded - slash commands will sync per-guild via CogManager")
