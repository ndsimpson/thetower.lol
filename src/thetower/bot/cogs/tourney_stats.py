import asyncio
import datetime
from pathlib import Path
from typing import Dict

import discord
import pandas as pd
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import commands, tasks
from django.db.models import Q

from thetower.backend.sus.models import SusPerson
from thetower.backend.tourney_results.constants import how_many_results_hidden_site, leagues, legend
from thetower.backend.tourney_results.data import get_results_for_patch, get_tourneys
from thetower.backend.tourney_results.models import PatchNew as Patch
from thetower.bot.basecog import BaseCog

# Define league hierarchy - order matters for importance
LEAGUE_HIERARCHY = ["legend", "champion", "platinum", "gold", "silver", "copper"]


class TourneyStats(BaseCog, name="Tourney Stats"):
    """
    Player-focused tournament statistics.

    Tracks player performance metrics across different leagues and tournaments,
    focusing on wave counts, placements, and other statistics.
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.logger.info("Initializing TourneyStats")

        # Initialize data storage variables
        self.league_dfs = {}
        self.latest_patch = None
        self.last_updated = None
        self.tournament_counts = {}

        # Define settings with descriptions
        settings_config = {
            "cache_filename": ("tourney_stats_data.pkl", "Filename for caching tournament data"),
            "update_check_interval": (6 * 60 * 60, "How often to check for updates (seconds)"),
            "update_error_retry_interval": (30 * 60, "How long to wait after errors (seconds)"),
            "recent_tournaments_display_count": (3, "Number of recent tournaments to display")
        }

        # Initialize settings
        for name, (value, description) in settings_config.items():
            if not self.has_setting(name):
                self.set_setting(name, value, description=description)

        # Load settings into instance variables
        self._load_settings()

        # Initialize file-related instance variables
        self.cache_filename = self.get_setting("cache_filename")

    def _load_settings(self) -> None:
        """Load settings into instance variables."""
        self.update_check_interval = self.get_setting('update_check_interval')
        self.update_error_retry_interval = self.get_setting('update_error_retry_interval')
        self.recent_tournaments_display_count = self.get_setting('recent_tournaments_display_count')

    @property
    def cache_file(self) -> Path:
        """Get the cache file path using the cog's data directory"""
        return self.data_directory / self.cache_filename

    async def cog_initialize(self):
        """Initialize the cog - called by BaseCog during ready process"""
        try:
            # Load saved data first
            await self.load_data()

            # Refresh if needed
            if not self.league_dfs:
                await self.get_tournament_data(refresh=True)

            # Start the update check task with tasks.loop
            self.periodic_update_check.start()

            self.logger.info("Tournament stats initialization complete")

        except Exception as e:
            self.logger.error(f"Error during tournament stats initialization: {e}", exc_info=True)
            raise

    @tasks.loop(seconds=None)  # Will set interval in before_loop
    async def periodic_update_check(self):
        """Check for new patches and refresh data if needed."""
        try:
            # Start the update check task
            async with self.task_tracker.task_context("Update Check", "Checking for new game patch versions"):
                # Get the current latest patch from DB
                current_patch = await self.get_latest_patch_from_db()

                # Check if patch is different
                if self.latest_patch and str(current_patch) != str(self.latest_patch):
                    self.logger.info(f"New patch detected: {current_patch} (was {self.latest_patch})")
                    self.task_tracker.update_task_status("Update Check", f"New patch found: {current_patch}")

                    # Reset patch and force refresh
                    self.latest_patch = None

                    # Track the data refresh as a separate task
                    async with self.task_tracker.task_context("Data Refresh", f"Refreshing tournament data for patch {current_patch}"):
                        await self.get_tournament_data(refresh=True)

                    # Update last_updated time
                    self.last_updated = datetime.datetime.now()
                    self.mark_data_modified()
                    await self.save_data()

        except asyncio.CancelledError:
            self.logger.info("Update check task was cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Error checking for patch updates: {e}", exc_info=True)
            raise

    @periodic_update_check.before_loop
    async def before_periodic_update_check(self):
        """Setup before the update check task starts."""
        self.logger.info(f"Starting tournament updates check task (interval: {self.update_check_interval}s)")
        await self.bot.wait_until_ready()
        await self.wait_until_ready()

        # Set the interval dynamically based on settings
        self.periodic_update_check.change_interval(seconds=self.update_check_interval)

    @periodic_update_check.after_loop
    async def after_periodic_update_check(self):
        """Cleanup after the update check task ends."""
        if self.periodic_update_check.is_being_cancelled():
            self.logger.info("Tournament update check task was cancelled")

    async def save_data(self) -> bool:
        """Save tournament data using BaseCog's utility."""
        try:
            # Prepare the data to save
            save_data = {
                'latest_patch': self.latest_patch,
                'league_dfs': self.league_dfs,
                'last_updated': self.last_updated or datetime.datetime.now(),
                'tournament_counts': self.tournament_counts
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
                self.latest_patch = save_data.get('latest_patch')
                self.league_dfs = save_data.get('league_dfs', {})
                self.last_updated = save_data.get('last_updated')
                self.tournament_counts = save_data.get('tournament_counts', {})

                self.logger.info(f"Loaded tournament data from {self.cache_file}")
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
                try:
                    # Get patch info
                    patch = await self.get_latest_patch()
                    self.logger.info(f"Using patch: {patch}")

                    self.task_tracker.update_task_status(task_name, "Getting excluded player IDs...")
                    # Get sus IDs to filter out
                    sus_ids = {item.player_id for item in await sync_to_async(list)(SusPerson.objects.filter(Q(sus=True) | Q(shun=True)))}
                    self.logger.info(f"Found {len(sus_ids)} excluded player IDs")

                    # Clear existing data if refreshing
                    self.league_dfs = {}
                    self.tournament_counts = {}

                    # Load data for all leagues
                    total_leagues = len(leagues)
                    start_time = datetime.datetime.now()

                    for i, league_name in enumerate(leagues):
                        self.task_tracker.update_task_status(task_name, f"Loading {league_name} league data ({i + 1}/{total_leagues})...")
                        league_start_time = datetime.datetime.now()

                        # Wrap the database operations in sync_to_async
                        results = await sync_to_async(get_results_for_patch)(patch=patch, league=league_name)
                        df = await sync_to_async(get_tourneys)(
                            results,
                            limit=how_many_results_hidden_site
                        )

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

                except Exception as e:
                    error_msg = f"Error loading tournament data: {str(e)}"
                    self.logger.error(error_msg)
                    raise

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
            best_date = best_position_row.date if 'date' in best_position_row else None

            # Calculate average position and wave
            avg_position = player_df.position.mean()
            avg_wave = player_df.wave.mean()

            # Find most recent tournament
            latest_tournament = player_df.sort_values('date', ascending=False).iloc[0] if 'date' in player_df.columns else None
            latest_position = latest_tournament.position if latest_tournament is not None else None
            latest_wave = latest_tournament.wave if latest_tournament is not None else None
            latest_date = latest_tournament.date if latest_tournament is not None else None

            return {
                'best_position': best_position,
                'position_at_best_wave': best_position,
                'best_wave': best_wave,
                'best_date': best_date,
                'avg_position': round(avg_position, 2),
                'avg_wave': round(avg_wave, 2),
                'latest_position': latest_position,
                'latest_wave': latest_wave,
                'latest_date': latest_date,
                'total_tourneys': total_tourneys,
                'max_wave': player_df.wave.max(),
                'min_wave': player_df.wave.min(),
                'tournaments': player_df[['date', 'position', 'wave']].sort_values('date', ascending=False).to_dict('records') if 'date' in player_df.columns else []
            }
        else:
            # For other leagues, higher wave is better
            best_wave = player_df.wave.max()
            best_wave_row = player_df[player_df.wave == best_wave].iloc[0]
            position_at_best = best_wave_row.position
            best_date = best_wave_row.date if 'date' in best_wave_row else None

            # Calculate average position and wave
            avg_position = player_df.position.mean()
            avg_wave = player_df.wave.mean()

            # Find most recent tournament
            latest_tournament = player_df.sort_values('date', ascending=False).iloc[0] if 'date' in player_df.columns else None
            latest_position = latest_tournament.position if latest_tournament is not None else None
            latest_wave = latest_tournament.wave if latest_tournament is not None else None
            latest_date = latest_tournament.date if latest_tournament is not None else None

            return {
                'best_wave': best_wave,
                'position_at_best_wave': position_at_best,
                'best_date': best_date,
                'avg_position': round(avg_position, 2),
                'avg_wave': round(avg_wave, 2),
                'latest_position': latest_position,
                'latest_wave': latest_wave,
                'latest_date': latest_date,
                'total_tourneys': total_tourneys,
                'best_position': player_df.position.min(),
                'max_wave': best_wave,
                'min_wave': player_df.wave.min(),
                'tournaments': player_df[['date', 'position', 'wave']].sort_values('date', ascending=False).to_dict('records') if 'date' in player_df.columns else []
            }

    async def send_battle_conditions_embed(self, channel, league, tourney_date, battleconditions):
        """Helper method to create and send battle conditions embeds

        Args:
            channel: Channel to send the embed to
            league: League name for the battle conditions
            tourney_date: Tournament date string
            battleconditions: List of battle condition strings

        Returns:
            bool: Whether the message was sent successfully
        """
        try:
            embed = discord.Embed(
                title=f"{league} League Battle Conditions",
                description=f"Tournament on {tourney_date}",
                color=discord.Color.gold()
            )

            bc_text = "\n".join([f"• {bc}" for bc in battleconditions])
            embed.add_field(name="Predicted Battle Conditions", value=bc_text, inline=False)

            await channel.send(embed=embed)
            self.logger.info(f"Sent battle conditions for {league} league to channel {channel.name}")
            return True
        except Exception as e:
            self.logger.error(f"Error sending battle conditions for {league} league: {e}")
            return False

    @commands.group(
        name="tourney",
        aliases=["ts"],
        description="Tournament statistics commands"
    )
    async def tourney_group(self, ctx):
        """Commands for tournament statistics and analysis."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @tourney_group.command(
        name="status",
        description="Display operational status and statistics"
    )
    async def show_status(self, ctx):
        """Display current operational status of the player tournament stats system."""
        # Determine overall status
        if not self.is_ready:
            status_emoji = "⏳"
            status_text = "Initializing"
            embed_color = discord.Color.orange()
        elif self.has_task_errors():  # Use the new task error checking method
            status_emoji = "❌"
            status_text = "Error"
            embed_color = discord.Color.red()
        else:
            status_emoji = "✅"
            status_text = "Operational"
            embed_color = discord.Color.blue()

        embed = discord.Embed(
            title="Tournament Stats Status",
            description="Current operational state and statistics",
            color=embed_color
        )

        # Add status information
        status_value = [f"{status_emoji} Status: {status_text}"]
        if self._last_operation:
            time_since = self.format_relative_time(self._last_operation)
            status_value.append(f"🕒 Last Operation: {time_since}")

        embed.add_field(
            name="System State",
            value="\n".join(status_value),
            inline=False
        )

        # Add dependency information
        dependencies = []
        dependencies.append(f"Database Connection: {'✅ Available' if self.latest_patch else '❌ Not Established'}")

        if dependencies:
            embed.add_field(name="Dependencies", value="\n".join(dependencies), inline=False)

        # Add settings information
        settings = self.get_all_settings()
        settings_text = []
        for name, value in settings.items():
            settings_text.append(f"**{name}:** {value}")

        embed.add_field(
            name="Current Settings",
            value="\n".join(settings_text),
            inline=False
        )

        # Add process information using the task tracking system
        self.add_task_status_fields(embed)

        # Add cache statistics
        if self.league_dfs:
            total_rows = sum(len(df) for df in self.league_dfs.values())
            embed.add_field(
                name="Cache Statistics",
                value=f"Loaded {len(self.league_dfs)} leagues with {total_rows} total tournament entries",
                inline=False
            )

        # Add statistics
        stats_text = []
        if self._operation_count:
            stats_text.append(f"Operations completed: {self._operation_count}")
        if self.last_updated:
            stats_text.append(f"Last data update: {self.format_relative_time(self.last_updated)} ago")
        if stats_text:
            embed.add_field(
                name="Statistics",
                value="\n".join(stats_text),
                inline=False
            )

        await ctx.send(embed=embed)

    @tourney_group.command(
        name="settings",
        description="Manage tournament stats settings"
    )
    @app_commands.describe(
        setting_name="Setting to change",
        value="New value for the setting"
    )
    async def settings_command(self, ctx: commands.Context, setting_name: str, value: str) -> None:
        """Change a tournament stats setting.

        Args:
            setting_name: Setting to change
            value: New value for the setting
        """
        try:
            # Validate setting exists
            if not self.has_setting(setting_name):
                valid_settings = list(self.get_all_settings().keys())
                return await ctx.send(f"Invalid setting. Valid options: {', '.join(valid_settings)}")

            # Convert value to correct type based on current setting type
            current_value = self.get_setting(setting_name)
            if isinstance(current_value, bool):
                value = value.lower() in ('true', '1', 'yes')
            elif isinstance(current_value, int):
                value = int(value)
            elif isinstance(current_value, float):
                value = float(value)

            # Save the setting
            self.set_setting(setting_name, value)

            # Update instance variable if it exists
            if hasattr(self, setting_name):
                setattr(self, setting_name, value)

            await ctx.send(f"✅ Set {setting_name} to {value}")
            self.logger.info(f"Setting changed: {setting_name} = {value}")

        except ValueError:
            await ctx.send(f"Invalid value format for {setting_name}")
        except Exception as e:
            self.logger.error(f"Error changing setting: {e}")
            await ctx.send("An error occurred changing the setting")

    @tourney_group.command(
        name="pause",
        description="Pause/unpause tournament data updates"
    )
    async def pause_command(self, ctx: commands.Context) -> None:
        """Toggle pausing of tournament data updates."""
        # Get current pause state from settings
        is_paused = self.get_setting("paused", False)

        # Toggle state
        new_state = not is_paused
        self.set_setting("paused", new_state)

        # Update periodic task if it exists
        if hasattr(self, 'periodic_update_check'):
            if new_state:
                self.periodic_update_check.cancel()
            else:
                self.periodic_update_check.start()

        await ctx.send(f"✅ Tournament updates {'paused' if new_state else 'resumed'}")
        self.logger.info(f"Update task {'paused' if new_state else 'resumed'} by {ctx.author}")

    @tourney_group.command(
        name="refresh",
        aliases=["reload"],
        description="Refresh tournament data cache"
    )
    async def refresh_command(self, ctx: commands.Context) -> None:
        """Refresh tournament data cache."""
        try:
            message = await ctx.send("🔄 Refreshing tournament data cache... This may take a while.")

            # Start refreshing in the background
            async with ctx.typing():
                start_time = datetime.datetime.now()
                await self.get_tournament_data(refresh=True)
                duration = datetime.datetime.now() - start_time

                # Create a response with stats about the refresh
                counts = [f"{league}: {count}" for league, count in self.tournament_counts.items()]
                stats = "\n".join(counts)

                embed = discord.Embed(
                    title="Tournament Data Refreshed",
                    description=f"Successfully refreshed tournament data in {duration.total_seconds():.1f} seconds.",
                    color=discord.Color.green()
                )
                embed.add_field(name="Tournament Counts", value=stats)
                embed.add_field(name="Patch", value=str(self.latest_patch), inline=False)
                embed.add_field(name="Last Updated", value=self.last_updated.strftime("%Y-%m-%d %H:%M:%S"), inline=False)

                await message.edit(content=None, embed=embed)

        except Exception as e:
            self.logger.error(f"Error refreshing tournament data: {e}")
            await ctx.send(f"❌ Error refreshing tournament data: {e}")

    @tourney_group.command(name="player")
    async def tourney_player_stats(self, ctx, player_id: str, league: str = None):
        """
        Get player stats for a specific league

        Args:
            player_id: The player's ID
            league: (Optional) Specific league to check stats for
        """
        async with ctx.typing():
            stats = await self.get_player_stats(player_id, league)

            if not stats:
                return await ctx.send(f"No data found for player {player_id}")

            embed = discord.Embed(title=f"Player Stats: {player_id}", color=discord.Color.blue())

            for league_name, league_stats in stats.items():
                # Format dates for display
                best_date = league_stats.get('best_date')
                latest_date = league_stats.get('latest_date')
                best_date_str = best_date.strftime("%Y-%m-%d") if best_date else "N/A"
                latest_date_str = latest_date.strftime("%Y-%m-%d") if latest_date else "N/A"

                # Format key stats for the embed
                stat_text = (
                    f"**Wave Stats:**\n"
                    f"• Best wave: **{league_stats.get('best_wave', 'N/A')}** (Position {league_stats.get('position_at_best_wave', 'N/A')}, {best_date_str})\n"
                    f"• Average: **{league_stats.get('avg_wave', 'N/A')}**\n"
                    f"• Latest: **{league_stats.get('latest_wave', 'N/A')}** ({latest_date_str})\n"
                    f"• Range: {league_stats.get('min_wave', 'N/A')} - {league_stats.get('max_wave', 'N/A')}\n\n"

                    f"**Position Stats:**\n"
                    f"• Best position: **{league_stats.get('best_position', 'N/A')}**\n"
                    f"• Average: **{league_stats.get('avg_position', 'N/A')}**\n"
                    f"• Latest: **{league_stats.get('latest_position', 'N/A')}** ({latest_date_str})\n\n"

                    f"**Participation:**\n"
                    f"• Total tournaments: **{league_stats.get('total_tourneys', 'N/A')}**"
                )

                embed.add_field(name=f"{league_name.title()} League", value=stat_text, inline=False)

                # Add brief recent history if available
                tournaments = league_stats.get('tournaments', [])
                if tournaments and len(tournaments) > 0:
                    history_text = "**Recent tournaments:**\n"
                    # Show last 3 tournaments
                    for i, t in enumerate(tournaments[:3]):
                        t_date = t.get('date')
                        date_str = t_date.strftime("%Y-%m-%d") if t_date else "N/A"
                        history_text += f"• {date_str}: Wave {t.get('wave')}, Position {t.get('position')}\n"

                    embed.add_field(name=f"{league_name.title()} History", value=history_text, inline=False)

        await ctx.send(embed=embed)

    @tourney_group.command(name="league")
    async def tourney_league_summary(self, ctx, league_name: str = "legend"):
        """
        Show summary statistics for a tournament league

        Args:
            league_name: The league to get stats for (optional - shows all if not specified)
        """
        async with ctx.typing():
            dfs = await self.get_tournament_data()

            if league_name and league_name.capitalize() not in dfs:
                league_list = ", ".join(dfs.keys())
                return await ctx.send(f"League not found. Available leagues: {league_list}")

            leagues_to_show = [league_name] if league_name else dfs.keys()

            embed = discord.Embed(
                title="Tournament League Summary",
                color=discord.Color.blue()
            )

            for league in leagues_to_show:
                df = dfs[league.capitalize()]

                # Calculate league statistics
                total_players = df['id'].nunique()
                total_tournaments = self.tournament_counts.get(league, 0)
                avg_wave = round(df['wave'].mean(), 2)
                max_wave = df['wave'].max()

                stats = (
                    f"**Players:** {total_players}\n"
                    f"**Tournaments:** {total_tournaments}\n"
                    f"**Average Wave:** {avg_wave}\n"
                    f"**Highest Wave:** {max_wave}\n"
                )

                embed.add_field(name=f"{league.title()} League", value=stats, inline=False)

            embed.set_footer(text=f"Patch: {self.latest_patch} | Last Updated: {self.last_updated.strftime('%Y-%m-%d %H:%M:%S')}")

        await ctx.send(embed=embed)

    @tourney_group.command(name="top")
    async def tourney_top_players(self, ctx, league: str = "legend", count: int = 5):
        """
        Show top players in a league by highest wave

        Args:
            league: The league to check
            count: Number of players to show (default: 5, max: 20)
        """
        if count > 20:
            return await ctx.send("Cannot show more than 20 players at once")

        async with ctx.typing():
            dfs = await self.get_tournament_data()

            if league.capitalize() not in dfs:
                league_list = ", ".join(dfs.keys())
                return await ctx.send(f"League not found. Available leagues: {league_list}")

            df = dfs[league.capitalize()]

            # Get the highest wave for each player
            if league.lower() == "legend":
                # For legend league, lower position is better
                best_players = df.sort_values('position').drop_duplicates('id').head(count)
                ranking_metric = "position"
            else:
                # For other leagues, higher wave is better
                best_players = df.sort_values('wave', ascending=False).drop_duplicates('id').head(count)
                ranking_metric = "wave"

            embed = discord.Embed(
                title=f"Top Players in {league.title()} League",
                description=f"By {'position' if ranking_metric == 'position' else 'highest wave'}",
                color=discord.Color.gold()
            )

            for i, (_, player) in enumerate(best_players.iterrows(), 1):
                player_name = f"Player {player['id']}"
                value = f"{'Position' if ranking_metric == 'position' else 'Wave'}: **{player[ranking_metric]}**"

                if 'date' in player and player['date']:
                    value += f" (on {player['date'].strftime('%Y-%m-%d')})"

                embed.add_field(
                    name=f"#{i}: {player_name}",
                    value=value,
                    inline=False
                )

        await ctx.send(embed=embed)

    @tourney_group.command(name="compare")
    async def tourney_compare_players(self, ctx, league: str = "league", *player_ids):
        """
        Compare stats between multiple players in the same league

        Args:
            league: The league to compare in
            player_ids: Two or more player IDs to compare
        """
        if len(player_ids) < 2:
            return await ctx.send("Please provide at least two player IDs to compare")

        if len(player_ids) > 5:
            return await ctx.send("Cannot compare more than 5 players at once")

        async with ctx.typing():
            dfs = await self.get_tournament_data()

            if league.capitalize() not in dfs:
                league_list = ", ".join(dfs.keys())
                return await ctx.send(f"League not found. Available leagues: {league_list}")

            df = dfs[league.capitalize()]

            comparison_data = []
            missing_players = []

            for player_id in player_ids:
                player_df = df[df.id == player_id]

                if player_df.empty:
                    missing_players.append(player_id)
                    continue

                stats = self._calculate_league_stats(player_df, league.lower())
                comparison_data.append((player_id, stats))

            if missing_players:
                missing_str = ", ".join(missing_players)
                await ctx.send(f"⚠️ No data found for: {missing_str}")

            if not comparison_data:
                return await ctx.send("No valid players to compare")

            embed = discord.Embed(
                title=f"Player Comparison - {league.title()} League",
                color=discord.Color.blue()
            )

            # Add comparison fields for key stats
            for stat_name, display_name in [
                ('best_wave', 'Best Wave'),
                ('avg_wave', 'Avg Wave'),
                ('best_position', 'Best Position'),
                ('total_tourneys', 'Tournaments')
            ]:
                values = []
                for player_id, stats in comparison_data:
                    stat_value = stats.get(stat_name, 'N/A')
                    values.append(f"{player_id}: **{stat_value}**")

                embed.add_field(name=display_name, value="\n".join(values), inline=True)

        await ctx.send(embed=embed)

    @tourney_group.command(name="info")
    async def tourney_info_command(self, ctx):
        """Display information about the tournament stats system."""
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
            title="Tournament Statistics Information",
            description=(
                "Tracks and analyzes tournament performance across all leagues. "
                "Provides detailed statistics for player achievements and tournament history."
            ),
            color=embed_color
        )

        # Add status and data freshness
        status_value = [f"{status_emoji} System Status: {status_text}"]
        if self.last_updated:
            time_since_update = self.format_relative_time(self.last_updated)
            status_value.append(f"📅 Last Data Update: {time_since_update} ago")
        embed.add_field(
            name="System Status",
            value="\n".join(status_value),
            inline=False
        )

        # Add data coverage
        coverage = []
        for league, df in self.league_dfs.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                tournament_count = len(df)
                coverage.append(f"• {league}: {tournament_count} tournaments")

        if coverage:
            embed.add_field(
                name="Data Coverage",
                value="\n".join(coverage),
                inline=False
            )

        # Add statistics
        stats = []
        total_tournaments = sum(len(df) for df in self.league_dfs.values() if isinstance(df, pd.DataFrame))
        stats.append(f"📊 Total Tournaments: {total_tournaments}")
        if self.tournament_counts:
            for league, count in self.tournament_counts.items():
                stats.append(f"• {league}: {count} tracked")

        embed.add_field(
            name="Statistics",
            value="\n".join(stats),
            inline=False
        )

        # Add usage hint in footer
        embed.set_footer(text="Use /tourney help for detailed command information")

        await ctx.send(embed=embed)

    async def cog_unload(self):
        """Called when the cog is unloaded."""
        # Cancel the update task
        if hasattr(self, 'periodic_update_check') and self.periodic_update_check.is_running():
            self.periodic_update_check.cancel()

        # Save data when unloaded using super's implementation which handles
        # checking if data is modified and saving it appropriately
        await super().cog_unload()

        self.logger.info("Player tournament stats unloaded, data saved.")


async def setup(bot) -> None:
    await bot.add_cog(TourneyStats(bot))

