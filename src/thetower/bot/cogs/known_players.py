# Standard library
import asyncio
import datetime
import re
from typing import Any, Dict, List, Optional, Set

# Third-party
import discord
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import tasks

from thetower.backend.sus.models import KnownPlayer

# Local
from thetower.bot.basecog import BaseCog


class KnownPlayers(BaseCog, name="Known Players", description="Player identity management and lookup"):
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
        }

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

                for player in all_players:
                    # Cache player details
                    details = await self.get_player_details(player)
                    player_id = details.get("primary_id")
                    if player_id:
                        new_details[player_id] = details
                        new_ids[player_id] = player.pk

                        # Also cache by Discord ID if available
                        discord_id = details.get("discord_id")
                        if discord_id:
                            new_details[discord_id] = details
                            new_ids[discord_id] = player.pk

                        # Cache by all known player IDs
                        for pid in details.get("all_ids", []):
                            new_details[pid] = details
                            new_ids[pid] = player.pk

                # Update caches atomically
                self.player_details_cache = new_details
                self.cached_player_ids = new_ids
                self.last_cache_update = now

                # Save cache to disk if configured
                # Note: Using default for internal operation without guild context
                if self.default_settings.get("save_on_update", True):
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

        # Apply case sensitivity setting (use default for internal operations)
        if not self.default_settings.get("case_sensitive", False):
            search_term = search_term.lower()

        # First check exact matches in cache
        if search_term in self.player_details_cache:
            # Make sure we have the Django object
            if search_term not in self.player_cache:
                await self.rebuild_object_cache_for_keys({search_term})

            if search_term in self.player_cache:
                return [self.player_cache[search_term]]

        # Apply partial matching setting (use default for internal operations)
        if not self.default_settings.get("allow_partial_matches", True):
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

    async def get_player_details(self, player: KnownPlayer) -> Dict[str, Any]:
        """Get detailed information about a player"""
        # Fetch player IDs
        player_ids = await sync_to_async(list)(player.ids.all())

        # Find primary ID
        primary_id = next((pid.id for pid in player_ids if pid.primary), None)

        # Return formatted details
        return {
            "name": player.name,
            "discord_id": player.discord_id,
            "creator_code": player.creator_code,
            "approved": player.approved,
            "primary_id": primary_id,
            "all_ids": [pid.id for pid in player_ids],
            "ids_count": len(player_ids),
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
            if details.get("discord_id"):
                discord_ids.add(details["discord_id"])

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
            discord_id = player_details.get("discord_id")
            if discord_id and discord_id not in discord_mapping:
                # Find all IDs for this player
                all_ids = player_details.get("all_ids", [])
                primary_id = player_details.get("primary_id")

                # Create the mapping entry
                discord_mapping[discord_id] = {
                    "name": player_details.get("name", ""),
                    "primary_id": primary_id,
                    "all_ids": all_ids,
                    "approved": player_details.get("approved", True),
                }

                self.logger.debug(f"Added mapping for Discord ID {discord_id}: {all_ids}")

        self.logger.debug(f"Built Discord mapping with {len(discord_mapping)} entries")
        return discord_mapping

    # === Helper Methods ===

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
        url_patterns = [r"https?://", r"www\.", r"\.com", r"\.org", r"\.net", r"\.io", r"\.co", r"\.me"]

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
            r"[\U0001F600-\U0001F64F]|"  # emoticons
            r"[\U0001F300-\U0001F5FF]|"  # symbols & pictographs
            r"[\U0001F680-\U0001F6FF]|"  # transport & map symbols
            r"[\U0001F1E0-\U0001F1FF]|"  # flags (iOS)
            r"[\U00002702-\U000027B0]|"  # dingbats
            r"[\U000024C2-\U0001F251]"  # enclosed characters
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

    # === UI Components ===

    class CreatorCodeModal(discord.ui.Modal, title="Set Creator Code"):
        """Modal for setting creator code."""

        def __init__(self, cog, current_code: str = None):
            super().__init__()
            self.cog = cog
            self.creator_code_input = discord.ui.TextInput(
                label="Creator Code",
                placeholder="Enter your creator code (letters and numbers only)",
                default=current_code or "",
                required=False,
                max_length=50
            )
            self.add_item(self.creator_code_input)

        async def on_submit(self, interaction: discord.Interaction):
            discord_id = str(interaction.user.id)
            creator_code = self.creator_code_input.value.strip() if self.creator_code_input.value else None

            # Validate creator code format if provided
            if creator_code:
                is_valid, error_message = self.cog._validate_creator_code(creator_code)
                if not is_valid:
                    embed = discord.Embed(
                        title="Invalid Creator Code Format",
                        description=error_message,
                        color=discord.Color.red()
                    )
                    embed.add_field(
                        name="Valid Format",
                        value=(
                            "Creator codes must be alphanumeric only:\n"
                            "• Only letters (A-Z, a-z) and numbers (0-9)\n"
                            "• No spaces, punctuation, or special characters\n\n"
                            "Examples:\n"
                            "✅ `thedisasterfish`\n"
                            "✅ `mycreatorcode`\n"
                            "✅ `playername123`\n"
                            "❌ `my code` (no spaces)\n"
                            "❌ `my_code` (no underscores)\n"
                            "❌ `player-name` (no hyphens)"
                        ),
                        inline=False
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return

            try:
                # Find the player by Discord ID
                player = await sync_to_async(lambda: KnownPlayer.objects.filter(discord_id=discord_id).first())()

                if not player:
                    embed = discord.Embed(
                        title="Player Not Found",
                        description="No player account found linked to your Discord ID.",
                        color=discord.Color.red()
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return

                # Update the creator code
                old_code = player.creator_code
                player.creator_code = creator_code
                await sync_to_async(player.save)()

                # Clear cache for this player to force refresh
                player_cache_key = discord_id.lower()
                if player_cache_key in self.cog.player_details_cache:
                    del self.cog.player_details_cache[player_cache_key]
                if player_cache_key in self.cog.player_cache:
                    del self.cog.player_cache[player_cache_key]

                # Create response embed
                if creator_code:
                    embed = discord.Embed(
                        title="Creator Code Updated",
                        description=f"Your creator code has been set to: **{creator_code}**",
                        color=discord.Color.green()
                    )
                    if old_code and old_code != creator_code:
                        embed.add_field(name="Previous Code", value=old_code, inline=False)
                else:
                    embed = discord.Embed(
                        title="Creator Code Removed",
                        description="Your creator code has been removed.",
                        color=discord.Color.orange()
                    )
                    if old_code:
                        embed.add_field(name="Previous Code", value=old_code, inline=False)

                await interaction.response.send_message(embed=embed, ephemeral=True)

            except Exception as e:
                self.cog.logger.error(f"Error setting creator code for user {discord_id}: {e}")
                await interaction.response.send_message(f"❌ Error updating creator code: {e}", ephemeral=True)

    class ProfileView(discord.ui.View):
        """View with button to set creator code."""

        def __init__(self, cog, current_code: str = None):
            super().__init__(timeout=300)
            self.cog = cog
            self.current_code = current_code

        @discord.ui.button(label="Set Creator Code", style=discord.ButtonStyle.primary, emoji="✏️")
        async def set_creator_code_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            """Button to open creator code modal."""
            modal = KnownPlayers.CreatorCodeModal(self.cog, self.current_code)
            await interaction.response.send_modal(modal)

    # === Slash Commands ===

    @app_commands.command(name="profile", description="View your player profile and verification status")
    async def profile_slash(self, interaction: discord.Interaction) -> None:
        """View your own player profile and verification status."""
        if not await self.wait_until_ready():
            await interaction.response.send_message("⏳ Still initializing, please try again shortly.", ephemeral=True)
            return

        discord_id = str(interaction.user.id)

        # Try to find player by Discord ID
        player = await self.get_player_by_discord_id(discord_id)

        if not player:
            embed = discord.Embed(
                title="Not Verified",
                description="You don't have a verified player account linked to your Discord ID.",
                color=discord.Color.orange()
            )
            embed.add_field(
                name="How to Get Verified",
                value="Contact a server administrator to link your player ID to your Discord account.",
                inline=False
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Get player details
        details = await self.get_player_details(player)

        # Create profile embed
        embed = discord.Embed(
            title=f"Player Profile: {details['name'] or 'Unknown'}",
            description="✅ Your Discord account is verified!",
            color=discord.Color.green()
        )

        # Add basic info
        embed.add_field(
            name="Basic Info",
            value=(
                f"**Name:** {details['name'] or 'Not set'}\n"
                f"**Discord ID:** {details['discord_id']}\n"
                f"**Creator Code:** {details.get('creator_code') or 'Not set'}\n"
                f"**Status:** {'Approved ✅' if details['approved'] else 'Pending ⏳'}"
            ),
            inline=False
        )

        # Format player IDs
        primary_id = details["primary_id"]
        ids_list = details["all_ids"]

        formatted_ids = []
        if primary_id:
            formatted_ids.append(f"✅ **{primary_id}** (Primary)")
            ids_list = [pid for pid in ids_list if pid != primary_id]

        formatted_ids.extend(ids_list)

        embed.add_field(
            name=f"Player IDs ({len(details['all_ids'])})",
            value="\n".join(formatted_ids) if formatted_ids else "No IDs found",
            inline=False
        )

        # Create view with set creator code button
        view = KnownPlayers.ProfileView(self, details.get('creator_code'))

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="lookup", description="Look up a player by ID, name, or Discord user")
    @app_commands.describe(
        identifier="Player ID, name, or mention a Discord user",
        user="Discord user to look up (optional)"
    )
    async def lookup_slash(self, interaction: discord.Interaction, identifier: str = None, user: discord.User = None) -> None:
        """Look up a player by various identifiers."""
        if not await self.wait_until_ready():
            await interaction.response.send_message("⏳ Still initializing, please try again shortly.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Determine what to search for
        if user:
            search_term = str(user.id)
            player = await self.get_player_by_discord_id(search_term)
            if player:
                results = [player]
            else:
                results = []
        elif identifier:
            identifier = identifier.strip()
            # Check cache for exact match
            if identifier.lower() in self.player_details_cache:
                if identifier.lower() not in self.player_cache:
                    await self.rebuild_object_cache_for_keys({identifier.lower()})
                if identifier.lower() in self.player_cache:
                    player = self.player_cache[identifier.lower()]
                    results = [player] if player else []
                else:
                    results = await self.search_player(identifier)
            else:
                results = await self.search_player(identifier)
        else:
            await interaction.followup.send("❌ Please provide either an identifier or mention a user.", ephemeral=True)
            return

        if not results:
            search_display = f"<@{user.id}>" if user else f"'{identifier}'"
            await interaction.followup.send(f"No players found matching {search_display}", ephemeral=True)
            return

        if len(results) == 1:
            player = results[0]
            details = await self.get_player_details(player)

            embed = discord.Embed(
                title=f"Player Details: {details['name'] or 'Unknown'}",
                color=discord.Color.blue()
            )

            # Basic information
            discord_user_mention = f"<@{details['discord_id']}>" if details['discord_id'] else "Not set"
            embed.add_field(
                name="Basic Info",
                value=(
                    f"**Name:** {details['name'] or 'Not set'}\n"
                    f"**Discord:** {discord_user_mention}\n"
                    f"**Creator Code:** {details.get('creator_code') or 'Not set'}\n"
                    f"**Approved:** {'Yes ✅' if details['approved'] else 'No ❌'}"
                ),
                inline=False
            )

            # Player IDs
            primary_id = details["primary_id"]
            ids_list = details["all_ids"]

            formatted_ids = []
            if primary_id:
                formatted_ids.append(f"✅ **{primary_id}** (Primary)")
                ids_list = [pid for pid in ids_list if pid != primary_id]

            formatted_ids.extend(ids_list)

            embed.add_field(
                name=f"Player IDs ({len(details['all_ids'])})",
                value="\n".join(formatted_ids) if formatted_ids else "No IDs found",
                inline=False
            )

            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            # Multiple results
            embed = discord.Embed(
                title="Multiple Players Found",
                description=f"Found {len(results)} players. Showing first 5:",
                color=discord.Color.gold()
            )

            for i, player in enumerate(results[:5], 1):
                player_ids = await sync_to_async(list)(player.ids.all())
                primary_id = next((pid.id for pid in player_ids if pid.primary), None)

                formatted_ids = []
                if primary_id:
                    formatted_ids.append(f"✅ {primary_id}")

                other_ids = [pid.id for pid in player_ids if pid.id != primary_id]
                formatted_ids.extend(other_ids[:2])

                id_list = ", ".join(formatted_ids)
                if len(player_ids) > 3:
                    id_list += f" (+{len(player_ids) - 3} more)"

                discord_mention = f"<@{player.discord_id}>" if player.discord_id else "Not set"
                player_info = (
                    f"**Name:** {player.name}\n"
                    f"**Discord:** {discord_mention}\n"
                    f"**Player IDs:** {id_list}"
                )

                embed.add_field(name=f"Player #{i}", value=player_info, inline=False)

            if len(results) > 5:
                embed.set_footer(text=f"{len(results) - 5} more results not shown. Be more specific.")

            await interaction.followup.send(embed=embed, ephemeral=True)

    # === Helper Methods ===

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


async def setup(bot) -> None:
    await bot.add_cog(KnownPlayers(bot))
