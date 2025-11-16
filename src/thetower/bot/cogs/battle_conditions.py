import datetime
from typing import List, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from thetower.bot.basecog import BaseCog

# Graceful towerbcs import handling
try:
    from towerbcs.towerbcs import TournamentPredictor, predict_future_tournament

    TOWERBCS_AVAILABLE = True
except ImportError:
    TOWERBCS_AVAILABLE = False

    def predict_future_tournament(tourney_id, league):
        return ["Battle conditions unavailable - towerbcs package not installed"]

    class TournamentPredictor:
        @staticmethod
        def get_tournament_info():
            return None, "Unknown", 0


# === UI Components ===

class BCManagementView(discord.ui.View):
    """Main view for battle conditions management."""

    def __init__(self, cog: 'BattleConditions', can_generate: bool, can_run_schedule: bool, is_owner: bool):
        super().__init__(timeout=300)
        self.cog = cog

        # Always add View button (anyone can view)
        self.add_item(ViewBCButton())

        # Add Generate button if user has permission
        if can_generate:
            self.add_item(GenerateBCButton())

        # Add Run Schedule button if user has permission
        if can_run_schedule:
            self.add_item(ResendBCButton())

        # Add Settings button for owners only
        if is_owner:
            self.add_item(SettingsBCButton())


class ViewBCButton(discord.ui.Button):
    """Button to view current battle conditions."""

    def __init__(self):
        super().__init__(
            label="View BCs",
            style=discord.ButtonStyle.primary,
            emoji="👁️"
        )

    async def callback(self, interaction: discord.Interaction):
        view: BCManagementView = self.view
        cog = view.cog

        if not TOWERBCS_AVAILABLE:
            await interaction.response.send_message(
                "⚠️ Battle conditions package not available.",
                ephemeral=True
            )
            return

        # Get tournament info
        tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info()

        # Check if bot owner
        is_bot_owner = await cog.bot.is_owner(interaction.user)

        # Check viewing window (global setting, not per-guild)
        view_window_days = cog.get_setting("bc_view_window_days", guild_id=None)
        if view_window_days is None:
            view_window_days = cog.default_settings["bc_view_window_days"]

        # Check if outside viewing window
        outside_window = False
        if view_window_days is not None and days_until > view_window_days:
            outside_window = True
            if not is_bot_owner:
                await interaction.response.send_message(
                    f"⏰ Battle conditions are not yet available.\n"
                    f"You can view them {view_window_days} day(s) before the tournament.\n"
                    f"Next tournament: {tourney_date} ({days_until} days away)",
                    ephemeral=True
                )
                return

        # Get enabled leagues for this guild
        guild_id = interaction.guild.id
        enabled_leagues = cog.get_setting("enabled_leagues", guild_id=guild_id)
        if not enabled_leagues:
            enabled_leagues = cog.default_settings["enabled_leagues"]

        if not enabled_leagues:
            await interaction.response.send_message(
                "No leagues enabled. Use settings to configure.",
                ephemeral=True
            )
            return

        # Show league selection dropdown
        select_view = discord.ui.View(timeout=300)
        select_view.add_item(ViewLeagueSelect(cog, enabled_leagues, tourney_date, outside_window))

        warning_msg = ""
        if outside_window and is_bot_owner:
            warning_msg = f"⚠️ **Outside viewing window** (window: {view_window_days} days, current: {days_until} days)\n\n"

        await interaction.response.send_message(
            f"{warning_msg}Select a league to view battle conditions:",
            view=select_view,
            ephemeral=True
        )


class ViewLeagueSelect(discord.ui.Select):
    """Select menu for choosing which league BCs to view."""

    def __init__(self, cog: 'BattleConditions', enabled_leagues: List[str], tourney_date: str, outside_window: bool = False):
        options = [
            discord.SelectOption(
                label=league,
                value=league,
                emoji="🏆"
            )
            for league in enabled_leagues
        ]

        # Add "All Leagues" option at the top
        options.insert(0, discord.SelectOption(
            label="All Leagues",
            value="__all__",
            emoji="🌟"
        ))

        super().__init__(
            placeholder="Choose a league...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.cog = cog
        self.enabled_leagues = enabled_leagues
        self.tourney_date = tourney_date
        self.outside_window = outside_window

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]

        # Defer as this might take a moment
        await interaction.response.defer(ephemeral=True)

        if selected == "__all__":
            # Show all enabled leagues
            embeds = []
            for league in self.enabled_leagues:
                conditions = await self.cog.get_battle_conditions(league)

                embed = discord.Embed(
                    title=f"{league} League Battle Conditions",
                    description=f"Tournament on {self.tourney_date}",
                    color=discord.Color.gold()
                )

                bc_text = "\n".join([f"• {bc}" for bc in conditions])
                embed.add_field(name="Predicted Battle Conditions", value=bc_text, inline=False)
                embeds.append(embed)

            # Send up to 10 embeds (Discord limit)
            await interaction.followup.send(embeds=embeds[:10], ephemeral=True)
        else:
            # Show single league
            conditions = await self.cog.get_battle_conditions(selected)

            embed = discord.Embed(
                title=f"{selected} League Battle Conditions",
                description=f"Tournament on {self.tourney_date}",
                color=discord.Color.gold()
            )

            bc_text = "\n".join([f"• {bc}" for bc in conditions])
            embed.add_field(name="Predicted Battle Conditions", value=bc_text, inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)


class GenerateBCButton(discord.ui.Button):
    """Button to generate battle conditions to current channel."""

    def __init__(self):
        super().__init__(
            label="Generate to Channel",
            style=discord.ButtonStyle.success,
            emoji="📝"
        )

    async def callback(self, interaction: discord.Interaction):
        view: BCManagementView = self.view
        cog = view.cog

        # Check channel permission
        if not await cog.check_slash_channel_permission(interaction, "generate"):
            await interaction.response.send_message(
                "❌ You cannot use generate in this channel.",
                ephemeral=True
            )
            return

        if not TOWERBCS_AVAILABLE:
            await interaction.response.send_message(
                "⚠️ Battle conditions package not available.",
                ephemeral=True
            )
            return

        # Defer as this might take a moment
        await interaction.response.defer(ephemeral=True)

        # Get tournament info
        tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info()

        # Get enabled leagues for this guild
        guild_id = interaction.guild.id
        enabled_leagues = cog.get_setting("enabled_leagues", guild_id=guild_id)
        if not enabled_leagues:
            enabled_leagues = cog.default_settings["enabled_leagues"]

        # Send BCs to current channel
        sent_count = 0
        for league in enabled_leagues:
            conditions = await cog.get_battle_conditions(league)
            success = await cog.send_battle_conditions_embed(
                interaction.channel,
                league,
                tourney_date,
                conditions
            )
            if success:
                sent_count += 1

        # Confirm to user
        await interaction.followup.send(
            f"✅ Generated battle conditions for {sent_count} league(s) in {interaction.channel.mention}",
            ephemeral=True
        )


