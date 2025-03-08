import discord
from discord.ext import commands
import logging
import asyncio
import pandas as pd
from typing import List, Optional
from asgiref.sync import sync_to_async
import datetime
import pickle
from pathlib import Path

from fish_bot.basecog import BaseCog
from dtower.sus.models import KnownPlayer, SusPerson
from dtower.tourney_results.constants import leagues, legend, how_many_results_hidden_site
from dtower.tourney_results.data import get_results_for_patch, get_tourneys
from dtower.tourney_results.models import PatchNew as Patch

# Set up logging
logger = logging.getLogger(__name__)


class TourneyStats(BaseCog, name="Tourney Stats"):
    """
    Provides tournament statistics for players using data from the RoleTracker cog.

    Shows players' best performances across different leagues and tournaments,
    utilizing the cached member data for efficient lookups.
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.league_dfs = {}  # Cache for tournament dataframes by league
        self.latest_patch = None  # Cache for the latest patch
        self.data_file = Path("data/tourney_stats_data.pkl")
        self.last_updated = None  # When the data was last updated
        self.tournament_counts = {}  # Track number of tournaments per league
        self.latest_tournament_dates = {}  # Track the most recent tournament date per league

        # Load any previously saved data
        self.load_data()

        # Schedule a task to check for updates
        self.bot.loop.create_task(self.check_for_updates())

    def save_data(self):
        """Save tournament data to a pickle file."""
        try:
            # Ensure the directory exists
            self.data_file.parent.mkdir(parents=True, exist_ok=True)

            # Prepare the data to save
            save_data = {
                'latest_patch': self.latest_patch,
                'league_dfs': self.league_dfs,
                'last_updated': self.last_updated or datetime.datetime.now(),
                'tournament_counts': self.tournament_counts,
                'latest_tournament_dates': self.latest_tournament_dates
            }

            # Save the data
            with open(self.data_file, 'wb') as f:
                pickle.dump(save_data, f)

            logger.info(f"Saved tournament data to {self.data_file} (patch: {self.latest_patch})")
        except Exception as e:
            logger.error(f"Failed to save tournament data: {e}")

    def load_data(self):
        """Load tournament data from a pickle file."""
        try:
            if self.data_file.exists():
                with open(self.data_file, 'rb') as f:
                    save_data = pickle.load(f)

                self.latest_patch = save_data.get('latest_patch')
                self.league_dfs = save_data.get('league_dfs', {})
                self.last_updated = save_data.get('last_updated')
                self.tournament_counts = save_data.get('tournament_counts', {})
                self.latest_tournament_dates = save_data.get('latest_tournament_dates', {})

                logger.info(f"Loaded tournament data from {self.data_file}")
                logger.info(f"  - Patch: {self.latest_patch}")
                logger.info(f"  - Leagues: {list(self.league_dfs.keys())}")
                logger.info(f"  - Tournament row counts: {self.tournament_counts}")
                logger.info(f"  - Last updated: {self.last_updated}")
            else:
                logger.info(f"No saved tournament data file found at {self.data_file}")
        except Exception as e:
            logger.error(f"Failed to load tournament data: {e}")
            # Initialize as empty in case of loading error
            self.league_dfs = {}
            self.latest_patch = None
            self.last_updated = None
            self.tournament_counts = {}
            self.latest_tournament_dates = {}

    async def check_for_new_patch(self):
        """Check if there's a new patch and refresh data if needed."""
        await self.bot.wait_until_ready()

        try:
            # Get the current latest patch from DB
            current_patch = await self.get_latest_patch_from_db()

            # If we have data and patch is different, refresh
            if self.latest_patch and str(current_patch) != str(self.latest_patch):
                logger.info(f"New patch detected: {current_patch} (was {self.latest_patch})")

                # Reset patch and force refresh
                self.latest_patch = None
                await self.get_tournament_data(refresh=True)

                # Update last_updated time
                self.last_updated = datetime.datetime.now()

                # Save refreshed data
                self.save_data()
        except Exception as e:
            logger.error(f"Error checking for new patch: {e}")

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

    async def get_tournament_data(self, league=None, refresh=False, ctx=None, status_message=None):
        """Get tournament data for the latest patch, optionally filtered by league."""
        # If we need to refresh or don't have data yet
        if refresh or not self.league_dfs:
            try:
                # Get patch info and log it
                if status_message:
                    await status_message.edit(content="Retrieving latest patch information...")

                patch = await self.get_latest_patch()
                logger.info(f"Using patch: {patch}")

                # Get sus IDs
                if status_message:
                    await status_message.edit(content="Retrieving list of excluded players...")

                sus_ids = {item.player_id for item in await sync_to_async(list)(SusPerson.objects.filter(sus=True))}
                logger.info(f"Found {len(sus_ids)} excluded player IDs")

                # Load data for all leagues
                total_leagues = len(leagues)
                start_time = datetime.datetime.now()

                # Clear existing data
                self.league_dfs = {}

                # Reset tournament tracking data
                self.tournament_counts = {}
                self.latest_tournament_dates = {}

                for i, league_name in enumerate(leagues):
                    league_start_time = datetime.datetime.now()

                    # Update status with progress
                    progress_msg = f"Loading data for {league_name} league ({i + 1}/{total_leagues})..."
                    logger.info(progress_msg)
                    if status_message:
                        await status_message.edit(content=progress_msg)

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

                    # If available, store the most recent tournament date
                    if 'date' in self.league_dfs[league_name].columns:
                        try:
                            most_recent = self.league_dfs[league_name]['date'].max()
                            self.latest_tournament_dates[league_name] = most_recent
                            logger.info(f"Most recent tournament in {league_name}: {most_recent}")
                        except Exception as e:
                            logger.warning(f"Could not determine most recent tournament date for {league_name}: {e}")

                    # Calculate timing info
                    league_time = datetime.datetime.now() - league_start_time
                    elapsed_total = datetime.datetime.now() - start_time

                    # Estimate remaining time
                    remaining_leagues = total_leagues - (i + 1)
                    if i > 0:  # Only after first league to get better estimates
                        avg_time_per_league = elapsed_total.total_seconds() / (i + 1)
                        est_remaining = datetime.timedelta(seconds=avg_time_per_league * remaining_leagues)
                    else:
                        est_remaining = "Calculating..."

                    # Log detailed stats
                    stats_msg = (
                        f"Loaded {league_name} data: {filtered_rows} rows "
                        f"({original_rows - filtered_rows} filtered) in {league_time.total_seconds():.1f}s"
                    )
                    logger.info(stats_msg)

                    # Update status with more details
                    if status_message:
                        progress_percent = ((i + 1) / total_leagues) * 100
                        detailed_msg = (
                            f"Progress: {i + 1}/{total_leagues} leagues loaded ({progress_percent:.1f}%)\n"
                            f"Latest: {league_name} with {filtered_rows} rows in {league_time.total_seconds():.1f}s\n"
                            f"Time elapsed: {elapsed_total}, remaining: {est_remaining}"
                        )
                        await status_message.edit(content=detailed_msg)

                    # Give asyncio a chance to process other tasks
                    await asyncio.sleep(0)

                # Final status update
                total_time = datetime.datetime.now() - start_time
                total_rows = sum(len(df) for df in self.league_dfs.values())
                final_msg = f"✅ Loaded tournament data for {len(self.league_dfs)} leagues with {total_rows} total rows in {total_time}"
                logger.info(final_msg)

                if status_message:
                    await status_message.edit(content=final_msg)

                # Update last updated timestamp
                self.last_updated = datetime.datetime.now()

                # Save the updated data
                self.save_data()

            except Exception as e:
                error_msg = f"❌ Error loading tournament data: {str(e)}"
                logger.error(error_msg)
                if status_message:
                    await status_message.edit(content=error_msg)
                raise

        # Return either all data or just the requested league
        if league:
            return self.league_dfs.get(league, pd.DataFrame())
        return self.league_dfs

    def cog_unload(self):
        """Called when the cog is unloaded."""
        self.save_data()
        logger.info("Tournament stats unloaded, data saved.")

    async def get_player_tournament_stats(self, player_id: str):
        """Get tournament statistics for a specific player ID."""
        stats = {}
        dfs = await self.get_tournament_data()

        for league_name, df in dfs.items():
            # Get this player's data in this league
            player_df = df[df.id == player_id]

            if player_df.empty:
                continue

            if league_name == legend:
                # For legend league, track best position
                best_position = player_df.position.min()
                best_row = player_df[player_df.position == best_position].iloc[0]
                best_wave = best_row.wave
                best_date = best_row.date if 'date' in best_row else 'Unknown'

                stats[league_name] = {
                    'best_position': best_position,
                    'best_wave': best_wave,
                    'best_date': best_date,
                    'total_tourneys': len(player_df)
                }
            else:
                # For other leagues, track best wave
                best_wave = player_df.wave.max()
                best_row = player_df[player_df.wave == best_wave].iloc[0]
                position_at_best = best_row.position
                best_date = best_row.date if 'date' in best_row else 'Unknown'

                stats[league_name] = {
                    'best_wave': best_wave,
                    'position_at_best': position_at_best,
                    'best_date': best_date,
                    'total_tourneys': len(player_df)
                }

        return stats

    async def get_player_tournament_stats_batch(self, player_ids):
        """Fetch tournament stats for multiple players at once."""
        result = {}
        for player_id in player_ids:
            result[player_id] = await self.get_player_tournament_stats(player_id)
        return result

    async def get_player_ids_by_discord_id(self, discord_id: int) -> List[str]:
        """Get all player IDs associated with a Discord user."""
        # Get the RoleTracker cog to access member data
        role_tracker = await self.get_role_tracker()

        # Check if the Discord ID is being tracked
        tracked_member = role_tracker.tracked_members.get(discord_id)
        if tracked_member and tracked_member.player_id:
            return [tracked_member.player_id]

        # If not in role tracker, try database lookup
        player = await sync_to_async(lambda: next(iter(KnownPlayer.objects.filter(discord_id=str(discord_id))), None))()
        if player:
            player_ids = await sync_to_async(lambda p=player: list(p.ids.all().values_list('id', flat=True)))()
            return player_ids

        return []

    async def get_role_tracker(self):
        """Get the RoleTracker cog."""
        role_tracker = self.bot.get_cog("Role Tracker")
        if not role_tracker:
            raise ValueError("Role Tracker cog is not loaded")
        return role_tracker

    @commands.group(name="tourneystats", aliases=["ts"], invoke_without_command=True)
    async def tourneystats(self, ctx):
        """Tournament statistics commands."""
        if ctx.invoked_subcommand is None:
            commands_list = [command.name for command in self.tourneystats.commands]
            await ctx.send(f"Available subcommands: {', '.join(commands_list)}")

    @tourneystats.command(name="refresh")
    async def refresh(self, ctx):
        """Refresh tournament data from the database."""
        # Create initial status message
        status_message = await ctx.send("Starting tournament data refresh...")

        try:
            # Force a refresh of tournament data with status updates
            self.latest_patch = None
            await self.get_tournament_data(refresh=True, ctx=ctx, status_message=status_message)

            # Final success message (the method will have already updated the status message)
            leagues_loaded = list(self.league_dfs.keys())
            total_rows = sum(len(df) for df in self.league_dfs.values())

            # Add a final confirmation that includes the leagues_loaded and total_rows
            await ctx.send(f"✅ Successfully refreshed data for {len(leagues_loaded)} leagues with {total_rows} total rows.")

            # Also display which leagues were loaded
            league_details = ", ".join(f"{league} ({len(self.league_dfs[league])} rows)" for league in leagues_loaded)
            await ctx.send(f"Leagues loaded: {league_details}")

        except Exception as e:
            # Error handling (the method will have already updated the status message with the error)
            logger.error(f"Error in refresh command: {e}")
            await ctx.send(f"❌ Error refreshing tournament data: {str(e)}")

    @tourneystats.command(name="player")
    async def player(self, ctx, *, user_input: str = None):
        """Show tournament statistics for a player.

        Arguments:
            user_input: Discord mention, ID, or name
        """
        discord_id = None
        player_ids = []
        player_name = None

        # Handle case when no input is provided
        if not user_input and not ctx.message.mentions:
            # Use the command author
            discord_id = ctx.author.id
            player_ids = await self.get_player_ids_by_discord_id(discord_id)
            player_name = ctx.author.display_name
        else:
            # Try to extract user from mention
            if ctx.message.mentions:
                discord_id = ctx.message.mentions[0].id
                player_ids = await self.get_player_ids_by_discord_id(discord_id)
                player_name = ctx.message.mentions[0].display_name
            else:
                # Try by ID
                if user_input.isdigit():
                    discord_id = int(user_input)
                    player_ids = await self.get_player_ids_by_discord_id(discord_id)
                    member = ctx.guild.get_member(discord_id)
                    player_name = member.display_name if member else str(discord_id)
                else:
                    # Try by name using role tracker data
                    role_tracker = await self.get_role_tracker()
                    user_input_lower = user_input.lower()

                    for member_id, member in role_tracker.tracked_members.items():
                        if member.name and user_input_lower in member.name.lower():
                            discord_id = member_id
                            player_ids = [member.player_id] if member.player_id else []
                            player_name = member.name
                            break

        if not player_ids:
            await ctx.send(f"❌ No player IDs found for: {user_input or ctx.author.mention}")
            return

        # Ensure we have tournament data
        if not self.league_dfs:
            await ctx.send("Loading tournament data. This may take a moment...")
            await self.get_tournament_data()

        # Get stats for all player IDs
        all_stats = {}
        for player_id in player_ids:
            player_stats = await self.get_player_tournament_stats(player_id)
            # Merge stats (taking best results if multiple IDs)
            for league, league_stats in player_stats.items():
                if league not in all_stats:
                    all_stats[league] = league_stats
                else:
                    # For legend, keep the best position
                    if league == legend and 'best_position' in league_stats:
                        if league_stats['best_position'] < all_stats[league]['best_position']:
                            all_stats[league] = league_stats
                    # For others, keep the best wave
                    elif 'best_wave' in league_stats:
                        if league_stats['best_wave'] > all_stats[league]['best_wave']:
                            all_stats[league] = league_stats

        if not all_stats:
            await ctx.send(f"❌ No tournament statistics found for {player_name}")
            return

        # Create embed for stats
        embed = discord.Embed(
            title=f"Tournament Statistics for {player_name}",
            color=discord.Color.gold()
        )

        # Format and add stats for each league
        for league_name in leagues:
            if league_name in all_stats:
                stats = all_stats[league_name]

                if league_name == legend:
                    value = f"Best Position: {stats['best_position']} (Wave {stats['best_wave']})\n"
                    value += f"Achieved on: {stats['best_date']}\n"
                else:
                    value = f"Best Wave: {stats['best_wave']} (Position {stats.get('position_at_best', 'N/A')})\n"
                    value += f"Achieved on: {stats['best_date']}\n"

                value += f"Total Tournaments: {stats['total_tourneys']}"

                embed.add_field(
                    name=f"{league_name.capitalize()} League",
                    value=value,
                    inline=False
                )

        # Add footer with data source
        patch = await self.get_latest_patch()
        embed.set_footer(text=f"Data from patch {patch}")

        await ctx.send(embed=embed)

    @tourneystats.command(name="leaderboard")
    async def leaderboard(self, ctx, league: str = None):
        """Show leaderboard for a specific league."""
        # Normalize and validate league name
        if league:
            league_lower = league.lower()

            # Check if the input matches any league name (case-insensitive)
            valid_league = None
            for x in leagues:
                if x.lower() == league_lower:
                    valid_league = x
                    break

            if not valid_league:
                # Show the actual league names as they exist in the constants
                league_names = ", ".join(leagues)
                await ctx.send(f"❌ Invalid league. Valid leagues: {league_names}")
                return

            league = valid_league
        else:
            league = legend  # Default to legend

        # Ensure we have data
        if not self.league_dfs:
            await ctx.send("Loading tournament data. This may take a moment...")
            await self.get_tournament_data()

        df = self.league_dfs.get(league)
        if df is None or df.empty:
            await ctx.send(f"❌ No tournament data found for {league} league")
            return

        # Log available columns for debugging
        logger.info(f"Available columns in {league} DataFrame: {df.columns.tolist()}")

        # Group by player ID and get best stats
        if league == legend:
            # For legend, group by ID and get best position
            best_positions = df.groupby('id').apply(
                lambda x: x.loc[x['position'].idxmin()]
            ).sort_values(['position', 'wave', 'date'], ascending=[True, False, False]).head(10)

            # Create embed
            embed = discord.Embed(
                title=f"Top 10 Players in {league.capitalize()} League",
                description="Rankings based on best tournament position",
                color=discord.Color.blue()
            )

            # Add entries
            for i, (player_id, row) in enumerate(best_positions.iterrows()):
                discord_name = await self.get_discord_name_from_player_id(row.name)

                # Get nickname if available, otherwise use player ID
                if 'nickname' in row:
                    player_name = row['nickname']
                else:
                    player_name = f"Player {row.name}"

                name_field = f"{discord_name} ({player_name})" if discord_name else player_name

                date_str = f"{row['date']}" if 'date' in row else "Unknown date"

                embed.add_field(
                    name=f"{i + 1}. {name_field}",
                    value=f"Position: {row['position']}, Wave: {row['wave']}\nAchieved on: {date_str}",
                    inline=False
                )
        else:
            # For other leagues, group by ID and get best wave
            best_waves = df.groupby('id').apply(
                lambda x: x.loc[x['wave'].idxmax()]
            ).sort_values('wave', ascending=False).head(10)

            # Create embed
            embed = discord.Embed(
                title=f"Top 10 Players in {league.capitalize()} League",
                description="Rankings based on best wave reached",
                color=discord.Color.blue()
            )

            # Add entries
            for i, (player_id, row) in enumerate(best_waves.iterrows()):
                discord_name = await self.get_discord_name_from_player_id(row.name)

                # Get nickname if available, otherwise use player ID
                if 'nickname' in row:
                    player_name = row['nickname']
                else:
                    player_name = f"Player {row.name}"

                name_field = f"{discord_name} ({player_name})" if discord_name else player_name

                date_str = f"{row['date']}" if 'date' in row else "Unknown date"

                embed.add_field(
                    name=f"{i + 1}. {name_field}",
                    value=f"Wave: {row['wave']}, Position: {row['position']}\nAchieved on: {date_str}",
                    inline=False
                )

        # Add footer with data source
        patch = await self.get_latest_patch()
        embed.set_footer(text=f"Data from patch {patch}")

        await ctx.send(embed=embed)

    async def get_discord_name_from_player_id(self, player_id: str) -> Optional[str]:
        """Try to find a Discord name for a player ID using RoleTracker data."""
        role_tracker = await self.get_role_tracker()

        # Look through tracked members for matching player ID
        for tracked_member in role_tracker.tracked_members.values():
            if tracked_member.player_id == player_id:
                return tracked_member.name

        return None

    @tourneystats.command(name="status")
    async def status(self, ctx):
        """Show status of tournament data."""
        embed = discord.Embed(
            title="Tournament Stats Status",
            color=discord.Color.blue()
        )

        # Add patch info
        embed.add_field(
            name="Current Patch",
            value=str(self.latest_patch) if self.latest_patch else "Not loaded",
            inline=False
        )

        # Add last updated time
        if self.last_updated:
            time_since = datetime.datetime.now() - self.last_updated
            days = time_since.days
            hours = time_since.seconds // 3600
            minutes = (time_since.seconds // 60) % 60

            time_str = f"{self.last_updated.strftime('%Y-%m-%d %H:%M:%S')}\n"
            time_str += f"({days}d {hours}h {minutes}m ago)"

            embed.add_field(
                name="Last Updated",
                value=time_str,
                inline=True
            )
        else:
            embed.add_field(
                name="Last Updated",
                value="Never",
                inline=True
            )

        # Add tournament information
        league_info = []
        total_rows = 0

        for league_name in leagues:
            if league_name in self.league_dfs and league_name in self.tournament_counts:
                rows = len(self.league_dfs[league_name])
                total_rows += rows

                league_str = f"{league_name.capitalize()}: {rows} tournament rows"

                # Add most recent date if available
                if league_name in self.latest_tournament_dates:
                    most_recent = self.latest_tournament_dates[league_name]
                    league_str += f" (Latest: {most_recent})"

                league_info.append(league_str)

        if league_info:
            embed.add_field(
                name=f"Leagues Loaded ({total_rows} total tournaments)",
                value="\n".join(league_info),
                inline=False
            )
        else:
            embed.add_field(
                name="Leagues Loaded",
                value="None",
                inline=False
            )

        # Update data freshness checks
        try:
            # Check for patch freshness
            current_db_patch = await self.get_latest_patch_from_db()
            patch_current = str(current_db_patch) == str(self.latest_patch) if self.latest_patch else False

            # Check for tournament freshness
            has_new_tournaments = await self.has_new_tournament_data()

            # Determine overall status
            if not patch_current:
                status_str = f"❌ Outdated patch (new patch: {current_db_patch})"
            elif has_new_tournaments:
                status_str = "❌ New tournament data available"
            else:
                status_str = "✅ Data is up to date"

            embed.add_field(
                name="Data Status",
                value=status_str,
                inline=False
            )
        except Exception as e:
            embed.add_field(
                name="Data Status",
                value=f"❌ Error checking: {str(e)}",
                inline=False
            )

        await ctx.send(embed=embed)

    @tourneystats.command(name="userstats")
    async def userstats(self, ctx):
        """Show statistics about known users with tournament results for the latest patch."""
        # Send initial message
        status_message = await ctx.send("⏳ Gathering tournament player statistics...")

        # Ensure we have data
        if not self.league_dfs:
            await status_message.edit(content="Loading tournament data. This may take a moment...")
            await self.get_tournament_data()

        await status_message.edit(content="⏳ Processing player data...")

        # Create embed
        embed = discord.Embed(
            title="Tournament Player Statistics",
            description="Known Discord users vs. total players in tournaments",
            color=discord.Color.green()
        )

        # Pre-fetch ALL discord names for ALL player IDs once to avoid repeated lookups
        all_player_ids = set()
        for league_name, df in self.league_dfs.items():
            if df is not None and not df.empty:
                all_player_ids.update(set(df['id'].unique()))

        # Create a lookup dictionary mapping player IDs to Discord names
        player_id_to_discord_name = {}

        # Get the role tracker once
        role_tracker = await self.get_role_tracker()

        # First use the cached data from role tracker (fast)
        for member in role_tracker.tracked_members.values():
            if member.player_id and member.player_id in all_player_ids:
                player_id_to_discord_name[member.player_id] = member.name

        # Process in chunks for progress updates
        total_leagues = len(leagues)

        # Track unique IDs across all leagues
        known_player_ids = set()

        # Process each league with status updates
        for i, league_name in enumerate(leagues):
            # Update progress every league
            progress = ((i + 1) / total_leagues) * 100
            await status_message.edit(content=f"⏳ Processing league data: {league_name} ({progress:.1f}%)...")

            df = self.league_dfs.get(league_name)
            if df is None or df.empty:
                embed.add_field(
                    name=f"{league_name.capitalize()} League",
                    value="No tournament data available",
                    inline=True
                )
                continue

            # Count unique player IDs in this league
            league_player_ids = set(df['id'].unique())

            # Count how many are known Discord users (using our pre-built lookup)
            league_known_ids = {pid for pid in league_player_ids if pid in player_id_to_discord_name}
            known_player_ids.update(league_known_ids)

            # Calculate percentage
            known_count = len(league_known_ids)
            total_count = len(league_player_ids)
            percentage = (known_count / total_count * 100) if total_count > 0 else 0

            # Add to embed
            embed.add_field(
                name=f"{league_name.capitalize()} League",
                value=f"Known users: {known_count}/{total_count} ({percentage:.1f}%)",
                inline=True
            )

        # Calculate totals across all leagues
        total_known = len(known_player_ids)
        total_players = len(all_player_ids)
        total_percentage = (total_known / total_players * 100) if total_players > 0 else 0

        # Add totals to embed
        embed.add_field(
            name="Total Unique Known Users",
            value=f"{total_known}/{total_players} ({total_percentage:.1f}%)",
            inline=False
        )

        # Add footer with data source
        patch = await self.get_latest_patch()
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        embed.set_footer(text=f"Data from patch {patch}")

        # Send the final result
        await status_message.edit(content="✅ Player statistics complete!", embed=embed)

    async def check_for_updates(self):
        """Check for new patches or tournaments and refresh data if needed."""
        await self.bot.wait_until_ready()

        try:
            # Get the current latest patch from DB
            current_patch = await self.get_latest_patch_from_db()

            # Check if patch is different
            patch_changed = self.latest_patch and str(current_patch) != str(self.latest_patch)

            # Check if there are new tournaments
            has_new_tournaments = await self.has_new_tournament_data()

            # If either patch changed or new tournaments detected, refresh data
            if patch_changed or has_new_tournaments:
                if patch_changed:
                    logger.info(f"New patch detected: {current_patch} (was {self.latest_patch})")
                if has_new_tournaments:
                    logger.info("New tournament data detected")

                # Reset patch and force refresh
                if patch_changed:
                    self.latest_patch = None
                await self.get_tournament_data(refresh=True)

                # Update last_updated time
                self.last_updated = datetime.datetime.now()

                # Save refreshed data
                self.save_data()
        except Exception as e:
            logger.error(f"Error checking for updates: {e}")

    async def has_new_tournament_data(self):
        """Check if there are any new tournaments since last update."""
        # If we don't have any data yet, we need to get it
        if not self.league_dfs:
            return True

        try:
            # For each league, check if the tournament count has changed
            for league_name in leagues:
                # Get a small sample of recent tournament data
                results = await sync_to_async(get_results_for_patch)(
                    patch=await self.get_latest_patch(),
                    league=league_name
                )

                # Get the tournament count
                current_count = await sync_to_async(lambda: len(results))()
                previous_count = self.tournament_counts.get(league_name, 0)

                if current_count > previous_count:
                    logger.info(f"Detected new tournaments in {league_name} league: {current_count} vs {previous_count}")
                    return True

                # Check also for the most recent tournament date if available
                if results:
                    # Try to get the most recent tournament date
                    try:
                        dates = await sync_to_async(lambda: [r.date for r in results if hasattr(r, 'date')])()
                        if dates:
                            most_recent = max(dates)
                            previous_recent = self.latest_tournament_dates.get(league_name)

                            # If we have a new most recent date, or we didn't have one before
                            if not previous_recent or most_recent > previous_recent:
                                logger.info(f"Detected newer tournament in {league_name} league: {most_recent} vs {previous_recent}")
                                return True
                    except Exception as e:
                        logger.warning(f"Could not compare tournament dates for {league_name}: {e}")

        except Exception as e:
            logger.error(f"Error checking for new tournament data: {e}")

        # No new tournaments detected
        return False

    async def get_latest_tournament_date(self, league):
        """Get the date of the most recent tournament for a specific league."""
        if league.lower() in self.league_dfs:
            df = self.league_dfs[league.lower()]
            if not df.empty and 'date' in df.columns:
                return df['date'].max()
        return None


async def setup(bot) -> None:
    await bot.add_cog(TourneyStats(bot))
