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
from discord.ext import commands

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

        # Track pending role corrections with delayed timers (state-based approach)
        # Each entry is a task that will apply correction after delay if state remains wrong
        self.pending_corrections = {}  # {(guild_id, user_id): asyncio.Task}

        # Role cache for calculated tournament roles
        self.role_cache = {}  # {guild_id: {gameinstance_id: calculated_role_id}}
        self.cache_timestamp = None
        self.cache_latest_tourney_date = None  # Latest tournament date in cache
        self.cache_source_refreshed_at = None  # When source data was refreshed (from tourney_stats)

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
            "correction_delay_seconds": 3.0,  # Wait time before correcting wrong roles (allows changes to settle)
        }

        # Guild-specific settings
        self.guild_settings = {
            "roles_config": {},
            "verified_role_id": None,
            "log_channel_id": None,
            "dry_run_log_channel_id": None,  # Separate log channel for dry run mode (optional)
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
                "cache_source_refreshed_at": self.cache_source_refreshed_at.isoformat() if self.cache_source_refreshed_at else None,
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

                # Validate cache structure - if it uses old Discord-ID-based keys (strings), clear it
                cache_is_valid = True
                for guild_id, guild_cache in self.role_cache.items():
                    if guild_cache:
                        # Check first key - old cache used string Discord IDs, new cache uses int GameInstance IDs
                        first_key = next(iter(guild_cache.keys()))
                        if isinstance(first_key, str):
                            self.logger.warning(
                                f"Detected old cache format (Discord-ID-based) for guild {guild_id}. "
                                "Clearing cache to rebuild with new GameInstance-based format."
                            )
                            cache_is_valid = False
                            break

                if not cache_is_valid:
                    self.logger.info("Clearing outdated role cache - will rebuild on next update")
                    self.role_cache = {}
                    self.cache_timestamp = None
                    self.cache_latest_tourney_date = None
                    self.cache_source_refreshed_at = None
                    # Mark data as modified and save to overwrite old cache file
                    self.mark_data_modified()
                else:
                    # Only load timestamps if cache is valid
                    self.cache_timestamp = datetime.datetime.fromisoformat(save_data["cache_timestamp"]) if save_data.get("cache_timestamp") else None
                    self.cache_latest_tourney_date = (
                        datetime.datetime.fromisoformat(save_data["cache_latest_tourney_date"])
                        if save_data.get("cache_latest_tourney_date")
                        else None
                    )
                    self.cache_source_refreshed_at = (
                        datetime.datetime.fromisoformat(save_data["cache_source_refreshed_at"])
                        if save_data.get("cache_source_refreshed_at")
                        else None
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

    async def build_tourney_stats_embed(
        self,
        player_name: str,
        tower_ids: list,
        guild_id: int,
        discord_id: int = None,
        instance_name: str = None,
    ) -> discord.Embed:
        """Build a tournament stats embed for a set of tower IDs.

        Shared helper used by both TourneyStatsButton and GameInstanceSelect
        to ensure consistent stats display.

        Args:
            player_name: Display name for the player
            tower_ids: List of tower ID strings to aggregate stats for
            guild_id: Guild ID for role comparison
            discord_id: Discord user ID (for role comparison section)
            instance_name: Optional instance name to show in title

        Returns:
            discord.Embed with formatted tournament stats
        """
        tourney_stats_cog = await self.get_tourney_stats_cog()
        if not tourney_stats_cog:
            return discord.Embed(title="❌ Error", description="Tournament stats not available", color=discord.Color.red())

        # Get stats via unified batch path
        batch_stats = await tourney_stats_cog.get_batch_player_stats(set(tower_ids))
        player_stats = await self.core._aggregate_player_stats(tower_ids, batch_stats)

        current_patch = tourney_stats_cog.latest_patch if tourney_stats_cog.latest_patch else "Unknown"

        # Build title
        title = f"📊 Tournament Stats - {player_name}"
        if instance_name:
            title += f" ({instance_name})"

        embed = discord.Embed(
            title=title,
            description=f"Tournament performance for {player_name}",
            color=discord.Color.blue(),
        )

        # Player ID
        primary_id = tower_ids[0] if tower_ids else None
        if primary_id:
            embed.add_field(name="Player ID", value=f"`{primary_id}`", inline=False)

        if player_stats.total_tourneys > 0:
            # Latest Tournament
            latest = player_stats.latest_tournament
            if latest.get("league"):
                latest_text = f"**League:** {latest['league']}\n"
                latest_text += f"**Position:** {latest.get('placement', 'N/A')}\n"
                latest_text += f"**Wave:** {latest.get('wave', 'N/A')}\n"
                if latest.get("date"):
                    latest_text += f"**Date:** {latest['date']}"
                embed.add_field(name="📈 Latest Tournament", value=latest_text, inline=False)

            # Per-league stats
            for league_name, league_stats in player_stats.leagues.items():
                stats_text = []
                stats_text.append(f"**Tournaments:** {league_stats.get('total_tourneys', 0)}")

                # Best position with frequency
                best_position = league_stats.get("best_position", "N/A")
                tournaments = league_stats.get("tournaments", [])

                if tournaments and best_position != "N/A":
                    best_pos_tourneys = [t for t in tournaments if t.get("position") == best_position]
                    count = len(best_pos_tourneys)
                    if count == 1:
                        date = best_pos_tourneys[0].get("date", "")
                        date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
                        stats_text.append(f"**Best Position:** {best_position} ({date_str})")
                    else:
                        dates = sorted(
                            d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for t in best_pos_tourneys for d in [t.get("date", "")]
                        )
                        stats_text.append(f"**Best Position:** {best_position} ({count}x: first {dates[0]}, last {dates[-1]})")
                else:
                    stats_text.append(f"**Best Position:** {best_position}")

                # Highest wave with frequency
                highest_wave = league_stats.get("best_wave", 0)
                if tournaments and highest_wave:
                    best_wave_tourneys = [t for t in tournaments if t.get("wave") == highest_wave]
                    wave_count = len(best_wave_tourneys)
                    if wave_count == 1:
                        date = best_wave_tourneys[0].get("date", "")
                        date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
                        stats_text.append(f"**Highest Wave:** {highest_wave} ({date_str})")
                    else:
                        dates = sorted(
                            d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for t in best_wave_tourneys for d in [t.get("date", "")]
                        )
                        stats_text.append(f"**Highest Wave:** {highest_wave} ({wave_count}x: first {dates[0]}, last {dates[-1]})")
                else:
                    stats_text.append(f"**Highest Wave:** {highest_wave}")

                stats_text.append(f"**Avg Wave:** {league_stats.get('avg_wave', 0):.1f}")
                stats_text.append(f"**Avg Position:** {league_stats.get('avg_position', 0):.1f}")

                embed.add_field(name=f"🏆 {league_name.title()}", value="\n".join(stats_text), inline=True)
        else:
            embed.add_field(name="📈 Performance", value="No tournament participation found", inline=False)

        # Role comparison section
        if discord_id:
            guild = self.bot.get_guild(guild_id)
            if guild:
                member = guild.get_member(discord_id)
                if member:
                    calculated_role_id = None
                    gameinstance_id = await self._get_gameinstance_id_from_discord_id(discord_id)
                    if gameinstance_id and guild_id in self.role_cache:
                        calculated_role_id = self.role_cache[guild_id].get(gameinstance_id)

                    roles_config = self.core.get_roles_config(guild_id)
                    managed_role_ids = {str(config.id) for config in roles_config.values()}

                    if guild_id not in self.role_cache:
                        embed.add_field(
                            name="🎯 Current Tournament Roles",
                            value="⏳ Role calculations are not ready yet. Please use `/tourneyroles update` to calculate roles.",
                            inline=False,
                        )
                    else:
                        guild_role_map = {str(role.id): role.name for role in guild.roles}
                        current_tourney_roles = [role for role in member.roles if str(role.id) in managed_role_ids]
                        current_role_ids = {str(r.id) for r in current_tourney_roles}

                        role_status = []
                        if calculated_role_id:
                            calculated_role_name = guild_role_map.get(str(calculated_role_id), "Unknown")
                            if str(calculated_role_id) in current_role_ids:
                                role_status.append(f"✅ {calculated_role_name}")
                            else:
                                role_status.append(f"❌ {calculated_role_name} (should have)")

                        for role in current_tourney_roles:
                            if str(role.id) != str(calculated_role_id):
                                role_status.append(f"⚠️ {role.name} (has but shouldn't)")

                        if role_status:
                            embed.add_field(name="🎯 Current Tournament Roles", value="\n".join(role_status), inline=False)

        embed.set_footer(text=f"Stats from patch {current_patch}")
        return embed

    async def _get_gameinstance_id_from_player_id(self, player_id: int) -> Optional[int]:
        """Get the game instance ID for a given player ID.

        Args:
            player_id: The player ID to look up (primary or non-primary)

        Returns:
            Game instance ID if found, None otherwise
        """
        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import PlayerId

        def get_gameinstance_id():
            player_id_obj = PlayerId.objects.filter(id=player_id).select_related("game_instance").first()
            return player_id_obj.game_instance.id if player_id_obj and player_id_obj.game_instance else None

        return await sync_to_async(get_gameinstance_id)()

    async def _get_gameinstance_id_from_discord_id(self, discord_id: int) -> Optional[int]:
        """Get the game instance ID for a Discord account via role_source_instance.

        Args:
            discord_id: The Discord account ID

        Returns:
            Game instance ID if found, None otherwise
        """
        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import LinkedAccount

        def get_gameinstance_id():
            linked_account = (
                LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=str(discord_id))
                .select_related("role_source_instance")
                .first()
            )
            return linked_account.role_source_instance.id if linked_account and linked_account.role_source_instance else None

        return await sync_to_async(get_gameinstance_id)()

    # ============================================================================
    # NEW SIMPLIFIED ROLE CALCULATION AND CACHING SYSTEM
    # ============================================================================

    def _clear_cache(self, guild_id: int, gameinstance_id: int = None) -> None:
        """Clear role cache entries.

        Args:
            guild_id: Guild to clear cache for
            gameinstance_id: Specific GameInstance to clear, or None to clear entire guild
        """
        if gameinstance_id is None:
            # Clear entire guild cache
            if guild_id in self.role_cache:
                count = len(self.role_cache[guild_id])
                self.role_cache[guild_id] = {}
                self.logger.info(f"Cleared {count} cached roles for guild {guild_id}")
                self.cache_timestamp = None
                self.cache_latest_tourney_date = None
        else:
            # Clear specific GameInstance
            if guild_id in self.role_cache and gameinstance_id in self.role_cache[guild_id]:
                del self.role_cache[guild_id][gameinstance_id]
                self.logger.debug(f"Cleared cached role for GameInstance {gameinstance_id} in guild {guild_id}")

    async def _calculate_role_for_gameinstance(
        self, gameinstance_id: int, guild_id: int, tower_ids: list = None, batch_stats: dict = None
    ) -> Optional[int]:
        """Calculate the appropriate tournament role for a GameInstance.

        Pure calculation - does not touch cache. Supports both one-off and batch modes
        via a single aggregation path (_aggregate_player_stats → determine_best_role).

        Args:
            gameinstance_id: Database ID of the GameInstance
            guild_id: Guild to calculate role for
            tower_ids: Pre-loaded tower IDs for this GameInstance (skip DB lookup if provided)
            batch_stats: Pre-loaded batch stats from get_batch_player_stats (skip stats fetch if provided)

        Returns:
            Role ID (int) if a qualifying role exists, None otherwise
        """
        try:
            # Step 1: Get tower IDs (from caller or DB)
            if tower_ids is None:
                from asgiref.sync import sync_to_async

                from thetower.backend.sus.models import GameInstance

                game_instance = await sync_to_async(
                    lambda: GameInstance.objects.select_related("player").prefetch_related("player_ids").filter(id=gameinstance_id).first()
                )()

                if not game_instance:
                    self.logger.warning(f"GameInstance {gameinstance_id} not found in database")
                    return None

                player_ids = await sync_to_async(list)(game_instance.player_ids.all())
                tower_ids = [pid.id for pid in player_ids]

            if not tower_ids:
                self.logger.debug(f"GameInstance {gameinstance_id} has no player IDs")
                return None

            self.logger.debug(f"GameInstance {gameinstance_id} has player IDs: {tower_ids}")

            # Step 2: Get batch stats (from caller or fetch on demand)
            if batch_stats is None:
                tourney_stats_cog = await self.get_tourney_stats_cog()
                if not tourney_stats_cog:
                    self.logger.error("TourneyStats cog not available")
                    return None
                batch_stats = await tourney_stats_cog.get_batch_player_stats(set(tower_ids))

            # Step 3: Aggregate stats via single unified path
            player_stats = await self.core._aggregate_player_stats(tower_ids, batch_stats)

            if not player_stats or player_stats.total_tourneys == 0:
                self.logger.debug(f"No tournament stats found for GameInstance {gameinstance_id}")
                return None

            # Step 4: Determine best role using guild-specific config
            roles_config = self.core.get_roles_config(guild_id)
            league_hierarchy = self.core.get_league_hierarchy(guild_id)
            debug_logging = self.get_global_setting("debug_logging", False)

            role_id = self.core.determine_best_role(player_stats, roles_config, league_hierarchy, debug_logging)

            if role_id:
                self.logger.debug(f"Calculated role {role_id} for GameInstance {gameinstance_id} in guild {guild_id}")
            else:
                self.logger.debug(f"No qualifying role for GameInstance {gameinstance_id} in guild {guild_id}")

            return int(role_id) if role_id else None

        except Exception as e:
            self.logger.error(f"Error calculating role for GameInstance {gameinstance_id}: {e}", exc_info=True)
            return None

    def _cache_role(self, gameinstance_id: int, guild_id: int, role_id: Optional[int]) -> None:
        """Store a calculated role in cache.

        Args:
            gameinstance_id: Database ID of the GameInstance
            guild_id: Guild this role applies to
            role_id: Role ID to cache, or None if no qualifying role
        """
        if guild_id not in self.role_cache:
            self.role_cache[guild_id] = {}

        self.role_cache[guild_id][gameinstance_id] = role_id
        self.logger.debug(f"Cached role {role_id} for GameInstance {gameinstance_id} in guild {guild_id}")

    async def _calculate_and_cache_role_for_gameinstance(self, gameinstance_id: int, guild_id: int, force: bool = False) -> Optional[int]:
        """Calculate and cache the role for a GameInstance.

        Combines calculation and caching in one operation.

        Args:
            gameinstance_id: Database ID of the GameInstance
            guild_id: Guild to calculate role for
            force: If True, always calculate even if cached. If False, return cached value if available.

        Returns:
            Role ID if calculated, None otherwise
        """
        # Check cache first unless force is True
        if not force:
            cached_role_id = self.role_cache.get(guild_id, {}).get(gameinstance_id)
            if cached_role_id is not None:
                self.logger.debug(f"Using cached role {cached_role_id} for GameInstance {gameinstance_id} in guild {guild_id}")
                return cached_role_id

        # Calculate and cache
        role_id = await self._calculate_role_for_gameinstance(gameinstance_id, guild_id)
        self._cache_role(gameinstance_id, guild_id, role_id)
        return role_id

    async def _apply_role_for_discord_account(self, discord_id: int, guild_id: int) -> dict:
        """Apply the cached tournament role to a Discord account.

        Looks up the account's role source GameInstance, finds the cached role,
        and updates their Discord roles accordingly.

        Args:
            discord_id: Discord account ID
            guild_id: Guild to apply roles in

        Returns:
            Dict with stats: {
                "roles_added": int,
                "roles_removed": int,
                "errors": int,
                "skipped": str (reason) or None
            }
        """
        stats = {"roles_added": 0, "roles_removed": 0, "errors": 0, "skipped": None}

        try:
            # Get guild
            guild = self.bot.get_guild(guild_id)
            if not guild:
                stats["errors"] = 1
                stats["skipped"] = "guild_not_found"
                return stats

            # Get member
            member = guild.get_member(discord_id)
            if not member:
                stats["skipped"] = "not_in_guild"
                return stats

            # Get role source GameInstance ID using utility method
            gameinstance_id = await self._get_gameinstance_id_from_discord_id(discord_id)
            if not gameinstance_id:
                stats["skipped"] = "no_role_source"
                return stats

            # Check verification requirement
            verified_role_id = self.core.get_verified_role_id(guild_id)
            if verified_role_id:
                verified_role = guild.get_role(int(verified_role_id))
                if verified_role and verified_role not in member.roles:
                    # User not verified - remove all tournament roles if they have any
                    roles_config = self.core.get_roles_config(guild_id)
                    all_managed_role_ids = {str(config.id) for config in roles_config.values()}
                    current_tourney_roles = [role for role in member.roles if str(role.id) in all_managed_role_ids]

                    if current_tourney_roles:
                        new_roles = [role for role in member.roles if str(role.id) not in all_managed_role_ids and not role.is_default()]
                        try:
                            dry_run = self.get_global_setting("dry_run", False)
                            if not dry_run:
                                await member.edit(roles=new_roles, reason="Removing tournament roles - not verified")
                            stats["roles_removed"] = len(current_tourney_roles)
                            for role in current_tourney_roles:
                                self.bot.dispatch("tourney_role_removed", member, role)
                        except Exception as e:
                            self.logger.error(f"Error removing roles from {member.name}: {e}")
                            stats["errors"] = 1

                    stats["skipped"] = "not_verified"
                    return stats

            # Look up cached role using gameinstance_id
            cached_role_id = self.role_cache.get(guild_id, {}).get(gameinstance_id)

            # Get all managed tournament role IDs
            roles_config = self.core.get_roles_config(guild_id)
            all_managed_role_ids = {str(config.id) for config in roles_config.values()}

            # Find current tournament roles
            current_tourney_roles = {str(role.id): role for role in member.roles if str(role.id) in all_managed_role_ids}

            # Build new role list
            new_roles = [role for role in member.roles if str(role.id) not in all_managed_role_ids and not role.is_default()]

            changes = []

            # Add cached role if it exists
            if cached_role_id:
                role = guild.get_role(cached_role_id)
                if role:
                    new_roles.append(role)
                    if str(cached_role_id) not in current_tourney_roles:
                        changes.append(f"+{role.name}")
                        stats["roles_added"] = 1

            # Track removed roles
            for role_id_str, role in current_tourney_roles.items():
                if str(cached_role_id) != role_id_str:
                    changes.append(f"-{role.name}")
                    stats["roles_removed"] += 1

            # Apply changes if any
            if changes:
                try:
                    dry_run = self.get_global_setting("dry_run", False)
                    if not dry_run:
                        await member.edit(roles=new_roles, reason="Tournament role update")

                    # Dispatch events
                    for change in changes:
                        if change.startswith("+"):
                            role_name = change[1:]
                            added_role = next((r for r in new_roles if r.name == role_name and str(r.id) in all_managed_role_ids), None)
                            if added_role:
                                self.bot.dispatch("tourney_role_added", member, added_role)
                        elif change.startswith("-"):
                            role_name = change[1:]
                            removed_role = next((r for r_id, r in current_tourney_roles.items() if r.name == role_name), None)
                            if removed_role:
                                self.bot.dispatch("tourney_role_removed", member, removed_role)

                    # Log changes - respect guild's immediate_logging setting
                    immediate = self.get_setting("immediate_logging", default=True, guild_id=guild_id)
                    await self.log_role_change(guild_id, member.name, changes, immediate=immediate)

                except Exception as e:
                    self.logger.error(f"Error updating roles for {member.name}: {e}")
                    stats["errors"] = 1

            return stats

        except Exception as e:
            self.logger.error(f"Error applying role for Discord account {discord_id}: {e}", exc_info=True)
            stats["errors"] = 1
            return stats

    # ============================================================================
    # END NEW SIMPLIFIED ROLE SYSTEM
    # ============================================================================

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

        # Check if we're in dry run mode and use appropriate channel
        dry_run = self.get_global_setting("dry_run", False)
        if dry_run:
            # In dry run mode, only use dry_run_log_channel_id (no fallback to regular channel)
            log_channel_id = self.get_setting("dry_run_log_channel_id", guild_id=guild_id)
        else:
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

                tourney_stats_cog = await self.get_tourney_stats_cog()
                if tourney_stats_cog:
                    # Wait for tourney_stats to be ready to avoid race condition
                    if hasattr(tourney_stats_cog, "ready"):
                        self.logger.debug("Waiting for TourneyStats cog to be ready...")
                        await tourney_stats_cog.ready.wait()

                    # Get latest tournament date and refresh time from TourneyStats cog
                    latest_tourney_date = tourney_stats_cog.latest_tournament_date
                    source_refreshed_at = tourney_stats_cog.last_updated

                    if latest_tourney_date:
                        self.logger.info(f"Latest tournament date in database: {latest_tourney_date}")
                        if source_refreshed_at:
                            self.logger.info(f"Source data last refreshed at: {source_refreshed_at}")

                        # Compare with cached data
                        if self.cache_latest_tourney_date:
                            # Check if tournament date is newer
                            tourney_date_newer = latest_tourney_date > self.cache_latest_tourney_date

                            # Check if source was refreshed after our cache was built
                            source_newer = False
                            if source_refreshed_at and self.cache_source_refreshed_at:
                                source_newer = source_refreshed_at > self.cache_source_refreshed_at

                            if tourney_date_newer:
                                self.logger.info(
                                    f"Newer tournament data available: {latest_tourney_date} > {self.cache_latest_tourney_date}. "
                                    "Cache will be rebuilt on next full update."
                                )
                            elif source_newer:
                                self.logger.info(
                                    f"Source data was refreshed ({source_refreshed_at} > {self.cache_source_refreshed_at}). "
                                    "Cache will be rebuilt on next full update."
                                )
                            else:
                                self.logger.info(
                                    f"Cache is up to date (tournament date: {self.cache_latest_tourney_date}, "
                                    f"source refreshed: {self.cache_source_refreshed_at})"
                                )
                        else:
                            self.logger.info("No cached tournament date found - cache will be built on first update")
                    else:
                        self.logger.warning("TourneyStats cog ready but has no tournament date loaded yet")
                else:
                    self.logger.warning("TourneyStats cog not available for tournament date check")

                # 4. Run startup role update if enabled
                if self.get_global_setting("update_on_startup", True):
                    self.logger.debug("Running startup role update")
                    tracker.update_status("Running startup role update")
                    # TODO: Implement a loop to check all discord accounts.

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

        # Extract game instances from new structure
        game_instances = details.get("game_instances", [])
        if not game_instances:
            return None

        return TourneyStatsInstanceSelectorButton(self, details, guild_id)

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

        # Extract game instances from new structure
        game_instances = details.get("game_instances", [])
        if not game_instances:
            return None

        # Check if requesting user is viewing their own profile
        # Need to check all discord accounts across all instances
        all_discord_accounts = set()
        for instance in game_instances:
            all_discord_accounts.update(instance.get("discord_accounts_receiving_roles", []))
        # Also check unassigned accounts
        all_discord_accounts.update(details.get("unassigned_discord_accounts", []))

        is_own_profile = str(requesting_user.id) in all_discord_accounts

        if is_own_profile:
            # If single instance, create button directly
            if len(game_instances) == 1:
                instance = game_instances[0]
                discord_accounts = instance.get("discord_accounts_receiving_roles", [])
                if discord_accounts:
                    discord_id = discord_accounts[0]  # Use first Discord account
                    return TourneySelfRefreshButton(self, int(discord_id), guild_id)
                return None
            # Multiple instances - return selector button
            return TourneyRolesInstanceSelectorButton(self, details, guild_id, requesting_user.id, is_self_refresh=True)
        else:
            # For other users, check if requesting user has permission to refresh roles
            authorized_groups = self.get_setting("authorized_refresh_groups", guild_id=guild_id, default=[])
            if authorized_groups and permission_context.has_any_group(authorized_groups):
                # If single instance, create button directly
                if len(game_instances) == 1:
                    instance = game_instances[0]
                    discord_accounts = instance.get("discord_accounts_receiving_roles", [])
                    if discord_accounts:
                        discord_id = discord_accounts[0]  # Use first Discord account
                        return TourneyRolesRefreshButton(self, int(discord_id), guild_id, requesting_user.id)
                    return None
                # Multiple instances - return selector button
                return TourneyRolesInstanceSelectorButton(self, details, guild_id, requesting_user.id, is_self_refresh=False)

            return None

    async def cog_unload(self):
        """Clean up when cog is unloaded"""
        # Flush any remaining log buffers before shutdown
        try:
            await self.flush_log_buffer()
        except Exception as e:
            self.logger.error(f"Error flushing log buffers during unload: {e}")

        # Cancel all pending correction timers
        for task in self.pending_corrections.values():
            task.cancel()
        self.pending_corrections.clear()

        if self.update_task:
            self.update_task.cancel()
        await super().cog_unload()
        self.logger.info("Tournament roles cog unloaded")

    async def _delayed_correction(self, guild_id: int, user_id: int, expected_role_id: int):
        """Apply role correction after delay if state is still wrong.

        Args:
            guild_id: Guild ID
            user_id: User ID
            expected_role_id: The role ID that should be applied
        """
        try:
            # Wait for configured delay
            delay = self.get_global_setting("correction_delay_seconds", 3.0)
            await asyncio.sleep(delay)

            # Get guild and member from cache (cache is current since no events = no changes during timer)
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return

            member = guild.get_member(user_id)
            if not member:
                return  # User left server during timer

            # Get current state
            roles_config = self.core.get_roles_config(guild_id)
            managed_role_ids = {str(config.id) for config in roles_config.values()}
            current_tourney_roles = {role.id for role in member.roles if str(role.id) in managed_role_ids}

            # Check if state is now correct (defensive check, should still be wrong)
            if expected_role_id in current_tourney_roles and len(current_tourney_roles) == 1:
                self.logger.debug(f"Timer expired but {member.name} now has correct role - ignoring")
                return

            # Apply correction
            await self._apply_role_correction(member, expected_role_id, guild_id, current_tourney_roles)

        except asyncio.CancelledError:
            # Timer was cancelled because state became correct
            pass
        except Exception as e:
            self.logger.error(f"Error in delayed correction for user {user_id}: {e}", exc_info=True)
        finally:
            # Clean up pending correction only if we're still the tracked task
            # This prevents cancelled tasks from removing newer task references
            member_key = (guild_id, user_id)
            if self.pending_corrections.get(member_key) is asyncio.current_task():
                self.pending_corrections.pop(member_key, None)

    async def _apply_role_correction(self, member: discord.Member, expected_role_id: int, guild_id: int, current_tourney_roles: set):
        """Apply the actual role correction.

        Args:
            member: Discord member
            expected_role_id: Role ID that should be applied
            guild_id: Guild ID
            current_tourney_roles: Set of current tournament role IDs
        """
        try:
            expected_role = member.guild.get_role(expected_role_id)
            if not expected_role:
                self.logger.warning(f"Expected role {expected_role_id} not found in guild")
                return

            changes = []

            # Determine what needs to change
            if expected_role_id not in current_tourney_roles:
                # Add missing role
                await member.add_roles(expected_role, reason="Correcting tournament role")
                changes.append(f"+{expected_role.name}")
                self.logger.info(f"Restored tournament role {expected_role.name} to {member.name}")
                self.bot.dispatch("tourney_role_added", member, expected_role)

            # Remove extra roles
            if len(current_tourney_roles) > 1:
                roles_to_remove = []
                for role_id in current_tourney_roles:
                    if role_id != expected_role_id:
                        role = member.guild.get_role(role_id)
                        if role:
                            roles_to_remove.append(role)

                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove, reason="Removing extra tournament roles")
                    for role in roles_to_remove:
                        changes.append(f"-{role.name}")
                        self.bot.dispatch("tourney_role_removed", member, role)
                    removed_names = [r.name for r in roles_to_remove]
                    self.logger.info(f"Removed extra tournament roles {removed_names} from {member.name}")

            # Log changes
            if changes:
                await self.log_role_change(guild_id, member.name, changes, immediate=True)

        except Exception as e:
            self.logger.error(f"Error applying role correction for {member.name}: {e}", exc_info=True)

    @discord.ext.commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Monitor role changes and handle tournament roles using state-based correction.

        Handles:
        1. Verified role changes (add/remove tournament roles)
        2. State-based tournament role corrections with delayed timer
        """
        try:
            # Only process if this cog is enabled for the guild
            if not self.bot.cog_manager.can_guild_use_cog(self.cog_name, after.guild.id, False):
                return

            member_key = (after.guild.id, after.id)

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
                        # Role added - calculate and apply tournament roles
                        self.logger.info(f"Member {after.name} ({after.id}) gained verified role - applying tournament roles")

                        # Get user's GameInstance ID
                        gameinstance_id = await self._get_gameinstance_id_from_discord_id(after.id)

                        if gameinstance_id:
                            # Calculate and cache role for this GameInstance (force=True to ensure fresh calculation)
                            await self._calculate_and_cache_role_for_gameinstance(gameinstance_id, after.guild.id, force=True)

                            # Apply the cached role to the Discord account
                            await self._apply_role_for_discord_account(after.id, after.guild.id)
                        else:
                            self.logger.info(f"User {after.name} ({after.id}) has no game instance - skipping role calculation")

                        return  # Don't process tournament role corrections for this update
                    else:
                        # Role removed - remove tournament roles
                        self.logger.info(f"Member {after.name} ({after.id}) lost verified role - removing tournament roles")

                        # Apply roles (will remove all tournament roles since verification check fails)
                        await self._apply_role_for_discord_account(after.id, after.guild.id)
                        return  # Don't process tournament role corrections for this update

            # Check if tournament roles changed
            roles_config = self.core.get_roles_config(after.guild.id)
            managed_role_ids = {str(config.id) for config in roles_config.values()}

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

                # Get expected role from cache (cache is GameInstance-based, not Discord-ID-based)
                gameinstance_id = await self._get_gameinstance_id_from_discord_id(after.id)
                if not gameinstance_id:
                    self.logger.debug(f"No GameInstance found for {after.name} - ignoring role change")
                    return

                expected_role_id = self.role_cache.get(after.guild.id, {}).get(gameinstance_id)

                if not expected_role_id:
                    # No cached role - user shouldn't have tournament roles
                    self.logger.debug(f"No cached role for {after.name} (GameInstance {gameinstance_id}) - ignoring role change")
                    return

                # STATE-BASED CHECK: Is current state correct?
                expected_role_id_int = int(expected_role_id)
                if expected_role_id_int in after_tourney_roles and len(after_tourney_roles) == 1:
                    # State is correct! Cancel any pending correction
                    if member_key in self.pending_corrections:
                        self.pending_corrections[member_key].cancel()
                        del self.pending_corrections[member_key]
                        self.logger.debug(f"Role change for {after.name} resulted in correct state - cancelled pending correction")
                    return  # No work needed

                # State is wrong - start or reset delayed correction timer
                if member_key in self.pending_corrections:
                    # Cancel existing timer and start new one (extends wait period)
                    self.pending_corrections[member_key].cancel()
                    self.logger.debug(f"Resetting correction timer for {after.name}")
                else:
                    self.logger.info(f"Starting correction timer for {after.name} (expected: {expected_role_id}, current: {after_tourney_roles})")

                # Create new delayed correction task
                self.pending_corrections[member_key] = asyncio.create_task(self._delayed_correction(after.guild.id, after.id, expected_role_id_int))

        except Exception as e:
            self.logger.error(f"Error in on_member_update: {e}", exc_info=True)

    @discord.ext.commands.Cog.listener()
    async def on_tourney_data_refreshed(self, data: dict):
        """Called when TourneyStats has refreshed its tournament data.

        Implements the new simplified role update flow:
        1. Clear all role caches (data is now stale)
        2. Calculate roles for all GameInstances
        3. Apply roles to all Discord accounts

        Args:
            data: Dictionary containing:
                - latest_date: The newest tournament date
                - patch: Current game patch
                - total_tournaments: Total number of tournaments
                - league_counts: Tournament counts per league
                - refreshed_at: When the source data was refreshed
        """
        try:
            latest_date = data.get("latest_date")
            refreshed_at = data.get("refreshed_at")
            patch = data.get("patch")
            total_tournaments = data.get("total_tournaments")
            self.logger.info(
                f"Received tourney_data_refreshed signal: date={latest_date}, patch={patch}, "
                f"total_tournaments={total_tournaments}, refreshed_at={refreshed_at}"
            )

            # Check global pause setting
            if self.get_global_setting("pause", False):
                self.logger.info("Role updates are globally paused, ignoring tournament data refresh")
                return

            # Prevent concurrent updates
            if self.currently_updating:
                self.logger.warning("Role update already in progress, skipping tournament data refresh")
                return

            self.currently_updating = True

            try:
                async with self.task_tracker.task_context("Tournament Data Refresh"):
                    start_time = datetime.datetime.now(datetime.timezone.utc)

                    # Get all enabled guilds
                    enabled_guilds = [g for g in self.bot.guilds if self.bot.cog_manager.can_guild_use_cog(self.cog_name, g.id, False)]

                    if not enabled_guilds:
                        self.logger.info("No guilds have TourneyRoles enabled")
                        return

                    # Phase 1: Clear all caches
                    self.logger.info(f"Phase 1: Clearing role caches for {len(enabled_guilds)} guilds")
                    for guild in enabled_guilds:
                        self._clear_cache(guild.id)

                    # Phase 2: Calculate roles for all GameInstances (batch-optimized)
                    self.logger.info("Phase 2: Calculating roles for all GameInstances")

                    from asgiref.sync import sync_to_async

                    from thetower.backend.sus.models import GameInstance

                    # Step 2a: Bulk load all GameInstances with their player_ids in ONE query
                    all_game_instances = await sync_to_async(list)(GameInstance.objects.prefetch_related("player_ids").all())

                    if not all_game_instances:
                        self.logger.warning("No GameInstances found in database")
                        return

                    # Step 2b: Collect all unique tower IDs and build per-GameInstance mapping
                    gi_player_ids = {}  # gi.id -> list of tower_id strings
                    all_tower_ids = set()

                    for gi in all_game_instances:
                        # Access prefetched player_ids (no additional DB query)
                        tower_ids = [pid.id for pid in gi.player_ids.all()]
                        gi_player_ids[gi.id] = tower_ids
                        all_tower_ids.update(tower_ids)

                    self.logger.info(f"Found {len(all_game_instances)} GameInstances with {len(all_tower_ids)} unique tower IDs")

                    # Step 2c: Get tournament stats for ALL players in one batch operation
                    tourney_stats_cog = await self.get_tourney_stats_cog()
                    if not tourney_stats_cog:
                        self.logger.error("TourneyStats cog not available, cannot calculate roles")
                        return

                    batch_stats = await tourney_stats_cog.get_batch_player_stats(all_tower_ids)
                    self.logger.info(f"Batch stats loaded for {len(batch_stats)} players")

                    # Step 2d: Calculate and cache roles per GameInstance per guild
                    calculated_count = 0
                    error_count = 0

                    for gi in all_game_instances:
                        tower_ids = gi_player_ids.get(gi.id, [])

                        for guild in enabled_guilds:
                            try:
                                role_id = await self._calculate_role_for_gameinstance(gi.id, guild.id, tower_ids=tower_ids, batch_stats=batch_stats)
                                self._cache_role(gi.id, guild.id, role_id)
                                calculated_count += 1
                            except Exception as e:
                                self.logger.error(f"Error calculating role for GameInstance {gi.id} in guild {guild.id}: {e}")
                                self._cache_role(gi.id, guild.id, None)
                                error_count += 1

                        # Yield control periodically
                        await asyncio.sleep(0)

                    calculation_duration = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds()
                    self.logger.info(
                        f"Calculated {calculated_count} roles ({error_count} errors) in {calculation_duration:.1f}s "
                        f"({calculated_count/calculation_duration:.1f} roles/sec)"
                    )

                    # Phase 3: Apply roles to all Discord accounts
                    self.logger.info("Phase 3: Applying roles to all Discord members")

                    from thetower.backend.sus.models import LinkedAccount

                    # Get all Discord accounts with role sources
                    discord_accounts = await sync_to_async(list)(
                        LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, role_source_instance__isnull=False)
                        .select_related("role_source_instance")
                        .values_list("account_id", flat=True)
                    )

                    self.logger.info(f"Found {len(discord_accounts)} Discord accounts with role sources")

                    # Apply roles per guild
                    total_applied = 0
                    total_added = 0
                    total_removed = 0
                    total_errors = 0

                    for guild in enabled_guilds:
                        # Check guild-level pause
                        if self.get_setting("pause", default=False, guild_id=guild.id):
                            self.logger.info(f"Guild {guild.name} has paused role updates, skipping")
                            continue

                        guild_stats = {"added": 0, "removed": 0, "errors": 0, "processed": 0}

                        for discord_id_str in discord_accounts:
                            try:
                                discord_id = int(discord_id_str)
                                result = await self._apply_role_for_discord_account(discord_id, guild.id)

                                if result["skipped"] is None:  # Actually processed
                                    guild_stats["added"] += result["roles_added"]
                                    guild_stats["removed"] += result["roles_removed"]
                                    guild_stats["errors"] += result["errors"]
                                    guild_stats["processed"] += 1

                            except Exception as e:
                                self.logger.error(f"Error applying role for Discord account {discord_id_str} in guild {guild.id}: {e}")
                                guild_stats["errors"] += 1

                            # Yield control periodically
                            await asyncio.sleep(0)

                        # Flush log buffer for this guild
                        await self.flush_log_buffer(guild.id)

                        self.logger.info(
                            f"Guild {guild.name}: processed {guild_stats['processed']}, "
                            f"added {guild_stats['added']}, removed {guild_stats['removed']}, errors {guild_stats['errors']}"
                        )

                        total_applied += guild_stats["processed"]
                        total_added += guild_stats["added"]
                        total_removed += guild_stats["removed"]
                        total_errors += guild_stats["errors"]

                    # Update metadata
                    self.cache_timestamp = datetime.datetime.now(datetime.timezone.utc)
                    self.cache_latest_tourney_date = latest_date
                    self.cache_source_refreshed_at = refreshed_at
                    self.last_full_update = self.cache_timestamp
                    self.logger.info(
                        f"Updated cache metadata: timestamp={self.cache_timestamp}, "
                        f"tourney_date={self.cache_latest_tourney_date}, source_refreshed_at={self.cache_source_refreshed_at}"
                    )

                    # Save data
                    self.mark_data_modified()
                    await self.save_data()

                    total_duration = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds()
                    self.logger.info(
                        f"Tournament data refresh complete in {total_duration:.1f}s: "
                        f"{total_applied} accounts processed, {total_added} roles added, {total_removed} roles removed, {total_errors} errors"
                    )

            finally:
                self.currently_updating = False

        except Exception as e:
            self.logger.error(f"Error handling tourney_data_refreshed event: {e}", exc_info=True)
            self.currently_updating = False

    @commands.Cog.listener()
    async def on_player_verified(self, guild_id: int, discord_id: str, primary_player_id: int, old_primary_player_id: int = None) -> None:
        """Event listener triggered when a player is verified or primary player ID changes.

        This allows TourneyRoles to invalidate and recalculate roles for the player
        without requiring direct coupling between validation and tourney_roles cogs.

        Processes ALL guilds where the player is a member and TourneyRoles is enabled,
        not just the guild where verification occurred.

        Args:
            guild_id: Guild where verification occurred (for logging)
            discord_id: Discord account ID that was verified
            primary_player_id: The new primary player ID (tower ID)
            old_primary_player_id: The old primary player ID (if it changed), or None for new verifications
        """
        try:
            self.logger.info(
                f"Player verified event: origin_guild={guild_id}, discord_id={discord_id}, " f"new={primary_player_id}, old={old_primary_player_id}"
            )

            # Find all guilds where this Discord user is a member AND TourneyRoles is enabled
            target_guilds = []
            for guild in self.bot.guilds:
                # Check if cog is enabled for this guild
                if not self.is_cog_enabled_for_guild(guild.id):
                    continue

                # Check if the Discord user is a member of this guild
                member = guild.get_member(int(discord_id))
                if member:
                    target_guilds.append(guild.id)

            if not target_guilds:
                self.logger.debug(f"Discord user {discord_id} not found in any guilds with TourneyRoles enabled")
                return

            self.logger.info(f"Processing verification for {len(target_guilds)} guild(s): {target_guilds}")

            # Process each guild where the player is a member
            for target_guild_id in target_guilds:
                try:
                    # Get the game instance that contains the new player ID
                    # (old player ID won't exist in DB anymore if it was changed)
                    gameinstance_id = await self._get_gameinstance_id_from_player_id(primary_player_id)

                    if not gameinstance_id:
                        self.logger.warning(f"No game instance found for player ID {primary_player_id} in guild {target_guild_id}")
                        continue

                    # Clear cache for this game instance (player data has changed)
                    self._clear_cache(target_guild_id, gameinstance_id=gameinstance_id)

                    # Calculate and cache role for this game instance
                    await self._calculate_and_cache_role_for_gameinstance(gameinstance_id, target_guild_id)

                    # Apply role to the Discord account
                    await self._apply_role_for_discord_account(int(discord_id), target_guild_id)

                except Exception as e:
                    self.logger.error(f"Error processing verification for guild {target_guild_id}: {e}", exc_info=True)

        except Exception as e:
            self.logger.error(f"Error handling player_verified event: {e}", exc_info=True)

    async def refresh_user_roles_for_user(self, user_id: int, guild_id: int) -> str:
        """Public method for other cogs to refresh tournament roles for a specific user.

        Uses the new simplified system:
        1. Get user's GameInstance ID
        2. Calculate and cache role for that GameInstance
        3. Apply cached role to Discord account

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

            # Get user's GameInstance ID using utility method
            gameinstance_id = await self._get_gameinstance_id_from_discord_id(user_id)
            if not gameinstance_id:
                return "❌ Player data not found."

            # Calculate and cache role for this GameInstance
            await self._calculate_and_cache_role_for_gameinstance(gameinstance_id, guild_id)

            # Apply the cached role to the Discord account
            apply_result = await self._apply_role_for_discord_account(user_id, guild_id)

            # Check for errors
            if apply_result.get("errors", 0) > 0:
                return "❌ Error updating roles"

            # Handle skip reasons
            if apply_result.get("skipped"):
                skip_reason = apply_result["skipped"]
                if skip_reason == "not_verified":
                    return "❌ User not verified for tournament roles"
                elif skip_reason == "no_role_source":
                    return "❌ No role source configured for this account"
                elif skip_reason == "not_in_guild":
                    return "❌ User not found in server"
                else:
                    return f"❌ Skipped: {skip_reason}"

            # Format response based on dry_run mode
            dry_run = self.get_global_setting("dry_run", False)
            roles_added = apply_result.get("roles_added", 0)
            roles_removed = apply_result.get("roles_removed", 0)

            if dry_run:
                if roles_added > 0 or roles_removed > 0:
                    changes = []
                    if roles_added > 0:
                        changes.append(f"would add {roles_added} role(s)")
                    if roles_removed > 0:
                        changes.append(f"would remove {roles_removed} role(s)")
                    return f"🔍 DRY RUN: {', '.join(changes)}"
                return "🔍 DRY RUN: No role changes needed"
            else:
                if roles_added > 0 or roles_removed > 0:
                    changes = []
                    if roles_added > 0:
                        changes.append(f"added {roles_added} role(s)")
                    if roles_removed > 0:
                        changes.append(f"removed {roles_removed} role(s)")
                    return f"✅ {', '.join(changes)}"
                return "✅ No role changes needed"

        except Exception as e:
            self.logger.error(f"Error refreshing roles for user {user_id}: {e}", exc_info=True)
            return f"❌ Error updating roles: {str(e)}"


