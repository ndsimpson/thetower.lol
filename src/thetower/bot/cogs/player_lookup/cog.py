# Standard library
from typing import Any, Dict, List, Optional

# Third-party
import discord
from asgiref.sync import sync_to_async
from discord import app_commands

from thetower.backend.sus.models import KnownPlayer, ModerationRecord

# Local
from thetower.bot.basecog import BaseCog

from .ui import UserInteractions
from .ui.settings import PlayerLookupSettingsView


class UnverifiedPlayer:
    """Represents an unverified player found through moderation records."""

    def __init__(self, tower_id: str):
        self.tower_id = tower_id
        self.name = f"Unverified Player ({tower_id})"
        self.discord_id = None
        self.is_unverified = True


class PlayerLookup(BaseCog, name="Player Lookup", description="Universal player search and lookup"):
    """Universal player search and lookup across all player data sources.

    Provides commands for finding players by ID, name or Discord info, regardless
    of verification status. Searches both verified players and moderation records.
    """

    # Settings view class for the cog manager
    settings_view_class = PlayerLookupSettingsView

    def __init__(self, bot):
        super().__init__(bot)
        self.logger.info("Initializing PlayerLookup")

        # Store reference on bot
        self.bot.player_lookup = self

        # Define default settings
        self.default_settings = {
            "results_per_page": 5,
            "allow_partial_matches": True,
            "case_sensitive": False,
            # Security settings
            "restrict_lookups_to_known_users": True,
            # Profile posting settings
            "profile_post_channels": [],
        }

        # Initialize UI interactions
        self.user_interactions = UserInteractions(self)

    async def _check_additional_interaction_permissions(self, interaction: discord.Interaction) -> bool:
        """Override additional interaction permissions for slash commands.

        The /lookup command opens ephemeral UIs where permissions are checked
        at the button level, not at the command level. This allows everyone to
        open the UI and see what actions they can perform based on their permissions.
        """
        # Allow all slash commands through - permissions checked in button callbacks
        return True

    @property
    def results_per_page(self) -> int:
        """Get results per page setting."""
        return self.config.config.get("player_lookup", {}).get("results_per_page", self.default_settings["results_per_page"])

    @property
    def allow_partial_matches(self) -> bool:
        """Get allow partial matches setting."""
        return self.config.config.get("player_lookup", {}).get("allow_partial_matches", self.default_settings["allow_partial_matches"])

    @property
    def case_sensitive(self) -> bool:
        """Get case sensitive setting."""
        return self.config.config.get("player_lookup", {}).get("case_sensitive", self.default_settings["case_sensitive"])

    @property
    def restrict_lookups_to_known_users(self) -> bool:
        """Get restrict lookups to known users setting."""
        return self.config.config.get("player_lookup", {}).get(
            "restrict_lookups_to_known_users", self.default_settings["restrict_lookups_to_known_users"]
        )

    @property
    def profile_post_channels(self) -> List[int]:
        """Get profile post channels setting."""
        return self.config.config.get("player_lookup", {}).get("profile_post_channels", self.default_settings["profile_post_channels"])

    async def check_show_moderation_records_permission(self, discord_user: discord.User) -> bool:
        """Check if a Discord user can see moderation records based on Django group membership.

        Delegates to manage_sus cog if available, otherwise uses fallback logic.
        """
        # Try to delegate to manage_sus cog first
        manage_sus_cog = self.bot.get_cog("Manage Sus")
        if manage_sus_cog:
            return await manage_sus_cog._user_can_view_moderation_records_in_profiles(discord_user)

        # Fallback: deny access if manage_sus is not available
        return False

    async def check_show_all_ids_permission(self, discord_user: discord.User) -> bool:
        """Check if a Discord user can see all player IDs based on Django group membership.

        Delegates to manage_sus cog if available, otherwise uses fallback logic.
        """
        # Try to delegate to manage_sus cog first
        manage_sus_cog = self.bot.get_cog("Manage Sus")
        if manage_sus_cog:
            return await manage_sus_cog._user_can_view_full_ids(discord_user)

        # Fallback: deny access if manage_sus is not available
        return False

    async def get_player_by_player_id(self, player_id: str) -> Optional[KnownPlayer]:
        """Get a player by their Tower player id"""
        await self.wait_until_ready()
        try:
            # Query database directly for the player
            player = await sync_to_async(KnownPlayer.objects.filter(ids__id=player_id).select_related("django_user").first)()
            return player
        except Exception as e:
            self.logger.error(f"Error getting player by player ID {player_id}: {e}")
            return None

    async def get_player_by_discord_id(self, discord_id: str) -> Optional[KnownPlayer]:
        """Get a player by their Discord ID"""
        await self.wait_until_ready()
        try:
            # Query database directly for the player
            player = await sync_to_async(KnownPlayer.objects.filter(discord_id=discord_id).select_related("django_user").first)()
            return player
        except Exception as e:
            self.logger.error(f"Error getting player by Discord ID {discord_id}: {e}")
            return None

    async def get_player_by_name(self, name: str) -> Optional[KnownPlayer]:
        """Get a player by their name (case insensitive)"""
        await self.wait_until_ready()
        try:
            # Query database directly for the player (case insensitive)
            player = await sync_to_async(KnownPlayer.objects.filter(name__iexact=name).select_related("django_user").first)()
            return player
        except Exception as e:
            self.logger.error(f"Error getting player by name {name}: {e}")
            return None

    async def get_player_by_any(self, identifier: str) -> Optional[KnownPlayer]:
        """Get a player by any identifier (name, Discord ID, or player ID)"""
        await self.wait_until_ready()

        # Try direct lookups in order of specificity
        player = None

        # Try Discord ID first (most specific)
        if identifier.isdigit() and len(identifier) >= 15:  # Discord IDs are long numbers
            player = await self.get_player_by_discord_id(identifier)

        # Try player ID
        if not player:
            player = await self.get_player_by_player_id(identifier)

        # Try name (case insensitive)
        if not player:
            player = await self.get_player_by_name(identifier)

        return player

    async def get_discord_to_player_mapping(self, discord_id: str = None) -> Dict[str, Dict[str, Any]]:
        """Get mapping of Discord IDs to player information.

        Args:
            discord_id: Optional Discord ID to get data for a single user.
                       If None, returns mapping for all users.

        Returns:
            Dict mapping Discord IDs to player information dictionaries.
            Each player info dict contains: all_ids, discord_id, name, player_id
        """
        await self.wait_until_ready()

        if discord_id is not None:
            # Single user lookup
            try:
                known_player = await sync_to_async(KnownPlayer.objects.filter(discord_id=discord_id).select_related("django_user").first)()

                if not known_player:
                    return {}

                # Get all player IDs for this user
                all_ids = await sync_to_async(lambda: list(known_player.ids.values_list("id", flat=True)))()

                return {
                    discord_id: {
                        "all_ids": all_ids,
                        "discord_id": discord_id,
                        "name": known_player.name or "",
                        "player_id": all_ids[0] if all_ids else "",  # Primary ID
                    }
                }

            except Exception as e:
                self.logger.error(f"Error getting player mapping for Discord ID {discord_id}: {e}")
                return {}

        else:
            # Full mapping lookup
            try:
                # Get all known players with Discord IDs
                known_players = await sync_to_async(list)(
                    KnownPlayer.objects.exclude(discord_id__isnull=True).exclude(discord_id="").select_related("django_user")
                )

                mapping = {}
                for player in known_players:
                    discord_id = player.discord_id
                    if discord_id:  # Double-check it's not empty
                        # Get all player IDs for this user
                        all_ids = await sync_to_async(lambda: list(player.ids.values_list("id", flat=True)))()

                        mapping[discord_id] = {
                            "all_ids": all_ids,
                            "discord_id": discord_id,
                            "name": player.name or "",
                            "player_id": all_ids[0] if all_ids else "",  # Primary ID
                        }

                return mapping

            except Exception as e:
                self.logger.error(f"Error getting full player mapping: {e}")
                return {}

    def get_profile_post_channels(self, guild_id: int) -> List[int]:
        """Get profile post channels setting for a specific guild."""
        guild_config = self.config.config.get("guilds", {}).get(str(guild_id), {}).get("player_lookup", {})
        return guild_config.get("profile_post_channels", [])

    async def search_player(self, search_term: str) -> List[KnownPlayer]:
        """
        Search for players by name, ID, or Discord info across all data sources

        Args:
            search_term: Name, player ID, or Discord ID/name to search for

        Returns:
            List of matching KnownPlayer objects and UnverifiedPlayer objects
        """
        await self.wait_until_ready()
        search_term = search_term.strip()

        # Apply case sensitivity setting
        if not self.case_sensitive:
            search_term = search_term.lower()

        # If not allowing partial matches, only do exact searches
        if not self.allow_partial_matches:
            # For exact matches, we need to check both verified and unverified sources
            results = []

            # Check verified players first
            verified_player = await self.get_player_by_any(search_term)
            if verified_player:
                results.append(verified_player)

            # Check moderation records for exact tower_id matches
            moderation_results = await sync_to_async(list)(
                ModerationRecord.objects.filter(tower_id__iexact=search_term).values_list("tower_id", flat=True).distinct()
            )
            for tower_id in moderation_results:
                # Only add if not already found as verified player
                if not any(isinstance(r, KnownPlayer) and any(pid.id == tower_id for pid in r.ids.all()) for r in results):
                    unverified_player = UnverifiedPlayer(tower_id)
                    results.append(unverified_player)

            return results
        else:
            # Partial matching enabled - search all sources
            results: List[Any] = []

            # Search verified players
            # Search by name (case insensitive)
            name_results = await sync_to_async(list)(KnownPlayer.objects.filter(name__icontains=search_term))
            results.extend(name_results)

            # Search by player ID
            id_results = await sync_to_async(list)(KnownPlayer.objects.filter(ids__id__icontains=search_term).distinct())
            results.extend([r for r in id_results if r not in results])

            # Search by Discord ID
            discord_results = await sync_to_async(list)(KnownPlayer.objects.filter(discord_id__icontains=search_term))
            results.extend([r for r in discord_results if r not in results])

            # Search by tower_id in ModerationRecord for unverified players
            moderation_results = await sync_to_async(list)(
                ModerationRecord.objects.filter(tower_id__icontains=search_term).values_list("tower_id", flat=True).distinct()
            )
            # For moderation results, create UnverifiedPlayer objects
            for tower_id in moderation_results:
                if not any(isinstance(r, KnownPlayer) and any(pid.id == tower_id for pid in r.ids.all()) for r in results):
                    # Create an UnverifiedPlayer object
                    unverified_player = UnverifiedPlayer(tower_id)
                    results.append(unverified_player)

            return results

    async def _load_settings(self) -> None:
        """Load and initialize default settings."""
        # Ensure player_lookup config section exists
        lookup_config = self.config.config.setdefault("player_lookup", {})

        # Set defaults for any missing settings
        for key, default_value in self.default_settings.items():
            if key not in lookup_config:
                lookup_config[key] = default_value
                self.logger.debug(f"Set default setting {key} = {default_value}")

        # Save the config if any defaults were set
        if lookup_config:
            self.config.save_config()
            self.logger.debug("Saved updated config with default settings")

    # === Slash Commands ===

    @app_commands.command(name="profile", description="View your player profile and verification status")
    async def profile_slash(self, interaction: discord.Interaction) -> None:
        """View your own player profile and verification status."""
        # Default to the caller's own Discord ID
        identifier = str(interaction.user.id)
        await self.user_interactions.handle_profile_command(interaction, identifier)

    @app_commands.command(name="lookup", description="Look up a player by ID, name, or Discord mention")
    @app_commands.describe(identifier="Player ID, name, or mention a Discord user")
    async def lookup_slash(self, interaction: discord.Interaction, identifier: str) -> None:
        """Look up a player by various identifiers."""
        await self.user_interactions.handle_lookup_command(interaction, identifier)

    async def cog_initialize(self) -> None:
        """Initialize the Player Lookup cog."""
        self.logger.info("Initializing PlayerLookup cog")
        try:
            self.logger.info("Starting Player Lookup initialization")

            async with self.task_tracker.task_context("Initialization") as tracker:
                # Initialize parent
                self.logger.debug("Initializing parent cog")
                await super().cog_initialize()

                # Load settings
                self.logger.debug("Loading settings")
                tracker.update_status("Loading settings")
                await self._load_settings()

                # Mark as ready and complete initialization
                self.set_ready(True)
                self.logger.info("Player Lookup initialization complete")

        except Exception as e:
            self.logger.error(f"Player Lookup initialization failed: {e}", exc_info=True)
            self._has_errors = True
            raise

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded"""
        # Call parent unload
        await super().cog_unload()
        self.logger.info("Player Lookup cog unloaded")
