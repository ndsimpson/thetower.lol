from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from ..cog import TourneyStats


class TourneyStatsSettingsView(discord.ui.View):
    """Settings view for TourneyStats cog - only accessible to bot owner."""

    def __init__(self, cog: "TourneyStats"):
        super().__init__(timeout=300)  # 5 minute timeout
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the user is the bot owner."""
        if not await self.cog.bot.is_owner(interaction.user):
            await interaction.response.send_message("❌ Only the bot owner can access these settings.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Cache Settings", style=discord.ButtonStyle.primary, emoji="💾")
    async def cache_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Manage cache-related settings."""
        embed = discord.Embed(title="Cache Settings", description="Configure tournament data caching", color=discord.Color.blue())

        # Get current settings
        cache_filename = self.cog.get_setting("cache_filename", "tourney_stats_data.pkl")
        update_interval = self.cog.get_setting("update_check_interval", 6 * 60 * 60)

        embed.add_field(
            name="Current Settings",
            value=(f"**Cache Filename:** {cache_filename}\n" f"**Update Interval:** {update_interval // 3600} hours\n"),
            inline=False,
        )

        # Create buttons for editing
        view = CacheSettingsView(self.cog)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Display Settings", style=discord.ButtonStyle.secondary, emoji="📊")
    async def display_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Manage display-related settings."""
        embed = discord.Embed(title="Display Settings", description="Configure how tournament data is displayed", color=discord.Color.green())

        # Get current settings
        display_count = self.cog.get_setting("recent_tournaments_display_count", 3)

        embed.add_field(name="Current Settings", value=f"**Recent Tournaments Display Count:** {display_count}", inline=False)

        # Create buttons for editing
        view = DisplaySettingsView(self.cog)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="System Control", style=discord.ButtonStyle.danger, emoji="⚙️")
    async def system_control(self, interaction: discord.Interaction, button: discord.ui.Button):
        """System control options."""
        embed = discord.Embed(title="System Control", description="Control tournament stats system behavior", color=discord.Color.red())

        # Get current pause state
        is_paused = self.cog.get_setting("paused", False)

        embed.add_field(name="Current Status", value=f"**Updates Paused:** {'Yes' if is_paused else 'No'}", inline=False)

        view = SystemControlView(self.cog)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class CacheSettingsView(discord.ui.View):
    """View for editing cache settings."""

    def __init__(self, cog: "TourneyStats"):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="Change Cache Filename", style=discord.ButtonStyle.primary)
    async def change_cache_filename(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Change the cache filename."""
        modal = CacheFilenameModal(self.cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Change Update Interval", style=discord.ButtonStyle.primary)
    async def change_update_interval(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Change the update check interval."""
        modal = UpdateIntervalModal(self.cog)
        await interaction.response.send_modal(modal)


class DisplaySettingsView(discord.ui.View):
    """View for editing display settings."""

    def __init__(self, cog: "TourneyStats"):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="Change Display Count", style=discord.ButtonStyle.primary)
    async def change_display_count(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Change the recent tournaments display count."""
        modal = DisplayCountModal(self.cog)
        await interaction.response.send_modal(modal)


class SystemControlView(discord.ui.View):
    """View for system control options."""

    def __init__(self, cog: "TourneyStats"):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="Toggle Pause", style=discord.ButtonStyle.danger)
    async def toggle_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Toggle the pause state of updates."""
        is_paused = self.cog.get_setting("paused", False)
        new_state = not is_paused

        self.cog.set_setting("paused", new_state)

        # Update periodic task if it exists
        if hasattr(self.cog, "periodic_update_check"):
            if new_state:
                self.cog.periodic_update_check.cancel()
            else:
                self.cog.periodic_update_check.start()

        status = "paused" if new_state else "resumed"
        await interaction.response.send_message(f"✅ Tournament updates {status}", ephemeral=True)

    @discord.ui.button(label="Force Refresh", style=discord.ButtonStyle.secondary)
    async def force_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Force a refresh of tournament data."""
        await interaction.response.defer(ephemeral=True)

        try:
            await self.cog.get_tournament_data(refresh=True)
            await interaction.followup.send("✅ Tournament data refreshed successfully", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error refreshing data: {e}", ephemeral=True)


class CacheFilenameModal(discord.ui.Modal, title="Change Cache Filename"):
    """Modal for changing cache filename."""

    filename = discord.ui.TextInput(label="Cache Filename", placeholder="tourney_stats_data.pkl", default="tourney_stats_data.pkl", max_length=100)

    def __init__(self, cog: "TourneyStats"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission."""
        try:
            new_filename = str(self.filename)
            self.cog.set_setting("cache_filename", new_filename)
            await interaction.response.send_message(f"✅ Cache filename changed to: {new_filename}", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error changing cache filename: {e}", ephemeral=True)


class UpdateIntervalModal(discord.ui.Modal, title="Change Update Interval"):
    """Modal for changing update interval."""

    hours = discord.ui.TextInput(label="Update Interval (hours)", placeholder="6", default="6", max_length=3)

    def __init__(self, cog: "TourneyStats"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission."""
        try:
            hours = int(str(self.hours))
            if hours < 1 or hours > 168:  # 1 hour to 1 week
                await interaction.response.send_message("❌ Hours must be between 1 and 168", ephemeral=True)
                return

            seconds = hours * 60 * 60
            self.cog.set_setting("update_check_interval", seconds)

            # Update the running task interval
            if hasattr(self.cog, "periodic_update_check"):
                self.cog.periodic_update_check.change_interval(seconds=seconds)

            await interaction.response.send_message(f"✅ Update interval changed to: {hours} hours", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number of hours", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error changing update interval: {e}", ephemeral=True)


class DisplayCountModal(discord.ui.Modal, title="Change Display Count"):
    """Modal for changing display count."""

    count = discord.ui.TextInput(label="Recent Tournaments Display Count", placeholder="3", default="3", max_length=2)

    def __init__(self, cog: "TourneyStats"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission."""
        try:
            display_count = int(str(self.count))
            if display_count < 1 or display_count > 10:
                await interaction.response.send_message("❌ Count must be between 1 and 10", ephemeral=True)
                return

            self.cog.set_setting("recent_tournaments_display_count", display_count)
            await interaction.response.send_message(f"✅ Display count changed to: {display_count}", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error changing display count: {e}", ephemeral=True)