class TourneyStatsInstanceSelectorButton(discord.ui.Button):
    """Button to view tournament stats. Handles single and multiple game instances."""

    def __init__(self, cog, details: dict, guild_id: int):
        super().__init__(label="View Tournament Stats", style=discord.ButtonStyle.secondary, emoji="📊", row=2)
        self.cog = cog
        self.details = details
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Show tournament stats — auto-select for single instance, dropdown for multiple."""
        game_instances = self.details.get("game_instances", [])
        player_name = self.details.get("account_name") or self.details.get("name", "Unknown")

        if len(game_instances) == 1:
            # Single instance — go straight to loading → stats
            await self._show_single_instance_stats(interaction, game_instances[0], player_name)
        else:
            # Multiple instances — show placeholder embed + dropdown
            placeholder_embed = discord.Embed(
                title=f"📊 Tournament Stats - {player_name}",
                description="Select a game account below to view tournament stats.",
                color=discord.Color.light_grey(),
            )

            select = GameInstanceSelect(
                placeholder="Select a game account...",
                game_instances=game_instances,
                player_name=player_name,
                button_type="stats",
                cog=self.cog,
                guild_id=self.guild_id,
            )

            view = discord.ui.View(timeout=300)
            view.add_item(select)

            await interaction.response.send_message(
                embed=placeholder_embed,
                view=view,
                ephemeral=True,
            )

    async def _show_single_instance_stats(self, interaction: discord.Interaction, instance: dict, player_name: str):
        """Show stats for a single game instance directly (no dropdown)."""
        # Send loading embed
        loading_embed = discord.Embed(
            title="📊 Loading Tournament Stats...",
            description=f"Gathering tournament data for {player_name}...",
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=loading_embed, ephemeral=True)

        try:
            # Get tower IDs from the instance
            tower_ids = instance.get("all_player_ids", [])
            if not tower_ids:
                tower_ids = [pid["id"] for pid in instance.get("player_ids", [])]

            if not tower_ids:
                error_embed = discord.Embed(title="❌ Error", description="No player IDs found", color=discord.Color.red())
                await interaction.edit_original_response(embed=error_embed)
                return

            # Get discord_id for role comparison
            discord_accounts = instance.get("discord_accounts_receiving_roles", [])
            discord_id = int(discord_accounts[0]) if discord_accounts else None

            # Build embed using shared helper
            embed = await self.cog.build_tourney_stats_embed(
                player_name=player_name,
                tower_ids=tower_ids,
                guild_id=self.guild_id,
                discord_id=discord_id,
            )

            # View with just Post Publicly button (no dropdown needed)
            view = discord.ui.View(timeout=300)
            view.add_item(TourneyStatsPostPubliclyButton(embed, interaction.guild.id, interaction.channel.id, self.cog))

            await interaction.edit_original_response(embed=embed, view=view)

        except Exception as e:
            self.cog.logger.error(f"Error showing tournament stats: {e}", exc_info=True)
            error_embed = discord.Embed(title="❌ Error", description=f"Error loading stats: {str(e)}", color=discord.Color.red())
            await interaction.edit_original_response(embed=error_embed)


class TourneyRolesInstanceSelectorButton(discord.ui.Button):
    """Button that opens a game instance selector for role refresh."""

    def __init__(self, cog, details: dict, guild_id: int, requesting_user_id: int, is_self_refresh: bool = True):
        label = "Refresh My Roles" if is_self_refresh else "Update Tournament Roles"
        super().__init__(label=label, style=discord.ButtonStyle.primary, emoji="🔄", row=2)
        self.cog = cog
        self.details = details
        self.guild_id = guild_id
        self.requesting_user_id = requesting_user_id
        self.is_self_refresh = is_self_refresh

    async def callback(self, interaction: discord.Interaction):
        """Show game instance selector."""
        game_instances = self.details.get("game_instances", [])
        player_name = self.details.get("account_name") or self.details.get("name", "Unknown")

        # Create select menu with game instances
        select = GameInstanceSelect(
            placeholder="Select a game account...",
            game_instances=game_instances,
            player_name=player_name,
            button_type="refresh_self" if self.is_self_refresh else "refresh_other",
            cog=self.cog,
            guild_id=self.guild_id,
            requesting_user_id=self.requesting_user_id,
        )

        view = discord.ui.View(timeout=180)
        view.add_item(select)

        action = "refresh your roles" if self.is_self_refresh else "update tournament roles"
        await interaction.response.send_message(
            f"Select which game account to {action} for **{player_name}**:",
            view=view,
            ephemeral=True,
        )


class GameInstanceSelect(discord.ui.Select):
    """Select menu for choosing a game instance."""

    def __init__(
        self,
        placeholder: str,
        game_instances: list,
        player_name: str,
        button_type: str,
        cog,
        guild_id: int,
        requesting_user_id: int = None,
    ):
        options = []
        for instance in game_instances:
            primary_id = instance.get("primary_player_id")
            instance_name = instance.get("name", "Unnamed")
            is_primary = instance.get("primary", False)

            label = f"{instance_name}"
            if is_primary:
                label = f"⭐ {label}"

            description = f"ID: {primary_id}" if primary_id else "No ID"

            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(instance.get("id")),
                    description=description,
                )
            )

        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=1)
        self.game_instances = game_instances
        self.player_name = player_name
        self.button_type = button_type
        self.cog = cog
        self.guild_id = guild_id
        self.requesting_user_id = requesting_user_id

    async def callback(self, interaction: discord.Interaction):
        """Handle instance selection."""
        selected_instance_id = int(self.values[0])

        # Find the selected instance
        selected_instance = next((inst for inst in self.game_instances if inst.get("id") == selected_instance_id), None)

        if not selected_instance:
            await interaction.response.send_message("❌ Instance not found", ephemeral=True)
            return

        if self.button_type == "stats":
            await self._show_stats(interaction, selected_instance)
        elif self.button_type == "refresh_self" or self.button_type == "refresh_other":
            discord_accounts = selected_instance.get("discord_accounts_receiving_roles", [])
            if not discord_accounts:
                await interaction.response.send_message("❌ No Discord account associated with this game instance", ephemeral=True)
                return
            discord_id = int(discord_accounts[0])
            instance_name = selected_instance.get("name", "Selected instance")
            await interaction.response.edit_message(content=f"✅ Selected: **{instance_name}**", view=None)
            await self._refresh_roles(interaction, discord_id)
        else:
            await interaction.response.send_message("❌ Unknown button type", ephemeral=True)

    async def _show_stats(self, interaction: discord.Interaction, selected_instance: dict):
        """Show tournament stats for the selected instance by editing the current message."""
        try:
            # Get tower IDs from the SELECTED instance only
            tower_ids = selected_instance.get("all_player_ids", [])
            if not tower_ids:
                tower_ids = [pid["id"] for pid in selected_instance.get("player_ids", [])]

            if not tower_ids:
                error_embed = discord.Embed(title="❌ Error", description="No player IDs found for this instance", color=discord.Color.red())
                await interaction.response.edit_message(embed=error_embed, view=None)
                return

            # Show loading state in the same message
            loading_embed = discord.Embed(
                title="📊 Loading Tournament Stats...",
                description=f"Gathering tournament data for {self.player_name}...",
                color=discord.Color.orange(),
            )
            await interaction.response.edit_message(embed=loading_embed, view=None)

            # Get discord_id for role comparison
            discord_accounts = selected_instance.get("discord_accounts_receiving_roles", [])
            discord_id = int(discord_accounts[0]) if discord_accounts else None

            instance_name = selected_instance.get("name") if len(self.game_instances) > 1 else None

            # Build embed using shared helper
            embed = await self.cog.build_tourney_stats_embed(
                player_name=self.player_name,
                tower_ids=tower_ids,
                guild_id=self.guild_id,
                discord_id=discord_id,
                instance_name=instance_name,
            )

            # Build view with instance selector dropdown + post publicly button
            view = discord.ui.View(timeout=300)

            # Re-add the instance selector so the user can switch between instances
            instance_select = GameInstanceSelect(
                placeholder="Switch game account...",
                game_instances=self.game_instances,
                player_name=self.player_name,
                button_type="stats",
                cog=self.cog,
                guild_id=self.guild_id,
            )
            view.add_item(instance_select)
            view.add_item(TourneyStatsPostPubliclyButton(embed, interaction.guild.id, interaction.channel.id, self.cog))

            await interaction.edit_original_response(embed=embed, view=view)

        except Exception as e:
            self.cog.logger.error(f"Error showing stats: {e}", exc_info=True)
            error_embed = discord.Embed(title="❌ Error", description=f"Error loading stats: {str(e)}", color=discord.Color.red())
            await interaction.edit_original_response(embed=error_embed, view=None)

    async def _refresh_roles(self, interaction: discord.Interaction, discord_id: int):
        """Refresh tournament roles for the selected instance."""
        loading_embed = discord.Embed(
            title="🔄 Refreshing Roles...",
            description="Updating tournament roles...",
            color=discord.Color.orange(),
        )
        message = await interaction.followup.send(embed=loading_embed, ephemeral=True, wait=True)

        try:
            result = await self.cog.refresh_user_roles_for_user(discord_id, self.guild_id)
            success_embed = discord.Embed(title="✅ Roles Updated", description=result, color=discord.Color.green())
            await message.edit(embed=success_embed)
        except Exception as e:
            self.cog.logger.error(f"Error refreshing roles: {e}", exc_info=True)
            error_embed = discord.Embed(title="❌ Error", description=f"Error updating roles: {str(e)}", color=discord.Color.red())
            await message.edit(embed=error_embed)


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

            # Defer the response since this may take a moment
            await interaction.response.defer(ephemeral=True)

            # Use the standardized refresh method
            result = await self.cog.refresh_user_roles_for_user(self.user_id, self.guild_id)

            # Send the result
            await interaction.followup.send(result, ephemeral=True)

        except Exception as e:
            self.cog.logger.error(f"Error refreshing tournament roles for user {self.user_id}: {e}")
            error_message = f"❌ Error updating roles: {str(e)}"
            await interaction.followup.send(error_message, ephemeral=True)


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

            from thetower.backend.sus.models import LinkedAccount

            # Get authorized groups from settings
            authorized_groups = self.cog.get_setting("authorized_refresh_groups", guild_id=self.guild_id, default=[])

            if not authorized_groups:
                await interaction.followup.send("❌ Tournament role refresh is not configured for this server.", ephemeral=True)
                return

            # Get Django user from Discord ID via LinkedAccount
            discord_id = str(interaction.user.id)

            def get_linked_account():
                return (
                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=discord_id)
                    .select_related("player__django_user")
                    .first()
                )

            linked_account = await sync_to_async(get_linked_account)()

            if not linked_account or not linked_account.player or not linked_account.player.django_user:
                await interaction.followup.send("❌ No Django user account found for your Discord ID.", ephemeral=True)
                return

            django_user = linked_account.player.django_user

            # Check if user is in approved groups
            def get_user_groups():
                return [group.name for group in django_user.groups.all()]

            user_groups = await sync_to_async(get_user_groups)()
            has_permission = any(group in authorized_groups for group in user_groups)

            if not has_permission:
                await interaction.followup.send("❌ You don't have permission to refresh tournament roles for other players.", ephemeral=True)
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
