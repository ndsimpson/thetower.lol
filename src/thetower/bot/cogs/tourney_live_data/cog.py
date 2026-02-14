# Standard library
from typing import Any, Dict, List, Optional, Tuple

# Third-party
import discord
from asgiref.sync import sync_to_async

from thetower.backend.tourney_results.constants import leagues
from thetower.backend.tourney_results.shun_config import include_shun_enabled_for
from thetower.backend.tourney_results.tourney_utils import TourneyState, check_all_live_entry, get_full_brackets, get_live_df, get_tourney_state

# Local
from thetower.bot.basecog import BaseCog


class TourneyLiveData(BaseCog, name="Tourney Live Data", description="Commands for accessing live tournament data"):
    """Cog for accessing live tournament data.

    Provides commands to check player participation in live tournaments.
    """

    # Global settings
    global_settings = {
        "enabled": True,
    }

    def __init__(self, bot):
        super().__init__(bot)

        # Re-export for convenient access by other cogs
        self.TourneyState = TourneyState

    @property
    def tourney_state(self) -> TourneyState:
        """Current tournament state (INACTIVE, ENTRY_OPEN, or EXTENDED).

        Accessible from other cogs via ``bot.tourney_live_data.tourney_state``.
        """
        return get_tourney_state()

    async def get_player_live_stats(self, player_id: str) -> Optional[Tuple[str, int, int, int, str, str]]:
        """Get player's current live tournament stats.

        Args:
            player_id: Player ID to check

        Returns:
            Tuple of (league, global_position, bracket_position, wave, bracket_name, last_refresh) if player is in live tournament, None otherwise
        """
        # Check if shunned players should be included based on config
        include_shun = include_shun_enabled_for("player")

        for league in leagues:
            try:
                # Get live data for this league
                # shun parameter: True means exclude only sus (include shunned), False means exclude both sus and shunned
                df = await sync_to_async(get_live_df)(league, include_shun)

                # Filter to full brackets only
                _, fullish_brackets = await sync_to_async(get_full_brackets)(df)
                filtered_df = df[df.bracket.isin(fullish_brackets)]

                # Check if player is in this league
                player_data = filtered_df[filtered_df.player_id == player_id]
                if not player_data.empty:
                    # Get the latest entry for this player
                    latest_entry = player_data.loc[player_data.datetime.idxmax()]
                    player_bracket = latest_entry.bracket

                    # Get global position using tie-aware ranking on wave (descending)
                    latest_datetime = filtered_df.datetime.max()
                    latest_df = filtered_df[filtered_df.datetime == latest_datetime]
                    latest_df = latest_df.sort_values("wave", ascending=False).reset_index(drop=True)
                    # Assign the same position to equal waves (method='min' gives the lowest index for the tie group)
                    latest_df["global_rank"] = latest_df["wave"].rank(method="min", ascending=False).astype(int)
                    global_row = latest_df[latest_df.player_id == player_id]
                    global_position = int(global_row["global_rank"].iloc[0]) if not global_row.empty else None

                    # Get bracket-specific position using tie-aware ranking within bracket
                    bracket_df = latest_df[latest_df.bracket == player_bracket]
                    bracket_df = bracket_df.sort_values("wave", ascending=False).reset_index(drop=True)
                    bracket_df["bracket_rank"] = bracket_df["wave"].rank(method="min", ascending=False).astype(int)
                    bracket_row = bracket_df[bracket_df.player_id == player_id]
                    bracket_position = int(bracket_row["bracket_rank"].iloc[0]) if not bracket_row.empty else None

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
            details: Per-instance player details dictionary with primary_id, game_instance, etc.
            requesting_user: The Discord user requesting the info
            permission_context: Permission context for the requesting user

        Returns:
            List of embed field dictionaries to add to the player embed
        """
        try:
            # Get all player IDs to check for this instance, with primary ID first
            primary_id = details["primary_id"]
            all_player_ids = [primary_id] + [pid["id"] for pid in details["game_instance"]["player_ids"] if pid["id"] != primary_id]

            # Check if any of the player's IDs have joined the current live tournament
            join_checks = [await sync_to_async(check_all_live_entry)(player_id) for player_id in all_player_ids]
            has_joined = any(join_checks)

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
                    field_value = f"✅ Joined ({league})\n**Global:** #{global_position} • **Bracket:** #{bracket_position} • **Wave:** {wave}\n*Last updated: {last_refresh}*"
                else:
                    # Fallback if we can't get detailed stats
                    field_value = "✅ Joined"
            else:
                field_value = "⛔ Not Joined"

            result = [{"name": "Current Tournament", "value": field_value, "inline": False}]
            return result

        except Exception as e:
            player_name = details.get("name", "Unknown")
            self.logger.error(f"Error getting tourney join status for player {player_name}: {e}")

    async def _initialize_cog_specific(self, tracker) -> None:
        """Initialize cog-specific functionality."""
        # Register info extension for player lookup
        self.logger.debug("Registering player lookup info extension")
        tracker.update_status("Registering extensions")
        self.bot.cog_manager.register_info_extension(
            target_cog="player_lookup", source_cog="tourney_live_data", provider_func=self.provide_player_lookup_info
        )
        self.logger.info("TourneyLiveData: Info extension registered successfully")
