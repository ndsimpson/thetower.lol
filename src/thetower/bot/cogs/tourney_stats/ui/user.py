"""User-facing interaction flows for TourneyStats."""

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from ..cog import TourneyStats


class TourneyStatsUserInterface:
    """Handles user-facing interactions for tournament statistics."""

    def __init__(self, cog: "TourneyStats"):
        self.cog = cog

    async def send_player_stats_embed(self, ctx, player_id: str, league: str = None):
        """Send player statistics embed to the context."""
        async with ctx.typing():
            stats = await self.cog.get_player_stats(player_id, league)

            if not stats:
                return await ctx.send(f"No data found for player {player_id}")

            from .core import create_stats_embed
            embed = create_stats_embed(player_id, stats)
            await ctx.send(embed=embed)

    async def send_league_summary_embed(self, ctx, league_name: str = None):
        """Send league summary embed to the context."""
        async with ctx.typing():
            dfs = await self.cog.get_tournament_data()

            if league_name and league_name.capitalize() not in dfs:
                league_list = ", ".join(dfs.keys())
                return await ctx.send(f"League not found. Available leagues: {league_list}")

            leagues_to_show = [league_name] if league_name else dfs.keys()

            embed = discord.Embed(title="Tournament League Summary", color=discord.Color.blue())

            for league in leagues_to_show:
                df = dfs[league.capitalize()]

                # Calculate league statistics
                total_players = df["id"].nunique()
                total_tournaments = self.cog.tournament_counts.get(league.lower(), 0)
                avg_wave = round(df["wave"].mean(), 2)
                max_wave = df["wave"].max()

                stats = (
                    f"**Players:** {total_players}\n"
                    f"**Tournaments:** {total_tournaments}\n"
                    f"**Average Wave:** {avg_wave}\n"
                    f"**Highest Wave:** {max_wave}\n"
                )

                embed.add_field(name=f"{league.title()} League", value=stats, inline=False)

            embed.set_footer(text=f"Patch: {self.cog.latest_patch} | Last Updated: {self.cog.last_updated.strftime('%Y-%m-%d %H:%M:%S') if self.cog.last_updated else 'Never'}")

            await ctx.send(embed=embed)

    async def send_top_players_embed(self, ctx, league: str, count: int):
        """Send top players embed to the context."""
        if count > 20:
            return await ctx.send("Cannot show more than 20 players at once")

        async with ctx.typing():
            dfs = await self.cog.get_tournament_data()

            if league.capitalize() not in dfs:
                league_list = ", ".join(dfs.keys())
                return await ctx.send(f"League not found. Available leagues: {league_list}")

            df = dfs[league.capitalize()]

            # Get the highest wave for each player
            if league.lower() == "legend":
                # For legend league, lower position is better
                best_players = df.sort_values("position").drop_duplicates("id").head(count)
                ranking_metric = "position"
            else:
                # For other leagues, higher wave is better
                best_players = df.sort_values("wave", ascending=False).drop_duplicates("id").head(count)
                ranking_metric = "wave"

            embed = discord.Embed(
                title=f"Top Players in {league.title()} League",
                description=f"By {'position' if ranking_metric == 'position' else 'highest wave'}",
                color=discord.Color.gold(),
            )

            for i, (_, player) in enumerate(best_players.iterrows(), 1):
                player_name = f"Player {player['id']}"
                value = f"{'Position' if ranking_metric == 'position' else 'Wave'}: **{player[ranking_metric]}**"

                if "date" in player and player["date"]:
                    value += f" (on {player['date'].strftime('%Y-%m-%d')})"

                embed.add_field(name=f"#{i}: {player_name}", value=value, inline=False)

            await ctx.send(embed=embed)

    async def send_comparison_embed(self, ctx, league: str, player_ids: list):
        """Send player comparison embed to the context."""
        if len(player_ids) < 2:
            return await ctx.send("Please provide at least two player IDs to compare")

        if len(player_ids) > 5:
            return await ctx.send("Cannot compare more than 5 players at once")

        async with ctx.typing():
            dfs = await self.cog.get_tournament_data()

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

                stats = self.cog._calculate_league_stats(player_df, league.lower())
                comparison_data.append((player_id, stats))

            if missing_players:
                missing_str = ", ".join(missing_players)
                await ctx.send(f"⚠️ No data found for: {missing_str}")

            if not comparison_data:
                return await ctx.send("No valid players to compare")

            embed = discord.Embed(title=f"Player Comparison - {league.title()} League", color=discord.Color.blue())

            # Add comparison fields for key stats
            for stat_name, display_name in [
                ("best_wave", "Best Wave"),
                ("avg_wave", "Avg Wave"),
                ("best_position", "Best Position"),
                ("total_tourneys", "Tournaments"),
            ]:
                values = []
                for player_id, stats in comparison_data:
                    stat_value = stats.get(stat_name, "N/A")
                    values.append(f"{player_id}: **{stat_value}**")

                embed.add_field(name=display_name, value="\n".join(values), inline=True)

            await ctx.send(embed=embed)
