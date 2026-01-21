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

        # Initialize per-guild log buffers for proper context
        self.log_buffers = {}  # {guild_id: [messages]}
        self.log_buffer_max_size = 8000  # Characters before forcing flush

        # Track members currently being updated to prevent duplicate logging from on_member_update
        # This includes manual updates, bulk updates, and role corrections
        self.updating_members = set()  # Set of (guild_id, user_id) tuples

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
            "pause": False,  # Global pause - bot owner can pause all role updates
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
            "authorized_refresh_groups": [],  # List of Django group names that can refresh tournament roles for others
        }

        # Hardcoded cache filename (not configurable)
        self.roles_cache_filename = "tourney_roles.json"

    async def save_data(self) -> bool:
        """Save tournament role data using BaseCog's utility."""
        try:
            # Collect roles_config from all guilds
            roles_config = {}
            for guild in self.bot.guilds:
                guild_roles_config = self.get_setting("roles_config", {}, guild_id=guild.id)
                if guild_roles_config:
                    roles_config[str(guild.id)] = guild_roles_config

            # Prepare serializable data
            save_data = {
                "roles_config": roles_config,
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

                # Load role cache - convert guild IDs from strings to integers
                raw_cache = save_data.get("role_cache", {})
                self.role_cache = {int(guild_id): users for guild_id, users in raw_cache.items()}

                self.cache_timestamp = datetime.datetime.fromisoformat(save_data["cache_timestamp"]) if save_data.get("cache_timestamp") else None
                self.cache_latest_tourney_date = (
                    datetime.datetime.fromisoformat(save_data["cache_latest_tourney_date"]) if save_data.get("cache_latest_tourney_date") else None
                )

                # Log cache loading details
                total_guilds = len(self.role_cache)
                total_users = sum(len(users) for users in self.role_cache.values())
                self.logger.info(
                    f"Loaded tournament role data - last_full_update: {self.last_full_update}, "
                    f"cache_latest_tourney_date: {self.cache_latest_tourney_date}, "
                    f"guilds in cache: {total_guilds}, total users: {total_users}"
                )
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

    async def _check_tournament_data_on_startup(self) -> None:
        """Check for newer tournament data on startup to catch any missed events.

        This ensures we don't miss tournament data updates that happened while
        the bot was offline or during restarts. Uses TourneyStats cog as the
        source of truth for tournament dates.
        """
        try:
            self.logger.info("Checking for tournament data updates on startup")

            # Get the TourneyStats cog
            tourney_stats_cog = await self.get_tourney_stats_cog()
            if not tourney_stats_cog:
                self.logger.warning("TourneyStats cog not available for startup check")
                return

            # Wait for TourneyStats to be ready
            if not tourney_stats_cog.is_ready:
                self.logger.info("Waiting for TourneyStats to be ready...")
                ready = await tourney_stats_cog.wait_until_ready(timeout=30)
                if not ready:
                    self.logger.warning("TourneyStats cog not ready within timeout, skipping startup check")
                    return

            # Get the latest tournament date from TourneyStats
            latest_tourney_date = tourney_stats_cog.latest_tournament_date

            if not latest_tourney_date:
                self.logger.info("No tournament data loaded in TourneyStats yet")
                return

            # Normalize both to dates for comparison (ignore time component)
            if isinstance(latest_tourney_date, datetime.datetime):
                latest_date = latest_tourney_date.date()
            else:
                latest_date = latest_tourney_date

            # Extract date from cached datetime
            cached_date = self.cache_latest_tourney_date
            if cached_date:
                if isinstance(cached_date, datetime.datetime):
                    cached_date = cached_date.date()

            # Compare dates only
            if cached_date is None:
                # No cache, we'll need to calculate on first update
                self.logger.info(f"No cached tournament date, will calculate on first update (TourneyStats has: {latest_date})")
            elif latest_date > cached_date:
                # TourneyStats has newer data
                self.logger.info(f"Newer tournament data found on startup: {latest_date} > {cached_date}")
                self.logger.info("Invalidating cache and triggering recalculation")

                # Invalidate cache
                self.cache_latest_tourney_date = None
                self.cache_timestamp = None

                # Trigger recalculation (calculation phase only)
                # Check global pause setting first
                if self.get_global_setting("pause", False):
                    self.logger.info("Role updates are globally paused, skipping startup recalculation")
                else:
                    calc_success = await self.calculate_all_roles()
                if calc_success:
                    self.logger.info("Startup role recalculation completed successfully")
                    self.mark_data_modified()
                    await self.save_data()
                else:
                    self.logger.warning("Startup role recalculation failed")
            else:
                self.logger.info(f"Cache is current (latest: {self.cache_latest_tourney_date})")

        except Exception as e:
            self.logger.error(f"Error checking tournament data on startup: {e}", exc_info=True)
            # Don't raise - this is a non-critical check

    async def is_cache_valid_with_tourney_check(self, guild_id: int) -> bool:
        """Check if cache is valid, including checking for newer tournament data."""
        if not self.is_cache_valid(guild_id):
            return False

        # Check if there's newer tournament data
        try:
            latest_tourney_date = await self.get_latest_tournament_date()
            if latest_tourney_date and self.cache_latest_tourney_date:
                # Compare only dates, not times, since tournaments are based on UTC date
                latest_date = latest_tourney_date.date() if isinstance(latest_tourney_date, datetime.datetime) else latest_tourney_date
                cache_date = (
                    self.cache_latest_tourney_date.date()
                    if isinstance(self.cache_latest_tourney_date, datetime.datetime)
                    else self.cache_latest_tourney_date
                )
                if latest_date > cache_date:
                    self.logger.info(f"Cache invalidated: New tournament data available ({latest_date} > {cache_date})")
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

    async def get_discord_to_player_mapping(self, discord_id: str = None):
        """Get mapping of Discord IDs to player information from PlayerLookup

        Args:
            discord_id: Optional Discord ID to get data for a single user.
                       If None, returns mapping for all users.

        Returns:
            Dict mapping Discord IDs to player information dictionaries.
        """
        known_players_cog = await self.get_known_players_cog()
        if not known_players_cog:
            self.logger.error("Failed to get PlayerLookup cog")
            return {}

        try:
            # Wait for PlayerLookup to be ready
            if not known_players_cog.is_ready:
                self.logger.info("Waiting for PlayerLookup to be ready...")
                await known_players_cog.wait_until_ready()

            # Get the mapping (pass through discord_id for single-user lookups)
            mapping = await known_players_cog.get_discord_to_player_mapping(discord_id=discord_id)

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

    async def calculate_roles_for_users(
        self,
        user_ids: Optional[list] = None,
        guild_id: int = None,
        discord_to_player: Optional[dict] = None,
        progress_callback: Optional[object] = None,
    ) -> dict:
        """
        Calculate tournament roles and update cache.

        Args:
            user_ids: List of user IDs to calculate for, or None for all users
            guild_id: Guild to calculate roles for
            discord_to_player: Pre-fetched player mapping (optional, will fetch if None)
            progress_callback: Optional async callback(current, total) for progress

        Returns:
            dict: {
                "calculated": int,
                "skipped": int,
                "latest_tourney_date": datetime or None
            }
        """
        # 1. Fetch discord_to_player if not provided
        if discord_to_player is None:
            discord_to_player = await self.get_discord_to_player_mapping()
            if not discord_to_player:
                self.logger.error("Failed to get player mapping for role calculation")
                return {"calculated": 0, "skipped": 0, "latest_tourney_date": None}

        # 2. Get guild and configuration
        guild = self.bot.get_guild(guild_id)
        if not guild:
            self.logger.error(f"Guild {guild_id} not found")
            return {"calculated": 0, "skipped": 0, "latest_tourney_date": None}

        roles_config = self.core.get_roles_config(guild_id)
        league_hierarchy = self.core.get_league_hierarchy(guild_id)
        debug_logging = self.get_global_setting("debug_logging", False)

        # 3. Get tourney stats cog for player data
        tourney_stats_cog = await self.get_tourney_stats_cog()
        if not tourney_stats_cog:
            self.logger.error("TourneyStats cog not available")
            return {"calculated": 0, "skipped": 0, "latest_tourney_date": None}

        # 4. Determine which users to process
        if user_ids is None:
            # Bulk mode: all users in discord_to_player
            users_to_process = list(discord_to_player.keys())
        else:
            # Single user mode: just specified users
            users_to_process = [str(uid) for uid in user_ids]

        # 5. Pre-fetch all tournament stats (for bulk mode efficiency)
        loop_start_time = datetime.datetime.now(datetime.timezone.utc)
        self.logger.info(f"[LOOP START] calculate_roles_for_users: Building stats lookup for {len(users_to_process)} users")

        stats_lookup = await self.core.build_batch_player_stats(tourney_stats_cog, discord_to_player)

        lookup_duration = (datetime.datetime.now(datetime.timezone.utc) - loop_start_time).total_seconds()
        self.logger.info(f"Stats lookup built in {lookup_duration:.1f}s for {len(stats_lookup)} users")

        # 6. Calculate roles for each user
        calculated = 0
        skipped = 0
        latest_tourney_date = None

        # Initialize cache for guild if needed
        if guild_id not in self.role_cache:
            self.role_cache[guild_id] = {}

        total_users = len(users_to_process)
        calc_start_time = datetime.datetime.now(datetime.timezone.utc)

        for idx, discord_id in enumerate(users_to_process):
            # Get player stats
            player_stats = stats_lookup.get(discord_id)
            if not player_stats:
                skipped += 1
                continue

            # Track latest tournament date
            if player_stats.latest_tournament and player_stats.latest_tournament.get("date"):
                tourney_date = player_stats.latest_tournament["date"]
                # Convert to datetime if needed
                if isinstance(tourney_date, str):
                    tourney_date = datetime.datetime.fromisoformat(tourney_date.replace("Z", "+00:00"))
                if latest_tourney_date is None or tourney_date > latest_tourney_date:
                    latest_tourney_date = tourney_date

            # Determine best role
            best_role_id = self.core.determine_best_role(player_stats, roles_config, league_hierarchy, debug_logging)

            # Update cache
            self.role_cache[guild_id][discord_id] = best_role_id
            calculated += 1

            # Report progress
            if progress_callback:
                await progress_callback(idx + 1, total_users)

            # Yield control
            await asyncio.sleep(0)

        # 7. Update global cache metadata
        self.cache_timestamp = datetime.datetime.now(datetime.timezone.utc)
        if latest_tourney_date:
            self.cache_latest_tourney_date = latest_tourney_date

        calc_duration = (datetime.datetime.now(datetime.timezone.utc) - calc_start_time).total_seconds()
        rate = calculated / calc_duration if calc_duration > 0 else 0
        self.logger.info(
            f"[LOOP END] calculate_roles_for_users: Calculated {calculated} roles (skipped {skipped}) in {calc_duration:.1f}s ({rate:.1f} users/sec)"
        )

        return {"calculated": calculated, "skipped": skipped, "latest_tourney_date": latest_tourney_date}

    async def apply_roles_for_users(self, user_ids: Optional[list] = None, guild_id: int = None, progress_callback: Optional[object] = None) -> dict:
        """
        Apply pre-calculated tournament roles from cache.

        Args:
            user_ids: List of user IDs to apply roles for, or None for all cached users
            guild_id: Guild to apply roles in
            progress_callback: Optional async callback(current, total) for progress

        Returns:
            dict: {
                "processed": int,
                "roles_added": int,
                "roles_removed": int,
                "errors": int,
                "skipped_no_cache": int,
                "skipped_not_verified": int
            }
        """
        # 1. Get guild and configuration
        guild = self.bot.get_guild(guild_id)
        if not guild:
            self.logger.error(f"Guild {guild_id} not found")
            return {"error": "Guild not found"}

        # Check if this guild has paused role updates
        if self.get_setting("pause", default=False, guild_id=guild_id):
            self.logger.info(f"Role updates are paused for guild {guild.name}, skipping")
            return {
                "processed": 0,
                "roles_added": 0,
                "roles_removed": 0,
                "errors": 0,
                "skipped_no_cache": 0,
                "skipped_not_verified": 0,
                "not_in_guild": 0,
            }

        roles_config = self.core.get_roles_config(guild_id)
        all_managed_role_ids = set(config.id for config in roles_config.values())
        verified_role_id = self.core.get_verified_role_id(guild_id)
        dry_run = self.get_global_setting("dry_run", False)

        # 2. Determine which users to process
        if user_ids is None:
            # Bulk mode: all users in cache for this guild
            cached_users = self.role_cache.get(guild_id, {})
            users_to_process = list(cached_users.keys())
            is_single_user_mode = False
        else:
            # Single user mode
            users_to_process = [str(uid) for uid in user_ids]
            is_single_user_mode = True

        # 3. Stats tracking
        stats = {
            "processed": 0,
            "roles_added": 0,
            "roles_removed": 0,
            "errors": 0,
            "skipped_no_cache": 0,
            "skipped_not_verified": 0,
            "not_in_guild": 0,
        }

        total_cache_size = len(self.role_cache.get(guild_id, {}))
        total_users = len(users_to_process)
        loop_start_time = datetime.datetime.now(datetime.timezone.utc)
        self.logger.info(f"[LOOP START] apply_roles_for_users: Processing {total_users} users from role_cache for guild {guild.name}")

        # 4. Process each user
        for idx, discord_id_str in enumerate(users_to_process):
            discord_id = int(discord_id_str)
            member = guild.get_member(discord_id)

            if not member:
                stats["not_in_guild"] += 1
                continue

            # Get calculated role from cache
            calculated_role_id = self.role_cache.get(guild_id, {}).get(discord_id_str)

            # Handle cache miss
            if calculated_role_id is None:
                if is_single_user_mode:
                    # Single user - try to calculate now with single-user player mapping
                    self.logger.warning(f"Cache miss for user {discord_id} in single-user mode, calculating...")

                    # Fetch player mapping for just this user to avoid rebuilding stats for all users
                    single_user_mapping = await self.get_discord_to_player_mapping(discord_id=discord_id_str)

                    if not single_user_mapping:
                        self.logger.info(f"User {discord_id} has no player data - skipping role calculation")
                        stats["skipped_no_cache"] += 1
                        stats["errors"] += 1
                        continue

                    calc_result = await self.calculate_roles_for_users([discord_id], guild_id, discord_to_player=single_user_mapping)

                    if calc_result["calculated"] == 0:
                        self.logger.info(f"No role calculated for user {discord_id} (player data may be incomplete)")
                        stats["skipped_no_cache"] += 1
                        stats["errors"] += 1
                        continue

                    calculated_role_id = self.role_cache.get(guild_id, {}).get(discord_id_str)
                    if calculated_role_id is None:
                        stats["skipped_no_cache"] += 1
                        stats["errors"] += 1
                        continue
                else:
                    # Bulk mode - skip silently (expected for users without player data)
                    self.logger.debug(f"Skipping user {discord_id} - no calculated role in cache")
                    stats["skipped_no_cache"] += 1
                    continue

            # Check verification requirement
            if verified_role_id:
                verified_role = guild.get_role(int(verified_role_id))
                if verified_role and verified_role not in member.roles:
                    # User not verified - remove all tournament roles
                    current_tourney_roles = [role for role in member.roles if str(role.id) in all_managed_role_ids]

                    if current_tourney_roles:
                        # Build new role list without tournament roles
                        new_roles = [role for role in member.roles if str(role.id) not in all_managed_role_ids and not role.is_default()]

                        member_key = (guild_id, member.id)
                        self.updating_members.add(member_key)
                        try:
                            changes = []
                            if not dry_run:
                                await member.edit(roles=new_roles, reason="Removing tournament roles - not verified")

                            for role in current_tourney_roles:
                                changes.append(f"-{role.name}")
                                stats["roles_removed"] += 1
                                # Dispatch custom event for role removal
                                self.bot.dispatch("tourney_role_removed", member, role)

                            if changes:
                                await self.log_role_change(guild_id, member.name, changes, immediate=is_single_user_mode)
                        except Exception as e:
                            self.logger.error(f"Error removing roles from {member.name}: {e}")
                            stats["errors"] += 1
                        finally:
                            # Delay removal to allow Discord's on_member_update event to fire and be ignored
                            async def delayed_removal():
                                await asyncio.sleep(0.5)
                                self.updating_members.discard(member_key)

                            asyncio.create_task(delayed_removal())

                    stats["skipped_not_verified"] += 1
                    stats["processed"] += 1
                    continue

            # Determine what changes are needed
            current_tourney_roles = {str(role.id): role for role in member.roles if str(role.id) in all_managed_role_ids}

            changes = []

            # Build new role list atomically
            new_roles = [role for role in member.roles if str(role.id) not in all_managed_role_ids and not role.is_default()]

            # Add calculated role if they should have one
            if calculated_role_id:
                role = guild.get_role(int(calculated_role_id))
                if role:
                    new_roles.append(role)
                    if calculated_role_id not in current_tourney_roles:
                        changes.append(f"+{role.name}")
                        stats["roles_added"] += 1

            # Track removed roles
            for role_id, role in current_tourney_roles.items():
                if calculated_role_id != role_id:
                    changes.append(f"-{role.name}")
                    stats["roles_removed"] += 1

            # Apply changes if any
            if changes:
                member_key = (guild_id, member.id)
                self.updating_members.add(member_key)
                try:
                    if not dry_run:
                        await member.edit(roles=new_roles, reason="Tournament participation role update")

                    # Dispatch custom events for individual role changes
                    for change in changes:
                        if change.startswith("+"):
                            role_name = change[1:]  # Remove the + prefix
                            # Find the role object that was added
                            added_role = None
                            for role in new_roles:
                                if role.name == role_name and str(role.id) in all_managed_role_ids:
                                    added_role = role
                                    break
                            if added_role:
                                self.bot.dispatch("tourney_role_added", member, added_role)
                        elif change.startswith("-"):
                            role_name = change[1:]  # Remove the - prefix
                            # Find the role object that was removed
                            removed_role = None
                            for role_id, role in current_tourney_roles.items():
                                if role.name == role_name:
                                    removed_role = role
                                    break
                            if removed_role:
                                self.bot.dispatch("tourney_role_removed", member, removed_role)

                    # Log changes
                    await self.log_role_change(guild_id, member.name, changes, immediate=is_single_user_mode)
                except Exception as e:
                    self.logger.error(f"Error updating roles for {member.name}: {e}")
                    stats["errors"] += 1
                finally:
                    # Delay removal to allow Discord's on_member_update event to fire and be ignored
                    # Discord's gateway can take a moment to process the role change and trigger the event
                    async def delayed_removal():
                        await asyncio.sleep(0.5)  # 500ms delay
                        self.updating_members.discard(member_key)

                    asyncio.create_task(delayed_removal())

            stats["processed"] += 1

            # Report progress
            if progress_callback:
                await progress_callback(idx + 1, total_users)

            # Yield control
            await asyncio.sleep(0)

        # Flush logs for bulk mode
        if not is_single_user_mode:
            await self.flush_log_buffer(guild_id)

        loop_duration = (datetime.datetime.now(datetime.timezone.utc) - loop_start_time).total_seconds()
        rate = stats["processed"] / loop_duration if loop_duration > 0 else 0

        # Log comprehensive statistics
        self.logger.info(
            f"[LOOP END] apply_roles_for_users: Completed in {loop_duration:.1f}s ({rate:.1f} users/sec)\n"
            f"  Guild: {guild.name} ({guild.id})\n"
            f"  Total users in role_cache: {total_cache_size}\n"
            f"  Users being processed: {total_users}\n"
            f"  Users not in guild: {stats['not_in_guild']}\n"
            f"  Users processed: {stats['processed']}\n"
            f"  Roles added: {stats['roles_added']}\n"
            f"  Roles removed: {stats['roles_removed']}\n"
            f"  Skipped (not verified): {stats['skipped_not_verified']}\n"
            f"  Skipped (no cache): {stats['skipped_no_cache']}\n"
            f"  Errors: {stats['errors']}"
        )

        return stats

    async def update_all_roles(self):
        """Update roles for all users across all enabled guilds using separated calculation and application phases"""
        if self.currently_updating:
            self.logger.warning("Role update already in progress, skipping")
            return

        # Check global pause setting (bot owner control)
        if self.get_global_setting("pause", False):
            self.logger.info("Role updates are globally paused. Skipping update.")
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
                # Send error to all enabled guilds
                for guild in self.bot.guilds:
                    if self.bot.cog_manager.can_guild_use_cog(self.cog_name, guild.id, False):
                        await self.add_log_message(f"❌ Error during role update: {e}", guild_id=guild.id)
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
            start_time = datetime.datetime.now(datetime.timezone.utc)
            calculation_message = None

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

                # Process each enabled guild for calculation using unified method
                total_calculated = 0
                for guild in enabled_guilds:
                    self.logger.info(f"Calculating roles for guild: {guild.name} (ID: {guild.id})")

                    # Check if we need to recalculate roles or can use cache
                    if not await self.is_cache_valid_with_tourney_check(guild.id):
                        self.logger.info(f"Cache invalid for guild {guild.id}, recalculating roles")
                        calc_result = await self.calculate_roles_for_users(
                            user_ids=None, guild_id=guild.id, discord_to_player=discord_to_player, progress_callback=None
                        )
                        total_calculated += calc_result["calculated"]
                    else:
                        self.logger.info(f"Using cached roles for guild {guild.id}")
                        cached_users = self.role_cache.get(guild.id, {})
                        total_calculated += len(cached_users)

                    # Store guild roles in calculated_roles for backward compatibility
                    self.calculated_roles[guild.id] = self.role_cache.get(guild.id, {})

                self.calculation_complete = True
                self.logger.info("Role calculation phase completed successfully")

                # Update the calculation message with completion status
                if calculation_message:
                    try:
                        duration = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds()
                        await calculation_message.edit(
                            content=f"✅ Tournament role calculation completed in {duration:.1f}s ({total_calculated} users processed)"
                        )
                    except Exception as e:
                        self.logger.error(f"Error updating calculation message: {e}")

                return True

            except Exception as e:
                self.logger.error(f"Error during role calculation: {e}")

                # Update message with error status
                if calculation_message:
                    try:
                        duration = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds()
                        await calculation_message.edit(content=f"❌ Tournament role calculation failed after {duration:.1f}s: {str(e)}")
                    except Exception as edit_error:
                        self.logger.error(f"Error updating calculation error message: {edit_error}")

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

                # Get enabled guilds for this cog
                enabled_guilds = []
                for guild in self.bot.guilds:
                    try:
                        if self.bot.cog_manager.can_guild_use_cog(self.cog_name, guild.id, False):
                            enabled_guilds.append(guild)
                    except Exception as e:
                        self.logger.debug(f"Error checking cog enablement for guild {guild.id}: {e}")

                # Process each enabled guild for role application using unified method
                for guild in enabled_guilds:
                    self.logger.info(f"Applying roles for guild: {guild.name} (ID: {guild.id})")

                    # Apply roles using unified method
                    apply_result = await self.apply_roles_for_users(user_ids=None, guild_id=guild.id, progress_callback=None)

                    # Update stats
                    self.processed_users += apply_result["processed"]
                    self.roles_assigned += apply_result["roles_added"]
                    self.roles_removed += apply_result["roles_removed"]

                # Log completion to console only (embed shows this to users)
                if dry_run:
                    self.logger.info("Dry run role application completed")
                else:
                    self.logger.info("Role application completed")

                self.logger.info(
                    f"Application Stats: Processed {self.processed_users} users, "
                    f"{self.roles_assigned} roles assigned, {self.roles_removed} roles removed"
                )

                # Note: Completion status and stats are shown in the embed via update_progress_message
                # No need to send duplicate text messages to the log channel

                return True

            except Exception as e:
                self.logger.error(f"Error during role application: {e}")
                # Send error to all enabled guilds
                for guild in self.bot.guilds:
                    if self.bot.cog_manager.can_guild_use_cog(self.cog_name, guild.id, False):
                        await self.add_log_message(f"❌ Error during role application: {e}", guild_id=guild.id)
                await self.flush_log_buffer()
                return False

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
        manual_update = data.get("manual_update", True)

        # Calculate percentage
        current_percentage = int((processed / total) * 100) if total > 0 else 0

        # Calculate timing info
        elapsed = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds()

        # Update every time during progress (not just on percentage change) to show live updates
        if not final:
            # Calculate processing rate and ETA
            rate = processed / elapsed if elapsed > 0 and processed > 0 else 0
            remaining = total - processed
            eta_seconds = remaining / rate if rate > 0 else 0

            # Format ETA
            if eta_seconds > 3600:
                eta_str = f"{eta_seconds / 3600:.1f} hours"
            elif eta_seconds > 60:
                eta_str = f"{eta_seconds / 60:.1f} minutes"
            else:
                eta_str = f"{eta_seconds:.0f} seconds"

            # Create progress bar (20 characters)
            filled = int(current_percentage / 5)  # 5% per block
            progress_bar = "█" * filled + "░" * (20 - filled)

            # Create embed
            update_type = "Manual" if manual_update else "Automatic"
            title = f"{update_type} Tournament Role Update" + (" (DRY RUN)" if dry_run else "")
            embed = discord.Embed(
                title=title,
                description=f"Calculating roles for {total:,} users",
                color=discord.Color.blue(),
            )

            embed.add_field(
                name="Progress",
                value=f"{progress_bar} {current_percentage}%\n**{processed:,}** / **{total:,}** users",
                inline=False,
            )

            embed.add_field(
                name="⏱️ Processing Rate",
                value=f"{rate:.1f} users/sec",
                inline=True,
            )

            embed.add_field(
                name="🕐 Estimated Time Remaining",
                value=eta_str,
                inline=True,
            )

            try:
                await message.edit(content=None, embed=embed)
            except Exception as e:
                self.logger.error(f"Error updating progress embed: {e}")

        elif final:
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

    async def log_role_change(self, guild_id: int, username: str, changes: list, immediate: bool = False):
        """
        Unified logging function for all role changes.

        Args:
            guild_id: The guild where the role change occurred
            username: The Discord username
            changes: List of changes in format ['+RoleName', '-OtherRole']
            immediate: If True, flush immediately (for individual changes). If False, buffer (for bulk updates)
        """
        if not changes:
            return

        # Format the log message consistently
        message = f"{username}: {', '.join(changes)}"

        # Initialize guild buffer if needed
        if guild_id not in self.log_buffers:
            self.log_buffers[guild_id] = []

        # Add to guild-specific buffer
        self.log_buffers[guild_id].append(message)

        # Determine if we should flush
        should_flush = immediate

        if not immediate:
            # Check if we've hit batch size or buffer size limit
            batch_size = self.get_global_setting("log_batch_size", 10)

            if len(self.log_buffers[guild_id]) >= batch_size:
                should_flush = True
            else:
                # Check buffer size in characters
                buffer_size = sum(len(msg) + 1 for msg in self.log_buffers[guild_id])  # +1 for newline
                if buffer_size >= self.log_buffer_max_size:
                    should_flush = True

        # Flush if needed
        if should_flush:
            await self.flush_log_buffer(guild_id)

    async def add_log_message(self, message: str, guild_id: int = None):
        """
        Legacy method for non-role-change log messages (status updates, errors, etc).

        Args:
            message: The log message to add
            guild_id: The guild ID (if None, uses first guild - only for backwards compatibility)
        """
        if guild_id is None:
            # Legacy behavior - use first guild
            guild_id = self.bot.guilds[0].id if self.bot.guilds else None
            if guild_id is None:
                self.logger.warning("No guild ID available for log message")
                return

        # Initialize guild buffer if needed
        if guild_id not in self.log_buffers:
            self.log_buffers[guild_id] = []

        self.log_buffers[guild_id].append(message)

        # Check if we should send immediately
        batch_size = self.get_global_setting("log_batch_size", 10)

        if len(self.log_buffers[guild_id]) >= batch_size:
            await self.flush_log_buffer(guild_id)

    async def flush_log_buffer(self, guild_id: int = None):
        """Send all accumulated log messages in the buffer for a specific guild

        Args:
            guild_id: The guild ID to flush logs for. If None, flushes all guilds.
        """
        if guild_id is None:
            # Flush all guild buffers
            for gid in list(self.log_buffers.keys()):
                await self.flush_log_buffer(gid)
            return

        if guild_id in self.log_buffers and self.log_buffers[guild_id]:
            messages = self.log_buffers[guild_id]
            await self.send_role_logs_batch(guild_id, messages)
            self.log_buffers[guild_id] = []  # Clear the buffer after sending

    async def send_role_logs_batch(self, guild_id: int, log_messages: list):
        """Send a batch of role update logs to the configured channel

        Args:
            guild_id: The guild ID for context
            log_messages: List of log messages to send
        """
        if not log_messages:
            return

        log_channel_id = self.get_setting("log_channel_id", guild_id=guild_id)
        if not log_channel_id:
            return  # No logging channel configured

        channel = self.bot.get_channel(int(log_channel_id))
        if not channel:
            self.logger.warning(f"Could not find log channel with ID {log_channel_id} for guild {guild_id}")
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
            self.logger.error(f"Error sending role log batch: {e}", exc_info=True)

    async def cog_initialize(self) -> None:
        """Initialize the TourneyRoles cog."""
        self.logger.info("Initializing TourneyRoles cog")
        try:
            self.logger.info("Starting TourneyRoles initialization")

            async with self.task_tracker.task_context("Initialization") as tracker:
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

                # 3. Check for newer tournament data on startup
                self.logger.debug("Checking for tournament data updates")
                tracker.update_status("Checking tournament data")
                await self._check_tournament_data_on_startup()

                # 4. Run startup role update if enabled
                if self.get_global_setting("update_on_startup", True):
                    self.logger.debug("Running startup role update")
                    tracker.update_status("Running startup role update")
                    await self.update_all_roles()

                # 5. Mark as ready and complete initialization
                self.set_ready(True)
                self.logger.info("TourneyRoles initialization complete")

        except Exception as e:
            self.logger.error(f"Error during TourneyRoles initialization: {e}", exc_info=True)
            self._has_errors = True
            raise

    def register_ui_extensions(self) -> None:
        """Register UI extensions that this cog provides to other cogs."""
        # Register tournament stats button for all users
        self.bot.cog_manager.register_ui_extension(
            target_cog="player_lookup", source_cog=self.__class__.__name__, provider_func=self.get_tourney_stats_button_for_player
        )

        # Register role refresh button for authorized users
        self.bot.cog_manager.register_ui_extension(
            target_cog="player_lookup", source_cog=self.__class__.__name__, provider_func=self.get_tourney_roles_button_for_player
        )

    def _user_can_refresh_roles(self, user: discord.User, guild_id: int) -> bool:
        """Check if authorized refresh groups are configured (lightweight check).

        This is a synchronous method used in UI button providers.
        Actual permission checking happens in the button callback.

        Args:
            user: The Discord user to check (unused, kept for signature compatibility)
            guild_id: The guild ID to check permissions in

        Returns:
            True if refresh groups are configured, False otherwise
        """
        # Get authorized groups from settings
        authorized_groups = self.get_setting("authorized_refresh_groups", guild_id=guild_id, default=[])

        # Return True if groups are configured (actual permission check is in button callback)
        return bool(authorized_groups)

    def get_tourney_stats_button_for_player(
        self, details, requesting_user: discord.User, guild_id: int, permission_context
    ) -> Optional[discord.ui.Button]:
        """Get a tournament stats button for a player.

        This method is called by the player_lookup cog to extend /lookup functionality.
        Returns a button that shows tournament stats for the player.
        """
        # Check if this cog is enabled for the guild
        if not self.bot.cog_manager.can_guild_use_cog(self.cog_name, guild_id, False):
            return None

        # Only show button if the player has a Discord ID
        if not details.get("discord_id"):
            return None

        # Show stats button to everyone (no permission check needed for viewing)
        return TourneyStatsButton(self, int(details["discord_id"]), guild_id, details["name"])

    def get_tourney_roles_button_for_player(
        self, details, requesting_user: discord.User, guild_id: int, permission_context
    ) -> Optional[discord.ui.Button]:
        """Get a tournament roles refresh button for a player.

        This method is called by the player_lookup cog to extend /lookup and /profile functionality.
        Returns a button that refreshes tournament roles for the player.

        - If viewing own profile: returns "Refresh My Roles" button (always shown)
        - If viewing someone else: returns "Refresh Tournament Roles" button (only if user has permission)
        """
        # Check if this cog is enabled for the guild
        if not self.bot.cog_manager.can_guild_use_cog(self.cog_name, guild_id, False):
            return None

        # Only show button if the player has a Discord ID
        if not details.get("discord_id"):
            return None

        # Check if requesting user is viewing their own profile
        is_own_profile = str(details["discord_id"]) == str(requesting_user.id)

        if is_own_profile:
            # Always show refresh button on own profile
            return TourneySelfRefreshButton(self, int(details["discord_id"]), guild_id)
        else:
            # For other users, check if requesting user has permission to refresh roles
            # Get authorized groups from settings and check if user has any of them
            authorized_groups = self.get_setting("authorized_refresh_groups", guild_id=guild_id, default=[])
            if authorized_groups and permission_context.has_any_group(authorized_groups):
                # Use the player's Discord ID (the person being looked up), not the requesting user's ID
                return TourneyRolesRefreshButton(self, int(details["discord_id"]), guild_id, requesting_user.id)

            return None

    async def cog_unload(self):
        """Clean up when cog is unloaded"""
        if self.update_task:
            self.update_task.cancel()
        await super().cog_unload()
        self.logger.info("Tournament roles cog unloaded")

    @discord.ext.commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Monitor role changes and handle tournament roles.

        Handles both:
        1. Verified role changes (add/remove tournament roles)
        2. Tournament role corrections for verified users
        """
        try:
            # Only process if this cog is enabled for the guild
            if not self.bot.cog_manager.can_guild_use_cog(self.cog_name, after.guild.id, False):
                return

            # Skip if we're already updating this member (prevents duplicate logging)
            # This includes manual updates, bulk updates, and role corrections
            member_key = (after.guild.id, after.id)
            if member_key in self.updating_members:
                return

            # Get verified role ID from settings
            verified_role_id = self.get_setting("verified_role_id", guild_id=after.guild.id)
            verified_role = after.guild.get_role(int(verified_role_id)) if verified_role_id else None

            # Check if verified role changed
            if verified_role:
                had_verified = verified_role in before.roles
                has_verified = verified_role in after.roles

                if had_verified != has_verified:
                    # Verified role was added or removed - update tournament roles
                    if has_verified:
                        # Role added - apply tournament roles
                        self.logger.info(f"Member {after.name} ({after.id}) gained verified role - applying tournament roles")

                        # Check cache first
                        cached_role = self.role_cache.get(after.guild.id, {}).get(str(after.id))

                        if cached_role is None:
                            # Not in cache - try to calculate
                            single_user_mapping = await self.get_discord_to_player_mapping(discord_id=str(after.id))

                            if single_user_mapping:
                                # User has player data - calculate their role
                                await self.calculate_roles_for_users([after.id], after.guild.id, discord_to_player=single_user_mapping)
                            else:
                                self.logger.info(f"User {after.name} ({after.id}) has no player data - skipping role calculation")
                                return

                        # Apply roles (will use cache if available, or handle verification requirement)
                        await self.apply_roles_for_users([after.id], after.guild.id)
                        return  # Don't process tournament role corrections for this update
                    else:
                        # Role removed - remove tournament roles
                        self.logger.info(f"Member {after.name} ({after.id}) lost verified role - removing tournament roles")
                        await self.apply_roles_for_users([after.id], after.guild.id)
                        return  # Don't process tournament role corrections for this update

            # Check if tournament roles changed
            roles_config = self.core.get_roles_config(after.guild.id)
            managed_role_ids = {config.id for config in roles_config.values()}

            before_tourney_roles = {role.id for role in before.roles if str(role.id) in managed_role_ids}
            after_tourney_roles = {role.id for role in after.roles if str(role.id) in managed_role_ids}

            # If tournament roles changed
            if before_tourney_roles != after_tourney_roles:
                # Check if user has verified role - if not, don't restore tournament roles
                verified_role_id = self.core.get_verified_role_id(after.guild.id)
                has_verified_role = False
                if verified_role_id:
                    has_verified_role = any(role.id == int(verified_role_id) for role in after.roles)

                # Only restore roles if user has verified role
                if not has_verified_role:
                    self.logger.debug(f"Tournament role changed for {after.name} but user is not verified - no correction")
                    return

                # Check if user should have their cached role
                cached_role_id = self.role_cache.get(after.guild.id, {}).get(str(after.id))

                # Determine if any correction is actually needed
                needs_correction = False

                if cached_role_id:
                    # User should have this specific role
                    if cached_role_id not in after_tourney_roles:
                        # Role was removed, add it back
                        needs_correction = True
                        role = after.guild.get_role(int(cached_role_id))
                        if role:
                            # Mark as updating to prevent duplicate logging
                            member_key = (after.guild.id, after.id)
                            self.updating_members.add(member_key)
                            try:
                                await after.add_roles(role, reason="Correcting tournament role removal")
                                self.logger.info(f"Restored tournament role {role.name} to {after.name}")

                                # Dispatch custom event for role addition
                                self.bot.dispatch("tourney_role_added", after, role)

                                # Log using unified function with immediate flush
                                await self.log_role_change(after.guild.id, after.name, [f"+{role.name}"], immediate=True)
                            finally:
                                # Delay removal to allow Discord's on_member_update event to fire and be ignored
                                async def delayed_removal():
                                    await asyncio.sleep(0.5)
                                    self.updating_members.discard(member_key)

                                asyncio.create_task(delayed_removal())
                    elif len(after_tourney_roles) > 1:
                        # User has multiple tournament roles, remove extras
                        needs_correction = True
                        roles_to_remove = []
                        for role_id in after_tourney_roles:
                            if role_id != int(cached_role_id):
                                role = after.guild.get_role(role_id)
                                if role:
                                    roles_to_remove.append(role)

                        if roles_to_remove:
                            # Mark as updating to prevent duplicate logging
                            member_key = (after.guild.id, after.id)
                            self.updating_members.add(member_key)
                            try:
                                await after.remove_roles(*roles_to_remove, reason="Removing extra tournament roles")
                                removed_names = [role.name for role in roles_to_remove]
                                self.logger.info(f"Removed extra tournament roles {removed_names} from {after.name}")

                                # Dispatch custom events for role removals
                                for role in roles_to_remove:
                                    self.bot.dispatch("tourney_role_removed", after, role)

                                # Log using unified function with immediate flush
                                changes = [f"-{name}" for name in removed_names]
                                await self.log_role_change(after.guild.id, after.name, changes, immediate=True)
                            finally:
                                # Delay removal to allow Discord's on_member_update event to fire and be ignored
                                async def delayed_removal():
                                    await asyncio.sleep(0.5)
                                    self.updating_members.discard(member_key)

                                asyncio.create_task(delayed_removal())

                # Only log if we actually made a correction
                if needs_correction:
                    self.logger.debug(f"Corrected tournament role change for {after.name} ({after.id})")
                else:
                    self.logger.debug(f"Tournament role change for {after.name} ({after.id}) - no correction needed")

        except Exception as e:
            self.logger.error(f"Error in on_member_update: {e}")

    @discord.ext.commands.Cog.listener()
    async def on_tourney_data_refreshed(self, data: dict):
        """Called when TourneyStats has refreshed its tournament data.

        This event is dispatched by the TourneyStats cog when it detects
        new tournament data and refreshes its cache.

        Args:
            data: Dictionary containing:
                - latest_date: The newest tournament date
                - patch: Current game patch
                - total_tournaments: Total number of tournaments
                - league_counts: Tournament counts per league
        """
        try:
            latest_date = data.get("latest_date")
            self.logger.info(f"Received tourney_data_refreshed event for date: {latest_date}")

            # Check if this is actually newer than our cache
            if self.cache_latest_tourney_date and latest_date:
                # Compare dates only (handle both datetime and date objects)
                cache_date = (
                    self.cache_latest_tourney_date.date()
                    if isinstance(self.cache_latest_tourney_date, datetime.datetime)
                    else self.cache_latest_tourney_date
                )
                event_date = latest_date.date() if isinstance(latest_date, datetime.datetime) else latest_date
                if event_date <= cache_date:
                    self.logger.debug(f"Event date {event_date} not newer than cache {cache_date}, ignoring")
                    return

            # Invalidate our role cache
            self.logger.info("Invalidating role cache due to new tournament data")
            self.cache_latest_tourney_date = None
            self.cache_timestamp = None

            # If we're not currently updating, trigger a full update with role application
            if not self.currently_updating:
                self.logger.info("Triggering full role update for new tournament data")

                # Check global pause setting first
                if self.get_global_setting("pause", False):
                    self.logger.info("Role updates are globally paused, skipping automatic update")
                    return

                # Trigger full update (calculation + application)
                # When new tournament data is detected, we want to apply role changes immediately
                # Note: Guild-level pause setting is also checked per-guild during role application
                await self.update_all_roles()
            else:
                self.logger.info("Role update already in progress, skipping event-triggered update")

        except Exception as e:
            self.logger.error(f"Error handling tourney_data_refreshed event: {e}", exc_info=True)

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

            # Get player mapping for just this user
            single_user_mapping = await self.get_discord_to_player_mapping(discord_id=str(user_id))

            if not single_user_mapping:
                return "❌ Player data not found"

            # Calculate roles for this user
            calc_result = await self.calculate_roles_for_users(
                user_ids=[user_id], guild_id=guild_id, discord_to_player=single_user_mapping, progress_callback=None
            )

            # Check if calculation succeeded
            if calc_result["calculated"] == 0:
                if calc_result["skipped"] > 0:
                    return "❌ No player data found. Use `/player register` to link your account."
                return "❌ Error calculating tournament roles"

            # Apply roles for this user
            apply_result = await self.apply_roles_for_users(user_ids=[user_id], guild_id=guild_id, progress_callback=None)

            # Check for errors
            if apply_result.get("errors", 0) > 0:
                return "❌ Error updating roles"

            if apply_result["skipped_not_verified"] > 0:
                return "❌ User not verified for tournament roles"

            # Format response based on dry_run mode
            dry_run = self.get_global_setting("dry_run", False)

            if dry_run:
                if apply_result["roles_added"] > 0 or apply_result["roles_removed"] > 0:
                    changes = []
                    if apply_result["roles_added"] > 0:
                        changes.append(f"would add {apply_result['roles_added']} role(s)")
                    if apply_result["roles_removed"] > 0:
                        changes.append(f"would remove {apply_result['roles_removed']} role(s)")
                    return f"🔍 DRY RUN: {', '.join(changes)}"
                return "🔍 DRY RUN: No role changes needed"
            else:
                if apply_result["roles_added"] > 0 or apply_result["roles_removed"] > 0:
                    changes = []
                    if apply_result["roles_added"] > 0:
                        changes.append(f"added {apply_result['roles_added']} role(s)")
                    if apply_result["roles_removed"] > 0:
                        changes.append(f"removed {apply_result['roles_removed']} role(s)")
                    return f"✅ {', '.join(changes)}"
                return "✅ No role changes needed"

        except Exception as e:
            self.logger.error(f"Error refreshing roles for user {user_id}: {e}")
            return f"❌ Error updating roles: {str(e)}"


class TourneyStatsButton(discord.ui.Button):
    """Button to view tournament stats for a specific player."""

    def __init__(self, cog, user_id: int, guild_id: int, player_name: str):
        super().__init__(label="View Tournament Stats", style=discord.ButtonStyle.secondary, emoji="📊", row=2)
        self.cog = cog
        self.user_id = user_id
        self.guild_id = guild_id
        self.player_name = player_name

    async def callback(self, interaction: discord.Interaction):
        """Show tournament statistics for the player."""
        # Send immediate loading response
        loading_embed = discord.Embed(
            title="📊 Loading Tournament Stats...", description=f"Gathering tournament data for {self.player_name}...", color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=loading_embed, ephemeral=True)

        try:
            # Get tournament stats cog
            tourney_stats_cog = await self.cog.get_tourney_stats_cog()
            if not tourney_stats_cog:
                error_embed = discord.Embed(title="❌ Error", description="Tournament stats not available", color=discord.Color.red())
                await interaction.edit_original_response(embed=error_embed)
                return

            # Get player lookup cog to get player IDs
            player_lookup_cog = await self.cog.get_known_players_cog()
            if not player_lookup_cog:
                error_embed = discord.Embed(title="❌ Error", description="Player lookup not available", color=discord.Color.red())
                await interaction.edit_original_response(embed=error_embed)
                return

            # Get player data - use single-user lookup instead of full mapping
            player_data = await player_lookup_cog.get_discord_to_player_mapping(discord_id=str(self.user_id))
            player_data = player_data.get(str(self.user_id)) if player_data else None

            if not player_data or "all_ids" not in player_data:
                error_embed = discord.Embed(title="❌ Error", description="No player data found", color=discord.Color.red())
                await interaction.edit_original_response(embed=error_embed)
                return

            # Get tournament stats using cached DataFrames (fast!)
            # Build single-user batch lookup
            player_ids = set(player_data["all_ids"])
            batch_stats = await tourney_stats_cog.get_batch_player_stats(player_ids)

            # Aggregate stats across all player IDs (returns TournamentStats object)
            player_stats = await self.cog.core._aggregate_player_stats(player_data["all_ids"], batch_stats)

            # Get current patch info
            current_patch = tourney_stats_cog.latest_patch if tourney_stats_cog.latest_patch else "Unknown"

            # Create embed
            embed = discord.Embed(
                title=f"📊 Tournament Stats - {self.player_name}",
                description=f"Tournament performance for {player_data.get('name', self.player_name)}",
                color=discord.Color.blue(),
            )

            # Add player ID (just primary)
            primary_id = player_data.get("primary_id")
            if primary_id:
                embed.add_field(name="Player ID", value=f"`{primary_id}`", inline=False)

            # Add overall stats
            if player_stats.total_tourneys > 0:
                # Latest Tournament section
                latest = player_stats.latest_tournament
                if latest.get("league"):
                    latest_text = f"**League:** {latest['league']}\n"
                    latest_text += f"**Position:** {latest.get('placement', 'N/A')}\n"
                    latest_text += f"**Wave:** {latest.get('wave', 'N/A')}\n"
                    if latest.get("date"):
                        latest_text += f"**Date:** {latest['date']}"

                    embed.add_field(name="📈 Latest Tournament", value=latest_text, inline=False)

                # Add league-specific stats
                for league_name, league_stats in player_stats.leagues.items():
                    stats_text = []
                    stats_text.append(f"**Tournaments:** {league_stats.get('total_tourneys', 0)}")

                    # Best position with frequency
                    best_position = league_stats.get("best_position", "N/A")
                    tournaments = league_stats.get("tournaments", [])

                    if tournaments and best_position != "N/A":
                        # Count how many times best position was achieved
                        best_pos_tourneys = [t for t in tournaments if t.get("position") == best_position]
                        count = len(best_pos_tourneys)

                        if count == 1:
                            date = best_pos_tourneys[0].get("date", "")
                            date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
                            stats_text.append(f"**Best Position:** {best_position} ({date_str})")
                        else:
                            dates = []
                            for t in best_pos_tourneys:
                                d = t.get("date", "")
                                dates.append(d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d))
                            dates = sorted(dates)
                            first_date = dates[0]  # Earliest date
                            last_date = dates[-1]  # Most recent date
                            stats_text.append(f"**Best Position:** {best_position} ({count}x: first {first_date}, last {last_date})")
                    else:
                        stats_text.append(f"**Best Position:** {best_position}")

                    # Highest Wave with frequency and date pattern
                    highest_wave = league_stats.get("best_wave", 0)
                    if tournaments and highest_wave:
                        # Count how many times highest wave was achieved
                        best_wave_tourneys = [t for t in tournaments if t.get("wave") == highest_wave]
                        wave_count = len(best_wave_tourneys)

                        if wave_count == 1:
                            date = best_wave_tourneys[0].get("date", "")
                            date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
                            stats_text.append(f"**Highest Wave:** {highest_wave} ({date_str})")
                        else:
                            dates = []
                            for t in best_wave_tourneys:
                                d = t.get("date", "")
                                dates.append(d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d))
                            dates = sorted(dates)
                            first_date = dates[0]  # Earliest date
                            last_date = dates[-1]  # Most recent date
                            stats_text.append(f"**Highest Wave:** {highest_wave} ({wave_count}x: first {first_date}, last {last_date})")
                    else:
                        stats_text.append(f"**Highest Wave:** {highest_wave}")
                    stats_text.append(f"**Avg Wave:** {league_stats.get('avg_wave', 0):.1f}")
                    stats_text.append(f"**Avg Position:** {league_stats.get('avg_position', 0):.1f}")

                    embed.add_field(name=f"🏆 {league_name.title()}", value="\n".join(stats_text), inline=True)
            else:
                embed.add_field(name="📈 Performance", value="No tournament participation found", inline=False)

            # Add current tournament roles with calculated role comparison
            guild = self.cog.bot.get_guild(self.guild_id)
            if guild:
                member = guild.get_member(self.user_id)
                if member:
                    # Get what role they SHOULD have from TourneyRoles cache
                    calculated_role_id = None
                    if self.guild_id in self.cog.role_cache and str(self.user_id) in self.cog.role_cache[self.guild_id]:
                        calculated_role_id = self.cog.role_cache[self.guild_id][str(self.user_id)]

                    roles_config = self.cog.core.get_roles_config(self.guild_id)
                    managed_role_ids = {str(config.id) for config in roles_config.values()}

                    # Check if role cache is populated
                    if self.guild_id not in self.cog.role_cache:
                        # Cache not populated yet
                        embed.add_field(
                            name="🎯 Current Tournament Roles",
                            value="⏳ Role calculations are not ready yet. Please use `/tourneyroles update` to calculate roles.",
                            inline=False,
                        )
                    else:
                        # Build map of role_id -> role_name from guild
                        guild_role_map = {str(role.id): role.name for role in guild.roles}

                        # Get what tournament roles they ACTUALLY have in Discord
                        current_tourney_roles = [role for role in member.roles if str(role.id) in managed_role_ids]
                        current_role_ids = {str(r.id) for r in current_tourney_roles}

                        # Build role status text
                        role_status = []
                        has_discrepancy = False

                        # Show what they should have
                        if calculated_role_id:
                            calculated_role_name = guild_role_map.get(str(calculated_role_id), "Unknown")
                            if str(calculated_role_id) in current_role_ids:
                                # They have it - only show if there's a discrepancy
                                role_status.append(f"✅ {calculated_role_name}")
                            else:
                                # They should have it but don't
                                role_status.append(f"❌ {calculated_role_name} (should have)")
                                has_discrepancy = True

                        # Show roles they have but shouldn't
                        for role in current_tourney_roles:
                            if str(role.id) != str(calculated_role_id):
                                role_status.append(f"⚠️ {role.name} (has but shouldn't)")
                                has_discrepancy = True

                        # If no discrepancy and they have a role, just show the checkmark version
                        if not has_discrepancy and calculated_role_id and current_role_ids:
                            # Already added with checkmark above
                            pass

                        if role_status:
                            embed.add_field(name="🎯 Current Tournament Roles", value="\n".join(role_status), inline=False)

            embed.set_footer(text=f"Stats from patch {current_patch}")

            # Create a view with Post Publicly button
            view = TourneyStatsPublicView(embed, interaction.guild.id, interaction.channel.id, self.cog)
            await interaction.edit_original_response(embed=embed, view=view)

        except Exception as e:
            self.cog.logger.error(f"Error showing tournament stats for user {self.user_id}: {e}", exc_info=True)
            error_embed = discord.Embed(title="❌ Error", description=f"Error loading stats: {str(e)}", color=discord.Color.red())
            await interaction.edit_original_response(embed=error_embed)


class TourneyStatsPublicView(discord.ui.View):
    """View with Post Publicly button for tournament stats."""

    def __init__(self, embed: discord.Embed, guild_id: int, channel_id: int, cog):
        super().__init__(timeout=300)  # 5 minute timeout
        self.embed = embed
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.cog = cog

        # Add post publicly button
        self.add_item(TourneyStatsPostPubliclyButton(embed, guild_id, channel_id, cog))


class TourneyStatsPostPubliclyButton(discord.ui.Button):
    """Button to post tournament stats publicly."""

    def __init__(self, embed: discord.Embed, guild_id: int, channel_id: int, cog):
        super().__init__(label="Post Publicly", style=discord.ButtonStyle.secondary, emoji="📢")
        self.embed = embed
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        """Post tournament stats publicly to the channel."""
        # Get player lookup cog to check authorized channels
        player_lookup_cog = self.cog.bot.get_cog("Player Lookup")
        if not player_lookup_cog:
            await interaction.response.send_message("❌ Player lookup system not available.", ephemeral=True)
            return

        # Check if posting everywhere is allowed or if this channel is in the allowed list
        allow_everywhere = player_lookup_cog.is_post_publicly_allowed_everywhere(self.guild_id)
        allowed_channels = player_lookup_cog.get_profile_post_channels(self.guild_id)

        if not allow_everywhere and self.channel_id not in allowed_channels:
            embed = discord.Embed(
                title="Channel Not Authorized", description="This channel is not configured for public profile posting.", color=discord.Color.red()
            )
            embed.add_field(
                name="What you can do",
                value="• The stats are still visible privately above\n• Ask a server admin to add this channel to the profile posting list",
                inline=False,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check if user has permission to post in this channel
        if not interaction.channel.permissions_for(interaction.user).send_messages:
            embed = discord.Embed(
                title="Permission Denied", description="You don't have permission to send messages in this channel.", color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Post publicly to the channel
        try:
            await interaction.response.send_message(embed=self.embed)
        except Exception as e:
            self.cog.logger.error(f"Error posting tournament stats publicly: {e}")
            await interaction.response.send_message("❌ Failed to post stats publicly. Please try again.", ephemeral=True)


class TourneySelfRefreshButton(discord.ui.Button):
    """Button for users to refresh their own tournament roles from their profile."""

    def __init__(self, cog, user_id: int, guild_id: int):
        super().__init__(label="Refresh My Roles", style=discord.ButtonStyle.primary, emoji="🔄", row=2)
        self.cog = cog
        self.user_id = user_id
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Button to refresh user's own tournament roles."""
        try:
            # Verify the user is refreshing their own roles
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ You can only refresh your own tournament roles.", ephemeral=True)
                return

            # Get guild and member
            guild = self.cog.bot.get_guild(self.guild_id)
            if not guild:
                await interaction.response.send_message("❌ Guild not found", ephemeral=True)
                return

            member = guild.get_member(self.user_id)
            if not member:
                await interaction.response.send_message("❌ Member not found", ephemeral=True)
                return

            # Check if we have a cached role for this user
            cached_role_id = self.cog.role_cache.get(self.guild_id, {}).get(str(self.user_id))

            if cached_role_id:
                # Fast path: Use cached role (same as on_member_update)
                await interaction.response.send_message("🔄 Refreshing roles...", ephemeral=True)

                # Mark member as being updated to prevent duplicate logging
                member_key = (self.guild_id, self.user_id)
                self.cog.updating_members.add(member_key)
                try:
                    role = guild.get_role(int(cached_role_id))
                    if not role:
                        await interaction.edit_original_response(content="❌ Cached role not found")
                        return

                    # Get current tournament roles
                    roles_config = self.cog.core.get_roles_config(self.guild_id)
                    managed_role_ids = {config.id for config in roles_config.values()}
                    current_tourney_roles = {r for r in member.roles if str(r.id) in managed_role_ids}

                    # Check what needs to be done
                    changes = []
                    roles_to_add = []
                    roles_to_remove = []

                    if role not in current_tourney_roles:
                        roles_to_add.append(role)
                        changes.append(f"+{role.name}")

                    # Remove any other tournament roles
                    for existing_role in current_tourney_roles:
                        if existing_role.id != role.id:
                            roles_to_remove.append(existing_role)
                            changes.append(f"-{existing_role.name}")

                    # Apply role changes
                    if roles_to_add:
                        await member.add_roles(*roles_to_add, reason="User refreshed tournament roles")
                        # Dispatch custom events for role additions
                        for role in roles_to_add:
                            self.cog.bot.dispatch("tourney_role_added", member, role)
                    if roles_to_remove:
                        await member.remove_roles(*roles_to_remove, reason="User refreshed tournament roles")
                        # Dispatch custom events for role removals
                        for role in roles_to_remove:
                            self.cog.bot.dispatch("tourney_role_removed", member, role)

                    # Log changes if any
                    if changes:
                        await self.cog.log_role_change(self.guild_id, member.name, changes, immediate=True)
                        await interaction.edit_original_response(content=f"✅ Roles updated: {', '.join(changes)}")
                    else:
                        await interaction.edit_original_response(content="✅ Your roles are already up to date!")
                finally:
                    # Delay removal to allow Discord's on_member_update event to fire and be ignored
                    async def delayed_removal():
                        await asyncio.sleep(0.5)
                        self.cog.updating_members.discard(member_key)

                    asyncio.create_task(delayed_removal())
            else:
                # Slow path: No cache, need to recalculate
                loading_embed = discord.Embed(
                    title="🔄 Calculating Roles...",
                    description="No cached data found. Fetching your tournament stats...",
                    color=discord.Color.orange(),
                )
                await interaction.response.send_message(embed=loading_embed, ephemeral=True)

                member_key = (self.guild_id, self.user_id)
                self.cog.updating_members.add(member_key)
                try:
                    result = await self.cog.refresh_user_roles_for_user(self.user_id, self.guild_id)
                    success_embed = discord.Embed(title="✅ Roles Updated", description=result, color=discord.Color.green())
                    await interaction.edit_original_response(embed=success_embed)
                finally:
                    # Delay removal to allow Discord's on_member_update event to fire and be ignored
                    async def delayed_removal():
                        await asyncio.sleep(0.5)
                        self.cog.updating_members.discard(member_key)

                    asyncio.create_task(delayed_removal())

        except Exception as e:
            self.cog.logger.error(f"Error refreshing tournament roles for user {self.user_id}: {e}")
            error_embed = discord.Embed(title="❌ Error", description=f"Error updating roles: {str(e)}", color=discord.Color.red())
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=error_embed)
            else:
                await interaction.response.send_message(embed=error_embed, ephemeral=True)


