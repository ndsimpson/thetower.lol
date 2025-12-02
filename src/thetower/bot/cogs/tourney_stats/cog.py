import asyncio
import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Dict

import discord
import pandas as pd
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import tasks

from thetower.backend.tourney_results.constants import how_many_results_hidden_site, leagues, legend
from thetower.backend.tourney_results.data import get_results_for_patch, get_shun_ids, get_sus_ids, get_tourneys
from thetower.backend.tourney_results.models import PatchNew as Patch
from thetower.bot.basecog import BaseCog
from thetower.bot.exceptions import ChannelUnauthorized, UserUnauthorized

from .ui import TourneyAdminView, TourneyStatsSettingsView


def include_shun_roles_enabled() -> bool:
    """Check for repo-root flag file `include_shun_roles`.

    If the file exists, the bot will INCLUDE shunned players (i.e. not treat them as excluded).
    """
    repo_root = Path(__file__).resolve().parents[4]
    return (repo_root / "include_shun_roles").exists()


# Define league hierarchy - order matters for importance
LEAGUE_HIERARCHY = ["legend", "champion", "platinum", "gold", "silver", "copper"]


class TourneyStats(BaseCog, name="Tourney Stats"):
    """
    Player-focused tournament statistics.

    Tracks player performance metrics across different leagues and tournaments,
    focusing on wave counts, placements, and other statistics.
    """

    # Settings view class for the cog manager - only accessible to bot owner
    settings_view_class = TourneyStatsSettingsView

    def __init__(self, bot):
        super().__init__(bot)
        self.logger.info("Initializing TourneyStats")

        # Store reference on bot
        self.bot.tourney_stats = self

        # Initialize data storage variables
        self.league_dfs = {}
        self.latest_patch = None
        self.latest_tournament_date = None
        self.last_updated = None
        self.tournament_counts = {}
        self.total_tournaments = 0

        # Global settings (bot-wide)
        self.global_settings = {
            "cache_filename": "tourney_stats_data.pkl",
            "cache_check_interval": 5 * 60,  # Check every 5 minutes for new tournaments
            "update_error_retry_interval": 30 * 60,
            "recent_tournaments_display_count": 3,
        }

        # Guild-specific settings (none for this cog currently)
        self.guild_settings = {}

    @property
    def cache_file(self) -> Path:
        """Get the cache file path using the cog's data directory"""
        cache_filename = self.global_settings["cache_filename"]
        return self.data_directory / cache_filename

    @property
    def cache_check_interval(self) -> int:
        """Get the cache check interval from settings"""
        return self.get_setting("cache_check_interval", self.global_settings["cache_check_interval"])

    async def cog_initialize(self) -> None:
        """Initialize the cog - called by BaseCog during ready process"""
        self.logger.info("Initializing TourneyStats module...")

        try:
            async with self.task_tracker.task_context("Initialization") as tracker:
                # Initialize parent
                self.logger.debug("Initializing parent cog")
                tracker.update_status("Loading saved data")
                await super().cog_initialize()

                # Load saved data first
                tracker.update_status("Loading tournament data")
                await self.load_data()

                # Refresh if needed
                if not self.league_dfs:
                    tracker.update_status("Refreshing tournament data")
                    await self.get_tournament_data(refresh=True)

                # Start the update check task
                tracker.update_status("Starting background tasks")
                self.periodic_update_check.start()

                # Mark the cog as ready
                self.set_ready(True)
                self.logger.info("TourneyStats initialization complete")

        except Exception as e:
            self._has_errors = True
            self.logger.error(f"Failed to initialize TourneyStats module: {e}", exc_info=True)
            raise

    @tasks.loop(seconds=None)  # Will set interval in before_loop
    async def periodic_update_check(self):
        """Check for new tournament dates and refresh data if needed."""
        try:
            # Start the update check task
            async with self.task_tracker.task_context("Tournament Check", "Checking for new tournament data"):
                # Get the latest tournament date from DB
                latest_db_date = await self.get_latest_tournament_date_from_db()

                if latest_db_date is None:
                    self.logger.debug("No tournaments found in database")
                    return

                # Check if we have a newer tournament date
                if self.latest_tournament_date is None or latest_db_date > self.latest_tournament_date:
                    if self.latest_tournament_date:
                        self.logger.info(f"New tournament detected: {latest_db_date} (was {self.latest_tournament_date})")
                        self.task_tracker.update_task_status("Tournament Check", f"New tournament found: {latest_db_date}")
                    else:
                        self.logger.info(f"Loading tournament data for: {latest_db_date}")
                        self.task_tracker.update_task_status("Tournament Check", f"Loading tournament: {latest_db_date}")

                    # Track the data refresh as a separate task
                    async with self.task_tracker.task_context("Data Refresh", f"Refreshing tournament data for {latest_db_date}"):
                        await self.get_tournament_data(refresh=True)

                    # Update last_updated time
                    self.last_updated = datetime.datetime.now()
                    self.mark_data_modified()
                    await self.save_data()
                else:
                    self.logger.debug(f"No new tournaments (latest: {self.latest_tournament_date})")

        except asyncio.CancelledError:
            self.logger.info("Tournament check task was cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Error checking for new tournaments: {e}", exc_info=True)
            raise

    @periodic_update_check.before_loop
    async def before_periodic_update_check(self):
        """Setup before the update check task starts."""
        self.logger.info(f"Starting tournament check task (interval: {self.cache_check_interval}s)")
        await self.bot.wait_until_ready()
        await self.wait_until_ready()

        # Set the interval dynamically based on settings
        self.periodic_update_check.change_interval(seconds=self.cache_check_interval)

    @periodic_update_check.after_loop
    async def after_periodic_update_check(self):
        """Cleanup after the update check task ends."""
        if self.periodic_update_check.is_being_cancelled():
            self.logger.info("Tournament check task was cancelled")

    async def save_data(self) -> bool:
        """Save tournament data using BaseCog's utility."""
        try:
            # Prepare the data to save
            save_data = {
                "latest_patch": self.latest_patch,
                "latest_tournament_date": self.latest_tournament_date,
                "league_dfs": self.league_dfs,
                "last_updated": self.last_updated or datetime.datetime.now(),
                "tournament_counts": self.tournament_counts,
                "total_tournaments": self.total_tournaments,
            }

            # Use BaseCog's utility to save data
            success = await self.save_data_if_modified(save_data, self.cache_file)

            if success:
                self.logger.info(f"Saved tournament data to {self.cache_file}")
                return True
            return False

        except Exception as e:
            self.logger.error(f"Error saving tournament data: {e}", exc_info=True)
            self._has_errors = True
            return False

    async def load_data(self) -> bool:
        """Load tournament data using BaseCog's utility."""
        try:
            # Use BaseCog's utility to load data
            data = await super().load_data(self.cache_file)
            save_data = data or {}  # Use empty dict if no data loaded

            if save_data:
                self.latest_patch = save_data.get("latest_patch")
                self.latest_tournament_date = save_data.get("latest_tournament_date")
                self.league_dfs = save_data.get("league_dfs", {})
                self.last_updated = save_data.get("last_updated")
                self.tournament_counts = save_data.get("tournament_counts", {})
                self.total_tournaments = save_data.get("total_tournaments", 0)

                self.logger.info(f"Loaded tournament data from {self.cache_file} (latest tournament: {self.latest_tournament_date})")
                return True

            self.logger.info("No saved tournament data found, starting fresh")
            return False

        except Exception as e:
            self.logger.error(f"Error loading tournament data: {e}", exc_info=True)
            self._has_errors = True
            return False

    async def get_latest_patch_from_db(self):
        """Get the latest patch directly from the database."""
        patches = await sync_to_async(list)(Patch.objects.all())
        latest_patch = sorted(patches)[-1] if patches else None
        return latest_patch

    async def get_latest_tournament_date_from_db(self):
        """Get the latest tournament date from the database across all leagues."""
        from thetower.backend.tourney_results.models import TourneyResult

        # Get the most recent tournament date across all public tournaments
        latest_result = await sync_to_async(lambda: TourneyResult.objects.filter(public=True).order_by("-date").first())()

        return latest_result.date if latest_result else None

    async def get_latest_patch(self):
        """Get the latest patch or use cached value."""
        if not self.latest_patch:
            self.latest_patch = await self.get_latest_patch_from_db()
        return self.latest_patch

    async def get_tournament_data(self, league=None, refresh=False):
        """Get tournament data for the latest patch, optionally filtered by league."""
        # If we need to refresh or don't have data yet
        if refresh or not self.league_dfs:
            task_name = "Tournament Data Load"
            async with self.task_tracker.task_context(task_name, "Loading tournament data..."):
                # Get patch info
                patch = await self.get_latest_patch()
                self.logger.info(f"Using patch: {patch}")

                # Get and store the latest tournament date
                self.latest_tournament_date = await self.get_latest_tournament_date_from_db()
                if self.latest_tournament_date:
                    self.logger.info(f"Latest tournament date: {self.latest_tournament_date}")

                self.task_tracker.update_task_status(task_name, "Getting excluded player IDs...")
                # Get sus IDs to filter out. The bot respects its own repo-root flag
                # `include_shun_roles` — if present, shunned players are INCLUDED and
                # therefore not added to the exclusion list.
                if include_shun_roles_enabled():
                    sus_ids = await sync_to_async(get_sus_ids)()
                else:
                    sus_ids = await sync_to_async(get_sus_ids)()
                    shun_ids = await sync_to_async(get_shun_ids)()
                    sus_ids = sus_ids.union(shun_ids)
                self.logger.info(f"Found {len(sus_ids)} excluded player IDs")

                # Clear existing data if refreshing
                self.league_dfs = {}
                self.tournament_counts = {}
                self.total_tournaments = 0

                # Load data for all leagues
                total_leagues = len(leagues)
                start_time = datetime.datetime.now()

                for i, league_name in enumerate(leagues):
                    self.task_tracker.update_task_status(task_name, f"Loading {league_name} league data ({i + 1}/{total_leagues})...")
                    league_start_time = datetime.datetime.now()

                    # Wrap the database operations in sync_to_async
                    results = await sync_to_async(get_results_for_patch)(patch=patch, league=league_name)
                    df = await sync_to_async(get_tourneys)(results, limit=how_many_results_hidden_site)

                    # Count the number of tournaments (TourneyResult objects) for this league
                    tournament_count_for_league = await sync_to_async(lambda: results.count())()
                    self.total_tournaments += tournament_count_for_league

                    # Filter out sus players
                    original_rows = len(df)
                    self.league_dfs[league_name] = df[~df.id.isin(sus_ids)]
                    filtered_rows = len(self.league_dfs[league_name])

                    # Record the tournament count
                    self.tournament_counts[league_name] = filtered_rows

                    # Calculate timing info
                    league_time = datetime.datetime.now() - league_start_time

                    # Log detailed stats
                    stats_msg = (
                        f"Loaded {league_name} data: {filtered_rows} rows "
                        f"({original_rows - filtered_rows} filtered) in {league_time.total_seconds():.1f}s"
                    )
                    self.logger.info(stats_msg)

                    # Give asyncio a chance to process other tasks
                    await asyncio.sleep(0)

                # Final status update
                total_time = datetime.datetime.now() - start_time
                total_rows = sum(len(df) for df in self.league_dfs.values())
                final_msg = f"Loaded {len(self.league_dfs)} leagues with {total_rows} total rows in {total_time.total_seconds():.1f}s"
                self.logger.info(final_msg)
                self.task_tracker.update_task_status(task_name, final_msg)

                # Update last updated timestamp
                self.last_updated = datetime.datetime.now()

                # Mark data as modified
                self.mark_data_modified()

                try:
                    # Save the updated data
                    await self.save_data()
                except Exception as e:
                    self.logger.error(f"Error saving tournament data: {e}")

        # Return either all data or just the requested league
        if league:
            return self.league_dfs.get(league, pd.DataFrame())
        return self.league_dfs

    async def get_player_stats(self, player_id: str, league: str = None) -> Dict:
        """
        Get comprehensive tournament statistics for a player in a specific league.

        Args:
            player_id: The player's ID
            league: The league to get stats from. If None, returns stats for all leagues.

        Returns:
            Dictionary containing statistics for the player
        """
        stats = {}
        dfs = await self.get_tournament_data()

        # If a specific league is provided, only analyze that league
        if league:
            if league in dfs:
                league_df = dfs[league]
                player_df = league_df[league_df.id == player_id]
                if not player_df.empty:
                    stats[league] = self._calculate_league_stats(player_df, league)
        else:
            # Analyze all leagues
            for league_name, df in dfs.items():
                player_df = df[df.id == player_id]
                if not player_df.empty:
                    stats[league_name] = self._calculate_league_stats(player_df, league_name)

        return stats

    def _calculate_league_stats(self, player_df: pd.DataFrame, league_name: str) -> Dict:
        """Calculate statistics for a player in a specific league."""
        total_tourneys = len(player_df)

        if league_name == legend:
            # For legend league, lower position is better
            best_position = player_df.position.min()
            best_position_row = player_df[player_df.position == best_position].iloc[0]
            best_wave = best_position_row.wave
            best_date = best_position_row.date if "date" in best_position_row else None

            # Calculate average position and wave
            avg_position = player_df.position.mean()
            avg_wave = player_df.wave.mean()

            # Find most recent tournament
            latest_tournament = player_df.sort_values("date", ascending=False).iloc[0] if "date" in player_df.columns else None
            latest_position = latest_tournament.position if latest_tournament is not None else None
            latest_wave = latest_tournament.wave if latest_tournament is not None else None
            latest_date = latest_tournament.date if latest_tournament is not None else None

            return {
                "best_position": best_position,
                "position_at_best_wave": best_position,
                "best_wave": best_wave,
                "best_date": best_date,
                "avg_position": round(avg_position, 2),
                "avg_wave": round(avg_wave, 2),
                "latest_position": latest_position,
                "latest_wave": latest_wave,
                "latest_date": latest_date,
                "total_tourneys": total_tourneys,
                "max_wave": player_df.wave.max(),
                "min_wave": player_df.wave.min(),
                "tournaments": (
                    player_df[["date", "position", "wave"]].sort_values("date", ascending=False).to_dict("records")
                    if "date" in player_df.columns
                    else []
                ),
            }
        else:
            # For other leagues, higher wave is better
            best_wave = player_df.wave.max()
            best_wave_row = player_df[player_df.wave == best_wave].iloc[0]
            position_at_best = best_wave_row.position
            best_date = best_wave_row.date if "date" in best_wave_row else None

            # Calculate average position and wave
            avg_position = player_df.position.mean()
            avg_wave = player_df.wave.mean()

            # Find most recent tournament
            latest_tournament = player_df.sort_values("date", ascending=False).iloc[0] if "date" in player_df.columns else None
            latest_position = latest_tournament.position if latest_tournament is not None else None
            latest_wave = latest_tournament.wave if latest_tournament is not None else None
            latest_date = latest_tournament.date if latest_tournament is not None else None

            return {
                "best_wave": best_wave,
                "position_at_best_wave": position_at_best,
                "best_date": best_date,
                "avg_position": round(avg_position, 2),
                "avg_wave": round(avg_wave, 2),
                "latest_position": latest_position,
                "latest_wave": latest_wave,
                "latest_date": latest_date,
                "total_tourneys": total_tourneys,
                "best_position": player_df.position.min(),
                "max_wave": best_wave,
                "min_wave": player_df.wave.min(),
                "tournaments": (
                    player_df[["date", "position", "wave"]].sort_values("date", ascending=False).to_dict("records")
                    if "date" in player_df.columns
                    else []
                ),
            }

    async def _check_additional_interaction_permissions(self, interaction: discord.Interaction) -> bool:
        """Additional permission checks that cogs can override."""
        # Allow the tourney command to work in any channel (admin command)
        if interaction.command and interaction.command.name == "tourney":
            return True

        # For other commands, use the default permission checking
        if not interaction.command:
            return True

        # Create a mock context for permission manager
        # Include parent attribute to match expected command structure
        ctx = SimpleNamespace(
            command=SimpleNamespace(name=interaction.command.name, parent=getattr(interaction.command, "parent", None)),
            bot=interaction.client,
            guild=interaction.guild,
            channel=interaction.channel,
            author=interaction.user,
            message=SimpleNamespace(channel_mentions=[]),
        )

        try:
            await self.bot.permission_manager.check_command_permissions(ctx)
            return True
        except (UserUnauthorized, ChannelUnauthorized) as e:
            # Send error message as ephemeral response
            if isinstance(e, UserUnauthorized):
                await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            elif isinstance(e, ChannelUnauthorized):
                await interaction.response.send_message("❌ This command cannot be used in this channel.", ephemeral=True)
            return False

    # Unified admin slash command
    @app_commands.command(name="tourney", description="Tournament Statistics Admin Panel")
    async def tourney_admin(self, interaction: discord.Interaction):
        """Display the tournament statistics admin panel with system status and management options."""
        view = TourneyAdminView(self)
        embed = await view.create_admin_embed()

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def cog_unload(self):
        """Called when the cog is unloaded."""
        # Cancel the update task
        if hasattr(self, "periodic_update_check") and self.periodic_update_check.is_running():
            self.periodic_update_check.cancel()

        # Save data when unloaded using super's implementation which handles
        # checking if data is modified and saving it appropriately
        await super().cog_unload()

        self.logger.info("Player tournament stats unloaded, data saved.")


async def setup(bot) -> None:
    await bot.add_cog(TourneyStats(bot))
