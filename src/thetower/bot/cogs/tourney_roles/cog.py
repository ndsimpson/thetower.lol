"""
Tournament Roles Cog

A modular Discord bot cog for automatically assigning tournament-based roles
based on competitive performance across different leagues.

This cog follows the unified cog design architecture with:
- Modular UI components separated by function/role
- Integration with global settings system
- Slash command-based interface
- Robust background processing and task management
"""

import asyncio
import datetime
from typing import Optional

import discord

from thetower.bot.basecog import BaseCog

from .ui import (
    TournamentRolesCore,
    TournamentRolesSettingsView,
)


class TourneyRoles(BaseCog, name="Tourney Roles"):
    """
    Tournament role management system.

    Automatically assigns Discord roles based on tournament participation
    and performance across different leagues.
    """

    # Settings view class for the cog manager
    settings_view_class = TournamentRolesSettingsView

    def __init__(self, bot):
        super().__init__(bot)
        self.logger.info("Initializing TourneyRoles")

        # Store reference on bot
        self.bot.tourney_roles = self

        # Initialize core instance variables with descriptions
        self.member_roles = {}  # {guild_id: {user_id: roles}}
        self.processed_users = 0
        self.roles_assigned = 0
        self.roles_removed = 0
        self.users_with_no_player_data = 0

        # Status tracking variables
        self.last_full_update = None
        self.currently_updating = False
        self.update_task = None
        self.startup_message_shown = False

        # Phase separation variables
        self.currently_calculating = False
        self.calculation_complete = False
        self.calculated_roles = {}  # {guild_id: {user_id: role_id}}

        # Initialize log buffer
        self.log_buffer = []
        self.log_buffer_max_size = 8000  # Characters before forcing flush

        # Role cache for calculated tournament roles
        self.role_cache = {}  # {guild_id: {user_id: calculated_role_id}}
        self.cache_timestamp = None
        self.cache_latest_tourney_date = None  # Latest tournament date in cache

        # Core components
        self.core = TournamentRolesCore(self)

        # UI components (no longer separate cogs)
        # self.user_ui = UserTournamentRoles(self)
        # self.admin_ui = AdminTournamentRoles(self)

        # Default settings - separated into global and guild-specific
        # Global settings (bot owner only)
        self.global_settings = {
            "update_interval": 2 * 60 * 60,  # 2 hours instead of 6
            "update_on_startup": True,
            "dry_run": False,
            "debug_logging": False,
            "log_batch_size": 10,
            "process_batch_size": 50,
            "process_delay": 5,
            "error_retry_delay": 300,
            "league_hierarchy": ["Legend", "Champion", "Platinum", "Gold", "Silver", "Copper"],
        }

        # Guild-specific settings
        self.guild_settings = {
            "roles_config": {},
            "verified_role_id": None,
            "log_channel_id": None,
            "pause": False,
            "immediate_logging": True,
            "bulk_batch_size": 45,  # Concurrent operations per batch
            "bulk_batch_delay": 0.1,  # Delay between batches
            "authorized_refresh_roles": [],  # List of Discord role IDs that can refresh tournament roles for others
        }

        # Hardcoded cache filename (not configurable)
        self.roles_cache_filename = "tourney_roles.json"

    async def save_data(self) -> bool:
        """Save tournament role data using BaseCog's utility."""
        try:
            # Prepare serializable data
            save_data = {
                "roles_config": self.get_setting("roles_config", {}),
                "last_full_update": self.last_full_update.isoformat() if self.last_full_update else None,
                "processed_users": self.processed_users,
                "roles_assigned": self.roles_assigned,
                "roles_removed": self.roles_removed,
                "users_with_no_player_data": self.users_with_no_player_data,
                "role_cache": self.role_cache,
                "cache_timestamp": self.cache_timestamp.isoformat() if self.cache_timestamp else None,
                "cache_latest_tourney_date": self.cache_latest_tourney_date.isoformat() if self.cache_latest_tourney_date else None,
            }

            # Use BaseCog's utility to save data
            success = await self.save_data_if_modified(save_data, self.cache_file)
            if success:
                self.logger.info("Saved tournament role data")
            return success

        except Exception as e:
            self.logger.error(f"Error saving tournament role data: {e}", exc_info=True)
            self._has_errors = True
            return False

    async def load_data(self) -> bool:
        """Load tournament role data using BaseCog's utility."""
        try:
            save_data = await super().load_data(self.cache_file)

            if save_data:
                # Load roles configuration (guild-specific) - will be loaded later when guilds are available
                roles_config = save_data.get("roles_config", {})
                if roles_config:
                    # Store for later loading into guild settings
                    self._saved_roles_config = roles_config

                # Load tracking data
                self.last_full_update = datetime.datetime.fromisoformat(save_data["last_full_update"]) if save_data.get("last_full_update") else None
                self.processed_users = save_data.get("processed_users", 0)
                self.roles_assigned = save_data.get("roles_assigned", 0)
                self.roles_removed = save_data.get("roles_removed", 0)
                self.users_with_no_player_data = save_data.get("users_with_no_player_data", 0)

                # Load role cache
                self.role_cache = save_data.get("role_cache", {})
                self.cache_timestamp = datetime.datetime.fromisoformat(save_data["cache_timestamp"]) if save_data.get("cache_timestamp") else None
                self.cache_latest_tourney_date = (
                    datetime.datetime.fromisoformat(save_data["cache_latest_tourney_date"]) if save_data.get("cache_latest_tourney_date") else None
                )

                self.logger.info("Loaded tournament role data")
                return True

            self.logger.info("No saved tournament role data found")
            return False

        except Exception as e:
            self.logger.error(f"Error loading tournament role data: {e}", exc_info=True)
            self._has_errors = True
            return False

    @property
    def update_interval(self):
        """Get the update interval in seconds."""
        return self.get_global_setting("update_interval", 6 * 60 * 60)

    @property
    def process_batch_size(self):
        """Get the process batch size."""
        return self.get_global_setting("process_batch_size", 50)

    @property
    def process_delay(self):
        """Get the process delay between batches."""
        return self.get_global_setting("process_delay", 5)

    async def _load_settings(self) -> None:
        """Load and initialize default settings."""
        # Initialize global settings
        for key, default_value in self.global_settings.items():
            if not self.has_global_setting(key):
                self.set_global_setting(key, default_value)
                self.logger.debug(f"Set default global setting {key} = {default_value}")

        # Clean up settings for guilds where this cog is no longer enabled
        enabled_guild_ids = set()
        for guild in self.bot.guilds:
            try:
                if self.bot.cog_manager.can_guild_use_cog(self.cog_name, guild.id, False):
                    enabled_guild_ids.add(guild.id)
                    # Initialize guild-specific settings
                    self.ensure_settings_initialized(guild_id=guild.id, default_settings=self.guild_settings)

                    # If we have saved roles config, load it for this guild
                    if hasattr(self, "_saved_roles_config") and self._saved_roles_config:
                        self.set_setting("roles_config", self._saved_roles_config, guild_id=guild.id)
                        self.logger.debug(f"Loaded saved roles config for guild {guild.id}")
            except Exception as e:
                self.logger.debug(f"Error initializing settings for guild {guild.id}: {e}")

        # Remove settings for guilds where cog is no longer enabled
        try:
            all_guild_settings = self.config.get_all_cog_settings(self.cog_name)
            for guild_id_str in list(all_guild_settings.keys()):
                guild_id = int(guild_id_str)
                if guild_id not in enabled_guild_ids:
                    # Remove all settings for this guild
                    for setting_key in list(all_guild_settings[guild_id_str].keys()):
                        self.config.remove_cog_setting(self.cog_name, setting_key, guild_id)
                    self.logger.debug(f"Removed settings for disabled guild {guild_id}")
        except Exception as e:
            self.logger.debug(f"Error cleaning up settings for disabled guilds: {e}")

        # Clean up saved roles config after loading
        if hasattr(self, "_saved_roles_config"):
            del self._saved_roles_config

    async def get_known_players_cog(self):
        """Get the PlayerLookup cog instance."""
        return self.bot.get_cog("Player Lookup")

    async def get_tourney_stats_cog(self):
        """Get the TourneyStats cog instance."""
        return self.bot.get_cog("Tourney Stats")

    def is_cache_valid(self, guild_id: int) -> bool:
        """Check if the role cache is still valid for a guild."""
        if not self.cache_timestamp or guild_id not in self.role_cache:
            return False

        # Cache is valid until new tournament data arrives or admin clears it
        return True

    async def is_cache_valid_with_tourney_check(self, guild_id: int) -> bool:
        """Check if cache is valid, including checking for newer tournament data."""
        if not self.is_cache_valid(guild_id):
            return False

        # Check if there's newer tournament data
        try:
            latest_tourney_date = await self.get_latest_tournament_date()
            if latest_tourney_date and self.cache_latest_tourney_date:
                if latest_tourney_date > self.cache_latest_tourney_date:
                    self.logger.info(f"Cache invalidated: New tournament data available ({latest_tourney_date} > {self.cache_latest_tourney_date})")
                    return False
            elif latest_tourney_date and not self.cache_latest_tourney_date:
                self.logger.info(f"Cache invalidated: Tournament data now available ({latest_tourney_date})")
                return False
        except Exception as e:
            self.logger.error(f"Error checking tournament date for cache validation: {e}")
            # If we can't check, assume cache is still valid to avoid unnecessary recalculation
            return True

        return True

    async def get_latest_tournament_date(self) -> Optional[datetime.datetime]:
        """Get the latest tournament date from TourneyResult model."""
        try:
            # Import Django models synchronously
            from asgiref.sync import sync_to_async
            from django.apps import apps

            # Get the TourneyResult model
            TourneyResult = apps.get_model("tourney_results", "TourneyResult")

            # Query for the most recent tournament date
            latest_result = await sync_to_async(lambda: TourneyResult.objects.order_by("-date").first())()

            if latest_result and latest_result.date:
                # Convert date to datetime (set to end of day to be safe)
                latest_datetime = datetime.datetime.combine(latest_result.date, datetime.time.max, tzinfo=datetime.timezone.utc)
                self.logger.debug(f"Latest tournament date from database: {latest_datetime}")
                return latest_datetime

            self.logger.warning("No tournament results found in database")
            return None

        except Exception as e:
            self.logger.error(f"Error querying latest tournament date from database: {e}")
            # Fallback to sampling player data
            self.logger.info("Falling back to player data sampling for latest tournament date")
            return await self._get_latest_tournament_date_from_players()

    async def _get_latest_tournament_date_from_players(self) -> Optional[datetime.datetime]:
        """Fallback method to get latest tournament date by sampling player data."""
        try:
            tourney_stats_cog = await self.get_tourney_stats_cog()
            if not tourney_stats_cog:
                return None

            # Fallback: check if any recent tournaments exist by looking at player data
            discord_mapping = await self.get_discord_to_player_mapping()
            if not discord_mapping:
                return None

            latest_date = None
            sample_players = list(discord_mapping.values())[:5]  # Check first 5 players

            for player_data in sample_players:
                if "all_ids" in player_data and player_data["all_ids"]:
                    try:
                        player_stats = await self.core.get_player_tournament_stats(tourney_stats_cog, player_data["all_ids"][:1])
                        if player_stats.latest_tournament and player_stats.latest_tournament.get("date"):
                            tourney_date = player_stats.latest_tournament["date"]
                            if isinstance(tourney_date, str):
                                tourney_date = datetime.datetime.fromisoformat(tourney_date.replace("Z", "+00:00"))
                            if latest_date is None or tourney_date > latest_date:
                                latest_date = tourney_date
                    except Exception as e:
                        self.logger.debug(f"Error getting tournament date for player: {e}")

            return latest_date

        except Exception as e:
            self.logger.error(f"Error in fallback tournament date lookup: {e}")
            return None

    async def calculate_all_user_roles(self, guild_id: int, discord_to_player: dict) -> dict:
        """Calculate tournament roles for all users in a guild."""
        self.logger.info(f"Calculating tournament roles for guild {guild_id}")

        guild = self.bot.get_guild(guild_id)
        if not guild:
            self.logger.error(f"Guild {guild_id} not found")
            return {}

        # Get required cogs
        tourney_stats_cog = await self.get_tourney_stats_cog()
        if not tourney_stats_cog:
            self.logger.error("TourneyStats cog not available")
            return {}

        user_roles = {}
        roles_config = self.core.get_roles_config(guild_id)
        league_hierarchy = self.core.get_league_hierarchy(guild_id)
        debug_logging = self.get_global_setting("debug_logging", False)

        latest_tourney_date = None
        processed_count = 0

        for discord_id, player_data in discord_to_player.items():
            try:
                if "all_ids" not in player_data or not player_data["all_ids"]:
                    continue

                member = guild.get_member(int(discord_id))
                if not member:
                    continue

                # Get tournament stats
                player_tournaments = await self.core.get_player_tournament_stats(tourney_stats_cog, player_data["all_ids"])

                # Track latest tournament date
                if player_tournaments.latest_tournament and player_tournaments.latest_tournament.get("date"):
                    tourney_date = player_tournaments.latest_tournament["date"]
                    if isinstance(tourney_date, str):
                        tourney_date = datetime.datetime.fromisoformat(tourney_date.replace("Z", "+00:00"))
                    if latest_tourney_date is None or tourney_date > latest_tourney_date:
                        latest_tourney_date = tourney_date

                # Determine best role
                best_role_id = self.core.determine_best_role(
                    player_tournaments,
                    roles_config,
                    league_hierarchy,
                    debug_logging,
                )

                user_roles[str(discord_id)] = best_role_id

                # Yield control to event loop every 10 users to prevent heartbeat blocking
                processed_count += 1
                if processed_count % 10 == 0:
                    await asyncio.sleep(0)

            except Exception as e:
                self.logger.error(f"Error calculating role for user {discord_id}: {e}")

        # Update cache
        self.role_cache[guild_id] = user_roles
        self.cache_timestamp = datetime.datetime.now(datetime.timezone.utc)
        self.cache_latest_tourney_date = latest_tourney_date

        self.logger.info(f"Calculated roles for {len(user_roles)} users in guild {guild_id}, latest tournament date: {latest_tourney_date}")
        return user_roles

    async def get_discord_to_player_mapping(self):
        """Get mapping of Discord IDs to player information from PlayerLookup"""
        known_players_cog = await self.get_known_players_cog()
        if not known_players_cog:
            self.logger.error("Failed to get PlayerLookup cog")
            return {}

        try:
            # Wait for PlayerLookup to be ready
            if not known_players_cog.is_ready:
                self.logger.info("Waiting for PlayerLookup to be ready...")
                await known_players_cog.wait_until_ready()

            # Get the mapping
            mapping = await known_players_cog.get_discord_to_player_mapping()

            # Add detailed debug logging
            if mapping:
                self.logger.debug(f"Retrieved {len(mapping)} entries from PlayerLookup")
                sample_entry = next(iter(mapping.items()))
                self.logger.debug(f"Sample mapping entry: {sample_entry}")
            else:
                self.logger.warning("PlayerLookup returned empty mapping")
                # Check if PlayerLookup has any data at all
                # Note: PlayerLookup doesn't have a cache like KnownPlayers did
                self.logger.debug("PlayerLookup returned empty mapping")

            return mapping or {}  # Ensure we return at least an empty dict

        except Exception as e:
            self.logger.error(f"Error getting player mapping: {e}", exc_info=True)
            return {}

    async def schedule_periodic_updates(self):
        """Schedule periodic role updates"""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                # Check if it's time to run an update
                should_update = False
                if not self.last_full_update:
                    # Check if update_on_startup is enabled
                    if self.get_global_setting("update_on_startup", True):
                        should_update = True
                        self.logger.info("No previous update found, running initial role update")
                    elif not self.startup_message_shown:
                        # Only log this message once
                        self.logger.info("No previous update found, but update_on_startup is disabled. Waiting for manual update.")
                        self.startup_message_shown = True
                else:
                    time_since_update = (datetime.datetime.now(datetime.timezone.utc) - self.last_full_update).total_seconds()
                    if time_since_update >= self.update_interval:
                        should_update = True
                        self.logger.info(f"Time since last update ({time_since_update:.1f}s) exceeds interval, running role update")

                if should_update and not self.currently_updating:
                    # Check if the cog is enabled for any guilds
                    enabled_guilds = []
                    for guild in self.bot.guilds:
                        try:
                            if self.bot.cog_manager.can_guild_use_cog(self.cog_name, guild.id, False):  # Assume not bot owner for guild check
                                enabled_guilds.append(guild)
                        except Exception as e:
                            self.logger.debug(f"Error checking cog enablement for guild {guild.id}: {e}")

                    if not enabled_guilds:
                        self.logger.debug("TourneyRoles cog is not enabled for any guilds, skipping update")
                        # Sleep until next check
                        await asyncio.sleep(300)  # Check every 5 minutes if update needed
                        continue

                    # For automatic updates, create a message in the log channel
                    log_channel_id = self.get_setting("log_channel_id", guild_id=enabled_guilds[0].id) if enabled_guilds else None
                    if log_channel_id:
                        try:
                            channel = self.bot.get_channel(int(log_channel_id))
                            if channel:
                                # Get dry run status
                                dry_run = self.default_settings.get("dry_run")
                                initial_message = (
                                    "🔍 Starting automatic role update in DRY RUN mode..." if dry_run else "🔄 Starting automatic role update..."
                                )
                                message = await channel.send(f"{initial_message} This may take a while.")

                                # Run the update with progress tracking
                                await self.start_update_with_progress(message, manual_update=False)
                            else:
                                # No valid channel, run update without progress message
                                self.logger.warning("Log channel not found for automatic update progress message")
                                await self.update_all_roles()
                        except Exception as e:
                            self.logger.error(f"Error creating progress message for automatic update: {e}")
                            await self.update_all_roles()  # Still run the update
                    else:
                        # No log channel configured, run without progress message
                        await self.update_all_roles()

                # Sleep until next check
                await asyncio.sleep(300)  # Check every 5 minutes if update needed
            except Exception as e:
                self.logger.error(f"Error in periodic role update: {e}")
                await asyncio.sleep(self.get_global_setting("error_retry_delay", 300))  # Sleep on error

    async def update_all_roles(self):
        """Update roles for all users across all enabled guilds using separated calculation and application phases"""
        if self.currently_updating:
            self.logger.warning("Role update already in progress, skipping")
            return

        # Check if updates are paused
        if self.get_setting("pause", guild_id=self.bot.guilds[0].id if self.bot.guilds else None):
            self.logger.info("Role updates are currently paused. Skipping update.")
            return

        async with self.task_tracker.task_context("Role Update", "Updating tournament roles"):
            start_time = datetime.datetime.now(datetime.timezone.utc)
            try:
                self.currently_updating = True
                self.logger.info("Starting full role update")

                # Phase 1: Calculate roles if needed
                if not self.calculation_complete:
                    self.logger.info("Running calculation phase")
                    calc_success = await self.calculate_all_roles()
                    if not calc_success:
                        self.logger.error("Role calculation failed, aborting update")
                        return
                else:
                    self.logger.info("Using previously calculated roles")

                # Phase 2: Apply roles
                self.logger.info("Running application phase")
                apply_success = await self.apply_all_roles()
                if not apply_success:
                    self.logger.error("Role application failed")
                    return

                # Update timestamp and mark completion
                self.last_full_update = datetime.datetime.now(datetime.timezone.utc)
                duration = (self.last_full_update - start_time).total_seconds()

                self.logger.info(f"Role update completed in {duration:.1f}s")

                # Mark data as modified and save
                self.mark_data_modified()
                await self.save_data()

                # Reset phase flags for next update
                self.calculation_complete = False
                self.calculated_roles = {}

            except Exception as e:
                # Set the timestamp even if there was an error
                error_time = datetime.datetime.now(datetime.timezone.utc)
                error_duration = (error_time - start_time).total_seconds()
                self.logger.error(f"Error during role update after {error_duration:.1f}s: {e}")
                self.last_full_update = error_time
                if hasattr(self, "update_progress"):
                    self.update_progress["error"] = str(e)
                await self.add_log_message(f"❌ Error during role update: {e}")
                await self.flush_log_buffer()
                raise

            finally:
                # Make absolutely sure we unset the updating flag
                self.currently_updating = False
                if hasattr(self, "update_progress"):
                    self.update_progress["completed"] = True

    async def calculate_all_roles(self):
        """Calculate tournament roles for all users across all enabled guilds"""
        if self.currently_calculating:
            self.logger.warning("Role calculation already in progress, skipping")
            return False

        async with self.task_tracker.task_context("Role Calculation", "Calculating tournament roles"):
            try:
                self.currently_calculating = True
                self.logger.info("Starting role calculation phase")

                # Get enabled guilds for this cog
                enabled_guilds = []
                for guild in self.bot.guilds:
                    try:
                        if self.bot.cog_manager.can_guild_use_cog(self.cog_name, guild.id, False):
                            enabled_guilds.append(guild)
                    except Exception as e:
                        self.logger.debug(f"Error checking cog enablement for guild {guild.id}: {e}")

                # Get player data with retries
                max_retries = 3
                retry_delay = 5  # seconds
                discord_to_player = None

                for attempt in range(max_retries):
                    discord_to_player = await self.get_discord_to_player_mapping()
                    if discord_to_player:
                        break
                    if attempt < max_retries - 1:
                        self.logger.warning(f"Retry {attempt + 1}/{max_retries} getting player mapping...")
                        await asyncio.sleep(retry_delay)

                if not discord_to_player:
                    self.logger.error("Failed to get player mapping after retries")
                    return False

                if not enabled_guilds:
                    self.logger.warning("No guilds have TourneyRoles enabled, cannot proceed with role calculation")
                    return False

                # Process each enabled guild for calculation
                for guild in enabled_guilds:
                    self.logger.info(f"Calculating roles for guild: {guild.name} (ID: {guild.id})")

                    # Check if we need to recalculate roles or can use cache
                    if not await self.is_cache_valid_with_tourney_check(guild.id):
                        self.logger.info(f"Cache invalid for guild {guild.id}, recalculating roles")
                        user_roles = await self.calculate_all_user_roles(guild.id, discord_to_player)
                    else:
                        self.logger.info(f"Using cached roles for guild {guild.id}")
                        user_roles = self.role_cache.get(guild.id, {})

                    # Store calculated roles for application phase
                    self.calculated_roles[guild.id] = user_roles

                self.calculation_complete = True
                self.logger.info("Role calculation phase completed successfully")
                return True

            except Exception as e:
                self.logger.error(f"Error during role calculation: {e}")
                return False
            finally:
                self.currently_calculating = False

    async def apply_all_roles(self):
        """Apply calculated tournament roles to all users across all enabled guilds"""
        if not self.calculation_complete:
            self.logger.warning("Cannot apply roles - calculation phase not complete")
            return False

        if not self.calculated_roles:
            self.logger.warning("No calculated roles available for application")
            return False

        async with self.task_tracker.task_context("Role Application", "Applying tournament roles"):
            try:
                self.logger.info("Starting role application phase")

                # Log if in dry run mode
                dry_run = self.get_global_setting("dry_run", False)
                if dry_run:
                    self.logger.info("Running in DRY RUN mode - no actual role changes will be made")
                    self.logger.info("In dry run mode, processing all users for testing")

                # Reset stats for application phase
                self.processed_users = 0
                self.roles_assigned = 0
                self.roles_removed = 0
                self.users_with_no_player_data = 0

                # Get player data for application (needed for verification checks)
                discord_to_player = await self.get_discord_to_player_mapping()
                if not discord_to_player:
                    self.logger.error("Failed to get player mapping for role application")
                    return False

                # Get enabled guilds for this cog
                enabled_guilds = []
                for guild in self.bot.guilds:
                    try:
                        if self.bot.cog_manager.can_guild_use_cog(self.cog_name, guild.id, False):
                            enabled_guilds.append(guild)
                    except Exception as e:
                        self.logger.debug(f"Error checking cog enablement for guild {guild.id}: {e}")

                # Process each enabled guild for role application
                all_log_messages = []
                total_processed = 0

                for guild in enabled_guilds:
                    self.logger.info(f"Applying roles for guild: {guild.name} (ID: {guild.id})")

                    # Get calculated roles for this guild
                    user_roles = self.calculated_roles.get(guild.id, {})

                    # Perform bulk role updates for this guild
                    guild_log_messages = await self.update_guild_roles_bulk(guild, user_roles, discord_to_player)
                    all_log_messages.extend(guild_log_messages)

                    total_processed += len(user_roles)

                    # Send logs in batches to avoid flooding
                    log_batch_size = self.get_global_setting("log_batch_size", 10)
                    if len(all_log_messages) >= log_batch_size:
                        await self.send_role_logs_batch(all_log_messages)
                        all_log_messages = []

                # Send any remaining logs
                if all_log_messages:
                    await self.send_role_logs_batch(all_log_messages)

                # Send final log messages
                await self.flush_log_buffer()

                # Log completion
                if dry_run:
                    self.logger.info("Dry run role application completed")
                    await self.add_log_message("✅ Dry run role application completed")
                else:
                    self.logger.info("Role application completed")
                    await self.add_log_message("✅ Role application completed")

                self.logger.info(
                    f"Application Stats: Processed {total_processed} users across {len(enabled_guilds)} guilds, "
                    f"{self.roles_assigned} roles assigned, {self.roles_removed} roles removed"
                )
                await self.add_log_message(
                    f"📊 Application Stats: Processed {total_processed} users across {len(enabled_guilds)} guilds, "
                    f"{self.roles_assigned} roles assigned, {self.roles_removed} roles removed"
                )

                return True

            except Exception as e:
                self.logger.error(f"Error during role application: {e}")
                await self.add_log_message(f"❌ Error during role application: {e}")
                await self.flush_log_buffer()
                return False

    async def update_guild_roles_bulk(self, guild, user_roles, discord_to_player):
        """Update roles for a single guild using bulk operations."""
        log_messages = []
        dry_run = self.get_global_setting("dry_run", False)
        verified_role_id = self.core.get_verified_role_id(guild.id)

        # Get all managed role IDs
        roles_config = self.core.get_roles_config(guild.id)
        all_managed_role_ids = set(config.id for config in roles_config.values())

        # Group operations by role
        roles_to_add = {}  # {role_id: [members]}
        roles_to_remove = {}  # {role_id: [members]}

        processed_count = 0

        for discord_id_str, calculated_role_id in user_roles.items():
            discord_id = int(discord_id_str)
            member = guild.get_member(discord_id)
            if not member:
                continue

            # Check verification requirement
            if verified_role_id:
                verified_role = guild.get_role(int(verified_role_id))
                if not verified_role or verified_role not in member.roles:
                    # Remove all tournament roles if not verified
                    current_tourney_roles = [role for role in member.roles if str(role.id) in all_managed_role_ids]
                    for role in current_tourney_roles:
                        if str(role.id) not in roles_to_remove:
                            roles_to_remove[str(role.id)] = []
                        roles_to_remove[str(role.id)].append(member)
                        log_messages.append(f"{member.name}: -{role.name} (not verified)")
                        self.roles_removed += 1
                    continue

            # Determine what changes are needed
            current_tourney_roles = {str(role.id): role for role in member.roles if str(role.id) in all_managed_role_ids}

            # If user should have a role
            if calculated_role_id:
                if calculated_role_id not in current_tourney_roles:
                    # Need to add this role
                    if calculated_role_id not in roles_to_add:
                        roles_to_add[calculated_role_id] = []
                    roles_to_add[calculated_role_id].append(member)
                    log_messages.append(f"{member.name}: +{guild.get_role(int(calculated_role_id)).name}")
                    self.roles_assigned += 1

            # Remove roles they shouldn't have
            for role_id, role in current_tourney_roles.items():
                if calculated_role_id != role_id:
                    if role_id not in roles_to_remove:
                        roles_to_remove[role_id] = []
                    roles_to_remove[role_id].append(member)
                    log_messages.append(f"{member.name}: -{role.name}")
                    self.roles_removed += 1

            # Yield control to event loop every 10 users to prevent heartbeat blocking
            processed_count += 1
            if processed_count % 10 == 0:
                await asyncio.sleep(0)

        # Execute bulk operations
        bulk_batch_size = self.get_setting("bulk_batch_size", 45, guild_id=guild.id)
        bulk_batch_delay = self.get_setting("bulk_batch_delay", 0.1, guild_id=guild.id)

        # Add roles in bulk
        for role_id, members in roles_to_add.items():
            role = guild.get_role(int(role_id))
            if role:
                await self.bulk_add_role(role, members, bulk_batch_size, bulk_batch_delay, dry_run)

        # Remove roles in bulk
        for role_id, members in roles_to_remove.items():
            role = guild.get_role(int(role_id))
            if role:
                await self.bulk_remove_role(role, members, bulk_batch_size, bulk_batch_delay, dry_run)

        return log_messages

    async def bulk_add_role(self, role, members: list, batch_size: int, batch_delay: float, dry_run: bool):
        """Add a role to multiple members in batches, respecting Discord rate limits."""
        # Discord allows 10 role changes per 10 seconds per guild
        # Use smaller batches to avoid rate limits
        safe_batch_size = min(batch_size, 5)  # Conservative batch size

        for i in range(0, len(members), safe_batch_size):
            batch = members[i : i + safe_batch_size]
            if not dry_run:
                try:
                    # Apply roles sequentially within the batch to avoid rate limit spikes
                    for member in batch:
                        try:
                            await member.add_roles(role, reason="Tournament participation role update")
                        except discord.HTTPException as e:
                            if e.status == 429:  # Rate limited
                                self.logger.warning(f"Rate limited adding role to {member.name}, waiting...")
                                await asyncio.sleep(2)  # Wait and retry
                                await member.add_roles(role, reason="Tournament participation role update")
                            else:
                                raise
                except Exception as e:
                    self.logger.error(f"Error adding role {role.name} to batch: {e}")

            # Always add delay between batches
            if i + safe_batch_size < len(members):
                await asyncio.sleep(max(batch_delay, 2))  # Minimum 2 second delay

    async def bulk_remove_role(self, role, members: list, batch_size: int, batch_delay: float, dry_run: bool):
        """Remove a role from multiple members in batches, respecting Discord rate limits."""
        # Discord allows 10 role changes per 10 seconds per guild
        # Use smaller batches to avoid rate limits
        safe_batch_size = min(batch_size, 5)  # Conservative batch size

        for i in range(0, len(members), safe_batch_size):
            batch = members[i : i + safe_batch_size]
            if not dry_run:
                try:
                    # Remove roles sequentially within the batch to avoid rate limit spikes
                    for member in batch:
                        try:
                            await member.remove_roles(role, reason="Tournament participation role update")
                        except discord.HTTPException as e:
                            if e.status == 429:  # Rate limited
                                self.logger.warning(f"Rate limited removing role from {member.name}, waiting...")
                                await asyncio.sleep(2)  # Wait and retry
                                await member.remove_roles(role, reason="Tournament participation role update")
                            else:
                                raise
                except Exception as e:
                    self.logger.error(f"Error removing role {role.name} from batch: {e}")

            # Always add delay between batches
            if i + safe_batch_size < len(members):
                await asyncio.sleep(max(batch_delay, 2))  # Minimum 2 second delay

    async def update_member_roles(self, member, player_tournaments):
        """
        Update a member's roles based on tournament performance

        Args:
            member: Discord member to update
            player_tournaments: Tournament data for this player

        Returns:
            tuple: (roles_added, roles_removed, log_message or None)
        """
        try:
            # Dispatch start event
            self.bot.dispatch("bot_role_update_start", member.id)

            # Check if verified role is required
            verified_role_id = self.get_setting("verified_role_id", guild_id=member.guild.id)
            if verified_role_id:
                verified_role = member.guild.get_role(int(verified_role_id))
                if not verified_role:
                    self.logger.warning(f"Verified role with ID {verified_role_id} not found in guild")
                elif verified_role not in member.roles:
                    # Remove all tournament roles if user isn't verified
                    roles_config = self.get_setting("roles_config", {}, guild_id=member.guild.id)
                    all_managed_role_ids = [config.id for config in roles_config.values()]

                    dry_run = self.get_global_setting("dry_run", False)
                    roles_removed = 0
                    role_changes = []

                    for role in member.roles:
                        if str(role.id) in all_managed_role_ids:
                            try:
                                if not dry_run:
                                    await member.remove_roles(role, reason="User not verified for tournament roles")
                                roles_removed += 1
                                self.roles_removed += 1
                                role_changes.append(f"-{role.name}")
                                log_msg = (
                                    f"{'Would remove' if dry_run else 'Removed'} {role.name} role from {member.name} ({member.id}) - not verified"
                                )
                                self.logger.info(log_msg)
                            except Exception as e:
                                self.logger.error(f"Error removing role {role.name} from {member.name}: {e}")

                    # Return early if roles were removed
                    if role_changes:
                        log_message = f"{member.name}: {', '.join(role_changes)} (not verified)"
                        return 0, roles_removed, log_message
                    return 0, 0, None

            # Continue with normal role assignment
            # Determine the best role for this player
            best_role_id = self.core.determine_best_role(
                player_tournaments,
                self.core.get_roles_config(member.guild.id),
                self.core.get_league_hierarchy(member.guild.id),
                self.get_global_setting("debug_logging", False),
            )

            # Get all managed role IDs for comparison
            roles_config = self.get_setting("roles_config", {}, guild_id=member.guild.id)
            all_managed_role_ids = [config.id for config in roles_config.values()]

            dry_run = self.get_global_setting("dry_run", False)

            # Track changes
            roles_added = 0
            roles_removed = 0
            role_changes = []  # List of role changes for logging

            # If player qualifies for a role
            if best_role_id:
                best_role = member.guild.get_role(int(best_role_id))
                if not best_role:
                    self.logger.warning(f"Role with ID {best_role_id} not found in guild")
                    return roles_added, roles_removed, None

                # Add the role if they don't have it
                if best_role not in member.roles:
                    try:
                        if not dry_run:
                            await member.add_roles(best_role, reason="Tournament participation role update")
                        roles_added += 1
                        self.roles_assigned += 1
                        role_changes.append(f"+{best_role.name}")
                        log_msg = f"{'Would add' if dry_run else 'Added'} {best_role.name} role to {member.name} ({member.id})"
                        self.logger.info(log_msg)
                    except Exception as e:
                        self.logger.error(f"Error adding role {best_role.name} to {member.name}: {e}")

            # Remove any other tournament roles they shouldn't have
            for role in member.roles:
                if str(role.id) in all_managed_role_ids and (not best_role_id or str(role.id) != best_role_id):
                    try:
                        if not dry_run:
                            await member.remove_roles(role, reason="Tournament participation role update")
                        roles_removed += 1
                        self.roles_removed += 1
                        role_changes.append(f"-{role.name}")
                        log_msg = f"{'Would remove' if dry_run else 'Removed'} {role.name} role from {member.name} ({member.id})"
                        self.logger.info(log_msg)
                    except Exception as e:
                        self.logger.error(f"Error removing role {role.name} from {member.name}: {e}")

            # Generate log message if there were changes
            log_message = None
            if role_changes:
                log_message = f"{member.name}: {', '.join(role_changes)}"

            return roles_added, roles_removed, log_message

        finally:
            self.bot.dispatch("bot_role_update_end", member.id)

    async def start_update_with_progress(self, message, manual_update=False):
        """Start a role update with progress tracking

        Args:
            message: The Discord message to update with progress
            manual_update: Whether this is a manual update (True) or automatic (False)
        """
        # Store start time with timezone awareness
        start_time = datetime.datetime.now(datetime.timezone.utc)

        # Get total number of users to process
        discord_mapping = await self.get_discord_to_player_mapping()
        total_users = len(discord_mapping)

        # Get dry run status
        dry_run = self.get_global_setting("dry_run", False)

        # Create shared progress data
        progress_data = {
            "processed": 0,
            "total": total_users,
            "start_time": start_time,
            "message": message,
            "dry_run": dry_run,
            "last_percentage": -1,
            "completed": False,
            "error": None,
            "manual_update": manual_update,
        }

        # Store progress data where update task can access it
        self.update_progress = progress_data

        # Create background task to handle updates
        self.update_task = asyncio.create_task(self.update_all_roles())

        # Create separate task to update the progress message
        self.progress_task = asyncio.create_task(self.update_progress_message())

    async def update_progress_message(self):
        """Background task that updates the progress message"""
        if not hasattr(self, "update_progress"):
            return

        try:
            # Keep updating until the process completes
            while not self.update_progress["completed"]:
                # Update message every 3 seconds
                await self.update_progress_display()
                await asyncio.sleep(3)

            # One final update after completion
            await self.update_progress_display(final=True)
        except Exception as e:
            self.logger.error(f"Error in progress update: {e}")
        finally:
            # Clear reference
            if hasattr(self, "update_progress"):
                del self.update_progress

    async def update_progress_display(self, final=False):
        """Update the progress message with current status"""
        data = self.update_progress
        if not data:
            return

        message = data["message"]
        processed = data["processed"]
        total = data["total"]
        start_time = data["start_time"]
        dry_run = data["dry_run"]
        error = data["error"]
        manual_update = data.get("manual_update", True)  # Default to True for backwards compatibility

        # Calculate percentage
        current_percentage = int((processed / total) * 100) if total > 0 else 0

        # Only update UI on percentage changes or final update
        if final or current_percentage % 1 == 0 and current_percentage != data["last_percentage"]:
            data["last_percentage"] = current_percentage

            # Calculate timing info
            elapsed = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds()

            if final:
                if error:
                    await message.edit(content=f"❌ Error during role update: {error}")
                    return

                # Create completion embed
                duration = elapsed
                duration_str = f"{duration:.1f}"
                update_type = "Manual" if manual_update else "Automatic"
                embed = discord.Embed(
                    title=f"{update_type} Tournament Roles Updated" + (" (DRY RUN)" if dry_run else ""),
                    description=f"Successfully updated roles in {duration_str} seconds",
                    color=discord.Color.green(),
                )

                # Add stats
                embed.add_field(
                    name="Statistics",
                    value=(
                        f"**Users Processed:** {self.processed_users}\n"
                        f"**Roles Assigned:** {self.roles_assigned}\n"
                        f"**Roles Removed:** {self.roles_removed}\n"
                        f"**No Player Data:** {self.users_with_no_player_data}"
                    ),
                    inline=False,
                )

                # Add timestamp
                embed.set_footer(text=f"Completed at {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

                await message.edit(content=None, embed=embed)
            else:
                # Show progress bar during update
                if processed > 0:
                    avg_time_per_user = elapsed / processed
                    remaining_users = total - processed
                    eta_seconds = avg_time_per_user * remaining_users

                    # Format ETA
                    if eta_seconds < 60:
                        eta = f"{eta_seconds:.0f} seconds"
                    elif eta_seconds < 3600:
                        eta = f"{eta_seconds / 60:.1f} minutes"
                    else:
                        eta = f"{eta_seconds / 3600:.1f} hours"

                    progress_bar = "█" * (current_percentage // 5) + "░" * ((100 - current_percentage) // 5)
                    update_type = "Manual" if manual_update else "Automatic"
                    status = (
                        f"{update_type} {'🔍 DRY RUN: ' if dry_run else ''}Processing roles: **{processed}/{total}** users "
                        f"(**{current_percentage}%**)\n"
                        f"`{progress_bar}` \n"
                        f"⏱️ Estimated time remaining: **{eta}**"
                    )
                    await message.edit(content=status)

    async def add_log_message(self, message):
        """
        Add a message to the log buffer and potentially send it.

        Args:
            message: The log message to add
        """
        self.log_buffer.append(message)

        # Check if we should send immediately
        if self.get_setting("immediate_logging", True, guild_id=self.bot.guilds[0].id if self.bot.guilds else None):
            # Check if we've hit batch size or buffer size limit
            batch_size = self.get_global_setting("log_batch_size", 10)

            # If we've hit batch size, send it
            if len(self.log_buffer) >= batch_size:
                should_send = True
            else:
                # Check buffer size in characters
                buffer_size = sum(len(msg) + 1 for msg in self.log_buffer)  # +1 for newline

                # If buffer is getting large, send it
                if buffer_size >= self.log_buffer_max_size:
                    should_send = True
                else:
                    should_send = False

            # Send and clear buffer if needed
            if should_send:
                await self.flush_log_buffer()

    async def flush_log_buffer(self):
        """Send all accumulated log messages in the buffer"""
        if self.log_buffer:
            await self.send_role_logs_batch(self.log_buffer)
            self.log_buffer = []  # Clear the buffer after sending

    async def send_role_logs_batch(self, log_messages):
        """Send a batch of role update logs to the configured channel

        Args:
            log_messages: List of log messages to send
        """
        if not log_messages:
            return

        log_channel_id = self.get_setting("log_channel_id", guild_id=self.bot.guilds[0].id if self.bot.guilds else None)
        if not log_channel_id:
            return  # No logging channel configured

        channel = self.bot.get_channel(int(log_channel_id))
        if not channel:
            self.logger.warning(f"Could not find log channel with ID {log_channel_id}")
            return

        try:
            # Join messages with newlines, chunk if needed
            MAX_MESSAGE_LENGTH = 1950  # Discord limit is 2000, leave a small buffer for safety
            current_chunk = ""
            for msg in log_messages:
                # If adding this message would exceed limit, send current chunk and start new one
                if len(current_chunk) + len(msg) + 1 > MAX_MESSAGE_LENGTH:
                    if current_chunk:
                        await channel.send(current_chunk)
                    current_chunk = msg
                else:
                    if current_chunk:
                        current_chunk += "\n" + msg
                    else:
                        current_chunk = msg

            # Send any remaining messages
            if current_chunk:
                await channel.send(current_chunk)
        except Exception as e:
            self.logger.error(f"Error sending role log batch: {e}")

    async def cog_initialize(self) -> None:
        """Initialize the TourneyRoles cog."""
        self.logger.info("Initializing TourneyRoles cog")
        try:
            self.logger.info("Starting TourneyRoles initialization")

            async with self.task_tracker.task_context("Initialization") as tracker:
                # Register UI extensions for player profiles
                self.register_ui_extensions()

                # Set cache file path
                self.cache_file = self.data_directory / self.roles_cache_filename

                # 1. Verify settings
                self.logger.debug("Loading settings")
                tracker.update_status("Verifying settings")
                await self._load_settings()

                # 2. Load saved data
                self.logger.debug("Loading saved data")
                tracker.update_status("Loading saved data")
                if await self.load_data():
                    self.logger.info("Loaded saved tournament role data")
                else:
                    self.logger.info("No saved tournament role data found, using defaults")

                # 3. Start the update task
                self.logger.debug("Starting update task")
                tracker.update_status("Starting update task")
                self.update_task = self.bot.loop.create_task(self.schedule_periodic_updates())

                # 4. Mark as ready and complete initialization
                self.set_ready(True)
                self.logger.info("TourneyRoles initialization complete")

        except Exception as e:
            self.logger.error(f"Error during TourneyRoles initialization: {e}", exc_info=True)
            self._has_errors = True
            raise

    def register_ui_extensions(self) -> None:
        """Register UI extensions that this cog provides to other cogs."""
        # Register button provider for player profiles
        self.bot.cog_manager.register_ui_extension(
            target_cog="player_lookup", source_cog=self.__class__.__name__, provider_func=self.get_tourney_roles_button_for_player
        )

    def _user_can_refresh_roles(self, user: discord.User, guild_id: int) -> bool:
        """Check if a user has permission to refresh tournament roles for others.

        Args:
            user: The Discord user to check
            guild_id: The guild ID to check permissions in

        Returns:
            True if user has an authorized role, False otherwise
        """
        # Get authorized role IDs from settings
        authorized_role_ids = self.get_setting("authorized_refresh_roles", guild_id=guild_id, default=[])

        if not authorized_role_ids:
            # No roles configured - deny access
            return False

        # Get the guild and member
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return False

        member = guild.get_member(user.id)
        if not member:
            return False

        # Check if user has any of the authorized roles
        user_role_ids = {role.id for role in member.roles}
        return bool(user_role_ids.intersection(set(authorized_role_ids)))

    def get_tourney_roles_button_for_player(self, player, requesting_user: discord.User, guild_id: int) -> Optional[discord.ui.Button]:
        """Get a tournament roles refresh button for a player if the user has permission.

        This method is called by the player_lookup cog to extend /lookup functionality.
        Returns a button that refreshes tournament roles for the player,
        or None if the user doesn't have permission or the cog isn't enabled.
        """
        # Check if this cog is enabled for the guild
        if not self.bot.cog_manager.can_guild_use_cog(self.cog_name, guild_id, False):
            return None

        # Only show button if the player has a Discord ID
        if not player.discord_id:
            return None

        # Check if requesting user has permission to refresh roles
        if not self._user_can_refresh_roles(requesting_user, guild_id):
            return None

        # Use the player's Discord ID (the person being looked up), not the requesting user's ID
        return TourneyRolesRefreshButton(self, int(player.discord_id), guild_id, requesting_user.id)

    async def cog_unload(self):
        """Clean up when cog is unloaded"""
        if self.update_task:
            self.update_task.cancel()
        await super().cog_unload()
        self.logger.info("Tournament roles cog unloaded")

    @discord.ext.commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Monitor role changes and correct tournament role issues.

        Also monitors verified role changes to immediately apply/remove tournament roles.
        """
        try:
            # Only process if this cog is enabled for the guild
            if not self.bot.cog_manager.can_guild_use_cog(self.cog_name, after.guild.id, False):
                return

            # Check if verified role changed
            verified_role_id = self.core.get_verified_role_id(after.guild.id)
            if verified_role_id:
                verified_role_id_int = int(verified_role_id)
                before_has_verified = any(role.id == verified_role_id_int for role in before.roles)
                after_has_verified = any(role.id == verified_role_id_int for role in after.roles)

                # If verified role was added or removed, refresh tournament roles immediately
                if before_has_verified != after_has_verified:
                    if after_has_verified:
                        self.logger.info(f"Verified role added to {after.name} ({after.id}) - applying tournament roles")
                        await self.add_log_message(f"✅ {after.name} verified - checking tournament roles")
                    else:
                        self.logger.info(f"Verified role removed from {after.name} ({after.id}) - removing tournament roles")
                        await self.add_log_message(f"❌ {after.name} unverified - removing tournament roles")

                    # Trigger immediate role refresh
                    try:
                        result = await self.refresh_user_roles_for_user(after.id, after.guild.id)
                        self.logger.debug(f"Verification role change refresh result: {result}")
                    except Exception as e:
                        self.logger.error(f"Error refreshing roles after verification change for {after.name}: {e}")

                    # Don't process tournament role corrections below - we just refreshed everything
                    return

            # Check if tournament roles changed
            roles_config = self.core.get_roles_config(after.guild.id)
            managed_role_ids = {config.id for config in roles_config.values()}

            before_tourney_roles = {role.id for role in before.roles if str(role.id) in managed_role_ids}
            after_tourney_roles = {role.id for role in after.roles if str(role.id) in managed_role_ids}

            # If tournament roles changed
            if before_tourney_roles != after_tourney_roles:
                self.logger.info(f"Tournament role change detected for {after.name} ({after.id})")

                # Check if user should have their cached role
                cached_role_id = self.role_cache.get(after.guild.id, {}).get(str(after.id))

                if cached_role_id:
                    # User should have this specific role
                    if cached_role_id not in after_tourney_roles:
                        # Role was removed, add it back
                        role = after.guild.get_role(int(cached_role_id))
                        if role:
                            await after.add_roles(role, reason="Correcting tournament role removal")
                            self.logger.info(f"Restored tournament role {role.name} to {after.name}")
                            await self.add_log_message(f"🔧 Corrected: Restored {role.name} to {after.name}")
                    elif len(after_tourney_roles) > 1:
                        # User has multiple tournament roles, remove extras
                        roles_to_remove = []
                        for role_id in after_tourney_roles:
                            if role_id != cached_role_id:
                                role = after.guild.get_role(role_id)
                                if role:
                                    roles_to_remove.append(role)

                        if roles_to_remove:
                            await after.remove_roles(*roles_to_remove, reason="Removing extra tournament roles")
                            removed_names = [role.name for role in roles_to_remove]
                            self.logger.info(f"Removed extra tournament roles {removed_names} from {after.name}")
                            await self.add_log_message(f"🔧 Corrected: Removed extra roles {', '.join(removed_names)} from {after.name}")

        except Exception as e:
            self.logger.error(f"Error in on_member_update: {e}")

    async def refresh_user_roles_for_user(self, user_id: int, guild_id: int) -> str:
        """Public method for other cogs to refresh tournament roles for a specific user.

        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID

        Returns:
            str: Status message describing the result
        """
        try:
            # Get the guild and member
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return "❌ Guild not found"

            member = guild.get_member(user_id)
            if not member:
                return "❌ User not found in server"

            # Get required cogs
            known_players_cog = await self.get_known_players_cog()
            if not known_players_cog:
                return "❌ Player Lookup system unavailable"

            tourney_stats_cog = await self.get_tourney_stats_cog()
            if not tourney_stats_cog:
                return "❌ Tournament Stats system unavailable"

            # Get user's player data
            discord_mapping = await self.get_discord_to_player_mapping()
            player_data = discord_mapping.get(str(user_id))
            if not player_data:
                return "❌ No player data found. Use `/player register` to link your account."

            # Get tournament participation data
            player_stats = await self.core.get_player_tournament_stats(tourney_stats_cog, player_data.get("all_ids", []))

            # Update latest tournament date tracking
            if player_stats.latest_tournament and player_stats.latest_tournament.get("date"):
                tourney_date = player_stats.latest_tournament["date"]
                if isinstance(tourney_date, str):
                    tourney_date = datetime.datetime.fromisoformat(tourney_date.replace("Z", "+00:00"))
                if not self.cache_latest_tourney_date or tourney_date > self.cache_latest_tourney_date:
                    self.cache_latest_tourney_date = tourney_date
                    self.logger.debug(f"Updated latest tournament date to {tourney_date}")

            # Get roles config and settings
            roles_config = self.core.get_roles_config(guild_id)
            verified_role_id = self.core.get_verified_role_id(guild_id)
            dry_run = self.core.is_dry_run_enabled(guild_id)

            # Update member's roles using the core method
            result = await self.core.update_member_roles(member, player_stats, roles_config, verified_role_id, dry_run)

            # Update cache
            best_role_id = self.core.determine_best_role(
                player_stats,
                roles_config,
                self.core.get_league_hierarchy(guild_id),
                self.get_global_setting("debug_logging", False),
            )
            if guild_id not in self.role_cache:
                self.role_cache[guild_id] = {}
            self.role_cache[guild_id][str(user_id)] = best_role_id
            self.cache_timestamp = datetime.datetime.now(datetime.timezone.utc)

            # Create response message
            if dry_run:
                if result.roles_added > 0 or result.roles_removed > 0:
                    changes = []
                    if result.roles_added > 0:
                        changes.append(f"would add {result.roles_added} role(s)")
                    if result.roles_removed > 0:
                        changes.append(f"would remove {result.roles_removed} role(s)")
                    return f"🔍 DRY RUN: {', '.join(changes)}"
                else:
                    return "🔍 DRY RUN: No role changes needed"
            else:
                if result.roles_added > 0 or result.roles_removed > 0:
                    changes = []
                    if result.roles_added > 0:
                        changes.append(f"added {result.roles_added} role(s)")
                    if result.roles_removed > 0:
                        changes.append(f"removed {result.roles_removed} role(s)")
                    return f"✅ {', '.join(changes)}"
                else:
                    return "✅ No role changes needed"

        except Exception as e:
            self.logger.error(f"Error refreshing roles for user {user_id}: {e}")
            return f"❌ Error updating roles: {str(e)}"


class TourneyRolesRefreshButton(discord.ui.Button):
    """Button to refresh tournament roles for a specific user."""

    def __init__(self, cog, user_id: int, guild_id: int, requesting_user_id: int):
        super().__init__(label="Update Tournament Roles", style=discord.ButtonStyle.primary, emoji="🔄")
        self.cog = cog
        self.user_id = user_id
        self.guild_id = guild_id
        self.requesting_user_id = requesting_user_id

    async def callback(self, interaction: discord.Interaction):
        """Button to refresh tournament roles."""
        await interaction.response.defer(ephemeral=True)

        try:
            # Double-check permissions (defense in depth)
            if not self.cog._user_can_refresh_roles(interaction.user, self.guild_id):
                await interaction.followup.send("❌ You don't have permission to refresh tournament roles.", ephemeral=True)
                return

            # Call the public method to refresh roles
            result = await self.cog.refresh_user_roles_for_user(self.user_id, self.guild_id)

            # Send the result
            await interaction.followup.send(result, ephemeral=True)

        except Exception as e:
            self.cog.logger.error(f"Error refreshing tournament roles for user {self.user_id}: {e}")
            await interaction.followup.send(f"❌ Error updating roles: {str(e)}", ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(TourneyRoles(bot))
