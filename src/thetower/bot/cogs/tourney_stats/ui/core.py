"""Core business logic and shared components for TourneyStats."""

from datetime import datetime
from typing import Any, Dict

import discord


def format_relative_time(seconds: float) -> str:
    """Format seconds into a human-readable relative time string."""
    if seconds < 60:
        return f"{int(seconds)} seconds"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    elif seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''}"
    else:
        days = int(seconds // 86400)
        return f"{days} day{'s' if days != 1 else ''}"


def create_stats_embed(player_id: str, stats: Dict[str, Any]) -> discord.Embed:
    """Create an embed for player statistics.

    Args:
        player_id: The player's ID
        stats: Dictionary of league statistics

    Returns:
        Discord embed with formatted statistics
    """
    import discord

    embed = discord.Embed(title=f"Player Stats: {player_id}", color=discord.Color.blue())

    for league_name, league_stats in stats.items():
        # Format dates for display
        best_date = league_stats.get("best_date")
        latest_date = league_stats.get("latest_date")
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
        tournaments = league_stats.get("tournaments", [])
        if tournaments and len(tournaments) > 0:
            history_text = "**Recent tournaments:**\n"
            # Show last 3 tournaments
            for i, t in enumerate(tournaments[:3]):
                t_date = t.get("date")
                date_str = t_date.strftime("%Y-%m-%d") if t_date else "N/A"
                history_text += f"• {date_str}: Wave {t.get('wave')}, Position {t.get('position')}\n"

            embed.add_field(name=f"{league_name.title()} History", value=history_text, inline=False)

    return embed


def create_league_summary_embed(dfs: Dict, tournament_counts: Dict, latest_patch: str, last_updated: datetime) -> discord.Embed:
    """Create an embed for league summary statistics.

    Args:
        dfs: Dictionary of league dataframes
        tournament_counts: Dictionary of tournament counts per league
        latest_patch: Current patch version
        last_updated: Last update timestamp

    Returns:
        Discord embed with league summaries
    """
    import discord

    embed = discord.Embed(title="Tournament League Summary", color=discord.Color.blue())

    for league_name, df in dfs.items():
        # Calculate league statistics
        total_players = df["id"].nunique()
        total_tournaments = tournament_counts.get(league_name.lower(), 0)
        avg_wave = round(df["wave"].mean(), 2)
        max_wave = df["wave"].max()

        stats = (
            f"**Players:** {total_players}\n"
            f"**Tournaments:** {total_tournaments}\n"
            f"**Average Wave:** {avg_wave}\n"
            f"**Highest Wave:** {max_wave}\n"
        )

        embed.add_field(name=f"{league_name.title()} League", value=stats, inline=False)

    embed.set_footer(text=f"Patch: {latest_patch} | Last Updated: {last_updated.strftime('%Y-%m-%d %H:%M:%S')}")

    return embed
