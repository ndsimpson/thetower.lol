# Standard library
import asyncio
import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Third-party
import discord
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import tasks

from thetower.backend.sus.models import KnownPlayer

# Local
from thetower.bot.basecog import BaseCog

from .ui import (
    KnownPlayersSettingsView,
    UserInteractions,
    get_player_details,
    validate_creator_code,
)


class KnownPlayers(BaseCog, name="Known Players", description="Player identity management and lookup"):
    """Player identity management and lookup.

    Provides commands for finding players by ID, name or Discord info, and
    maintaining the database of known player identities.
    """

    # Settings view class for the cog manager
    settings_view_class = KnownPlayersSettingsView

    def __init__(self, bot):
        super().__init__(bot)
        self.logger.info("Initializing KnownPlayers")

        # Initialize core instance variables with descriptions
        self.player_cache: Dict[str, KnownPlayer] = {}  # Cache of player objects
        self.player_details_cache: Dict[str, Dict[str, Any]] = {}  # Serializable player details
        self.cached_player_ids: Dict[str, int] = {}  # Map player IDs to PKs

        # Status tracking
        self._active_process = None
        self._process_start_time = None
        self.last_cache_update = None

        # Store reference on bot
        self.bot.known_players = self

        # Define default settings
        self.default_settings = {
            "results_per_page": 5,
            "cache_refresh_interval": 3600,
            "cache_save_interval": 300,
            "cache_filename": "known_player_cache.pkl",
            "info_max_results": 3,
            "refresh_check_interval": 900,
            "auto_refresh": True,
            "save_on_update": True,
            "allow_partial_matches": True,
            "case_sensitive": False,
            "restrict_lookups_to_known_users": True,
            # Profile posting settings
            "profile_post_channels": [],  # List of channel IDs where profiles can be posted publicly
        }

        # Initialize UI interactions
        self.user_interactions = UserInteractions(self)

    async def _check_additional_interaction_permissions(self, interaction: discord.Interaction) -> bool:
        """Override additional interaction permissions for slash commands.

        The /profile and /lookup commands open ephemeral UIs where permissions are checked
        at the button level, not at the command level. This allows everyone to
        open the UI and see what actions they can perform based on their permissions.
        """
        # Allow all slash commands through - permissions checked in button callbacks
        return True

    @property
    def results_per_page(self) -> int:
        """Get results per page setting."""
        return self.config.config.get("known_players", {}).get("results_per_page", self.default_settings["results_per_page"])

    @property
    def cache_refresh_interval(self) -> int:
        """Get cache refresh interval setting."""
        return self.config.config.get("known_players", {}).get("cache_refresh_interval", self.default_settings["cache_refresh_interval"])

    @property
    def cache_save_interval(self) -> int:
        """Get cache save interval setting."""
        return self.config.config.get("known_players", {}).get("cache_save_interval", self.default_settings["cache_save_interval"])

    @property
    def info_max_results(self) -> int:
        """Get info max results setting."""
        return self.config.config.get("known_players", {}).get("info_max_results", self.default_settings["info_max_results"])

    @property
    def refresh_check_interval(self) -> int:
        """Get refresh check interval setting."""
        return self.config.config.get("known_players", {}).get("refresh_check_interval", self.default_settings["refresh_check_interval"])

    @property
    def auto_refresh(self) -> bool:
        """Get auto refresh setting."""
        return self.config.config.get("known_players", {}).get("auto_refresh", self.default_settings["auto_refresh"])

    @property
    def save_on_update(self) -> bool:
        """Get save on update setting."""
        return self.config.config.get("known_players", {}).get("save_on_update", self.default_settings["save_on_update"])

    @property
    def allow_partial_matches(self) -> bool:
        """Get allow partial matches setting."""
        return self.config.config.get("known_players", {}).get("allow_partial_matches", self.default_settings["allow_partial_matches"])

    @property
    def case_sensitive(self) -> bool:
        """Get case sensitive setting."""
        return self.config.config.get("known_players", {}).get("case_sensitive", self.default_settings["case_sensitive"])

    @property
    def restrict_lookups_to_known_users(self) -> bool:
        """Get restrict lookups to known users setting."""
        return self.config.config.get("known_players", {}).get(
            "restrict_lookups_to_known_users", self.default_settings["restrict_lookups_to_known_users"]
        )

    @property
    def profile_post_channels(self) -> List[int]:
        """Get profile post channels setting."""
        return self.config.config.get("known_players", {}).get("profile_post_channels", self.default_settings["profile_post_channels"])

    def get_profile_post_channels(self, guild_id: int) -> List[int]:
        """Get profile post channels setting for a specific guild."""
        guild_config = self.config.config.get("guilds", {}).get(str(guild_id), {}).get("known_players", {})
        return guild_config.get("profile_post_channels", [])

    @property
    def cache_file(self) -> Path:
        """Get the cache file path."""
        filename = self.config.config.get("known_players", {}).get("cache_filename", self.default_settings["cache_filename"])
        return self.data_directory / filename

    async def save_cache(self) -> bool:
        """Save the cache to disk"""
        if not self.last_cache_update:
            return False

        # Use BaseCog's task tracking for save operation
        async with self.task_tracker.task_context("Cache Save", "Saving player cache to disk"):
            # Prepare serializable data to save
            save_data = {"last_update": self.last_cache_update, "player_details": self.player_details_cache, "player_map": self.cached_player_ids}

            # Use BaseCog's utility to save data
            return await self.save_data_if_modified(save_data, self.cache_file)

    async def load_cache(self) -> bool:
        """Load the cache from disk"""
        try:
            async with self.task_tracker.task_context("Cache Load", "Loading player cache"):
                save_data = await self.load_data(self.cache_file, default={})

                if save_data:
                    self.player_details_cache = save_data.get("player_details", {})
                    self.cached_player_ids = save_data.get("player_map", {})
                    self.last_cache_update = save_data.get("last_update")
                    return True

                return False

        except Exception as e:
            self.logger.error(f"Error loading cache: {e}", exc_info=True)
            return False

    async def rebuild_object_cache_for_keys(self, keys: Set[str]) -> None:
        """Rebuild Django objects in cache for specific keys"""
        # Add ready check for helper method
        if not await self.wait_until_ready():
            self.logger.warning("Cannot rebuild cache - cog not ready")
            return

        async with self.task_tracker.task_context("Cache Rebuild", "Rebuilding object cache"):
            # Build a set of player PKs we need to fetch
            needed_pks: Set[int] = set()
            for key in keys:
                if key in self.cached_player_ids:
                    needed_pks.add(self.cached_player_ids[key])

            if not needed_pks:
                return

            # Update task status with count
            self.task_tracker.update_task_status("Cache Rebuild", f"Fetching {len(needed_pks)} players")

            # Fetch all needed KnownPlayer objects at once
            players = await sync_to_async(list)(KnownPlayer.objects.filter(pk__in=needed_pks))

            # Create a lookup by PK
            player_lookup = {player.pk: player for player in players}

            # Update the object cache
            for key in keys:
                if key in self.cached_player_ids:
                    pk = self.cached_player_ids[key]
                    if pk in player_lookup:
                        self.player_cache[key] = player_lookup[pk]

    async def refresh_cache(self, force: bool = False) -> bool:
        """Refresh the player cache."""
        # Replace the nested task contexts with a single tracked task
        task_name = "Cache Refresh"
        async with self.task_tracker.task_context(task_name, "Starting cache refresh"):
            try:
                # Add ready check for helper method
                if not await self.wait_until_ready():
                    self.logger.warning("Cannot refresh cache - cog not ready")
                    return False

                # If not forced, try loading from disk first
                if not force and not self.last_cache_update:
                    if await self.load_cache():
                        return True

                # Check if cache needs refresh
                now = datetime.datetime.now()
                if not force and self.last_cache_update and (now - self.last_cache_update).total_seconds() < self.cache_refresh_interval:
                    return True

                self.logger.info("Starting player cache refresh")
                self.task_tracker.update_task_status(task_name, "Fetching players from database")

                # Create serializable details cache
                all_players = await sync_to_async(list)(KnownPlayer.objects.all())
                self.logger.info(f"Found {len(all_players)} players in database")

                self.task_tracker.update_task_status(task_name, f"Processing {len(all_players)} players")

                new_details = {}
                new_ids = {}
                player_id_count = 0
                discord_id_count = 0

                for player in all_players:
                    # Cache player details
                    details = await get_player_details(player)
                    player_id = details.get("primary_id")
                    if player_id:
                        new_details[player_id] = details
                        new_ids[player_id] = player.pk
                        player_id_count += 1

                        # Also cache by Discord ID if available
                        discord_id = details.get("discord_id")
                        if discord_id:
                            new_details[discord_id] = details
                            new_ids[discord_id] = player.pk
                            discord_id_count += 1

                        # Cache by all known player IDs
                        for pid in details.get("all_ids", []):
                            new_details[pid] = details
                            new_ids[pid] = player.pk
                            player_id_count += 1

                # Update caches atomically
                self.player_details_cache = new_details
                self.cached_player_ids = new_ids
                self.last_cache_update = now

                # Save cache to disk if configured
                # Note: Using default for internal operation without guild context
                if self.save_on_update:
                    await self.save_cache()

                self.logger.info(
                    f"Player cache refresh complete. {len(new_details)} total entries cached ({player_id_count} player IDs, {discord_id_count} Discord IDs)."
                )
                return True

            except Exception as e:
                self.logger.error(f"Error refreshing cache: {e}", exc_info=True)
                raise

    async def search_player(self, search_term: str) -> List[KnownPlayer]:
        """
        Search for players by name, ID, or Discord info

                Args:
                    search_term: Name, player ID, or Discord ID/name to search for

                Returns:
                    List of matching KnownPlayer objects
        """
        await self.wait_until_ready()
        search_term = search_term.strip()

        # Apply case sensitivity setting (use default for internal operations)
        if not self.case_sensitive:
            search_term = search_term.lower()

        # First check exact matches in cache
        if search_term in self.player_details_cache:
            # Make sure we have the Django object
            if search_term not in self.player_cache:
                await self.rebuild_object_cache_for_keys({search_term})

            if search_term in self.player_cache:
                return [self.player_cache[search_term]]

        # Apply partial matching setting (use default for internal operations)
        if not self.allow_partial_matches:
            # Only do exact matches
            if search_term in self.player_details_cache:
                # Make sure we have the Django object
                if search_term not in self.player_cache:
                    await self.rebuild_object_cache_for_keys({search_term})

                if search_term in self.player_cache:
                    return [self.player_cache[search_term]]
        else:
            # If not in cache, do a database search
            results: List[KnownPlayer] = []

            # Search by name (case insensitive)
            name_results = await sync_to_async(list)(KnownPlayer.objects.filter(name__icontains=search_term))
            results.extend(name_results)

            # Search by player ID
            id_results = await sync_to_async(list)(KnownPlayer.objects.filter(ids__id__icontains=search_term).distinct())
            results.extend([r for r in id_results if r not in results])

            # Search by Discord ID
            discord_results = await sync_to_async(list)(KnownPlayer.objects.filter(discord_id__icontains=search_term))
            results.extend([r for r in discord_results if r not in results])

            return results

    async def get_player_by_player_id(self, player_id: str) -> Optional[KnownPlayer]:
        """Get a player by their Tower player id"""
        await self.wait_until_ready()
        if player_id in self.player_details_cache:
            if player_id not in self.player_cache:
                await self.rebuild_object_cache_for_keys({player_id})
            return self.player_cache.get(player_id)
        return None

    async def get_player_by_discord_id(self, discord_id: str) -> Optional[KnownPlayer]:
        """Get a player by their Discord ID"""
        await self.wait_until_ready()
        if discord_id in self.player_details_cache:
            if discord_id not in self.player_cache:
                await self.rebuild_object_cache_for_keys({discord_id})
            return self.player_cache.get(discord_id)
        return None

    async def get_player_by_name(self, name: str) -> Optional[KnownPlayer]:
        """Get a player by their name (case insensitive)"""
        name = name.lower().strip()
        await self.wait_until_ready()
        if name in self.player_details_cache:
            if name not in self.player_cache:
                await self.rebuild_object_cache_for_keys({name})
            return self.player_cache.get(name)
        return None

    async def get_player_by_any(self, identifier: str) -> Optional[KnownPlayer]:
        """Get a player by any identifier (name, Discord ID, or player ID)"""
        await self.wait_until_ready()

        # Try direct lookup first
        if identifier in self.player_details_cache:
            if identifier not in self.player_cache:
                await self.rebuild_object_cache_for_keys({identifier})
            return self.player_cache.get(identifier)

        # Try case-insensitive name lookup
        lower_id = identifier.lower().strip()
        if lower_id != identifier and lower_id in self.player_details_cache:
            if lower_id not in self.player_cache:
                await self.rebuild_object_cache_for_keys({lower_id})
            return self.player_cache.get(lower_id)

        return None

    async def get_all_discord_ids(self) -> List[str]:
        """Get all unique Discord IDs from the player cache"""
        await self.wait_until_ready()

        discord_ids: Set[str] = set()
        for details in self.player_details_cache.values():
            if details.get("discord_id"):
                discord_ids.add(details["discord_id"])

        return list(discord_ids)

    async def _load_settings(self) -> None:
        """Load and initialize default settings."""
        # Ensure known_players config section exists
        known_players_config = self.config.config.setdefault("known_players", {})

        # Set defaults for any missing settings
        for key, default_value in self.default_settings.items():
            if key not in known_players_config:
                known_players_config[key] = default_value
                self.logger.debug(f"Set default setting {key} = {default_value}")

        # Save the config if any defaults were set
        if known_players_config:
            self.config.save_config()
            self.logger.debug("Saved updated config with default settings")

    # === Helper Methods ===

    def _validate_creator_code(self, code: str) -> tuple[bool, str]:
        """Wrapper for the validation function"""
        return validate_creator_code(code)

    # === Slash Commands ===

    @app_commands.command(name="profile", description="View your player profile and verification status")
    async def profile_slash(self, interaction: discord.Interaction) -> None:
        """View your own player profile and verification status."""
        await self.user_interactions.handle_profile_command(interaction)

    @app_commands.command(name="lookup", description="Look up a player by ID, name, or Discord user")
    @app_commands.describe(identifier="Player ID, name, or mention a Discord user", user="Discord user to look up (optional)")
    async def lookup_slash(self, interaction: discord.Interaction, identifier: str = None, user: discord.User = None) -> None:
        """Look up a player by various identifiers."""
        await self.user_interactions.handle_lookup_command(interaction, identifier, user)

    # === Background Tasks ===

    @tasks.loop(seconds=None)  # Will set interval in before_loop
    async def periodic_cache_save(self):
        """Periodically save the player cache to disk."""
        try:
            if self.is_paused:
                return
            # Don't save if there's nothing to save
            if not self.last_cache_update:
                return

            # Update status tracking variables
            self._active_process = "Cache Save"
            self._process_start_time = datetime.datetime.now()

            # Prepare serializable data to save
            save_data = {"last_update": self.last_cache_update, "player_details": self.player_details_cache, "player_map": self.cached_player_ids}

            # Save data if it's been modified
            success = await self.save_data_if_modified(save_data, self.cache_file)

            if success:
                self.logger.debug(f"Saved player cache with {len(self.player_details_cache)} entries")

            # Update status tracking
            self._last_operation_time = datetime.datetime.now()
            self._active_process = None

        except asyncio.CancelledError:
            self.logger.info("Cache save task was cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Error saving player cache: {e}", exc_info=True)
            self._has_errors = True
            self._active_process = None

    @periodic_cache_save.before_loop
    async def before_periodic_cache_save(self):
        """Setup before the save task starts."""
        self.logger.info(f"Starting periodic cache save task (interval: {self.cache_save_interval}s)")
        await self.bot.wait_until_ready()
        await self.wait_until_ready()

        # Set the interval dynamically based on settings
        self.periodic_cache_save.change_interval(seconds=self.cache_save_interval)

    @periodic_cache_save.after_loop
    async def after_periodic_cache_save(self):
        """Cleanup after the save task ends."""
        if self.periodic_cache_save.is_being_cancelled():
            self.logger.info("Cache save task was cancelled")
            # Try to save one last time
            save_data = {"last_update": self.last_cache_update, "player_details": self.player_details_cache, "player_map": self.cached_player_ids}
            await self.save_data_if_modified(save_data, self.cache_file, force=True)

    @tasks.loop(seconds=None)  # Will set interval in before_loop
    async def periodic_refresh(self):
        """Periodically check if cache needs refresh based on refresh interval."""
        try:
            if self.is_paused:
                return
            # Track task execution
            self._active_process = "Cache Refresh Check"
            self._process_start_time = datetime.datetime.now()

            # If cache is too old, refresh it
            now = datetime.datetime.now()
            if not self.last_cache_update or (now - self.last_cache_update).total_seconds() >= self.cache_refresh_interval:
                self.logger.info("Cache refresh interval exceeded, refreshing...")
                await self.refresh_cache()

            # Update tracking variables
            self._last_operation_time = datetime.datetime.now()
            self._active_process = None

        except asyncio.CancelledError:
            self.logger.info("Cache refresh task was cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Error in periodic refresh: {e}", exc_info=True)
            self._has_errors = True
            self._active_process = None

    @periodic_refresh.before_loop
    async def before_periodic_refresh(self):
        """Setup before the refresh task starts."""
        self.logger.info(f"Starting periodic cache refresh task (interval: {self.refresh_check_interval}s)")
        await self.bot.wait_until_ready()
        await self.wait_until_ready()

        # Set the interval dynamically based on settings
        self.periodic_refresh.change_interval(seconds=self.refresh_check_interval)

    @periodic_refresh.after_loop
    async def after_periodic_refresh(self):
        """Cleanup after the refresh task ends."""
        if self.periodic_refresh.is_being_cancelled():
            self.logger.info("Cache refresh task was cancelled")

    async def cog_initialize(self) -> None:
        """Initialize the Known Players cog."""
        self.logger.info("Initializing KnownPlayers cog")
        try:
            self.logger.info("Starting Known Players initialization")

            async with self.task_tracker.task_context("Initialization") as tracker:
                # Initialize parent
                self.logger.debug("Initializing parent cog")
                await super().cog_initialize()

                # 1. Verify settings
                self.logger.debug("Loading settings")
                tracker.update_status("Verifying settings")
                await self._load_settings()

                # 2. Load cache
                self.logger.debug("Loading cache from disk")
                tracker.update_status("Loading cache")
                if await self.load_cache():
                    self.logger.info("Loaded cache from disk")
                else:
                    self.logger.info("No cache file found, will create new cache")

                # 3. Start maintenance tasks with proper task tracking
                self.logger.debug("Starting maintenance tasks")
                tracker.update_status("Starting maintenance tasks")

                # Start tasks after ensuring they're not already running
                if not self.periodic_cache_save.is_running():
                    self.periodic_cache_save.start()
                if not self.periodic_refresh.is_running():
                    self.periodic_refresh.start()

                # 4. Mark as ready and complete initialization
                self.set_ready(True)
                self.logger.info("Known Players initialization complete")

        except Exception as e:
            self.logger.error(f"Known Players initialization failed: {e}", exc_info=True)
            self._has_errors = True
            raise

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded"""
        # Cancel the periodic save task
        if self.periodic_cache_save.is_running():
            self.periodic_cache_save.cancel()

        # Cancel the periodic tasks
        if hasattr(self, "periodic_refresh") and self.periodic_refresh.is_running():
            self.periodic_refresh.cancel()

        # Save cache one last time
        try:
            save_data = {"last_update": self.last_cache_update, "player_details": self.player_details_cache, "player_map": self.cached_player_ids}
            await self.save_data_if_modified(save_data, self.cache_file, force=True)
        except Exception as e:
            self.logger.error(f"Error saving cache during unload: {e}")

        # Call parent unload last
        await super().cog_unload()
        self.logger.info("Known Players cog unloaded")
