# Standard library
from typing import Any, Dict, List, Optional, Tuple

# Third-party
import discord
from asgiref.sync import sync_to_async

from thetower.backend.tourney_results.constants import leagues
from thetower.backend.tourney_results.formatting import BASE_URL
from thetower.backend.tourney_results.tourney_utils import check_all_live_entry, get_full_brackets, get_live_df

# Local
from thetower.bot.basecog import BaseCog


class TourneyLiveData(BaseCog, name="Tourney Live Data", description="Commands for accessing live tournament data"):
    """Cog for accessing live tournament data.

    Provides commands to check player participation in live tournaments.
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.logger.info("Initializing TourneyLiveData")

        # Store reference on bot
        self.bot.tourney_live_data = self

        # Define default global settings
        self.global_settings = {
            "enabled": True,
        }

    async def get_player_live_stats(self, player_id: str) -> Optional[Tuple[str, int, int, int, str, str]]:
        """Get player's current live tournament stats.

        Args:
            player_id: Player ID to check

        Returns:
            Tuple of (league, global_position, bracket_position, wave, bracket_name, last_refresh) if player is in live tournament, None otherwise
        """
        for league in leagues:
            try:
                # Get live data for this league
                df = await sync_to_async(get_live_df)(league, True)

                # Filter to full brackets only
                _, fullish_brackets = await sync_to_async(get_full_brackets)(df)
                filtered_df = df[df.bracket.isin(fullish_brackets)]

                # Check if player is in this league
                player_data = filtered_df[filtered_df.player_id == player_id]
                if not player_data.empty:
                    # Get the latest entry for this player
                    latest_entry = player_data.loc[player_data.datetime.idxmax()]
                    player_bracket = latest_entry.bracket

                    # Get global position by finding the player's rank in the latest data
                    latest_datetime = filtered_df.datetime.max()
                    latest_df = filtered_df[filtered_df.datetime == latest_datetime]
                    latest_df = latest_df.sort_values("wave", ascending=False).reset_index(drop=True)

                    # Find player's global position (1-indexed)
                    global_position = None
                    for idx, row in latest_df.iterrows():
                        if row.player_id == player_id:
                            global_position = idx + 1
                            break

                    # Get bracket-specific position
                    bracket_df = latest_df[latest_df.bracket == player_bracket]
                    bracket_df = bracket_df.sort_values("wave", ascending=False).reset_index(drop=True)

                    # Find player's position within their bracket (1-indexed)
                    bracket_position = None
                    for idx, row in bracket_df.iterrows():
                        if row.player_id == player_id:
                            bracket_position = idx + 1
                            break

                    if global_position is not None and bracket_position is not None:
                        wave = int(latest_entry.wave)
                        last_refresh = latest_datetime.strftime("%b %d, %Y %H:%M UTC")
                        return (league, global_position, bracket_position, wave, player_bracket, last_refresh)

            except Exception as e:
                self.logger.debug(f"Error checking league {league} for player {player_id}: {e}")
                continue

        return None

    async def provide_player_lookup_info(self, details: dict, requesting_user: discord.User, permission_context) -> List[Dict[str, Any]]:
        """Provide tourney join status info for player lookup embeds.

        Args:
            details: Standardized player details dictionary with all_ids, primary_id, etc.
            requesting_user: The Discord user requesting the info
            permission_context: Permission context for the requesting user

        Returns:
            List of embed field dictionaries to add to the player embed
        """
        try:
            # Get all player IDs to check, with primary ID first
            primary_id = details["primary_id"]
            all_player_ids = [primary_id] + [pid["id"] for pid in details["all_ids"] if pid["id"] != primary_id]

            # Check if any of the player's IDs have joined the current live tournament
            has_joined = any(await sync_to_async(check_all_live_entry)(player_id) for player_id in all_player_ids)

            if has_joined:
                # Find which player ID has the live tournament entry
                active_player_id = None
                live_stats = None

                for player_id in all_player_ids:
                    live_stats = await self.get_player_live_stats(player_id)
                    if live_stats:
                        active_player_id = player_id
                        break

                if live_stats and active_player_id:
                    league, global_position, bracket_position, wave, bracket_name, last_refresh = live_stats
                    # Construct URLs for live tournament pages
                    bracket_url = f"https://{BASE_URL}/livebracketview?player_id={active_player_id}"
                    comparison_url = f"https://{BASE_URL}/comparison?bracket_player={active_player_id}"
                    placement_url = f"https://{BASE_URL}/liveplacement?player_id={active_player_id}"

                    field_value = f"✅ Joined ({league})\n**Global:** #{global_position} • **Bracket:** #{bracket_position} • **Wave:** {wave}\n[Bracket View]({bracket_url}) • [Comparison]({comparison_url}) • [Live Placement Analysis]({placement_url})\n*Last updated: {last_refresh}*"
                else:
                    # Fallback if we can't get detailed stats
                    field_value = "✅ Joined"
            else:
                field_value = "⛔ Not Joined"

            return [{"name": "Current Tournament", "value": field_value, "inline": True}]

        except Exception as e:
            player_name = details.get("name", "Unknown")
            self.logger.error(f"Error getting tourney join status for player {player_name}: {e}")
            return []

    async def cog_initialize(self) -> None:
        """Initialize the Tourney Live Data cog."""
        self.logger.info("Initializing TourneyLiveData cog")
        try:
            self.logger.info("Starting Tourney Live Data initialization")

            async with self.task_tracker.task_context("Initialization") as tracker:
                # Initialize parent
                self.logger.debug("Initializing parent cog")
                await super().cog_initialize()

                # Register info extension for player lookup
                self.logger.debug("Registering player lookup info extension")
                tracker.update_status("Registering extensions")
                self.bot.cog_manager.register_info_extension(
                    target_cog="player_lookup", source_cog="tourney_live_data", provider_func=self.provide_player_lookup_info
                )

                # Mark as ready and complete initialization
                self.set_ready(True)
                self.logger.info("Tourney Live Data initialization complete")

        except Exception as e:
            self.logger.error(f"Tourney Live Data initialization failed: {e}", exc_info=True)
            self._has_errors = True
            raise
            raise
            raise
