"""Admin interface for TourneyStats."""

from datetime import datetime
from typing import TYPE_CHECKING

import discord
import pandas as pd

if TYPE_CHECKING:
    from ..cog import TourneyStats


class TourneyAdminView(discord.ui.View):
    """Admin view for tournament statistics management."""

    def __init__(self, cog: "TourneyStats"):
        super().__init__(timeout=900)  # 10 minute timeout
        self.cog = cog

    async def create_admin_embed(self) -> discord.Embed:
        """Create the comprehensive admin embed with all system information."""
        # Determine overall status
        if not self.cog.is_ready:
            status_emoji = "⏳"
            status_text = "Initializing"
            embed_color = discord.Color.orange()
        elif self.cog.task_tracker.has_errors():
            status_emoji = "❌"
            status_text = "Error"
            embed_color = discord.Color.red()
        else:
            status_emoji = "✅"
            status_text = "Operational"
            embed_color = discord.Color.blue()

        embed = discord.Embed(
            title="🏆 Tournament Statistics Admin Panel", description="Comprehensive system status and management interface", color=embed_color
        )

        # System Status
        status_value = [f"{status_emoji} **Status:** {status_text}"]
        if self.cog._last_operation:
            time_since = self.cog.format_relative_time(self.cog._last_operation)
            status_value.append(f"🕒 **Last Operation:** {time_since}")
        embed.add_field(name="📊 System Status", value="\n".join(status_value), inline=False)

        # Dependencies
        dependencies = []
        dependencies.append(f"🗄️ **Database:** {'✅ Available' if self.cog.latest_patch else '❌ Not Established'}")
        embed.add_field(name="🔗 Dependencies", value="\n".join(dependencies), inline=False)

        # Current Settings
        settings = self.cog.get_all_global_settings()
        settings_text = []
        for name, value in settings.items():
            if name == "cache_check_interval":
                minutes = value // 60
                settings_text.append(f"**{name}:** {minutes} minutes")
            elif name == "update_error_retry_interval":
                minutes = value // 60
                settings_text.append(f"**{name}:** {minutes} minutes")
            else:
                settings_text.append(f"**{name}:** {value}")
        embed.add_field(name="⚙️ Current Settings", value="\n".join(settings_text), inline=False)

        # Cache Statistics
        if self.cog.league_dfs:
            total_rows = sum(len(df) for df in self.cog.league_dfs.values())
            cache_stats = [
                f"📁 **Leagues Loaded:** {len(self.cog.league_dfs)}",
                f"📈 **Total Entries:** {total_rows:,}",
                f"🎯 **Current Patch:** {self.cog.latest_patch or 'None'}",
                f"📅 **Latest Tournament:** {self.cog.latest_tournament_date or 'None'}",
            ]
            if self.cog.last_updated:
                cache_stats.append(f"🔄 **Last Updated:** {self.cog.last_updated.strftime('%Y-%m-%d %H:%M:%S')}")
            embed.add_field(name="💾 Cache Statistics", value="\n".join(cache_stats), inline=False)

        # Data Coverage & Statistics
        coverage_stats = []

        for league, df in self.cog.league_dfs.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                entry_count = len(df)
                coverage_stats.append(f"• **{league.title()}:** {entry_count:,} entries")

        if coverage_stats:
            coverage_stats.insert(0, f"🏆 **Total Tournaments:** {self.cog.total_tournaments:,}")
            embed.add_field(name="📊 Data Coverage", value="\n".join(coverage_stats), inline=False)

        embed.set_footer(text="Tournament data is accessed through other bot commands • Use refresh button to update data")

        return embed

    @discord.ui.button(label="Refresh Data", style=discord.ButtonStyle.primary, emoji="🔄")
    async def refresh_data(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Refresh tournament data (Bot Owner Only)."""
        # Check if user is bot owner
        if not await self.cog.bot.is_owner(interaction.user):
            await interaction.response.send_message("❌ Only the bot owner can refresh tournament data.", ephemeral=True)
            return

        # Disable button during refresh
        button.disabled = True
        button.label = "Refreshing..."
        await interaction.response.edit_message(view=self)

        try:
            start_time = datetime.now()
            await self.cog.get_tournament_data(refresh=True)
            duration = datetime.now() - start_time

            # Create success embed
            embed = discord.Embed(
                title="✅ Tournament Data Refreshed",
                description=f"Successfully refreshed tournament data in {duration.total_seconds():.1f} seconds.",
                color=discord.Color.green(),
            )

            # Add refresh statistics
            counts = [f"• **{league.title()}:** {count:,}" for league, count in self.cog.tournament_counts.items()]
            if counts:
                embed.add_field(name="📊 Tournament Counts", value="\n".join(counts), inline=False)

            embed.add_field(name="🎯 Current Patch", value=str(self.cog.latest_patch), inline=True)
            embed.add_field(name="🕒 Last Updated", value=self.cog.last_updated.strftime("%Y-%m-%d %H:%M:%S"), inline=True)

            # Re-enable button and update view
            button.disabled = False
            button.label = "Refresh Data"
            updated_embed = await self.create_admin_embed()

            await interaction.edit_original_response(embed=updated_embed, view=self)

        except Exception as e:
            self.cog.logger.error(f"Error refreshing tournament data: {e}")

            # Re-enable button
            button.disabled = False
            button.label = "Refresh Data"

            await interaction.edit_original_response(content=f"❌ Error refreshing tournament data: {e}", view=self)
