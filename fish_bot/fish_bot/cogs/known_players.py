import logging
import asyncio
import discord
from discord.ext import commands
from typing import List, Dict, Optional, Any, Set
from asgiref.sync import sync_to_async
import datetime
from pathlib import Path

from fish_bot.basecog import BaseCog
from dtower.sus.models import KnownPlayer


class KnownPlayers(BaseCog, name="Known Players"):
    """
    Player identity management and lookup.

    Provides commands for finding players by ID, name or Discord info, and
    maintaining the database of known player identities.
    """

    def __init__(self, bot):
        super().__init__(bot)  # Initialize the BaseCog

        # Set default settings
        if not self.has_setting("results_per_page"):
            self.set_setting("results_per_page", 5)  # Default results per page

        if not self.has_setting("cache_refresh_interval"):
            self.set_setting("cache_refresh_interval", 3600)  # 1 hour in seconds

        if not self.has_setting("cache_save_interval"):
            self.set_setting("cache_save_interval", 300)  # 5 minutes in seconds

        if not self.has_setting("cache_filename"):
            self.set_setting("cache_filename", "known_player_cache.pkl")

        if not self.has_setting("info_max_results"):
            self.set_setting("info_max_results", 3)  # Show up to 3 results when multiple matches found

        # Configure instance variables from settings
        self.results_per_page: int = self.get_setting('results_per_page')
        self.cache_refresh_interval: int = self.get_setting('cache_refresh_interval')
        self.cache_save_interval: int = self.get_setting('cache_save_interval')
        self.info_max_results: int = self.get_setting('info_max_results')

        self.logger: logging.Logger = logging.getLogger(__name__)

        # Cache for player data
        self.player_cache: Dict[str, KnownPlayer] = {}
        self.player_details_cache: Dict[str, Dict[str, Any]] = {}  # Store serializable player details
        self.last_cache_update: Optional[datetime.datetime] = None
        self.cached_player_ids: Dict[str, int] = {}  # Map player IDs to their KnownPlayer PKs for quick lookup

        self._save_task: Optional[asyncio.Task] = None

    @property
    def cache_file(self) -> Path:
        """Get the cache file path using the cog's data directory"""
        cache_filename = self.get_setting('cache_filename')
        return self.data_directory / cache_filename

    async def save_cache(self) -> bool:
        """Save the cache to disk"""
        if not self.last_cache_update:
            return False

        # Prepare serializable data to save
        save_data = {
            'last_update': self.last_cache_update,
            'player_details': self.player_details_cache,
            'player_map': self.cached_player_ids
        }

        # Use BaseCog's utility to save data
        success = await self.save_data_if_modified(save_data, self.cache_file)

        if success:
            self.logger.info(f"Saved player cache to {self.cache_file}")

        return success

    async def load_cache(self) -> bool:
        """Load the cache from disk"""
        try:
            # Use BaseCog's utility to load data
            data = await self.load_data(self.cache_file)

            if not data:
                self.logger.info("No cache file found or empty cache")
                return False

            # Check if the cache is valid
            if 'last_update' not in data or 'player_details' not in data:
                self.logger.warning("Invalid cache format, will rebuild cache")
                return False

            # Check if cache is too old
            cache_age = (datetime.datetime.now() - data['last_update']).total_seconds()
            if cache_age > self.cache_refresh_interval * 3:  # Allow 3x normal refresh interval
                self.logger.info(f"Cache is too old ({cache_age:.1f}s), will rebuild")
                return False

            # Load the cache data
            self.last_cache_update = data['last_update']
            self.player_details_cache = data['player_details']
            self.cached_player_ids = data.get('player_map', {})

            # Rebuild the player cache with actual Django objects (to be done on demand)
            self.logger.info(f"Loaded player cache from {self.cache_file} with {len(self.player_details_cache)} entries")
            return True

        except Exception as e:
            self.logger.error(f"Error loading player cache: {e}")
            return False

    async def rebuild_object_cache_for_keys(self, keys: Set[str]) -> None:
        """Rebuild Django objects in cache for specific keys"""
        # Build a set of player PKs we need to fetch
        needed_pks: Set[int] = set()
        for key in keys:
            if key in self.player_details_cache:
                needed_pks.add(self.player_details_cache[key]['pk'])

        if not needed_pks:
            return

        # Fetch all needed KnownPlayer objects at once
        players = await sync_to_async(list)(KnownPlayer.objects.filter(pk__in=needed_pks))

        # Create a lookup by PK
        player_lookup: Dict[int, KnownPlayer] = {player.pk: player for player in players}

        # Update the object cache
        for key in keys:
            if key in self.player_details_cache and self.player_details_cache[key]['pk'] in player_lookup:
                self.player_cache[key] = player_lookup[self.player_details_cache[key]['pk']]

    async def refresh_cache(self, force: bool = False) -> None:
        """Refresh the player cache"""
        # If not forced, try loading from disk first
        if not force and not self.last_cache_update:
            cache_loaded = await self.load_cache()
            if cache_loaded:
                return

        # Check if cache needs refresh
        now = datetime.datetime.now()
        if not force and self.last_cache_update and \
           (now - self.last_cache_update).total_seconds() < self.cache_refresh_interval:
            return

        self.logger.info("Refreshing player cache...")
        try:
            # Get all players and their IDs
            players = await sync_to_async(list)(KnownPlayer.objects.all().prefetch_related('ids'))
            self.player_cache = {}
            self.player_details_cache = {}
            self.cached_player_ids = {}

            # Build the cache
            for player in players:
                # Get all player IDs for this player
                player_ids = list(player.ids.all())

                # Create a serializable version of player data
                player_details = {
                    'pk': player.pk,
                    'name': player.name,
                    'discord_id': player.discord_id,
                    'approved': player.approved,
                    'player_ids': [{'id': pid.id, 'primary': pid.primary} for pid in player_ids]
                }

                # Cache the player by name (lowercase for case-insensitive lookup)
                if player.name:
                    self.player_cache[player.name.lower()] = player
                    self.player_details_cache[player.name.lower()] = player_details

                # Cache by Discord ID
                if player.discord_id:
                    self.player_cache[player.discord_id] = player
                    self.player_details_cache[player.discord_id] = player_details

                # Cache each player ID
                for pid in player_ids:
                    self.player_cache[pid.id] = player
                    self.player_details_cache[pid.id] = player_details
                    # Store a player ID to player PK mapping
                    self.cached_player_ids[pid.id] = player.pk

            self.last_cache_update = now

            # Mark cache as modified to ensure it gets saved
            self.mark_data_modified()

            self.logger.info(f"Player cache refreshed with {len(self.player_details_cache)} entries")

        except Exception as e:
            self.logger.error(f"Error refreshing player cache: {e}")

    async def search_player(self, search_term: str) -> List[KnownPlayer]:
        """
        Search for players by name, ID, or Discord info

        Args:
            search_term: Name, player ID, or Discord ID/name to search for

        Returns:
            List of matching KnownPlayer objects
        """
        await self.wait_until_ready()
        search_term = search_term.strip().lower()

        # First check exact matches in cache
        if search_term in self.player_details_cache:
            # Make sure we have the Django object
            if search_term not in self.player_cache:
                await self.rebuild_object_cache_for_keys({search_term})

            if search_term in self.player_cache:
                return [self.player_cache[search_term]]

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

        # First collect all players with their PKs
        player_details_by_pk: Dict[int, Dict[str, Any]] = {}
        for details in self.player_details_cache.values():
            if 'pk' in details:
                player_details_by_pk[details['pk']] = details

        # Now create the Discord ID mapping
        for details in player_details_by_pk.values():
            if details.get('discord_id'):
                # Extract player IDs from details
                player_ids = [pid['id'] for pid in details.get('player_ids', [])]
                primary_id = next((pid['id'] for pid in details.get('player_ids', [])
                                   if pid.get('primary')), None)

                discord_mapping[details['discord_id']] = {
                    'name': details.get('name', ''),
                    'primary_id': primary_id,
                    'all_ids': player_ids,
                    'pk': details['pk'],
                    'approved': details.get('approved', True)
                }

        return discord_mapping

    @commands.group(name="player", aliases=["p"], invoke_without_command=True)
    async def player_group(self, ctx: commands.Context) -> None:
        """Commands for player management and lookup"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @player_group.command(name="settings")
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

    @player_group.command(name="set")
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

    @player_group.command(name="search")
    async def player_search(self, ctx: commands.Context, *, search_term: str) -> None:
        """
        Search for players by name, ID, or Discord info

        Args:
            search_term: Name, player ID, or Discord ID/name to search for
        """
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

    @player_group.command(name="info")
    async def player_info(self, ctx: commands.Context, *, identifier: str) -> None:
        """
        Get detailed information about a specific player

        Args:
            identifier: Player ID, name, or Discord ID/name
        """
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

    @player_group.command(name="refresh")
    async def player_refresh_command(self, ctx: commands.Context) -> None:
        """Force refresh player cache"""
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
            await ctx.send(f"❌ Error refreshing player cache: {str(e)}")

    @player_group.command(name="cache")
    async def player_cache_command(self, ctx: commands.Context) -> None:
        """Show cache status information"""
        if not self.last_cache_update:
            return await ctx.send("Player cache has not been initialized yet.")

        embed = discord.Embed(
            title="Player Cache Status",
            color=discord.Color.blue()
        )

        # Basic cache information
        cache_age = (datetime.datetime.now() - self.last_cache_update).total_seconds()
        age_str = f"{cache_age:.1f} seconds ago"
        if cache_age > 3600:
            age_str = f"{cache_age / 3600:.1f} hours ago"
        elif cache_age > 60:
            age_str = f"{cache_age / 60:.1f} minutes ago"

        embed.add_field(
            name="Basic Info",
            value=(
                f"**Cache Size:** {len(self.player_details_cache)} entries\n"
                f"**Last Updated:** {self.last_cache_update.strftime('%Y-%m-%d %H:%M:%S')} ({age_str})\n"
                f"**Cache File:** {self.cache_file}\n"
                f"**Refresh Interval:** {self.cache_refresh_interval} seconds\n"
                f"**Save Interval:** {self.cache_save_interval} seconds"
            ),
            inline=False
        )

        # Better cache statistics calculation
        player_count = len(set(v['pk'] for v in self.player_details_cache.values()))
        name_entry_count = sum(1 for k, v in self.player_details_cache.items()
                               if k == v.get('name', '').lower())
        discord_id_count = sum(1 for k, v in self.player_details_cache.items()
                               if k == v.get('discord_id'))
        id_count = len(self.cached_player_ids)

        embed.add_field(
            name="Cache Statistics",
            value=(
                f"**Unique Players:** {player_count}\n"
                f"**Name Entries:** {name_entry_count}\n"
                f"**Discord ID Entries:** {discord_id_count}\n"
                f"**Player ID Entries:** {id_count}\n"
                f"**Total Cache Entries:** {len(self.player_details_cache)}"
            ),
            inline=False
        )

        await ctx.send(embed=embed)

    def create_periodic_save_task(self, save_interval: Optional[int] = None) -> asyncio.Task:
        """Create a task that periodically saves the cache"""
        if save_interval is None:
            save_interval = self.cache_save_interval

        async def periodic_save() -> None:
            await self.bot.wait_until_ready()
            await self.wait_until_ready()  # Wait until initial cache is built
            self.logger.info(f"Starting periodic cache save task (every {save_interval}s)")

            while not self.bot.is_closed():
                await asyncio.sleep(save_interval)
                if self.is_data_modified():
                    await self.save_cache()

        # Create and return the task
        task = self.bot.loop.create_task(periodic_save())
        return task

    async def cog_initialize(self) -> None:
        """Setup tasks when cog is loaded"""
        # Try to load cache from disk first
        await self.load_cache()

        # If cache couldn't be loaded or is too old, refresh it
        if not self.last_cache_update:
            await self.refresh_cache()

        # Setup periodic saving
        self._save_task = self.create_periodic_save_task()

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded"""
        # Cancel the periodic save task
        if self._save_task:
            self._save_task.cancel()

        # Save cache if modified
        if self.is_data_modified():
            await self.save_cache()

        # Call parent implementation
        await super().cog_unload()
        self.logger.info("Known Players cog unloaded")


async def setup(bot) -> None:
    await bot.add_cog(KnownPlayers(bot))
