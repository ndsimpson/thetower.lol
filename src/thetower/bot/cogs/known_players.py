# Standard library
import asyncio
import datetime
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Third-party
import discord
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import commands, tasks

from thetower.backend.sus.models import KnownPlayer

# Local
from thetower.bot.basecog import BaseCog


class KnownPlayers(BaseCog,
                   name="Known Players",
                   description="Player identity management and lookup"):
    """Player identity management and lookup.

    Provides commands for finding players by ID, name or Discord info, and
    maintaining the database of known player identities.
    """

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

        # Define settings with descriptions
        settings_config = {
            "results_per_page": (5, "Number of results to show per page in search"),
            "cache_refresh_interval": (3600, "How often to refresh cache (seconds)"),
            "cache_save_interval": (300, "How often to save cache to disk (seconds)"),
            "cache_filename": ("known_player_cache.pkl", "Cache data filename"),
            "info_max_results": (3, "Maximum results to show for info command"),
            "refresh_check_interval": (900, "How often to check if cache needs refresh"),
            "auto_refresh": (True, "Automatically refresh cache when stale"),
            "save_on_update": (True, "Save cache after each update"),
            "allow_partial_matches": (True, "Allow partial name matches in searches"),
            "case_sensitive": (False, "Use case-sensitive name matching")
        }

        # Initialize settings
        for name, (value, description) in settings_config.items():
            if not self.has_setting(name):
                self.set_setting(name, value, description=description)

        # Load settings into instance variables
        self._load_settings()

    def _load_settings(self) -> None:
        """Load settings into instance variables."""
        self.results_per_page = self.get_setting('results_per_page')
        self.cache_refresh_interval = self.get_setting('cache_refresh_interval')
        self.cache_save_interval = self.get_setting('cache_save_interval')
        self.info_max_results = self.get_setting('info_max_results')
        self.refresh_check_interval = self.get_setting('refresh_check_interval')

    @property
    def cache_file(self) -> Path:
        """Get the cache file path using the cog's data directory"""
        cache_filename = self.get_setting('cache_filename')
        return self.data_directory / cache_filename

    async def save_cache(self) -> bool:
        """Save the cache to disk"""
        if not self.last_cache_update:
            return False

        # Use BaseCog's task tracking for save operation
        async with self.task_tracker.task_context("Cache Save", "Saving player cache to disk"):
            # Prepare serializable data to save
            save_data = {
                'last_update': self.last_cache_update,
                'player_details': self.player_details_cache,
                'player_map': self.cached_player_ids
            }

            # Use BaseCog's utility to save data
            return await self.save_data_if_modified(save_data, self.cache_file)

    async def load_cache(self) -> bool:
        """Load the cache from disk"""
        try:
            async with self.task_tracker.task_context("Cache Load", "Loading player cache"):
                save_data = await self.load_data(self.cache_file, default={})

                if save_data:
                    self.player_details_cache = save_data.get('player_details', {})
                    self.cached_player_ids = save_data.get('player_map', {})
                    self.last_cache_update = save_data.get('last_update')
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
                if not force and self.last_cache_update and \
                   (now - self.last_cache_update).total_seconds() < self.cache_refresh_interval:
                    return True

                self.logger.info("Starting player cache refresh")
                self.task_tracker.update_task_status(task_name, "Fetching players from database")

                # Create serializable details cache
                all_players = await sync_to_async(list)(KnownPlayer.objects.all())
                self.logger.info(f"Found {len(all_players)} players in database")

                self.task_tracker.update_task_status(task_name, f"Processing {len(all_players)} players")

                new_details = {}
                new_ids = {}

                for player in all_players:
                    # Cache player details
                    details = await self.get_player_details(player)
                    player_id = details.get('primary_id')
                    if player_id:
                        new_details[player_id] = details
                        new_ids[player_id] = player.pk

                        # Also cache by Discord ID if available
                        discord_id = details.get('discord_id')
                        if discord_id:
                            new_details[discord_id] = details
                            new_ids[discord_id] = player.pk

                        # Cache by all known player IDs
                        for pid in details.get('all_ids', []):
                            new_details[pid] = details
                            new_ids[pid] = player.pk

                # Update caches atomically
                self.player_details_cache = new_details
                self.cached_player_ids = new_ids
                self.last_cache_update = now

                # Save cache to disk if configured
                if self.get_setting('save_on_update'):
                    await self.save_cache()

                self.logger.info(f"Player cache refresh complete. {len(new_details)} entries cached.")
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

        # Apply case sensitivity setting
        if not self.get_setting("case_sensitive"):
            search_term = search_term.lower()

        # First check exact matches in cache
        if search_term in self.player_details_cache:
            # Make sure we have the Django object
            if search_term not in self.player_cache:
                await self.rebuild_object_cache_for_keys({search_term})

            if search_term in self.player_cache:
                return [self.player_cache[search_term]]

        # Apply partial matching setting
        if not self.get_setting("allow_partial_matches"):
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
            name_results = await sync_to_async(list)(
                KnownPlayer.objects.filter(name__icontains=search_term)
            )
            results.extend(name_results)

            # Search by player ID
            id_results = await sync_to_async(list)(
                KnownPlayer.objects.filter(ids__id__icontains=search_term).distinct()
            )
            results.extend([r for r in id_results if r not in results])

            # Search by Discord ID
            discord_results = await sync_to_async(list)(
                KnownPlayer.objects.filter(discord_id__icontains=search_term)
            )
            results.extend([r for r in discord_results if r not in results])

            return results

    async def get_player_details(self, player: KnownPlayer) -> Dict[str, Any]:
        """Get detailed information about a player"""
        # Fetch player IDs
        player_ids = await sync_to_async(list)(player.ids.all())

        # Find primary ID
        primary_id = next((pid.id for pid in player_ids if pid.primary), None)

        # Return formatted details
        return {
            'name': player.name,
            'discord_id': player.discord_id,
            'creator_code': player.creator_code,
            'approved': player.approved,
            'primary_id': primary_id,
            'all_ids': [pid.id for pid in player_ids],
            'ids_count': len(player_ids)
        }

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
            if details.get('discord_id'):
                discord_ids.add(details['discord_id'])

        return list(discord_ids)

    async def get_discord_to_player_mapping(self) -> Dict[str, Dict[str, Any]]:
        """
        Get mapping of Discord IDs to player information

        Returns:
            dict: Dictionary with Discord IDs as keys and player info as values
                  Each value contains 'name', 'primary_id', and 'all_ids'
        """
        await self.wait_until_ready()

        # Create a mapping of Discord IDs to player details
        discord_mapping: Dict[str, Dict[str, Any]] = {}

        # Process all entries in player_details_cache
        for player_details in self.player_details_cache.values():
            # Only process each player once by checking for Discord ID
            discord_id = player_details.get('discord_id')
            if discord_id and discord_id not in discord_mapping:
                # Find all IDs for this player
                all_ids = player_details.get('all_ids', [])
                primary_id = player_details.get('primary_id')

                # Create the mapping entry
                discord_mapping[discord_id] = {
                    'name': player_details.get('name', ''),
                    'primary_id': primary_id,
                    'all_ids': all_ids,
                    'approved': player_details.get('approved', True)
                }

                self.logger.debug(f"Added mapping for Discord ID {discord_id}: {all_ids}")

        self.logger.debug(f"Built Discord mapping with {len(discord_mapping)} entries")
        return discord_mapping

    @commands.group(
        name="knownplayers",
        aliases=["kp"],
        description="Known players management commands"
    )
    async def knownplayers_group(self, ctx):
        """Known players management commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @knownplayers_group.command(
        name="info",
        description="Display information about the known players system"
    )
    async def kp_info_command(self, ctx: commands.Context) -> None:
        """Display information about the known players system."""
        # Determine status and color
        if not self.is_ready:
            status_emoji = "⏳"
            status_text = "Initializing"
            embed_color = discord.Color.orange()
        elif self._has_errors:
            status_emoji = "❌"
            status_text = "Error"
            embed_color = discord.Color.red()
        else:
            status_emoji = "✅"
            status_text = "Operational"
            embed_color = discord.Color.blue()

        # Create info embed
        embed = discord.Embed(
            title="Known Players Information",
            description=(
                "Manages and tracks player identities across different platforms. "
                "Links Discord users to their game IDs and handles alias management."
            ),
            color=embed_color
        )

        # Add status and data freshness
        status_value = [f"{status_emoji} System Status: {status_text}"]
        if hasattr(self, '_last_operation_time') and self._last_operation_time:
            time_since = self.format_relative_time(self._last_operation_time)
            status_value.append(f"🕒 Last Update: {time_since}")
        embed.add_field(
            name="System Status",
            value="\n".join(status_value),
            inline=False
        )

        # Add data coverage
        try:
            # Calculate accurate stats from cache
            player_count = len(set(v.get('pk', 0) for v in self.player_details_cache.values()))
            id_count = len(self.cached_player_ids) if hasattr(self, 'cached_player_ids') else 0
            discord_links = sum(1 for v in self.player_details_cache.values() if v.get('discord_id'))

            coverage = [
                f"📊 Total Players: {player_count}",
                f"🔤 Total IDs: {id_count}",
                f"🔗 Discord Links: {discord_links}"
            ]

            embed.add_field(
                name="Data Coverage",
                value="\n".join(coverage),
                inline=False
            )
        except Exception as e:
            self.logger.error(f"Error calculating coverage stats: {e}")
            embed.add_field(
                name="Data Coverage",
                value="Error calculating statistics",
                inline=False
            )

        # Add cache information
        if self.last_cache_update:
            cache_age = (datetime.datetime.now() - self.last_cache_update).total_seconds()
            age_str = self.format_relative_time(self.last_cache_update)
            cache_info = [
                f"💾 Cache Age: {age_str}",
                f"🔄 Next Refresh: {self.format_time_value(self.cache_refresh_interval - cache_age)} remaining"
            ]
            embed.add_field(
                name="Cache Information",
                value="\n".join(cache_info),
                inline=False
            )

        # Add statistics if available
        if hasattr(self, '_operation_count'):
            embed.add_field(
                name="Statistics",
                value=f"Operations completed: {self._operation_count}",
                inline=False
            )

        # Add usage hint in footer
        embed.set_footer(text="Use /kp help for detailed command information")

        await ctx.send(embed=embed)

    @knownplayers_group.command(
        name="settings",
        description="Display current player lookup settings"
    )
    async def player_settings_command(self, ctx: commands.Context) -> None:
        """Display current player lookup settings"""
        settings = self.get_all_settings()

        embed = discord.Embed(
            title="Player Lookup Settings",
            description="Current configuration for player lookups",
            color=discord.Color.blue()
        )

        for name, value in settings.items():
            # Format durations in a more readable way for time-based settings
            if name in ["cache_refresh_interval", "cache_save_interval"]:
                hours = value // 3600
                minutes = (value % 3600) // 60
                seconds = value % 60
                formatted_value = f"{hours}h {minutes}m {seconds}s ({value} seconds)"
                embed.add_field(name=name, value=formatted_value, inline=False)
            else:
                embed.add_field(name=name, value=str(value), inline=False)

        # Add cache status
        cache_status = "Initialized" if self.last_cache_update else "Not initialized"
        if self.last_cache_update:
            cache_age = (datetime.datetime.now() - self.last_cache_update).total_seconds()
            cache_status = f"Last updated {cache_age:.1f}s ago ({len(self.player_details_cache)} entries)"

        embed.add_field(name="Cache Status", value=cache_status, inline=False)

        await ctx.send(embed=embed)

    @knownplayers_group.command(
        name="set",
        description="Change a player lookup setting"
    )
    @app_commands.describe(
        setting_name="Setting to change (results_per_page, cache_refresh_interval, cache_save_interval, info_max_results)",
        value="New value for the setting"
    )
    async def player_set_setting_command(self, ctx: commands.Context, setting_name: str, value: int) -> None:
        """Change a player lookup setting

        Args:
            setting_name: Setting to change (results_per_page, cache_refresh_interval, cache_save_interval, info_max_results)
            value: New value for the setting
        """
        valid_settings = [
            "results_per_page",
            "cache_refresh_interval",
            "cache_save_interval",
            "info_max_results"
        ]

        if setting_name not in valid_settings:
            valid_settings_str = ", ".join(valid_settings)
            return await ctx.send(f"Invalid setting name. Valid options: {valid_settings_str}")

        # Validate inputs based on the setting
        if setting_name in ["cache_refresh_interval", "cache_save_interval"]:
            if value < 60:  # Minimum 60 seconds for time intervals
                return await ctx.send(f"Value for {setting_name} must be at least 60 seconds")
        elif setting_name == "results_per_page":
            if value < 1 or value > 20:
                return await ctx.send(f"Value for {setting_name} must be between 1 and 20")
        elif setting_name == "info_max_results":
            if value < 2 or value > 10:
                return await ctx.send(f"Value for {setting_name} must be between 2 and 10")

        # Save the setting
        self.set_setting(setting_name, value)

        # Update instance variable
        if hasattr(self, setting_name):
            setattr(self, setting_name, value)

            # If changing save interval, restart the save task
            if setting_name == "cache_save_interval" and self._save_task:
                self._save_task.cancel()
                self._save_task = self.create_periodic_save_task(
                    save_interval=self.cache_save_interval
                )

        # Format confirmation message
        if setting_name in ["cache_refresh_interval", "cache_save_interval"]:
            hours = value // 3600
            minutes = (value % 3600) // 60
            seconds = value % 60
            time_format = f"{hours}h {minutes}m {seconds}s"
            await ctx.send(f"✅ Set {setting_name} to {value} seconds ({time_format})")
        else:
            await ctx.send(f"✅ Set {setting_name} to {value}")

        # Log the change
        self.logger.info(f"Settings changed: {setting_name} set to {value} by {ctx.author}")

        # Mark settings as modified
        self.mark_data_modified()

    @knownplayers_group.command(
        name="search",
        description="Search for players by name, ID, or Discord info"
    )
    @app_commands.describe(
        search_term="Name, ID or Discord info to search for",
        limit="Maximum number of results to return"
    )
    async def player_search(
        self,
        ctx: commands.Context,
        search_term: str,
        limit: Optional[int] = None
    ) -> None:
        """Search for players by name, ID, or Discord info.

        Args:
            ctx: Command context
            search_term: Term to search for
            limit: Optional maximum results to return
        """
        if not await self.wait_until_ready():
            await ctx.send("⏳ Still initializing, please try again shortly.")
            return

        async with ctx.typing():
            # Make sure cache is ready
            if not self.last_cache_update:
                await self.refresh_cache()

            # Search for players
            results = await self.search_player(search_term)

            if not results:
                return await ctx.send(f"No players found matching '{search_term}'")

            # Format results
            embed = discord.Embed(
                title=f"Player Search Results for '{search_term}'",
                description=f"Found {len(results)} matching players",
                color=discord.Color.blue()
            )

            # Limit to reasonable number
            page_size = self.get_setting('results_per_page')
            displayed_results = results[:page_size]

            for i, player in enumerate(displayed_results, 1):
                # Get player IDs
                player_ids = await sync_to_async(list)(player.ids.all())

                # Format player information
                primary_id = next((pid.id for pid in player_ids if pid.primary), None)

                # Organize IDs to show primary first
                formatted_ids = []
                if primary_id:
                    formatted_ids.append(f"✅ {primary_id}")

                # Add other IDs (up to 3 total including primary)
                other_ids = [pid.id for pid in player_ids if pid.id != primary_id]
                remaining_slots = 3 - len(formatted_ids)
                formatted_ids.extend(other_ids[:remaining_slots])

                # Join the IDs into a string
                id_list = ", ".join(formatted_ids)
                if len(player_ids) > 3:
                    id_list += f" (+{len(player_ids) - 3} more)"

                player_info = (
                    f"**Name:** {player.name}\n"
                    f"**Discord ID:** {player.discord_id or 'Not set'}\n"
                    f"**Player IDs:** {id_list}"
                )

                embed.add_field(
                    name=f"Player #{i}",
                    value=player_info,
                    inline=False
                )

            if len(results) > page_size:
                embed.set_footer(text=f"Showing {page_size} of {len(results)} results. Use more specific search terms to narrow results.")

        await ctx.send(embed=embed)

    @knownplayers_group.command(
        name="lookup",
        description="Get detailed information about a specific player"
    )
    @app_commands.describe(
        identifier="Player ID, name, or Discord ID/name"
    )
    async def player_lookup(self, ctx: commands.Context, *, identifier: str) -> None:
        """
        Get detailed information about a specific player

        Args:
            identifier: Player ID, name, or Discord ID/name
        """
        # Add ready check for command
        if not await self.wait_until_ready():
            await ctx.send("⏳ Still initializing, please try again shortly.")
            return

        async with ctx.typing():
            # Make sure cache is ready
            if not self.last_cache_update:
                await self.refresh_cache()

            # Try exact lookup first
            identifier = identifier.strip()
            player = None

            # Check cache for exact match
            if identifier.lower() in self.player_details_cache:
                # Ensure we have the Django object
                if identifier.lower() not in self.player_cache:
                    await self.rebuild_object_cache_for_keys({identifier.lower()})

                if identifier.lower() in self.player_cache:
                    player = self.player_cache[identifier.lower()]

            # If not found in cache, search for matches
            if not player:
                results = await self.search_player(identifier)
                if len(results) == 1:
                    player = results[0]
                elif len(results) > 1:
                    # Get the setting for max results
                    max_results = self.get_setting('info_max_results')

                    # If we have more results than our threshold, show them up to the limit
                    if 1 < len(results) <= max_results:
                        embed = discord.Embed(
                            title=f"Multiple players found matching '{identifier}'",
                            description=f"Found {len(results)} possible matches. Showing details for all:",
                            color=discord.Color.gold()
                        )

                        for i, p in enumerate(results, 1):
                            details = await self.get_player_details(p)

                            # Organize IDs to show primary first with checkmark
                            formatted_ids = []
                            if details['primary_id']:
                                formatted_ids.append(f"✅ {details['primary_id']}")

                            # Add other IDs (up to 3 total including primary)
                            other_ids = [pid for pid in details['all_ids'] if pid != details['primary_id']]
                            remaining_slots = 3 - len(formatted_ids)
                            formatted_ids.extend(other_ids[:remaining_slots])

                            # Join the IDs into a string
                            id_list = ", ".join(formatted_ids)
                            if len(details['all_ids']) > 3:
                                id_list += f" (+{len(details['all_ids']) - 3} more)"

                            # Basic information
                            player_info = (
                                f"**Name:** {details['name'] or 'Not set'}\n"
                                f"**Discord ID:** {details['discord_id'] or 'Not set'}\n"
                                f"**Player IDs:** {id_list}"
                            )

                            embed.add_field(
                                name=f"Player #{i}: {details['name'] or 'Unknown'}",
                                value=player_info,
                                inline=False
                            )

                        await ctx.send(embed=embed)
                        return
                    else:
                        return await ctx.send(f"Found {len(results)} players matching '{identifier}'. Please be more specific or use the search command.")

            if not player:
                return await ctx.send(f"No player found matching '{identifier}'")

            # Get detailed information
            details = await self.get_player_details(player)

            # Create embed
            embed = discord.Embed(
                title=f"Player Details: {details['name'] or 'Unknown'}",
                color=discord.Color.blue()
            )

            # Basic information
            embed.add_field(
                name="Basic Info",
                value=(
                    f"**Name:** {details['name'] or 'Not set'}\n"
                    f"**Discord ID:** {details['discord_id'] or 'Not set'}\n"
                    f"**Creator Code:** {details.get('creator_code') or 'Not set'}\n"
                    f"**Approved:** {'Yes' if details['approved'] else 'No'}\n"
                ),
                inline=False
            )

            # Player IDs - rearrange to show primary first with checkmark
            primary_id = details['primary_id']
            ids_list = details['all_ids']

            # Format ID list to show primary first with checkmark
            formatted_ids = []

            # Add primary ID first with checkmark
            if primary_id:
                formatted_ids.append(f"✅ **{primary_id}**")
                # Remove primary ID from the list to avoid duplication
                ids_list = [pid for pid in ids_list if pid != primary_id]

            # Add the remaining IDs
            formatted_ids.extend(ids_list)

            # Add IDs to embed
            embed.add_field(
                name=f"Player IDs ({len(details['all_ids'])})",
                value="\n".join(formatted_ids) if formatted_ids else "No IDs found",
                inline=False
            )

        await ctx.send(embed=embed)

    def _validate_creator_code(self, code: str) -> tuple[bool, str]:
        """
        Validate creator code format - only one emoji allowed at the end, no punctuation or URLs.

        Args:
            code: The creator code to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not code or not code.strip():
            return True, ""  # Empty codes are allowed (removes code)

        code = code.strip()

        # Check for URLs (basic patterns)
        url_patterns = [
            r'https?://',
            r'www\.',
            r'\.com',
            r'\.org',
            r'\.net',
            r'\.io',
            r'\.co',
            r'\.me'
        ]

        for pattern in url_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                return False, "Creator codes cannot contain URLs or web addresses."

        # Check for punctuation and spaces (no punctuation or spaces allowed)
        # Allow only letters and numbers
        forbidden_characters = re.compile(r'[.,;:!?@#$%^&*()+=\[\]{}|\\<>"`~\/\-_\s]')
        if forbidden_characters.search(code):
            forbidden_chars = forbidden_characters.findall(code)
            return False, f"Creator codes can only contain letters and numbers. Found: {', '.join(set(forbidden_chars))}"

        # Regex pattern to match emojis (Unicode ranges for most common emojis)
        emoji_pattern = re.compile(
            r'[\U0001F600-\U0001F64F]|'  # emoticons
            r'[\U0001F300-\U0001F5FF]|'  # symbols & pictographs
            r'[\U0001F680-\U0001F6FF]|'  # transport & map symbols
            r'[\U0001F1E0-\U0001F1FF]|'  # flags (iOS)
            r'[\U00002702-\U000027B0]|'  # dingbats
            r'[\U000024C2-\U0001F251]'   # enclosed characters
        )

        # Find all emojis in the code
        emojis = emoji_pattern.findall(code)

        if len(emojis) == 0:
            return True, ""  # No emojis is fine
        elif len(emojis) > 1:
            return False, f"Only one emoji is allowed. Found {len(emojis)} emojis: {''.join(emojis)}"

        # Check if the single emoji is at the end
        emoji = emojis[0]
        if not code.endswith(emoji):
            return False, f"The emoji '{emoji}' must be at the end of your creator code."

        return True, ""

    @knownplayers_group.command(
        name="set_creator_code",
        description="Set your creator/supporter code"
    )
    @app_commands.describe(
        creator_code="Your creator/supporter code (e.g., 'thedisasterfish'). Leave empty to remove."
    )
    async def set_creator_code(self, ctx: commands.Context, creator_code: str = None) -> None:
        """Set creator/supporter code for the current Discord user."""
        # Add ready check for command
        if not await self.wait_until_ready():
            await ctx.send("⏳ Still initializing, please try again shortly.")
            return

        discord_id = str(ctx.author.id)

        # Validate creator code format if provided
        if creator_code:
            is_valid, error_message = self._validate_creator_code(creator_code)
            if not is_valid:
                embed = discord.Embed(
                    title="Invalid Creator Code Format",
                    description=error_message,
                    color=discord.Color.red()
                )
                embed.add_field(
                    name="Valid Format",
                    value="Creator codes must follow these rules:\n• Only letters and numbers allowed\n• No URLs or web addresses\n• No punctuation marks, spaces, or special characters\n\nExamples:\n✅ `thedisasterfish`\n✅ `mycreatorcode`\n✅ `playername123`\n❌ `my code` (spaces not allowed)\n❌ `my_code` (underscore not allowed)\n❌ `player-name` (hyphen not allowed)\n❌ `visit-mysite.com` (URL)",
                    inline=False
                )
                return await ctx.send(embed=embed)

        try:
            # Find the player by Discord ID
            player = await sync_to_async(
                lambda: KnownPlayer.objects.filter(discord_id=discord_id).first()
            )()

            if not player:
                embed = discord.Embed(
                    title="Player Not Found",
                    description="No player account found linked to your Discord ID.\nPlease verify your player ID first using the validation process.",
                    color=discord.Color.red()
                )
                return await ctx.send(embed=embed)

            # Update the creator code
            old_code = player.creator_code
            player.creator_code = creator_code.strip() if creator_code else None
            await sync_to_async(player.save)()

            # Clear cache for this player to force refresh
            player_cache_key = discord_id.lower()
            if player_cache_key in self.player_details_cache:
                del self.player_details_cache[player_cache_key]
            if player_cache_key in self.player_cache:
                del self.player_cache[player_cache_key]

            # Create response embed
            if creator_code:
                embed = discord.Embed(
                    title="Creator Code Updated",
                    description=f"Your creator code has been set to: **{creator_code}**",
                    color=discord.Color.green()
                )
                if old_code and old_code != creator_code:
                    embed.add_field(
                        name="Previous Code",
                        value=old_code,
                        inline=False
                    )
            else:
                embed = discord.Embed(
                    title="Creator Code Removed",
                    description="Your creator code has been removed.",
                    color=discord.Color.orange()
                )
                if old_code:
                    embed.add_field(
                        name="Previous Code",
                        value=old_code,
                        inline=False
                    )

            embed.add_field(
                name="Linked Player",
                value=f"**Name:** {player.name or 'Not set'}\n**Discord ID:** {player.discord_id}",
                inline=False
            )

            await ctx.send(embed=embed)

        except Exception as e:
            self.logger.error(f"Error setting creator code for user {discord_id}: {e}")
            await ctx.send(f"❌ Error updating creator code: {e}")

    @knownplayers_group.command(
        name="refresh",
        description="Force refresh player cache"
    )
    async def player_refresh_command(self, ctx: commands.Context) -> None:
        """Force refresh player cache"""
        # Add ready check for command
        if not await self.wait_until_ready():
            await ctx.send("⏳ Still initializing, please try again shortly.")
            return
        # Check pause state
        if self.is_paused:
            await ctx.send("❌ Cache management is currently paused")
            return

        try:
            message = await ctx.send("🔄 Refreshing player cache... This may take a while.")

            # Start refreshing in the background
            async with ctx.typing():
                start_time = datetime.datetime.now()
                await self.refresh_cache(force=True)
                duration = datetime.datetime.now() - start_time

                # Save the refreshed cache
                await self.save_cache()

                # Create a response
                embed = discord.Embed(
                    title="Player Cache Refreshed",
                    description=f"Successfully refreshed player cache in {duration.total_seconds():.1f} seconds.",
                    color=discord.Color.green()
                )
                embed.add_field(name="Cache Entries", value=str(len(self.player_details_cache)))
                embed.add_field(name="Last Updated", value=self.last_cache_update.strftime("%Y-%m-%d %H:%M:%S"), inline=False)
                embed.add_field(name="Cache File", value=str(self.cache_file), inline=False)

                await message.edit(content=None, embed=embed)

        except Exception as e:
            self.logger.error(f"Error refreshing player cache: {e}")
            await ctx.send(f"❌ Error refreshing player cache: {e}")

    def _calculate_cache_statistics(self) -> Dict[str, int]:
        """Calculate cache statistics about players and IDs.

        Returns:
            Dictionary containing:
            - unique_players: Number of unique players (by primary ID)
            - total_ids: Total number of player IDs across all players
            - discord_linked: Number of players with Discord IDs
        """
        try:
            # Get unique players by primary ID
            unique_players = len({details.get('primary_id') for details in self.player_details_cache.values()
                                  if details.get('primary_id')})

            # Get total number of player IDs
            all_player_ids = set()
            for details in self.player_details_cache.values():
                all_player_ids.update(details.get('all_ids', []))

            # Get number of players with Discord IDs
            players_with_discord = len({details.get('discord_id') for details in self.player_details_cache.values()
                                        if details.get('discord_id')})

            return {
                'unique_players': unique_players,
                'total_ids': len(all_player_ids),
                'discord_linked': players_with_discord
            }
        except Exception as e:
            self.logger.error(f"Error calculating cache statistics: {e}", exc_info=True)
            return {
                'unique_players': 0,
                'total_ids': 0,
                'discord_linked': 0
            }

    def _format_cache_info(self) -> List[str]:
        """Format basic cache information into display lines.

        Returns:
            List of formatted info strings
        """
        try:
            age_str = self.format_relative_time(self.last_cache_update)

            return [
                f"**Cache Size:** {len(self.player_details_cache)} entries",
                f"**Last Updated:** {self.last_cache_update.strftime('%Y-%m-%d %H:%M:%S')} ({age_str})",
                f"**Cache File:** {self.cache_file}",
                f"**Refresh Interval:** {self.format_time_value(self.cache_refresh_interval)}",
                f"**Save Interval:** {self.format_time_value(self.cache_save_interval)}"
            ]
        except Exception as e:
            self.logger.error(f"Error formatting cache info: {e}")
            return ["Error retrieving cache information"]

    @knownplayers_group.command(
        name="cache",
        description="Show cache status information"
    )
    async def player_cache_command(self, ctx: commands.Context) -> None:
        """Show cache status information"""
        if not self.last_cache_update:
            return await ctx.send("Player cache has not been initialized yet.")

        embed = discord.Embed(
            title="Player Cache Status",
            color=discord.Color.blue()
        )

        # Add basic cache information
        embed.add_field(
            name="Basic Info",
            value="\n".join(self._format_cache_info()),
            inline=False
        )

        # Add cache statistics
        stats = self._calculate_cache_statistics()
        if stats:
            stats_text = [
                f"**Unique Players:** {stats['unique_players']}",
                f"**Name Entries:** {stats['name_entries']}",
                f"**Discord ID Entries:** {stats['discord_entries']}",
                f"**Player ID Entries:** {stats['id_entries']}",
                f"**Total Cache Entries:** {stats['total_entries']}"
            ]
            embed.add_field(
                name="Cache Statistics",
                value="\n".join(stats_text),
                inline=False
            )
        else:
            embed.add_field(
                name="Cache Statistics",
                value="Error calculating statistics",
                inline=False
            )

        # Add cache statistics
        cache_stats = []
        if self.player_details_cache:
            try:
                # Get unique players by primary ID
                unique_players = len({details.get('primary_id') for details in self.player_details_cache.values()
                                      if details.get('primary_id')})

                # Get total number of player IDs
                all_player_ids = set()
                for details in self.player_details_cache.values():
                    all_player_ids.update(details.get('all_ids', []))

                # Get number of players with Discord IDs
                players_with_discord = len({details.get('discord_id') for details in self.player_details_cache.values()
                                            if details.get('discord_id')})

                cache_stats.extend([
                    f"Known players: {unique_players:,}",
                    f"Total player IDs: {len(all_player_ids):,}",
                    f"Players with Discord: {players_with_discord:,}"
                ])
            except Exception as e:
                self.logger.error(f"Error calculating cache stats: {e}")
                cache_stats.append("Error calculating statistics")
        else:
            cache_stats.append("No cache data available")
        embed.add_field(name="Cache Statistics", value="\n".join(cache_stats), inline=False)

        await ctx.send(embed=embed)

    @knownplayers_group.command(
        name="status",
        description="Display current operational status of the player lookup system"
    )
    async def show_status(self, ctx):
        """Display current operational status of the player lookup system."""
        embed = discord.Embed(
            title="Known Players Status",
            color=discord.Color.blue() if self.is_ready else discord.Color.orange()
        )

        # Overall status section
        status_lines = [
            f"**State**: {'✅ Ready' if self.is_ready else '⏳ Initializing'}",
            f"**Errors**: {'❌ Yes' if self._has_errors else '✅ None'}",
            f"**Cache**: {'✅ Initialized' if self.last_cache_update else '❌ Not initialized'}"
        ]
        embed.add_field(name="System Status", value="\n".join(status_lines), inline=False)

        # Cache information
        if self.last_cache_update:
            cache_age = (datetime.datetime.now() - self.last_cache_update).total_seconds()
            cache_info = [
                f"**Last Update**: {self.last_cache_update.strftime('%Y-%m-%d %H:%M:%S')}",
                f"**Cache Age**: {cache_age:.1f}s",
                f"**Cache File**: {self.cache_file}"
            ]
            embed.add_field(name="Cache Info", value="\n".join(cache_info), inline=False)

        # Statistics section
        stats = self._calculate_cache_statistics()
        if stats:
            stats_lines = [
                f"**Known Players**: {stats['unique_players']:,}",
                f"**Total Player IDs**: {stats['total_ids']:,}",
                f"**Discord Linked**: {stats['discord_linked']:,}"
            ]
            embed.add_field(name="Statistics", value="\n".join(stats_lines), inline=False)

        # Settings summary
        settings = self.get_all_settings()
        settings_lines = [
            f"**Auto Refresh**: {'✅' if settings.get('auto_refresh') else '❌'}",
            f"**Save on Update**: {'✅' if settings.get('save_on_update') else '❌'}",
            f"**Refresh Interval**: {settings.get('cache_refresh_interval', 0)}s",
            f"**Save Interval**: {settings.get('cache_save_interval', 0)}s"
        ]
        embed.add_field(name="Settings", value="\n".join(settings_lines), inline=False)

        await ctx.send(embed=embed)

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
            save_data = {
                'last_update': self.last_cache_update,
                'player_details': self.player_details_cache,
                'player_map': self.cached_player_ids
            }

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
            save_data = {
                'last_update': self.last_cache_update,
                'player_details': self.player_details_cache,
                'player_map': self.cached_player_ids
            }
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
            if not self.last_cache_update or \
               (now - self.last_cache_update).total_seconds() >= self.cache_refresh_interval:
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

                # 0. Create inherited commands
                self.create_pause_commands(self.knownplayers_group)

                # 1. Verify settings
                self.logger.debug("Loading settings")
                tracker.update_status("Verifying settings")
                self._load_settings()

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
        if hasattr(self, 'periodic_refresh') and self.periodic_refresh.is_running():
            self.periodic_refresh.cancel()

        # Save cache one last time
        try:
            save_data = {
                'last_update': self.last_cache_update,
                'player_details': self.player_details_cache,
                'player_map': self.cached_player_ids
            }
            await self.save_data_if_modified(save_data, self.cache_file, force=True)
        except Exception as e:
            self.logger.error(f"Error saving cache during unload: {e}")

        # Call parent unload last
        await super().cog_unload()
        self.logger.info("Known Players cog unloaded")

    @knownplayers_group.command(
        name="toggle_setting",
        description="Toggle a player lookup boolean setting"
    )
    @app_commands.describe(
        setting_name="Name of the setting to toggle",
        value="Optional boolean value to set explicitly"
    )
    async def player_toggle_setting(self, ctx: commands.Context, setting_name: str, value: Optional[bool] = None) -> None:
        """Toggle a player lookup boolean setting.

        Args:
            setting_name: Name of the setting to toggle
            value: Optional boolean value to set explicitly
        """
        # Define valid boolean settings for this cog
        valid_settings = {
            "auto_refresh": "Automatically refresh cache when stale",
            "save_on_update": "Save cache after each update",
            "allow_partial_matches": "Allow partial name matches in searches",
            "case_sensitive": "Use case-sensitive name matching"
        }

        # Use BaseCog's toggle handler
        await self._handle_toggle(
            ctx,
            setting_name,
            value,
            description=valid_settings.get(setting_name)
        )


async def setup(bot) -> None:
    await bot.add_cog(KnownPlayers(bot))
