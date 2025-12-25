import discord

from thetower.bot.ui.context import BaseSettingsView, SettingsViewContext


class TourneyStatsSettingsView(BaseSettingsView):
    """Settings view for TourneyStats cog - only accessible to bot owner."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(context)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the user is the bot owner."""
        if not await self.cog.bot.is_owner(interaction.user):
            await interaction.response.send_message("❌ Only the bot owner can access these settings.", ephemeral=True)
            return False
        return True

    async def get_embed(self) -> discord.Embed:
        """Create the main settings embed displaying all current settings."""
        embed = discord.Embed(
            title="Tournament Stats Settings",
            description="Configure tournament statistics tracking and caching (Bot Owner Only)",
            color=discord.Color.blue(),
        )

        # Cache Settings
        check_interval = self.cog.get_setting("cache_check_interval", 5 * 60)
        embed.add_field(name="💾 Cache Settings", value=f"**Check Interval:** {check_interval // 60} minutes", inline=False)

        # Display Settings
        display_count = self.cog.get_setting("recent_tournaments_display_count", 3)
        embed.add_field(name="📊 Display Settings", value=f"**Recent Tournaments Display Count:** {display_count}", inline=False)

        # System Status
        is_paused = self.cog.get_setting("paused", False)
        embed.add_field(name="⚙️ System Status", value=f"**Updates Paused:** {'Yes ⏸️' if is_paused else 'No ▶️'}", inline=False)

        return embed

    @discord.ui.button(label="Cache Settings", style=discord.ButtonStyle.primary, emoji="💾")
    async def cache_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Manage cache-related settings."""
        view = CacheSettingsView(self.context)
        embed = await view.get_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Display Settings", style=discord.ButtonStyle.secondary, emoji="📊")
    async def display_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Manage display-related settings."""
        view = DisplaySettingsView(self.context)
        embed = await view.get_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="System Control", style=discord.ButtonStyle.danger, emoji="⚙️")
    async def system_control(self, interaction: discord.Interaction, button: discord.ui.Button):
        """System control options."""
        view = SystemControlView(self.context)
        embed = await view.get_embed()
        await interaction.response.edit_message(embed=embed, view=view)


class CacheSettingsView(discord.ui.View):
    """View for editing cache settings."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context

    async def get_embed(self) -> discord.Embed:
        """Create the cache settings embed."""
        check_interval = self.cog.get_setting("cache_check_interval", 5 * 60)

        embed = discord.Embed(title="💾 Cache Settings", description="Configure tournament data caching behavior", color=discord.Color.blue())

        embed.add_field(
            name="Current Settings",
            value=f"**Cache Check Interval:** {check_interval // 60} minutes\n" f"*Controls how often the system checks for new tournament data*",
            inline=False,
        )

        return embed

    @discord.ui.button(label="Change Check Interval", style=discord.ButtonStyle.primary)
    async def change_check_interval(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Change the cache check interval."""
        modal = CacheCheckIntervalModal(self.context, self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go back to main settings."""
        main_view = TourneyStatsSettingsView(self.context)
        embed = await main_view.get_embed()
        await interaction.response.edit_message(embed=embed, view=main_view)


class DisplaySettingsView(discord.ui.View):
    """View for editing display settings."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context

    async def get_embed(self) -> discord.Embed:
        """Create the display settings embed."""
        display_count = self.cog.get_setting("recent_tournaments_display_count", 3)

        embed = discord.Embed(title="📊 Display Settings", description="Configure how tournament data is displayed", color=discord.Color.green())

        embed.add_field(
            name="Current Settings",
            value=f"**Recent Tournaments Display Count:** {display_count}\n" f"*Number of recent tournaments shown in commands*",
            inline=False,
        )

        return embed

    @discord.ui.button(label="Change Display Count", style=discord.ButtonStyle.primary)
    async def change_display_count(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Change the recent tournaments display count."""
        modal = DisplayCountModal(self.context, self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go back to main settings."""
        main_view = TourneyStatsSettingsView(self.context)
        embed = await main_view.get_embed()
        await interaction.response.edit_message(embed=embed, view=main_view)


class SystemControlView(discord.ui.View):
    """View for system control options."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context

    async def get_embed(self) -> discord.Embed:
        """Create the system control embed."""
        is_paused = self.cog.get_setting("paused", False)

        embed = discord.Embed(
            title="⚙️ System Control",
            description="Control tournament statistics system behavior",
            color=discord.Color.orange() if is_paused else discord.Color.green(),
        )

        status_emoji = "⏸️" if is_paused else "▶️"
        status_text = "Paused" if is_paused else "Active"

        embed.add_field(
            name="Current Status",
            value=f"{status_emoji} **{status_text}**\n" f"*Updates are currently {'paused' if is_paused else 'running normally'}*",
            inline=False,
        )

        embed.add_field(
            name="Available Actions",
            value="• **Toggle Pause**: Pause or resume automatic tournament data updates\n"
            "• **Force Refresh**: Immediately fetch latest tournament data",
            inline=False,
        )

        return embed

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

        # Refresh the view to show updated status
        embed = await self.get_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Force Refresh", style=discord.ButtonStyle.secondary)
    async def force_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Force a refresh of tournament data."""
        await interaction.response.defer()

        try:
            await self.cog.get_tournament_data(refresh=True)
            # Refresh view with success indicator in embed
            embed = await self.get_embed()
            embed.set_footer(text="✅ Tournament data refreshed successfully")
            await interaction.edit_original_response(embed=embed, view=self)
        except Exception as e:
            # Refresh view with error indicator in embed
            embed = await self.get_embed()
            embed.set_footer(text=f"❌ Error refreshing data: {e}")
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go back to main settings."""
        main_view = TourneyStatsSettingsView(self.context)
        embed = await main_view.get_embed()
        await interaction.response.edit_message(embed=embed, view=main_view)


class CacheCheckIntervalModal(discord.ui.Modal, title="Change Cache Check Interval"):
    """Modal for changing cache check interval."""

    minutes = discord.ui.TextInput(label="Cache Check Interval (minutes)", placeholder="5", default="5", max_length=4)

    def __init__(self, context: SettingsViewContext, parent_view: CacheSettingsView):
        super().__init__()
        self.cog = context.cog_instance
        self.parent_view = parent_view

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

            # Refresh the parent view to show updated settings
            embed = await self.parent_view.get_embed()
            embed.set_footer(text=f"✅ Cache check interval changed to: {minutes} minutes")
            await interaction.response.edit_message(embed=embed, view=self.parent_view)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number of minutes", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error changing cache check interval: {e}", ephemeral=True)


class DisplayCountModal(discord.ui.Modal, title="Change Display Count"):
    """Modal for changing display count."""

    count = discord.ui.TextInput(label="Recent Tournaments Display Count", placeholder="3", default="3", max_length=2)

    def __init__(self, context: SettingsViewContext, parent_view: DisplaySettingsView):
        super().__init__()
        self.cog = context.cog_instance
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission."""
        try:
            display_count = int(str(self.count))
            if display_count < 1 or display_count > 10:
                await interaction.response.send_message("❌ Count must be between 1 and 10", ephemeral=True)
                return

            self.cog.set_setting("recent_tournaments_display_count", display_count)

            # Refresh the parent view to show updated settings
            embed = await self.parent_view.get_embed()
            embed.set_footer(text=f"✅ Display count changed to: {display_count}")
            await interaction.response.edit_message(embed=embed, view=self.parent_view)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error changing display count: {e}", ephemeral=True)
