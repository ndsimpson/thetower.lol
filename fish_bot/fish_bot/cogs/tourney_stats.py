import logging
import asyncio
import pandas as pd
from typing import Dict
from asgiref.sync import sync_to_async
import datetime
import pickle
import discord
from discord.ext import commands
from pathlib import Path

from fish_bot.basecog import BaseCog
from dtower.sus.models import SusPerson
from dtower.tourney_results.constants import leagues, legend, how_many_results_hidden_site
from dtower.tourney_results.data import get_results_for_patch, get_tourneys
from dtower.tourney_results.models import PatchNew as Patch

# Define league hierarchy - order matters for importance
LEAGUE_HIERARCHY = ["legend", "champion", "platinum", "gold", "silver", "copper"]


class TourneyStats(BaseCog, name="Tourney Stats"):
    """
    Player-focused tournament statistics.

    Tracks player performance metrics across different leagues and tournaments,
    focusing on wave counts, placements, and other statistics.
    """

    def __init__(self, bot):
        super().__init__(bot)  # Initialize the BaseCog

        # Tourney data cache storage
        self.league_dfs = {}  # Cache for tournament dataframes by league
        self.latest_patch = None  # Cache for the latest patch
        self.last_updated = None  # When the data was last updated
        self.tournament_counts = {}  # Track number of tournaments per league

        # Set default settings if they don't exist
        if not self.has_setting("update_check_interval"):
            self.set_setting("update_check_interval", 6 * 60 * 60)  # 6 hours in seconds

        if not self.has_setting("update_error_retry_interval"):
            self.set_setting("update_error_retry_interval", 30 * 60)  # 30 minutes in seconds

        if not self.has_setting("recent_tournaments_display_count"):
            self.set_setting("recent_tournaments_display_count", 3)  # Default display count

        # Configure instance variables from settings
        self.update_check_interval = self.get_setting('update_check_interval')
        self.update_error_retry_interval = self.get_setting('update_error_retry_interval')
        self.recent_tournaments_display_count = self.get_setting('recent_tournaments_display_count')

        self.logger = logging.getLogger(__name__)

        self.load_cache_from_file()

    @property
    def cache_file(self) -> Path:
        """Get the cache file path using the cog's data directory"""
        cache_filename = self.get_setting('cache_filename', 'player_tourney_stats_data.pkl')
        return self.data_directory / cache_filename

    async def cog_initialize(self):
        """Initialize the cog - called by BaseCog during ready process"""
        # Load the tournament data
        await self.get_tournament_data(refresh=not self.league_dfs)

        # Start the update check task
        self.update_task = self.bot.loop.create_task(self.check_for_updates())

        self.logger.info("Tournament stats initialization complete")

    def load_cache_from_file(self):
        """Load the cache from a file"""
        try:
            # Check if file exists
            cache_file = self.cache_file
            if not cache_file.exists():
                self.logger.info("No tourney data cache file found, starting with empty cache")
                return

            # Load pickle data
            with open(cache_file, 'rb') as f:
                data = pickle.load(f)
            self.latest_patch = data.get('latest_patch')
            self.league_dfs = data.get('league_dfs', {})
            self.last_updated = data.get('last_updated')
            self.tournament_counts = data.get('tournament_counts', {})

            self.logger.info(f"Loaded data from {cache_file}")
            return data
        except Exception as e:
            self.logger.error(f"Failed to load data from {cache_file}: {e}")
            return

    async def save_data(self):
        """Save tournament data using BaseCog's utility."""
        # Prepare the data to save
        save_data = {
            'latest_patch': self.latest_patch,
            'league_dfs': self.league_dfs,
            'last_updated': self.last_updated or datetime.datetime.now(),
            'tournament_counts': self.tournament_counts
        }

        # Use BaseCog's utility to save data
        success = await self.save_data_if_modified(save_data, self.cache_file, force=True)

        if success:
            self.logger.info(f"Saved player tournament data to {self.cache_file} (patch: {self.latest_patch})")
        else:
            self.logger.error("Failed to save player tournament data")

    async def load_data(self):
        """Load tournament data using BaseCog's utility."""
        try:
            # Use BaseCog's utility to load data
            save_data = await self.load_data_from_file(self.cache_file, default={})

            if save_data:
                self.latest_patch = save_data.get('latest_patch')
                self.league_dfs = save_data.get('league_dfs', {})
                self.last_updated = save_data.get('last_updated')
                self.tournament_counts = save_data.get('tournament_counts', {})

                self.logger.info(f"Loaded player tournament data from {self.cache_file}")
                self.logger.info(f"  - Patch: {self.latest_patch}")
                self.logger.info(f"  - Leagues: {list(self.league_dfs.keys())}")
                self.logger.info(f"  - Tournament row counts: {self.tournament_counts}")
                self.logger.info(f"  - Last updated: {self.last_updated}")
            else:
                self.logger.info(f"No saved player tournament data file found at {self.cache_file}")
                # Initialize as empty
                self.league_dfs = {}
                self.latest_patch = None
                self.last_updated = None
                self.tournament_counts = {}
        except Exception as e:
            self.logger.error(f"Failed to load player tournament data: {e}")
            # Initialize as empty in case of loading error
            self.league_dfs = {}
            self.latest_patch = None
            self.last_updated = None
            self.tournament_counts = {}

    async def check_for_updates(self):
        """Check for new patches and refresh data if needed."""
        await self.bot.wait_until_ready()
        await self.wait_until_ready()

        while not self.bot.is_closed():
            try:
                # Get the current latest patch from DB
                current_patch = await self.get_latest_patch_from_db()

                # Check if patch is different
                if self.latest_patch and str(current_patch) != str(self.latest_patch):
                    self.logger.info(f"New patch detected: {current_patch} (was {self.latest_patch})")

                    # Reset patch and force refresh
                    self.latest_patch = None
                    await self.get_tournament_data(refresh=True)

                    # Update last_updated time
                    self.last_updated = datetime.datetime.now()

                    # Mark data as modified
                    self.mark_data_modified()

                    # Save refreshed data
                    await self.save_data()

                # Use configurable sleep intervals from settings
                update_interval = self.get_setting("update_check_interval")
                await asyncio.sleep(update_interval)

            except Exception as e:
                self.logger.error(f"Error checking for patch updates: {e}")
                # Use configurable error retry interval from settings
                error_retry_interval = self.get_setting("update_error_retry_interval")
                await asyncio.sleep(error_retry_interval)

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
            try:
                # Get patch info
                patch = await self.get_latest_patch()
                self.logger.info(f"Using patch: {patch}")

                # Get sus IDs to filter out
                sus_ids = {item.player_id for item in await sync_to_async(list)(SusPerson.objects.filter(sus=True))}
                self.logger.info(f"Found {len(sus_ids)} excluded player IDs")

                # Clear existing data if refreshing
                self.league_dfs = {}
                self.tournament_counts = {}

                # Load data for all leagues
                total_leagues = len(leagues)
                start_time = datetime.datetime.now()

                for i, league_name in enumerate(leagues):
                    league_start_time = datetime.datetime.now()
                    self.logger.info(f"Loading data for {league_name} league ({i + 1}/{total_leagues})...")

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
                final_msg = f"Loaded tournament data for {len(self.league_dfs)} leagues with {total_rows} total rows in {total_time}"
                self.logger.info(final_msg)

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

    @commands.group(name="tourney", aliases=["t"], invoke_without_command=True)
    async def tourney_group(self, ctx):
        """Commands for tournament statistics and player analysis"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @tourney_group.command(name="settings")
    async def tourney_settings_command(self, ctx):
        """Display current tournament statistics settings"""
        settings = self.get_all_settings()

        embed = discord.Embed(
            title="Tournament Stats Settings",
            description="Current configuration for tournament statistics",
            color=discord.Color.blue()
        )

        for name, value in settings.items():
            # Format durations in a more readable way for time-based settings
            if name in ["update_check_interval", "update_error_retry_interval"]:
                hours = value // 3600
                minutes = (value % 3600) // 60
                seconds = value % 60
                formatted_value = f"{hours}h {minutes}m {seconds}s ({value} seconds)"
                embed.add_field(name=name, value=formatted_value, inline=False)
            else:
                embed.add_field(name=name, value=str(value), inline=False)

        await ctx.send(embed=embed)

    @tourney_group.command(name="set")
    async def tourney_set_setting_command(self, ctx, setting_name: str, value: int):
        """Change a tournament stats setting

        Args:
            setting_name: Setting to change (update_check_interval, update_error_retry_interval, recent_tournaments_display_count)
            value: New value for the setting
        """
        valid_settings = [
            "update_check_interval",
            "update_error_retry_interval",
            "recent_tournaments_display_count"
        ]

        if setting_name not in valid_settings:
            valid_settings_str = ", ".join(valid_settings)
            return await ctx.send(f"Invalid setting name. Valid options: {valid_settings_str}")

        # Validate inputs based on the setting
        if setting_name in ["update_check_interval", "update_error_retry_interval"]:
            if value < 60:  # Minimum 60 seconds for time intervals
                return await ctx.send(f"Value for {setting_name} must be at least 60 seconds")
        elif setting_name == "recent_tournaments_display_count":
            if value < 1 or value > 10:
                return await ctx.send(f"Value for {setting_name} must be between 1 and 10")

        # Save the setting
        self.set_setting(setting_name, value)

        # Update instance variable
        if hasattr(self, setting_name):
            setattr(self, setting_name, value)

        # Format confirmation message
        if setting_name in ["update_check_interval", "update_error_retry_interval"]:
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

    @tourney_group.command(name="refresh")
    async def tourney_refresh_command(self, ctx):
        """Force refresh tournament data cache"""
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
            await ctx.send(f"❌ Error refreshing tournament data: {str(e)}")

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
        """Display information about the tournament stats system"""
        # Check if cache is ready or still loading
        cache_is_ready = self.is_ready

        embed = discord.Embed(
            title="Tournament Stats Information",
            color=discord.Color.blue() if cache_is_ready else discord.Color.orange()
        )

        # General information
        embed.add_field(
            name="Current Patch",
            value=str(self.latest_patch) if self.latest_patch else "Loading...",
            inline=False
        )

        embed.add_field(
            name="Last Updated",
            value=self.last_updated.strftime("%Y-%m-%d %H:%M:%S") if self.last_updated else "Never",
            inline=False
        )

        # Find latest tournament date
        latest_tourney_date = None
        if cache_is_ready and self.league_dfs:
            try:
                # Find the most recent tournament date across all leagues
                for league_name, df in self.league_dfs.items():
                    self.logger.debug(f"Checking dates for league {league_name}, columns: {df.columns.tolist()}")

                    if 'date' in df.columns and not df.empty:
                        # Make sure we're handling NaT values correctly
                        max_date = df['date'].max()
                        if pd.notna(max_date):  # Check if the date is valid (not NaT)
                            if latest_tourney_date is None or max_date > latest_tourney_date:
                                latest_tourney_date = max_date
                                self.logger.debug(f"Found new latest date: {latest_tourney_date} in league {league_name}")
            except Exception as e:
                self.logger.error(f"Error finding latest tournament date: {e}")
                # Don't let this error break the whole command
                latest_tourney_date = None

        # Add latest tournament date field
        if latest_tourney_date is not None:
            try:
                embed.add_field(
                    name="Latest Tournament Date",
                    value=latest_tourney_date.strftime("%Y-%m-%d"),
                    inline=False
                )
            except Exception as e:
                self.logger.error(f"Error formatting tournament date: {e}")
                embed.add_field(
                    name="Latest Tournament Date",
                    value=f"Error formatting date: {latest_tourney_date}",
                    inline=False
                )
        elif cache_is_ready:
            embed.add_field(
                name="Latest Tournament Date",
                value="No tournament dates found",
                inline=False
            )

        # League tournament counts
        if cache_is_ready and self.tournament_counts:
            counts_text = "\n".join([f"• **{league.title()}**: {count} tournament rows"
                                    for league, count in self.tournament_counts.items()])

            embed.add_field(
                name="Tournament Counts",
                value=counts_text,
                inline=False
            )
        else:
            embed.add_field(
                name="Tournament Counts",
                value="Data is currently being loaded...",
                inline=False
            )

        # System status with more detailed information
        if cache_is_ready:
            cache_status = "✅ Ready"
            embed.add_field(name="Cache Status", value=cache_status, inline=True)
        else:
            # If data is loading, provide estimated completion info
            loaded_leagues = len(self.league_dfs) if self.league_dfs else 0
            total_leagues = len(leagues)
            progress = f"{loaded_leagues}/{total_leagues} leagues"

            cache_status = f"⏳ Loading... ({progress})"
            embed.add_field(name="Cache Status", value=cache_status, inline=True)

            # Add a note about functionality during loading
            embed.set_footer(text="Some commands may have limited functionality until data loading completes.")

        await ctx.send(embed=embed)

    async def cog_unload(self):
        """Called when the cog is unloaded."""
        # Cancel the update task
        if hasattr(self, 'update_task'):
            self.update_task.cancel()

        # Save data when unloaded using super's implementation which handles
        # checking if data is modified and saving it appropriately
        await super().cog_unload()

        self.logger.info("Player tournament stats unloaded, data saved.")


async def setup(bot) -> None:
    await bot.add_cog(TourneyStats(bot))