class ResendBCButton(discord.ui.Button):
    """Button to trigger existing schedules."""

    def __init__(self):
        super().__init__(
            label="Run Schedule",
            style=discord.ButtonStyle.secondary,
            emoji="🔄"
        )

    async def callback(self, interaction: discord.Interaction):
        view: BCManagementView = self.view
        cog = view.cog
        guild_id = interaction.guild.id

        if not TOWERBCS_AVAILABLE:
            await interaction.response.send_message(
                "⚠️ Battle conditions package not available.",
                ephemeral=True
            )
            return

        # Get all schedules for this guild
        destination_schedules = cog.get_setting("destination_schedules", guild_id=guild_id)
        if not destination_schedules:
            destination_schedules = []

        if not destination_schedules:
            await interaction.response.send_message(
                "❌ No schedules configured for this server.\n"
                "Use Settings → Manage Schedules to create one.",
                ephemeral=True
            )
            return

        # Show schedule selection dropdown
        select_view = discord.ui.View(timeout=300)
        select_view.add_item(ScheduleSelect(cog, destination_schedules, guild_id))

        await interaction.response.send_message(
            "Select a schedule to run immediately:",
            view=select_view,
            ephemeral=True
        )


class ScheduleSelect(discord.ui.Select):
    """Select menu for choosing which schedule to run."""

    def __init__(self, cog: 'BattleConditions', schedules: list, guild_id: int):
        # Build options from schedules
        options = []
        for idx, schedule in enumerate(schedules):
            destination_id = schedule.get("destination_id", "Unknown")
            leagues = schedule.get("leagues", [])
            paused = schedule.get("paused", False)

            # Get channel name if possible
            channel = cog.bot.get_channel(int(destination_id))
            channel_name = channel.name if channel else f"ID: {destination_id}"

            label = f"#{idx}: {channel_name}"
            description = f"Leagues: {', '.join(leagues[:3])}" + ("..." if len(leagues) > 3 else "")
            if paused:
                description = "⏸️ PAUSED - " + description

            options.append(discord.SelectOption(
                label=label[:100],  # Discord limit
                value=str(idx),
                description=description[:100],
                emoji="⏸️" if paused else "📅"
            ))

        super().__init__(
            placeholder="Choose a schedule to run...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.cog = cog
        self.schedules = schedules
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        selected_idx = int(self.values[0])
        schedule = self.schedules[selected_idx]

        # Defer as this might take a moment
        await interaction.response.defer(ephemeral=True)

        # Get tournament info
        tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info()

        # Get schedule details
        destination_id = schedule.get("destination_id")
        leagues = schedule.get("leagues", [])
        paused = schedule.get("paused", False)

        # Get channel
        channel = self.cog.bot.get_channel(int(destination_id))
        if not channel:
            await interaction.followup.send(
                f"❌ Channel with ID {destination_id} not found. It may have been deleted.",
                ephemeral=True
            )
            return

        # Verify channel is in the correct guild
        if channel.guild.id != self.guild_id:
            await interaction.followup.send(
                f"❌ Channel {channel.mention} is not in this server.",
                ephemeral=True
            )
            return

        # Get enabled leagues for this guild
        enabled_leagues = self.cog.get_setting("enabled_leagues", guild_id=self.guild_id)
        if not enabled_leagues:
            enabled_leagues = self.cog.default_settings["enabled_leagues"]

        # Send BCs to channel
        sent_count = 0
        for league in leagues:
            # Skip leagues that aren't enabled
            if league not in enabled_leagues:
                continue

            try:
                conditions = await self.cog.get_battle_conditions(league)
                success = await self.cog.send_battle_conditions_embed(
                    channel,
                    league,
                    tourney_date,
                    conditions
                )
                if success:
                    sent_count += 1
            except Exception as e:
                self.cog.logger.error(f"Error sending BC for {league}: {e}")

        # Confirm to user
        paused_note = " (⚠️ Note: This schedule is paused)" if paused else ""
        await interaction.followup.send(
            f"✅ Sent battle conditions for {sent_count} league(s) to {channel.mention}{paused_note}",
            ephemeral=True
        )


class SettingsBCButton(discord.ui.Button):
    """Button to manage BC settings (owner only)."""

    def __init__(self):
        super().__init__(
            label="Settings",
            style=discord.ButtonStyle.secondary,
            emoji="⚙️"
        )

    async def callback(self, interaction: discord.Interaction):
        view: BCManagementView = self.view
        cog = view.cog

        # Check if bot owner
        is_bot_owner = await cog.bot.is_owner(interaction.user)

        # Show settings view
        settings_view = BCSettingsView(cog, is_bot_owner)

        guild_id = interaction.guild.id
        enabled_leagues = cog.get_setting("enabled_leagues", guild_id=guild_id) or cog.default_settings["enabled_leagues"]

        settings_text = (
            f"**Current Settings**\n\n"
            f"**Enabled Leagues:** {', '.join(enabled_leagues)}\n\n"
            f"Use the buttons below to configure settings."
        )

        await interaction.response.send_message(settings_text, view=settings_view, ephemeral=True)


class BCSettingsView(discord.ui.View):
    """View for managing BC settings."""

    def __init__(self, cog: 'BattleConditions', is_bot_owner: bool = False):
        super().__init__(timeout=300)
        self.cog = cog

        # Add buttons for different settings
        self.add_item(ConfigureLeaguesButton())
        self.add_item(ConfigurePermissionsButton())
        self.add_item(ManageSchedulesButton())

        # Add global settings button for bot owner only
        if is_bot_owner:
            self.add_item(GlobalSettingsButton())


class ConfigureLeaguesButton(discord.ui.Button):
    """Button to configure enabled leagues."""

    def __init__(self):
        super().__init__(
            label="Configure Leagues",
            style=discord.ButtonStyle.primary,
            emoji="🏆"
        )

    async def callback(self, interaction: discord.Interaction):
        view: BCSettingsView = self.view
        cog = view.cog
        guild_id = interaction.guild.id

        # Get current enabled leagues
        enabled_leagues = cog.get_setting("enabled_leagues", guild_id=guild_id) or cog.default_settings["enabled_leagues"]

        # Create select menu with all leagues
        league_select = LeagueSelect(cog, enabled_leagues)
        select_view = discord.ui.View(timeout=300)
        select_view.add_item(league_select)

        await interaction.response.send_message(
            "Select which leagues to enable:",
            view=select_view,
            ephemeral=True
        )


class LeagueSelect(discord.ui.Select):
    """Select menu for choosing enabled leagues."""

    def __init__(self, cog: 'BattleConditions', current_enabled: List[str]):
        all_leagues = ["Legend", "Champion", "Platinum", "Gold", "Silver", "Bronze"]

        options = [
            discord.SelectOption(
                label=league,
                value=league,
                default=league in current_enabled
            )
            for league in all_leagues
        ]

        super().__init__(
            placeholder="Select leagues to enable...",
            min_values=1,
            max_values=len(all_leagues),
            options=options
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        selected_leagues = self.values

        # Save to settings
        self.cog.set_setting("enabled_leagues", selected_leagues, guild_id=guild_id)

        await interaction.response.send_message(
            f"✅ Enabled leagues updated: {', '.join(selected_leagues)}",
            ephemeral=True
        )


class ConfigurePermissionsButton(discord.ui.Button):
    """Button to configure action permissions."""

    def __init__(self):
        super().__init__(
            label="Configure Permissions",
            style=discord.ButtonStyle.secondary,
            emoji="🔒"
        )

    async def callback(self, interaction: discord.Interaction):
        # Show permission configuration view
        perm_view = BCPermissionsView(self.view.cog)

        await interaction.response.send_message(
            "**Permission Configuration**\n\n"
            "Choose which action to configure permissions for:",
            view=perm_view,
            ephemeral=True
        )


class ManageSchedulesButton(discord.ui.Button):
    """Button to manage BC schedules."""

    def __init__(self):
        super().__init__(
            label="Manage Schedules",
            style=discord.ButtonStyle.primary,
            emoji="📅"
        )

    async def callback(self, interaction: discord.Interaction):
        view: BCSettingsView = self.view
        cog = view.cog
        guild_id = interaction.guild.id

        # Check manage_schedules permission
        can_manage = await cog.check_slash_action_permission(interaction, "manage_schedules")
        is_owner = interaction.guild.owner_id == interaction.user.id or await cog.bot.is_owner(interaction.user)

        # Get schedules for this guild
        schedules = cog.get_setting("destination_schedules", guild_id=guild_id) or []

        # Show schedule management view
        schedule_view = ScheduleManagementView(cog, guild_id, schedules, can_manage or is_owner)

        if schedules:
            schedule_list = []
            for idx, schedule in enumerate(schedules):
                dest_id = schedule.get("destination_id")
                channel = cog.bot.get_channel(int(dest_id))
                channel_name = channel.mention if channel else f"ID: {dest_id}"
                leagues = ", ".join(schedule.get("leagues", [])[:3])
                paused = "⏸️ " if schedule.get("paused", False) else ""
                time = f"{schedule.get('hour', 0):02d}:{schedule.get('minute', 0):02d}"
                schedule_list.append(f"{paused}**#{idx}**: {channel_name} - {leagues} @ {time} UTC")

            schedule_text = (
                f"**Current Schedules** ({len(schedules)})\n\n" +
                "\n".join(schedule_list[:10]) +
                (f"\n\n...and {len(schedules) - 10} more" if len(schedules) > 10 else "")
            )
        else:
            schedule_text = "**No schedules configured**\n\nClick 'Create Schedule' to add one."

        await interaction.response.send_message(
            schedule_text,
            view=schedule_view,
            ephemeral=True
        )


class ScheduleManagementView(discord.ui.View):
    """View for managing BC schedules."""

    def __init__(self, cog: 'BattleConditions', guild_id: int, schedules: list, can_manage: bool = False):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.schedules = schedules

        # Add management buttons only if user has permission
        if can_manage:
            # Add create button
            self.add_item(CreateScheduleButton())

            # Add edit/delete/pause buttons if schedules exist
            if schedules:
                self.add_item(EditScheduleButton())
                self.add_item(DeleteScheduleButton())
                self.add_item(TogglePauseScheduleButton())


class CreateScheduleButton(discord.ui.Button):
    """Button to create a new schedule."""

    def __init__(self):
        super().__init__(
            label="Create Schedule",
            style=discord.ButtonStyle.success,
            emoji="➕"
        )

    async def callback(self, interaction: discord.Interaction):
        # Step 1: Show channel picker
        channel_view = discord.ui.View(timeout=300)
        channel_view.add_item(ScheduleChannelSelect(self.view.cog, self.view.guild_id))

        await interaction.response.send_message(
            "**Step 1/3:** Select the channel or thread for battle conditions:",
            view=channel_view,
            ephemeral=True
        )


class ScheduleChannelSelect(discord.ui.ChannelSelect):
    """Channel select for new schedule."""

    def __init__(self, cog: 'BattleConditions', guild_id: int):
        super().__init__(
            placeholder="Select channel or thread...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.public_thread, discord.ChannelType.private_thread]
        )
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]

        # Step 2: Show time configuration modal
        modal = ScheduleTimeModal(self.cog, self.guild_id, channel.id)
        await interaction.response.send_modal(modal)


class ScheduleTimeModal(discord.ui.Modal, title="Schedule Time Configuration"):
    """Modal for configuring schedule time."""

    def __init__(self, cog: 'BattleConditions', guild_id: int, channel_id: int):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.channel_id = channel_id

        self.days_before_input = discord.ui.TextInput(
            label="Days before tournament (0-7)",
            placeholder="e.g., 1 for day before tournament",
            default="1",
            required=True,
            max_length=1
        )
        self.add_item(self.days_before_input)

        self.hour_input = discord.ui.TextInput(
            label="Hour (0-23, UTC)",
            placeholder="e.g., 14 for 2 PM UTC",
            default="0",
            required=True,
            max_length=2
        )
        self.add_item(self.hour_input)

        self.minute_input = discord.ui.TextInput(
            label="Minute (0-59)",
            placeholder="e.g., 30 for half past the hour",
            default="0",
            required=True,
            max_length=2
        )
        self.add_item(self.minute_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Parse and validate time inputs
            days_before = int(self.days_before_input.value)
            hour = int(self.hour_input.value)
            minute = int(self.minute_input.value)

            if not (0 <= days_before <= 7):
                await interaction.response.send_message("❌ Days before must be 0-7", ephemeral=True)
                return
            if not (0 <= hour <= 23):
                await interaction.response.send_message("❌ Hour must be 0-23", ephemeral=True)
                return
            if not (0 <= minute <= 59):
                await interaction.response.send_message("❌ Minute must be 0-59", ephemeral=True)
                return

            # Step 3: Show league picker
            league_view = discord.ui.View(timeout=300)
            league_view.add_item(ScheduleLeagueSelect(self.cog, self.guild_id, self.channel_id, hour, minute, days_before))

            await interaction.response.send_message(
                f"**Step 3/3:** Select leagues to include in this schedule:\n"
                f"Channel: <#{self.channel_id}>\n"
                f"Time: {hour:02d}:{minute:02d} UTC, {days_before} day(s) before tournament",
                view=league_view,
                ephemeral=True
            )

        except ValueError as e:
            await interaction.response.send_message(
                f"❌ Invalid input: {e}",
                ephemeral=True
            )


class ScheduleLeagueSelect(discord.ui.Select):
    """Select menu for choosing leagues for the schedule."""

    def __init__(self, cog: 'BattleConditions', guild_id: int, channel_id: int, hour: int, minute: int, days_before: int):
        all_leagues = ["Legend", "Champion", "Platinum", "Gold", "Silver", "Bronze"]

        options = [
            discord.SelectOption(
                label=league,
                value=league,
                emoji="🏆"
            )
            for league in all_leagues
        ]

        super().__init__(
            placeholder="Select leagues (choose one or more)...",
            min_values=1,
            max_values=len(all_leagues),
            options=options
        )
        self.cog = cog
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.hour = hour
        self.minute = minute
        self.days_before = days_before

    async def callback(self, interaction: discord.Interaction):
        selected_leagues = self.values

        # Create the schedule
        schedules = self.cog.get_setting("destination_schedules", guild_id=self.guild_id) or []
        schedules.append({
            "destination_id": self.channel_id,
            "destination_type": "channel",
            "guild_id": self.guild_id,
            "leagues": selected_leagues,
            "hour": self.hour,
            "minute": self.minute,
            "days_before": self.days_before,
            "paused": False
        })

        self.cog.set_setting("destination_schedules", schedules, guild_id=self.guild_id)
        self.cog.mark_data_modified()

        channel = interaction.guild.get_channel(self.channel_id)
        channel_mention = channel.mention if channel else f"<#{self.channel_id}>"

        await interaction.response.send_message(
            f"✅ **Schedule Created!**\n\n"
            f"📍 Channel: {channel_mention}\n"
            f"⏰ Time: {self.hour:02d}:{self.minute:02d} UTC\n"
            f"📅 When: {self.days_before} day(s) before tournament\n"
            f"🏆 Leagues: {', '.join(selected_leagues)}",
            ephemeral=True
        )


class EditScheduleButton(discord.ui.Button):
    """Button to edit an existing schedule."""

    def __init__(self):
        super().__init__(
            label="Edit Schedule",
            style=discord.ButtonStyle.primary,
            emoji="✏️"
        )

    async def callback(self, interaction: discord.Interaction):
        view: ScheduleManagementView = self.view

        # Show schedule selector
        select_view = discord.ui.View(timeout=300)
        select_view.add_item(EditScheduleSelect(view.cog, view.schedules, view.guild_id))

        await interaction.response.send_message(
            "Select a schedule to edit:",
            view=select_view,
            ephemeral=True
        )


class EditScheduleSelect(discord.ui.Select):
    """Select menu for choosing schedule to edit."""

    def __init__(self, cog: 'BattleConditions', schedules: list, guild_id: int):
        options = []
        for idx, schedule in enumerate(schedules[:25]):  # Discord limit
            dest_id = schedule.get("destination_id")
            channel = cog.bot.get_channel(int(dest_id))
            channel_name = channel.name if channel else f"ID: {dest_id}"

            label = f"#{idx}: {channel_name}"[:100]
            leagues = ", ".join(schedule.get("leagues", [])[:2])
            description = f"{leagues}"[:100]

            options.append(discord.SelectOption(
                label=label,
                value=str(idx),
                description=description
            ))

        super().__init__(
            placeholder="Choose schedule to edit...",
            options=options
        )
        self.cog = cog
        self.schedules = schedules
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        schedule = self.schedules[idx]

        # Show edit modal
        modal = EditScheduleModal(self.cog, self.guild_id, idx, schedule)
        await interaction.response.send_modal(modal)


class EditScheduleModal(discord.ui.Modal, title="Edit BC Schedule"):
    """Modal for editing an existing schedule."""

    def __init__(self, cog: 'BattleConditions', guild_id: int, schedule_idx: int, schedule: dict):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.schedule_idx = schedule_idx
        self.current_leagues = schedule.get("leagues", [])

        self.days_before_input = discord.ui.TextInput(
            label="Days before tournament (0-7)",
            default=str(schedule.get("days_before", 1)),
            required=True,
            max_length=1
        )
        self.add_item(self.days_before_input)

        self.hour_input = discord.ui.TextInput(
            label="Hour (0-23, UTC)",
            default=str(schedule.get("hour", 0)),
            required=True,
            max_length=2
        )
        self.add_item(self.hour_input)

        self.minute_input = discord.ui.TextInput(
            label="Minute (0-59)",
            default=str(schedule.get("minute", 0)),
            required=True,
            max_length=2
        )
        self.add_item(self.minute_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Parse and validate time values
            days_before = int(self.days_before_input.value)
            hour = int(self.hour_input.value)
            minute = int(self.minute_input.value)

            if not (0 <= days_before <= 7):
                await interaction.response.send_message("❌ Days before must be 0-7", ephemeral=True)
                return
            if not (0 <= hour <= 23):
                await interaction.response.send_message("❌ Hour must be 0-23", ephemeral=True)
                return
            if not (0 <= minute <= 59):
                await interaction.response.send_message("❌ Minute must be 0-59", ephemeral=True)
                return

            # Show league picker
            league_view = discord.ui.View(timeout=300)
            league_view.add_item(EditScheduleLeagueSelect(
                self.cog,
                self.guild_id,
                self.schedule_idx,
                hour,
                minute,
                days_before,
                self.current_leagues
            ))

            await interaction.response.send_message(
                f"**Final Step:** Select leagues for schedule #{self.schedule_idx}:\n"
                f"Time: {hour:02d}:{minute:02d} UTC, {days_before} day(s) before tournament",
                view=league_view,
                ephemeral=True
            )

        except ValueError as e:
            await interaction.response.send_message(
                f"❌ Invalid input: {e}",
                ephemeral=True
            )


class EditScheduleLeagueSelect(discord.ui.Select):
    """Select menu for choosing leagues when editing a schedule."""

    def __init__(self, cog: 'BattleConditions', guild_id: int, schedule_idx: int,
                 hour: int, minute: int, days_before: int, current_leagues: list):
        all_leagues = ["Legend", "Champion", "Platinum", "Gold", "Silver", "Bronze"]

        options = [
            discord.SelectOption(
                label=league,
                value=league,
                emoji="🏆",
                default=league in current_leagues
            )
            for league in all_leagues
        ]

        super().__init__(
            placeholder="Select leagues (choose one or more)...",
            min_values=1,
            max_values=len(all_leagues),
            options=options
        )
        self.cog = cog
        self.guild_id = guild_id
        self.schedule_idx = schedule_idx
        self.hour = hour
        self.minute = minute
        self.days_before = days_before

    async def callback(self, interaction: discord.Interaction):
        selected_leagues = self.values

        # Update schedule
        schedules = self.cog.get_setting("destination_schedules", guild_id=self.guild_id) or []
        schedules[self.schedule_idx].update({
            "hour": self.hour,
            "minute": self.minute,
            "days_before": self.days_before,
            "leagues": selected_leagues
        })

        self.cog.set_setting("destination_schedules", schedules, guild_id=self.guild_id)
        self.cog.mark_data_modified()

        await interaction.response.send_message(
            f"✅ **Schedule #{self.schedule_idx} Updated!**\n\n"
            f"⏰ Time: {self.hour:02d}:{self.minute:02d} UTC\n"
            f"📅 When: {self.days_before} day(s) before tournament\n"
            f"🏆 Leagues: {', '.join(selected_leagues)}",
            ephemeral=True
        )


class DeleteScheduleButton(discord.ui.Button):
    """Button to delete a schedule."""

    def __init__(self):
        super().__init__(
            label="Delete Schedule",
            style=discord.ButtonStyle.danger,
            emoji="🗑️"
        )

    async def callback(self, interaction: discord.Interaction):
        view: ScheduleManagementView = self.view

        # Show schedule selector
        select_view = discord.ui.View(timeout=300)
        select_view.add_item(DeleteScheduleSelect(view.cog, view.schedules, view.guild_id))

        await interaction.response.send_message(
            "Select a schedule to delete:",
            view=select_view,
            ephemeral=True
        )


class DeleteScheduleSelect(discord.ui.Select):
    """Select menu for choosing schedule to delete."""

    def __init__(self, cog: 'BattleConditions', schedules: list, guild_id: int):
        options = []
        for idx, schedule in enumerate(schedules[:25]):  # Discord limit
            dest_id = schedule.get("destination_id")
            channel = cog.bot.get_channel(int(dest_id))
            channel_name = channel.name if channel else f"ID: {dest_id}"

            label = f"#{idx}: {channel_name}"[:100]
            leagues = ", ".join(schedule.get("leagues", [])[:2])
            description = f"{leagues}"[:100]

            options.append(discord.SelectOption(
                label=label,
                value=str(idx),
                description=description,
                emoji="🗑️"
            ))

        super().__init__(
            placeholder="Choose schedule to delete...",
            options=options
        )
        self.cog = cog
        self.schedules = schedules
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        schedule = self.schedules[idx]

        # Get channel for confirmation
        dest_id = schedule.get("destination_id")
        channel = self.cog.bot.get_channel(int(dest_id))
        channel_name = channel.mention if channel else f"ID: {dest_id}"

        # Delete schedule
        schedules = self.cog.get_setting("destination_schedules", guild_id=self.guild_id) or []
        schedules.pop(idx)
        self.cog.set_setting("destination_schedules", schedules, guild_id=self.guild_id)
        self.cog.mark_data_modified()

        await interaction.response.send_message(
            f"✅ Deleted schedule #{idx} for {channel_name}",
            ephemeral=True
        )


class TogglePauseScheduleButton(discord.ui.Button):
    """Button to pause/resume schedules."""

    def __init__(self):
        super().__init__(
            label="Pause/Resume",
            style=discord.ButtonStyle.secondary,
            emoji="⏯️"
        )

    async def callback(self, interaction: discord.Interaction):
        view: ScheduleManagementView = self.view

        # Show schedule selector
        select_view = discord.ui.View(timeout=300)
        select_view.add_item(TogglePauseSelect(view.cog, view.schedules, view.guild_id))

        await interaction.response.send_message(
            "Select a schedule to pause/resume:",
            view=select_view,
            ephemeral=True
        )


class TogglePauseSelect(discord.ui.Select):
    """Select menu for pausing/resuming schedules."""

    def __init__(self, cog: 'BattleConditions', schedules: list, guild_id: int):
        options = []
        for idx, schedule in enumerate(schedules[:25]):  # Discord limit
            dest_id = schedule.get("destination_id")
            channel = cog.bot.get_channel(int(dest_id))
            channel_name = channel.name if channel else f"ID: {dest_id}"
            paused = schedule.get("paused", False)

            label = f"#{idx}: {channel_name}"[:100]
            status = "⏸️ PAUSED" if paused else "▶️ ACTIVE"
            description = f"{status}"[:100]

            options.append(discord.SelectOption(
                label=label,
                value=str(idx),
                description=description,
                emoji="⏸️" if paused else "▶️"
            ))

        super().__init__(
            placeholder="Choose schedule to toggle...",
            options=options
        )
        self.cog = cog
        self.schedules = schedules
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])

        # Toggle pause state
        schedules = self.cog.get_setting("destination_schedules", guild_id=self.guild_id) or []
        current_paused = schedules[idx].get("paused", False)
        schedules[idx]["paused"] = not current_paused

        self.cog.set_setting("destination_schedules", schedules, guild_id=self.guild_id)
        self.cog.mark_data_modified()

        # Get channel for feedback
        dest_id = schedules[idx].get("destination_id")
        channel = self.cog.bot.get_channel(int(dest_id))
        channel_name = channel.mention if channel else f"ID: {dest_id}"

        action = "Paused" if not current_paused else "Resumed"
        await interaction.response.send_message(
            f"✅ {action} schedule #{idx} for {channel_name}",
            ephemeral=True
        )


class GlobalSettingsButton(discord.ui.Button):
    """Button to configure global bot settings (bot owner only)."""

    def __init__(self):
        super().__init__(
            label="Global Settings",
            style=discord.ButtonStyle.danger,
            emoji="🌐"
        )

    async def callback(self, interaction: discord.Interaction):
        view: BCSettingsView = self.view
        cog = view.cog

        # Get current global settings
        view_window = cog.get_setting("bc_view_window_days", guild_id=None)
        if view_window is None:
            view_window = cog.default_settings["bc_view_window_days"]

        # Show modal for setting view window
        modal = ViewWindowModal(cog, view_window)
        await interaction.response.send_modal(modal)


class ViewWindowModal(discord.ui.Modal, title="Global BC View Window"):
    """Modal for setting the BC view window."""

    def __init__(self, cog: 'BattleConditions', current_value: Optional[int]):
        super().__init__()
        self.cog = cog

        self.view_window_input = discord.ui.TextInput(
            label="Days before tournament (blank = always)",
            placeholder="e.g., 3 for 3 days before tourney, or leave blank",
            default=str(current_value) if current_value is not None else "",
            required=False,
            max_length=3
        )
        self.add_item(self.view_window_input)

    async def on_submit(self, interaction: discord.Interaction):
        value_str = self.view_window_input.value.strip()

        if not value_str:
            # Blank means always available
            self.cog.set_setting("bc_view_window_days", None, guild_id=None)
            await interaction.response.send_message(
                "✅ BC view window set to **always available**",
                ephemeral=True
            )
        else:
            try:
                days = int(value_str)
                if days < 0:
                    await interaction.response.send_message(
                        "❌ Days must be 0 or positive",
                        ephemeral=True
                    )
                    return

                self.cog.set_setting("bc_view_window_days", days, guild_id=None)
                await interaction.response.send_message(
                    f"✅ BC view window set to **{days} day(s)** before tournament",
                    ephemeral=True
                )
            except ValueError:
                await interaction.response.send_message(
                    "❌ Invalid number. Please enter a valid number of days.",
                    ephemeral=True
                )


class BCPermissionsView(discord.ui.View):
    """View for configuring BC action permissions."""

    def __init__(self, cog: 'BattleConditions'):
        super().__init__(timeout=300)
        self.cog = cog

        self.add_item(ConfigureGeneratePermButton())
        self.add_item(ConfigureRunSchedulePermButton())
        self.add_item(ConfigureManageSchedulesPermButton())


class ConfigureGeneratePermButton(discord.ui.Button):
    """Button to configure generate permissions."""

    def __init__(self):
        super().__init__(
            label="Generate Permissions",
            style=discord.ButtonStyle.primary
        )

    async def callback(self, interaction: discord.Interaction):
        view: BCPermissionsView = self.view
        cog = view.cog
        guild_id = interaction.guild.id

        # Get current permissions
        perms = cog.get_setting("slash_permissions.generate", guild_id=guild_id) or {}
        current_users = perms.get("allowed_users", [])
        current_roles = perms.get("allowed_roles", [])

        # Build current permissions display
        current_mentions = []
        if current_roles:
            current_mentions.extend([f"<@&{rid}>" for rid in current_roles])
        if current_users:
            current_mentions.extend([f"<@{uid}>" for uid in current_users])

        if current_mentions:
            current_text = f"**Current permissions:** {', '.join(current_mentions)}\n\n"
        else:
            current_text = "**Current permissions:** Owner only (default)\n\n"

        # Create mentionable select with default values
        mentionable_select = ActionMentionableSelect(cog, "generate", guild_id)
        select_view = discord.ui.View(timeout=300)
        select_view.add_item(mentionable_select)

        await interaction.response.send_message(
            f"{current_text}Select roles/users that can use **Generate to Channel**:\n"
            "(Select none to clear and revert to owner-only)",
            view=select_view,
            ephemeral=True
        )


class ConfigureRunSchedulePermButton(discord.ui.Button):
    """Button to configure run schedule permissions."""

    def __init__(self):
        super().__init__(
            label="Run Schedule Permissions",
            style=discord.ButtonStyle.primary
        )

    async def callback(self, interaction: discord.Interaction):
        view: BCPermissionsView = self.view
        cog = view.cog
        guild_id = interaction.guild.id

        # Get current permissions
        perms = cog.get_setting("slash_permissions.run_schedule", guild_id=guild_id) or {}
        current_users = perms.get("allowed_users", [])
        current_roles = perms.get("allowed_roles", [])

        # Build current permissions display
        current_mentions = []
        if current_roles:
            current_mentions.extend([f"<@&{rid}>" for rid in current_roles])
        if current_users:
            current_mentions.extend([f"<@{uid}>" for uid in current_users])

        if current_mentions:
            current_text = f"**Current permissions:** {', '.join(current_mentions)}\n\n"
        else:
            current_text = "**Current permissions:** Owner only (default)\n\n"

        # Create mentionable select with default values
        mentionable_select = ActionMentionableSelect(cog, "run_schedule", guild_id)
        select_view = discord.ui.View(timeout=300)
        select_view.add_item(mentionable_select)

        await interaction.response.send_message(
            f"{current_text}Select roles/users that can use **Run Schedule**:\n"
            "(Select none to clear and revert to owner-only)",
            view=select_view,
            ephemeral=True
        )


class ConfigureManageSchedulesPermButton(discord.ui.Button):
    """Button to configure manage schedules permissions."""

    def __init__(self):
        super().__init__(
            label="Manage Schedules Permissions",
            style=discord.ButtonStyle.primary
        )

    async def callback(self, interaction: discord.Interaction):
        view: BCPermissionsView = self.view
        cog = view.cog
        guild_id = interaction.guild.id

        # Get current permissions
        perms = cog.get_setting("slash_permissions.manage_schedules", guild_id=guild_id) or {}
        current_users = perms.get("allowed_users", [])
        current_roles = perms.get("allowed_roles", [])

        # Build current permissions display
        current_mentions = []
        if current_roles:
            current_mentions.extend([f"<@&{rid}>" for rid in current_roles])
        if current_users:
            current_mentions.extend([f"<@{uid}>" for uid in current_users])

        if current_mentions:
            current_text = f"**Current permissions:** {', '.join(current_mentions)}\n\n"
        else:
            current_text = "**Current permissions:** Owner only (default)\n\n"

        # Create mentionable select with default values
        mentionable_select = ActionMentionableSelect(cog, "manage_schedules", guild_id)
        select_view = discord.ui.View(timeout=300)
        select_view.add_item(mentionable_select)

        await interaction.response.send_message(
            f"{current_text}Select roles/users that can use **Manage Schedules** (Create/Edit/Delete/Pause):\n"
            "(Select none to clear and revert to owner-only)",
            view=select_view,
            ephemeral=True
        )


class ActionMentionableSelect(discord.ui.MentionableSelect):
    """Mentionable select for configuring action permissions (roles and users)."""

    def __init__(self, cog: 'BattleConditions', action_name: str, guild_id: int):
        # Get current permissions to set as defaults
        perms = cog.get_setting(f"slash_permissions.{action_name}", guild_id=guild_id) or {}
        current_users = perms.get("allowed_users", [])
        current_roles = perms.get("allowed_roles", [])

        # Create default values from current permissions
        default_values = []
        for role_id in current_roles:
            default_values.append(discord.SelectDefaultValue(id=role_id, type=discord.SelectDefaultValueType.role))
        for user_id in current_users:
            default_values.append(discord.SelectDefaultValue(id=user_id, type=discord.SelectDefaultValueType.user))

        super().__init__(
            placeholder=f"Select roles/users for {action_name.replace('_', ' ')}...",
            min_values=0,
            max_values=25,
            default_values=default_values if default_values else None
        )
        self.cog = cog
        self.action_name = action_name

    async def callback(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id

        # Separate roles and users from the selected values
        role_ids = []
        user_ids = []

        for value in self.values:
            if isinstance(value, discord.Role):
                role_ids.append(value.id)
            elif isinstance(value, (discord.Member, discord.User)):
                user_ids.append(value.id)

        # Save to permissions
        self.cog.set_slash_action_permission(
            guild_id,
            self.action_name,
            allowed_roles=role_ids,
            allowed_users=user_ids
        )

        # Build response message
        mentions = []
        if role_ids:
            mentions.extend([f"<@&{rid}>" for rid in role_ids])
        if user_ids:
            mentions.extend([f"<@{uid}>" for uid in user_ids])

        if mentions:
            mention_list = ", ".join(mentions)
            await interaction.response.send_message(
                f"✅ {self.action_name.replace('_', ' ').title()} permissions updated for: {mention_list}",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"✅ {self.action_name.replace('_', ' ').title()} permissions cleared (owner-only default)",
                ephemeral=True
            )


class BattleConditions(BaseCog, name="Battle Conditions"):
    """Commands for predicting and displaying upcoming battle conditions.

    Provides functionality to:
    - Check upcoming tournament dates
    - Predict battle conditions for different leagues
    - Automatically announce battle conditions
    """

    # === Core Methods ===
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.logger.info("Initializing BattleConditions")

        # Define default settings (will be initialized per-guild on first use)
        self.default_settings = {
            # Time Settings
            "notification_hour": 0,
            "notification_minute": 0,
            "days_before_notification": 1,
            # Display Settings
            "enabled_leagues": ["Legend", "Champion", "Platinum", "Gold", "Silver"],
            # Schedule Settings
            "destination_schedules": [],
            # Global Settings (bot-wide, not per-guild)
            "bc_view_window_days": None,  # None = always available, or number of days before tourney
        }

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Override interaction check to bypass permission manager for slash commands.

        The /bc command opens an ephemeral UI where permissions are checked
        at the button level, not at the command level. This allows everyone to
        open the UI and see what actions they can perform based on their permissions.
        """
        # Allow all slash commands through - permissions checked in button callbacks
        return True

    async def cog_initialize(self) -> None:
        """Initialize the cog - called by BaseCog during ready process."""
        self.logger.info("Initializing Battle Conditions module")

        # Check if towerbcs is available
        if not TOWERBCS_AVAILABLE:
            self.logger.warning("towerbcs package not available - battle conditions functionality will be limited")
            self._has_errors = True

        try:
            async with self.task_tracker.task_context("Initialization") as tracker:
                # Initialize parent
                self.logger.debug("Initializing parent cog")
                await super().cog_initialize()

                # 1. Start scheduled task
                self.logger.debug("Starting scheduled task")
                tracker.update_status("Starting tasks")
                self.scheduled_bc_messages.start()

                # 2. Initialize state
                self._last_operation_time = datetime.datetime.utcnow()

                # 3. Mark as ready
                self.set_ready(True)
                self.logger.info("Battle conditions initialization complete")

        except Exception as e:
            self.logger.error(f"Error during Battle Conditions initialization: {e}", exc_info=True)
            self._has_errors = True
            raise

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded."""
        # Cancel any scheduled tasks
        if hasattr(self, "scheduled_bc_messages"):
            self.scheduled_bc_messages.cancel()

        # Call parent implementation for data saving
        await super().cog_unload()
        self.logger.info("Battle conditions cog unloaded")

    # === Slash Commands ===
    @app_commands.command(name="bc", description="View and manage battle conditions")
    @app_commands.guild_only()
    async def bc_slash(self, interaction: discord.Interaction) -> None:
        """Battle conditions management UI."""
        # Check permissions for different actions
        can_generate = await self.check_slash_action_permission(interaction, "generate")
        can_run_schedule = await self.check_slash_action_permission(interaction, "run_schedule")
        is_owner = interaction.guild.owner_id == interaction.user.id or await self.bot.is_owner(interaction.user)

        # Create the view with conditional buttons
        view = BCManagementView(self, can_generate, can_run_schedule, is_owner)

        # Get tournament info for display
        if TOWERBCS_AVAILABLE:
            tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info()
            info_text = f"📅 Next tournament: {tourney_date} ({days_until} days)\n\n"
            info_text += "Use the buttons below to manage battle conditions."
        else:
            info_text = "⚠️ Battle conditions package not available.\n\n"
            info_text += "Use the buttons below to manage settings."

        await interaction.response.send_message(info_text, view=view, ephemeral=True)

    # === Helper Methods ===
    async def get_battle_conditions(self, league: str) -> List[str]:
        """Get battle conditions for a league.

        Args:
            league: The league to get battle conditions for.

        Returns:
            List of battle condition strings.
        """
        if not TOWERBCS_AVAILABLE:
            return ["⚠️ Battle conditions unavailable - towerbcs package not installed"]

        tourney_id, _, _ = TournamentPredictor.get_tournament_info()

        try:
            self.logger.info(f"Fetching battle conditions for {league}")
            return predict_future_tournament(tourney_id, league)
        except Exception as e:
            self.logger.error(f"Error fetching battle conditions for {league}: {e}")
            return ["❌ Error fetching battle conditions"]

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
            embed = discord.Embed(title=f"{league} League Battle Conditions", description=f"Tournament on {tourney_date}", color=discord.Color.gold())

            bc_text = "\n".join([f"• {bc}" for bc in battleconditions])
            embed.add_field(name="Predicted Battle Conditions", value=bc_text, inline=False)

            await channel.send(embed=embed)
            self.logger.info(f"Sent battle conditions for {league} league to channel {channel.name}")
            return True
        except Exception as e:
            self.logger.error(f"Error sending battle conditions for {league} league: {e}")
            return False

    # === Task Methods ===
    @tasks.loop(minutes=1)  # Check every 1 minute
    async def scheduled_bc_messages(self):
        """Check all schedules and send battle condition messages as needed"""
        await self.bot.wait_until_ready()
        await self.wait_until_ready()

        # Check global pause setting
        if self.is_paused:
            self.logger.debug("Battle conditions announcements are globally paused")
            return

        async with self.task_tracker.task_context("Battle Conditions Check"):
            try:
                self._active_process = "Battle Conditions Check"
                self._process_start_time = datetime.datetime.utcnow()

                # Get tournament information
                tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info()
                now = datetime.datetime.utcnow()
                current_hour = now.hour
                current_minute = now.minute

                # Collect all schedules from all guilds that match current time/day
                # This is more efficient than checking every schedule every minute
                schedules_to_process = []

                for guild in self.bot.guilds:
                    guild_id = guild.id

                    # Get schedules for this guild
                    schedules = self.get_setting("destination_schedules", [], guild_id=guild_id)
                    enabled_leagues = self.get_setting("enabled_leagues", guild_id=guild_id)

                    # Filter schedules that match current time and day
                    for schedule in schedules:
                        # Skip paused schedules immediately
                        if schedule.get("paused", False):
                            continue

                        # Get schedule timing
                        hour = schedule.get("hour", self.default_settings.get("notification_hour", 0))
                        minute = schedule.get("minute", self.default_settings.get("notification_minute", 0))
                        days_before = schedule.get("days_before", self.default_settings.get("days_before_notification", 1))

                        # Check if this schedule should run now
                        time_match = current_hour == hour and (current_minute >= minute and current_minute < minute + 1)
                        day_match = days_until == days_before

                        if time_match and day_match:
                            # Add guild context to schedule for processing
                            schedules_to_process.append({
                                "schedule": schedule,
                                "guild_id": guild_id,
                                "enabled_leagues": enabled_leagues,
                            })

                # Process all matching schedules
                for item in schedules_to_process:
                    schedule = item["schedule"]
                    guild_id = item["guild_id"]
                    enabled_leagues = item["enabled_leagues"]

                    destination_id = schedule.get("destination_id")
                    leagues = schedule.get("leagues", [])

                    self.logger.info(f"Processing schedule for destination {destination_id} in guild {guild_id}, {schedule.get('days_before')} days before tournament")

                    channel = self.bot.get_channel(int(destination_id))
                    if not channel:
                        self.logger.warning(f"Could not find destination with ID {destination_id}")
                        continue

                    # Verify the channel belongs to the expected guild (safety check)
                    stored_guild_id = schedule.get("guild_id", channel.guild.id)
                    if channel.guild.id != stored_guild_id:
                        self.logger.warning(f"Channel {destination_id} guild mismatch: expected {stored_guild_id}, got {channel.guild.id}")
                        continue

                    # Track if we've sent anything to this channel
                    sent_something = False

                    # Send each league's battle conditions
                    for league in leagues:
                        # Skip leagues that aren't enabled
                        if league not in enabled_leagues:
                            continue

                        try:
                            # Get battle conditions and send message
                            battleconditions = await self.get_battle_conditions(league)
                            success = await self.send_battle_conditions_embed(channel, league, tourney_date, battleconditions)
                            if success:
                                sent_something = True
                        except Exception as e:
                            self.logger.error(f"Error processing battle conditions for {league} league: {e}")

                    # Log if we didn't send anything for this schedule
                    if not sent_something:
                        self.logger.warning(f"No battle conditions sent for schedule in channel {channel.name}")

                self._last_operation_time = datetime.datetime.utcnow()
                self._operation_count += 1
                self._active_process = None
            except Exception as e:
                self.logger.error(f"Error in scheduled battle conditions task: {e}")
                self._has_errors = True
                self._active_process = None

    @scheduled_bc_messages.before_loop
    async def before_scheduled_bc_messages(self):
        """Set up the task before it starts"""
        self.logger.info("Starting battle conditions scheduler with 1-minute interval")


async def setup(bot) -> None:
    await bot.add_cog(BattleConditions(bot))
