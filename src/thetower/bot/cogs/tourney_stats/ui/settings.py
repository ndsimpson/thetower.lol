import discord

from thetower.bot.ui.context import SettingsViewContext


class TourneyStatsSettingsView(discord.ui.View):
    """Settings view for TourneyStats cog - only accessible to bot owner."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)  # 5 minute timeout
        self.cog = context.cog_instance
        self.context = context

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
        check_interval = self.cog.get_setting("cache_check_interval", 5 * 60)

        embed.add_field(
            name="Current Settings",
            value=f"**Cache Check Interval:** {check_interval // 60} minutes",
            inline=False,
        )

        # Create buttons for editing
        view = CacheSettingsView(
            self.cog.SettingsViewContext(
                guild_id=self.context.guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=self.context.is_bot_owner
            )
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Display Settings", style=discord.ButtonStyle.secondary, emoji="📊")
    async def display_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Manage display-related settings."""
        embed = discord.Embed(title="Display Settings", description="Configure how tournament data is displayed", color=discord.Color.green())

        # Get current settings
        display_count = self.cog.get_setting("recent_tournaments_display_count", 3)

        embed.add_field(name="Current Settings", value=f"**Recent Tournaments Display Count:** {display_count}", inline=False)

        # Create buttons for editing
        view = DisplaySettingsView(
            self.cog.SettingsViewContext(
                guild_id=self.context.guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=self.context.is_bot_owner
            )
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="System Control", style=discord.ButtonStyle.danger, emoji="⚙️")
    async def system_control(self, interaction: discord.Interaction, button: discord.ui.Button):
        """System control options."""
        embed = discord.Embed(title="System Control", description="Control tournament stats system behavior", color=discord.Color.red())

        # Get current pause state
        is_paused = self.cog.get_setting("paused", False)

        embed.add_field(name="Current Status", value=f"**Updates Paused:** {'Yes' if is_paused else 'No'}", inline=False)

        view = SystemControlView(
            self.cog.SettingsViewContext(
                guild_id=self.context.guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=self.context.is_bot_owner
            )
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class CacheSettingsView(discord.ui.View):
    """View for editing cache settings."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context

    @discord.ui.button(label="Change Check Interval", style=discord.ButtonStyle.primary)
    async def change_check_interval(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Change the cache check interval."""
        modal = CacheCheckIntervalModal(self.context)
        await interaction.response.send_modal(modal)


class DisplaySettingsView(discord.ui.View):
    """View for editing display settings."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context

    @discord.ui.button(label="Change Display Count", style=discord.ButtonStyle.primary)
    async def change_display_count(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Change the recent tournaments display count."""
        modal = DisplayCountModal(self.context)
        await interaction.response.send_modal(modal)


class SystemControlView(discord.ui.View):
    """View for system control options."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context

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


class CacheCheckIntervalModal(discord.ui.Modal, title="Change Cache Check Interval"):
    """Modal for changing cache check interval."""

    minutes = discord.ui.TextInput(label="Cache Check Interval (minutes)", placeholder="5", default="5", max_length=4)

    def __init__(self, context: SettingsViewContext):
        super().__init__()
        self.cog = context.cog_instance

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission."""
        try:
            minutes = int(str(self.minutes))
            if minutes < 1 or minutes > 1440:  # 1 minute to 1 day
                await interaction.response.send_message("❌ Minutes must be between 1 and 1440 (24 hours)", ephemeral=True)
                return

            seconds = minutes * 60
            self.cog.set_setting("cache_check_interval", seconds)

            # Update the running task interval
            if hasattr(self.cog, "periodic_update_check"):
                self.cog.periodic_update_check.change_interval(seconds=seconds)

            await interaction.response.send_message(f"✅ Cache check interval changed to: {minutes} minutes", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number of minutes", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error changing cache check interval: {e}", ephemeral=True)


class DisplayCountModal(discord.ui.Modal, title="Change Display Count"):
    """Modal for changing display count."""

    count = discord.ui.TextInput(label="Recent Tournaments Display Count", placeholder="3", default="3", max_length=2)

    def __init__(self, context: SettingsViewContext):
        super().__init__()
        self.cog = context.cog_instance

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