class TourneyRolesRefreshButton(discord.ui.Button):
    """Button to refresh tournament roles for a specific user."""

    def __init__(self, cog, user_id: int, guild_id: int, requesting_user_id: int):
        super().__init__(label="Update Tournament Roles", style=discord.ButtonStyle.primary, emoji="🔄", row=2)
        self.cog = cog
        self.user_id = user_id
        self.guild_id = guild_id
        self.requesting_user_id = requesting_user_id

    async def callback(self, interaction: discord.Interaction):
        """Button to refresh tournament roles."""
        await interaction.response.defer(ephemeral=True)

        try:
            # Check permissions with Django groups
            from asgiref.sync import sync_to_async

            from thetower.backend.sus.models import KnownPlayer

            # Get authorized groups from settings
            authorized_groups = self.cog.get_setting("authorized_refresh_groups", guild_id=self.guild_id, default=[])

            if not authorized_groups:
                await interaction.followup.send("❌ Tournament role refresh is not configured for this server.", ephemeral=True)
                return

            # Get Django user from Discord ID via KnownPlayer
            discord_id = str(interaction.user.id)

            def get_known_player():
                return KnownPlayer.objects.filter(discord_id=discord_id).select_related("django_user").first()

            known_player = await sync_to_async(get_known_player)()

            if not known_player or not known_player.django_user:
                await interaction.followup.send("❌ No Django user account found for your Discord ID.", ephemeral=True)
                return

            django_user = known_player.django_user

            # Check if user is in approved groups
            def get_user_groups():
                return [group.name for group in django_user.groups.all()]

            user_groups = await sync_to_async(get_user_groups)()
            has_permission = any(group in authorized_groups for group in user_groups)

            if not has_permission:
                await interaction.followup.send("❌ You don't have permission to refresh tournament roles for other players.", ephemeral=True)
                return

            # Mark member as being updated to prevent duplicate logging from on_member_update
            member_key = (self.guild_id, self.user_id)
            self.cog.updating_members.add(member_key)
            try:
                # Call the public method to refresh roles
                result = await self.cog.refresh_user_roles_for_user(self.user_id, self.guild_id)

                # Send the result
                await interaction.followup.send(result, ephemeral=True)
            finally:
                # Always remove from updating set
                self.cog.updating_members.discard(member_key)

        except Exception as e:
            self.cog.logger.error(f"Error refreshing tournament roles for user {self.user_id}: {e}")
            await interaction.followup.send(f"❌ Error updating roles: {str(e)}", ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(TourneyRoles(bot))
