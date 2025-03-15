import logging
import datetime
from typing import List, Optional

import discord
from discord.ext import commands, tasks

from fish_bot.basecog import BaseCog
from towerbcs.towerbcs import predict_future_tournament, TournamentPredictor


class BattleConditions(BaseCog, name="Battle Conditions"):
    """Commands for predicting and displaying upcoming battle conditions.

    Provides functionality to:
    - Check upcoming tournament dates
    - Predict battle conditions for different leagues
    - Automatically announce battle conditions
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.logger = logging.getLogger(__name__)

        # Tracking variables for status reporting
        self._last_operation_time = None
        self._operation_count = 0
        self._has_errors = False
        self._active_process = None
        self._process_start_time = None

        # Initialize settings with clear comments for default values
        if not self.has_setting("notification_hour"):
            self.set_setting("notification_hour", 0)  # Default to midnight UTC

        if not self.has_setting("notification_minute"):
            self.set_setting("notification_minute", 0)  # Default to start of hour

        if not self.has_setting("days_before_notification"):
            self.set_setting("days_before_notification", 1)  # Default to 1 day before tournament

        if not self.has_setting("enabled_leagues"):
            # Include all standard leagues by default
            self.set_setting("enabled_leagues", ["Legend", "Champion", "Platinum", "Gold", "Silver"])

        if not self.has_setting("thread_schedules"):
            # Start with empty schedules configuration
            self.set_setting("thread_schedules", [])

        if not self.has_setting("paused"):
            # By default, the system is operational (not paused)
            self.set_setting("paused", False)

        # Load settings into instance variables for convenience
        self.default_hour = self.get_setting("notification_hour")
        self.default_minute = self.get_setting("notification_minute")
        self.default_days_before = self.get_setting("days_before_notification")
        self.enabled_leagues = self.get_setting("enabled_leagues")
        self.paused = self.get_setting("paused")

        # Thread IDs for each league
        self.league_threads = {
            "Legend": self.config.get_thread_id("battleconditions", "legend"),
            "Champion": self.config.get_thread_id("battleconditions", "champion"),
            "Platinum": self.config.get_thread_id("battleconditions", "platinum"),
            "Gold": self.config.get_thread_id("battleconditions", "gold"),
            "Silver": self.config.get_thread_id("battleconditions", "silver")
        }

    async def cog_initialize(self) -> None:
        """Initialize the cog - called by BaseCog during ready process"""
        # Wait until the cog is ready before starting the scheduler
        await self.wait_until_ready()
        self.scheduled_bc_messages.start()
        self.logger.info("Battle conditions initialization complete")

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded"""
        self.scheduled_bc_messages.cancel()
        # Call parent implementation for data saving
        await super().cog_unload()
        self.logger.info("Battle conditions cog unloaded")

    async def get_battle_conditions(self, league: str) -> List[str]:
        """Get battle conditions for a league.

        Args:
            league: The league to get battle conditions for.

        Returns:
            List of battle condition strings.
        """
        tourney_id, _, _ = TournamentPredictor.get_tournament_info()

        try:
            self.logger.info(f"Fetching battle conditions for {league}")
            return predict_future_tournament(tourney_id, league)
        except Exception as e:
            self.logger.error(f"Error fetching battle conditions for {league}: {e}")
            return ["Error fetching battle conditions"]

    @commands.group(name="bc", aliases=["battleconditions"], invoke_without_command=True)
    async def bc_group(self, ctx):
        """Battle conditions commands.

        Available subcommands:
        - get: Get predicted BCs for a league
        - tourney: Get the date of the next tourney
        - info: Display information about battle conditions system
        """
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @bc_group.command(name="get")
    async def get_bc_command(self, ctx, league: str = "Legend"):
        """Get predicted battle conditions for a specific league.

        Args:
            league: League name (Legend, Champion, Platinum, Gold, Silver)
        """
        league = league.title()  # Standardize to title case

        # Validate league
        valid_leagues = ["Legend", "Champion", "Platinum", "Gold", "Silver"]
        if league not in valid_leagues:
            valid_leagues_str = ", ".join(valid_leagues)
            return await ctx.send(f"❌ Invalid league. Valid leagues: {valid_leagues_str}")

        async with ctx.typing():
            # Get tournament info and battle conditions
            tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info()
            battleconditions = await self.get_battle_conditions(league)

            embed = discord.Embed(
                title=f"{league} League Battle Conditions",
                description=f"Tournament on {tourney_date}",
                color=discord.Color.gold()
            )

            # Add BC list
            bc_text = "\n".join([f"• {bc}" for bc in battleconditions])
            embed.add_field(name="Predicted Battle Conditions", value=bc_text, inline=False)

            # Add footer to explain predictions
            # embed.set_footer(text="Predictions based on historical data and may change")

        try:
            # Try to delete the command message if we have permissions
            await ctx.message.delete()
        except Exception as e:
            self.logger.debug(f"Could not delete command message: {e}")

        await ctx.send(embed=embed)

    @bc_group.command(name="tourney")
    async def get_tourney_command(self, ctx):
        """Get the date of the next tourney."""
        tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info()

        embed = discord.Embed(
            title="Next Tournament Information",
            color=discord.Color.blue()
        )

        if days_until == 0:
            embed.add_field(name="Status", value="The tournament is today! 🏆", inline=False)
        else:
            embed.add_field(name="Date", value=tourney_date, inline=True)
            embed.add_field(name="Days Remaining", value=f"{days_until} days", inline=True)

        await ctx.send(embed=embed)

    @bc_group.command(name="info")
    async def bc_info_command(self, ctx):
        """Display information about the battle conditions system"""
        tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info()

        embed = discord.Embed(
            title="Battle Conditions Information",
            description="System that predicts and posts tournament battle conditions.",
            color=discord.Color.blue()
        )

        # System status (paused or active)
        global_paused = self.get_setting("paused")
        status_emoji = "⏸️ Paused" if global_paused else "✅ Ready"
        embed.add_field(name="Status", value=status_emoji, inline=True)

        # Tournament info
        embed.add_field(
            name="Next Tournament",
            value=f"{tourney_date} ({days_until} days away)",
            inline=True
        )

        # Last updated
        now = datetime.datetime.utcnow()
        embed.add_field(
            name="Last Updated",
            value=f"{now.strftime('%Y-%m-%d %H:%M:%S')} UTC",
            inline=True
        )

        # Statistics - how many schedules and threads are configured
        thread_schedules = self.get_setting("thread_schedules", [])
        active_schedules = sum(1 for s in thread_schedules if not s.get("paused", False))
        embed.add_field(
            name="Statistics",
            value=f"📊 {active_schedules}/{len(thread_schedules)} active schedules",
            inline=False
        )

        # Dependency status
        embed.add_field(
            name="Dependencies",
            value="🔮 Tournament Predictor: Connected",
            inline=False
        )

        # Add footer with usage hint
        embed.set_footer(text="Use 'bc settings' to view configuration details")

        await ctx.send(embed=embed)

    @bc_group.command(name="settings")
    async def bc_settings_command(self, ctx):
        """Display current configuration for the Battle Conditions system."""
        embed = discord.Embed(
            title="Battle Conditions Settings",
            description="Current configuration for battle conditions system",
            color=discord.Color.blue()
        )

        # Time Settings
        hour = self.get_setting("notification_hour")
        minute = self.get_setting("notification_minute")
        days_before = self.get_setting("days_before_notification")
        time_str = f"{hour:02d}:{minute:02d} UTC"

        embed.add_field(
            name="🕒 Time Settings",
            value=f"Default Notification Time: {time_str}\n"
            f"Days Before Tournament: {days_before}",
            inline=False
        )

        # Display Settings
        enabled_leagues = self.get_setting("enabled_leagues")
        embed.add_field(
            name="🏆 Display Settings",
            value=f"Enabled Leagues: {', '.join(enabled_leagues)}",
            inline=False
        )

        # Flag Settings
        global_paused = self.get_setting("paused")
        paused_str = "❌ Disabled" if global_paused else "✅ Enabled"
        embed.add_field(
            name="🚩 Flag Settings",
            value=f"Announcements: {paused_str}",
            inline=False
        )

        # Thread schedules - summary
        thread_schedules = self.get_setting("thread_schedules", [])
        if thread_schedules:
            active_count = sum(1 for s in thread_schedules if not s.get("paused", False))
            paused_count = len(thread_schedules) - active_count

            schedule_summary = (
                f"📑 Total Schedules: {len(thread_schedules)}\n"
                f"✅ Active: {active_count}\n"
                f"⏸️ Paused: {paused_count}\n\n"
                f"Use `bc schedule_list` for detailed schedule information."
            )
        else:
            schedule_summary = "No schedules configured. Use `bc schedule_add` to set up."

        embed.add_field(
            name="📆 Schedule Settings",
            value=schedule_summary,
            inline=False
        )

        # Format timestamp for footer
        current_time = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        embed.set_footer(text=f"Last Updated: {current_time}")

        await ctx.send(embed=embed)

    @bc_group.command(name="set")
    async def bc_set_setting_command(self, ctx, setting_name: str, value: str):
        """Change a battle conditions setting

        Args:
            setting_name: Setting to change (notification_hour, notification_minute, days_before_notification)
            value: New value for the setting
        """
        valid_settings = ["notification_hour", "notification_minute", "days_before_notification"]

        if setting_name not in valid_settings:
            valid_settings_str = ", ".join(valid_settings)
            return await ctx.send(f"Invalid setting name. Valid options: {valid_settings_str}")

        try:
            int_value = int(value)

            # Validate inputs based on the setting
            if setting_name == "notification_hour" and not (0 <= int_value <= 23):
                return await ctx.send("Hour must be between 0 and 23")

            if setting_name == "notification_minute" and not (0 <= int_value <= 59):
                return await ctx.send("Minute must be between 0 and 59")

            if setting_name == "days_before_notification" and not (0 <= int_value <= 7):
                return await ctx.send("Days before notification must be between 0 and 7")

            # Save the setting
            self.set_setting(setting_name, int_value)

            # Update instance variable
            if hasattr(self, setting_name):
                setattr(self, setting_name, int_value)

            # Restart the task if we changed timing
            if setting_name in ["notification_hour", "notification_minute"]:
                self.scheduled_bc_messages.cancel()
                self.scheduled_bc_messages.change_time(
                    time=datetime.time(hour=self.get_setting("notification_hour"),
                                       minute=self.get_setting("notification_minute"))
                )
                self.scheduled_bc_messages.start()

            await ctx.send(f"✅ Set {setting_name} to {int_value}")

            # Mark settings as modified
            self.mark_data_modified()

        except ValueError:
            await ctx.send("Value must be a number")

    @bc_group.command(name="schedule_add")
    async def bc_schedule_add_command(self, ctx, channel_input,
                                      hour: Optional[int] = None,
                                      minute: Optional[int] = None,
                                      days_before: Optional[int] = None,
                                      *leagues):
        """Add a new schedule for battle conditions

        Args:
            channel_input: The channel to post battle conditions to (mention, name, or ID)
            hour: Hour to post (24-hour format, UTC) - defaults to global setting
            minute: Minute to post - defaults to global setting
            days_before: Days before tournament to post - defaults to global setting
            leagues: One or more leagues to post (Legend, Champion, etc)
        """
        # Handle different channel input types
        channel = None

        # Check if it's a channel mention
        if len(ctx.message.channel_mentions) > 0:
            channel = ctx.message.channel_mentions[0]
        else:
            # Try to interpret as a channel ID
            try:
                channel_id = int(channel_input)
                channel = ctx.guild.get_channel(channel_id)
            except (ValueError, TypeError):
                # Try to interpret as a channel name
                channel = discord.utils.get(ctx.guild.text_channels, name=channel_input)

        # If we couldn't find a channel, inform the user
        if not channel:
            return await ctx.send(f"❌ Could not find channel '{channel_input}'. Please provide a valid channel mention, name, or ID.")

        # Use default values if not specified
        if hour is None:
            hour = self.default_hour
        if minute is None:
            minute = self.default_minute
        if days_before is None:
            days_before = self.default_days_before

        # Validate timing inputs
        if not (0 <= hour <= 23):
            return await ctx.send("❌ Hour must be between 0 and 23")

        if not (0 <= minute <= 59):
            return await ctx.send("❌ Minute must be between 0 and 59")

        if not (0 <= days_before <= 7):
            return await ctx.send("❌ Days before notification must be between 0 and 7")

        # Validate leagues
        valid_leagues = ["Legend", "Champion", "Platinum", "Gold", "Silver"]
        leagues = [league.title() for league in leagues]

        invalid_leagues = [league for league in leagues if league not in valid_leagues]
        if invalid_leagues:
            return await ctx.send(f"❌ Invalid leagues: {', '.join(invalid_leagues)}. Valid leagues: {', '.join(valid_leagues)}")

        if not leagues:
            return await ctx.send("❌ You must specify at least one league")

        # Get current schedules and add the new one
        schedules = self.get_setting("thread_schedules", [])
        schedules.append({
            "thread_id": channel.id,
            "leagues": leagues,
            "hour": hour,
            "minute": minute,
            "days_before": days_before
        })

        # Save the updated schedules
        self.set_setting("thread_schedules", schedules)
        self.mark_data_modified()

        # Format time for feedback message
        time_str = f"{hour:02d}:{minute:02d} UTC"

        await ctx.send(
            f"✅ Added schedule for {channel.mention}:\n"
            f"- Leagues: {', '.join(leagues)}\n"
            f"- Time: {time_str}\n"
            f"- Days before tournament: {days_before}"
        )

    @bc_group.command(name="schedule_list")
    async def bc_schedule_list_command(self, ctx):
        """List all battle conditions schedules"""
        schedules = self.get_setting("thread_schedules", [])

        if not schedules:
            return await ctx.send("No battle conditions schedules configured")

        embed = discord.Embed(
            title="Battle Conditions Schedules",
            color=discord.Color.blue()
        )

        for i, schedule in enumerate(schedules, 1):
            thread_id = schedule.get("thread_id")
            leagues = schedule.get("leagues", [])
            hour = schedule.get("hour", self.default_hour)
            minute = schedule.get("minute", self.default_minute)
            days_before = schedule.get("days_before", self.default_days_before)

            channel = self.bot.get_channel(int(thread_id)) if thread_id else None
            channel_str = channel.mention if channel else f"Not found (ID: {thread_id})"
            time_str = f"{hour:02d}:{minute:02d} UTC"

            embed.add_field(
                name=f"Schedule #{i}",
                value=f"Channel: {channel_str}\n"
                f"Leagues: {', '.join(leagues)}\n"
                f"Time: {time_str}, {days_before} days before tournament",
                inline=False
            )

        await ctx.send(embed=embed)

    @bc_group.command(name="schedule_remove")
    async def bc_schedule_remove_command(self, ctx, index: int):
        """Remove a battle conditions schedule by index

        Args:
            index: The schedule index (from `bc schedule_list`)
        """
        schedules = self.get_setting("thread_schedules", [])

        if not schedules:
            return await ctx.send("No battle conditions schedules configured")

        if index < 1 or index > len(schedules):
            return await ctx.send(f"❌ Invalid index. Must be between 1 and {len(schedules)}")

        # Get the schedule to remove (for feedback)
        schedule = schedules[index - 1]
        thread_id = schedule.get("thread_id")
        leagues = schedule.get("leagues", [])

        channel = self.bot.get_channel(int(thread_id)) if thread_id else None
        channel_str = channel.mention if channel else f"(ID: {thread_id})"

        # Remove the schedule
        schedules.pop(index - 1)
        self.set_setting("thread_schedules", schedules)
        self.mark_data_modified()

        await ctx.send(f"✅ Removed schedule #{index} for {channel_str} with leagues: {', '.join(leagues)}")

    @bc_group.command(name="schedule_edit")
    async def bc_schedule_edit_command(self, ctx, index: int, setting: str, *, value: str):
        """Edit a specific setting of a schedule

        Args:
            index: The schedule index (from `bc schedule_list`)
            setting: Setting to change (hour, minute, days_before, leagues)
            value: New value for the setting
        """
        schedules = self.get_setting("thread_schedules", [])

        if not schedules:
            return await ctx.send("No battle conditions schedules configured")

        if index < 1 or index > len(schedules):
            return await ctx.send(f"❌ Invalid index. Must be between 1 and {len(schedules)}")

        valid_settings = ["hour", "minute", "days_before", "leagues"]
        if setting not in valid_settings:
            return await ctx.send(f"❌ Invalid setting. Must be one of: {', '.join(valid_settings)}")

        # Get the schedule to edit
        schedule = schedules[index - 1]

        try:
            if setting in ["hour", "minute", "days_before"]:
                # Handle numeric settings
                int_value = int(value)

                # Validate
                if setting == "hour" and not (0 <= int_value <= 23):
                    return await ctx.send("❌ Hour must be between 0 and 23")

                if setting == "minute" and not (0 <= int_value <= 59):
                    return await ctx.send("❌ Minute must be between 0 and 59")

                if setting == "days_before" and not (0 <= int_value <= 7):
                    return await ctx.send("❌ Days before must be between 0 and 7")

                # Update the setting
                schedule[setting] = int_value

            elif setting == "leagues":
                # Handle leagues list
                valid_leagues = ["Legend", "Champion", "Platinum", "Gold", "Silver"]
                new_leagues = [league.strip().title() for league in value.split(",")]

                invalid_leagues = [league for league in new_leagues if league not in valid_leagues]
                if invalid_leagues:
                    return await ctx.send(f"❌ Invalid leagues: {', '.join(invalid_leagues)}. Valid leagues: {', '.join(valid_leagues)}")

                if not new_leagues:
                    return await ctx.send("❌ You must specify at least one league")

                # Update the leagues
                schedule["leagues"] = new_leagues

            # Save the updated schedules
            schedules[index - 1] = schedule
            self.set_setting("thread_schedules", schedules)
            self.mark_data_modified()

            await ctx.send(f"✅ Updated {setting} for schedule #{index}")

        except ValueError:
            if setting in ["hour", "minute", "days_before"]:
                await ctx.send("❌ Value must be a number")
            else:
                await ctx.send("❌ Invalid format for leagues. Use comma-separated list.")

    @bc_group.command(name="pause")
    async def bc_pause_command(self, ctx, paused: Optional[bool] = None):
        """Pause or unpause battle conditions announcements.

        Args:
            paused: Set to True to pause, False to unpause, or leave empty to toggle.
        """
        current_state = self.get_setting("paused", False)

        # If no argument is provided, toggle the current state
        if paused is None:
            paused = not current_state

        # Update the setting
        self.set_setting("paused", paused)
        self.mark_data_modified()

        # Send confirmation message
        if paused:
            await ctx.send("System is now ⏸️ Paused")
        else:
            await ctx.send("System is now ✅ Running")

        # Add hint about schedule-specific pausing
        await ctx.send("*Tip: Use `bc schedule_pause <index>` to pause individual schedules*")

    @bc_group.command(name="toggle")
    async def bc_toggle_command(self, ctx, setting_name: str, value: Optional[bool] = None,
                                schedule_index: Optional[int] = None):
        """Toggle a boolean setting for battle conditions.

        Args:
            setting_name: The name of the setting to toggle.
            value: Optional explicit value (True/False). If not provided, will toggle current value.
            schedule_index: Optional schedule index to toggle a schedule-specific setting.
        """
        # Handle schedule-specific toggles
        if setting_name == "paused" and schedule_index is not None:
            schedules = self.get_setting("thread_schedules", [])

            if not schedules:
                return await ctx.send("No battle conditions schedules configured")

            if schedule_index < 1 or schedule_index > len(schedules):
                return await ctx.send(f"❌ Invalid index. Must be between 1 and {len(schedules)}")

            # Get the schedule and current pause state
            schedule = schedules[schedule_index - 1]
            current_value = schedule.get("paused", False)

            # If no value is provided, toggle the current value
            if value is None:
                new_value = not current_value
            else:
                new_value = value

            # Update the schedule
            schedule["paused"] = new_value
            schedules[schedule_index - 1] = schedule
            self.set_setting("thread_schedules", schedules)

            # Get channel info for feedback
            thread_id = schedule.get("thread_id")
            channel = self.bot.get_channel(int(thread_id)) if thread_id else None
            channel_str = channel.mention if channel else f"(ID: {thread_id})"

            # Send confirmation message
            status = "⏸️ Paused" if new_value else "✅ Enabled"
            await ctx.send(f"Schedule #{schedule_index} ({channel_str}) is now {status}")

            self.mark_data_modified()
            return

        # Handle global settings
        valid_settings = ["paused"]

        if setting_name not in valid_settings:
            return await ctx.send(f"❌ Invalid setting. Valid toggle settings: {', '.join(valid_settings)}")

        current_value = self.get_setting(setting_name, False)

        # If no value is provided, toggle the current value
        if value is None:
            new_value = not current_value
        else:
            new_value = value

        # Update the setting
        self.set_setting(setting_name, new_value)
        self.mark_data_modified()

        # Get a human-readable name for the setting
        setting_display_name = setting_name.replace("_", " ").title()

        # Send confirmation message
        status = "✅ Enabled" if new_value else "❌ Disabled"
        await ctx.send(f"Setting `{setting_display_name}` is now {status}")

        # If toggling pause, also provide the operational status message
        if setting_name == "paused":
            status_msg = "⏸️ Paused" if new_value else "✅ Running"
            await ctx.send(f"System is now {status_msg}")

    @bc_group.command(name="schedule_pause")
    async def bc_schedule_pause_command(self, ctx, index: int):
        """Pause a specific battle conditions schedule.

        Args:
            index: The schedule index (from `bc schedule_list`) to pause.
        """
        schedules = self.get_setting("thread_schedules", [])

        if not schedules:
            return await ctx.send("No battle conditions schedules configured")

        if index < 1 or index > len(schedules):
            return await ctx.send(f"❌ Invalid index. Must be between 1 and {len(schedules)}")

        # Get the schedule
        schedule = schedules[index - 1]
        thread_id = schedule.get("thread_id")

        # Check if already paused
        if schedule.get("paused", False):
            channel = self.bot.get_channel(int(thread_id)) if thread_id else None
            channel_str = channel.mention if channel else f"(ID: {thread_id})"
            return await ctx.send(f"Schedule #{index} ({channel_str}) is already paused")

        # Update the schedule
        schedule["paused"] = True
        schedules[index - 1] = schedule
        self.set_setting("thread_schedules", schedules)
        self.mark_data_modified()

        # Get channel for feedback
        channel = self.bot.get_channel(int(thread_id)) if thread_id else None
        channel_str = channel.mention if channel else f"(ID: {thread_id})"

        await ctx.send(f"✅ Paused schedule #{index} ({channel_str})")

    @bc_group.command(name="schedule_resume")
    async def bc_schedule_resume_command(self, ctx, index: int):
        """Resume a specific battle conditions schedule.

        Args:
            index: The schedule index (from `bc schedule_list`) to resume.
        """
        schedules = self.get_setting("thread_schedules", [])

        if not schedules:
            return await ctx.send("No battle conditions schedules configured")

        if index < 1 or index > len(schedules):
            return await ctx.send(f"❌ Invalid index. Must be between 1 and {len(schedules)}")

        # Get the schedule
        schedule = schedules[index - 1]
        thread_id = schedule.get("thread_id")

        # Check if already running
        if not schedule.get("paused", False):
            channel = self.bot.get_channel(int(thread_id)) if thread_id else None
            channel_str = channel.mention if channel else f"(ID: {thread_id})"
            return await ctx.send(f"Schedule #{index} ({channel_str}) is already running")

        # Update the schedule
        schedule["paused"] = False
        schedules[index - 1] = schedule
        self.set_setting("thread_schedules", schedules)
        self.mark_data_modified()

        # Get channel for feedback
        channel = self.bot.get_channel(int(thread_id)) if thread_id else None
        channel_str = channel.mention if channel else f"(ID: {thread_id})"

        await ctx.send(f"✅ Resumed schedule #{index} ({channel_str})")

    # Replace the existing resume command with a more comprehensive one
    @bc_group.command(name="resume")
    async def bc_resume_command(self, ctx, index: Optional[int] = None):
        """Resume battle conditions announcements.

        Args:
            index: Optional schedule index to resume (from `bc schedule_list`).
                   If not provided, all announcements will be resumed.
        """
        if index is None:
            # Resume all announcements
            self.set_setting("paused", False)
            self.mark_data_modified()
            await ctx.send("✅ All battle conditions announcements resumed")

            # Add hint about schedule-specific resuming
            await ctx.send("*Note: This does not resume individually paused schedules. Use `bc schedule_resume <index>` for those.*")
        else:
            # Use the dedicated schedule_resume command
            await self.bc_schedule_resume_command(ctx, index)

    @bc_group.command(name="trigger")
    @commands.has_permissions(administrator=True)
    async def bc_trigger_command(self, ctx, index: Optional[int] = None):
        """Manually trigger battle conditions announcements

        Args:
            index: Optional schedule index to trigger (from `bc schedule_list`).
                   If not provided, all schedules will be triggered.
        """
        # Check global pause setting
        if self.get_setting("paused"):
            return await ctx.send("❌ Cannot trigger announcements while globally paused")

        # Get tournament information
        tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info()

        # Get thread schedules from settings
        thread_schedules = self.get_setting("thread_schedules", [])
        enabled_leagues = self.get_setting("enabled_leagues")

        if not thread_schedules:
            return await ctx.send("No battle conditions schedules configured")

        if index is not None:
            # Trigger a specific schedule
            if index < 1 or index > len(thread_schedules):
                return await ctx.send(f"❌ Invalid index. Must be between 1 and {len(thread_schedules)}")

            # Get the specific schedule
            schedule = thread_schedules[index - 1]
            schedules_to_process = [schedule]
            await ctx.send(f"🔔 Triggering battle conditions for schedule #{index}...")
        else:
            # Trigger all schedules
            schedules_to_process = thread_schedules
            await ctx.send("🔔 Triggering battle conditions for all schedules...")

        # Track overall success
        triggered_count = 0

        # Process each schedule
        for schedule in schedules_to_process:
            thread_id = schedule.get("thread_id")
            leagues = schedule.get("leagues", [])

            # Get the channel
            channel = self.bot.get_channel(int(thread_id))
            if not channel:
                self.logger.warning(f"Could not find channel with ID {thread_id}")
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

                    embed = discord.Embed(
                        title=f"{league} League Battle Conditions",
                        description=f"Tournament on {tourney_date}",
                        color=discord.Color.gold()
                    )

                    bc_text = "\n".join([f"• {bc}" for bc in battleconditions])
                    embed.add_field(name="Predicted Battle Conditions", value=bc_text, inline=False)
                    embed.set_footer(text="Manually triggered announcement")

                    await channel.send(embed=embed)
                    sent_something = True
                    self.logger.info(f"Manually triggered battle conditions for {league} league to channel {channel.name}")

                except Exception as e:
                    self.logger.error(f"Error sending battle conditions for {league} league to channel {channel.name}: {e}")

            if sent_something:
                triggered_count += 1

        # Provide feedback on how many were triggered
        if triggered_count > 0:
            await ctx.send(f"✅ Successfully triggered {triggered_count} schedule(s)")
        else:
            await ctx.send("⚠️ No battle conditions were sent. Check that leagues are enabled and channels exist.")

    @bc_group.command(name="schedules_reload")
    async def bc_schedules_reload_command(self, ctx):
        """Reload battle conditions schedules from the config file.

        This is useful when configurations have been edited externally
        and you need to refresh them in the running bot without restarting.
        """
        try:
            # Get the guild ID to access the proper config section
            guild_id = str(ctx.guild.id)

            # Reload the config from disk
            self.bot.config.reload_config()

            # Access the BattleConditions section for the current guild
            cog_configs = self.bot.config.config.get("cogs", {}).get(guild_id, {})
            bc_config = cog_configs.get("BattleConditions", {})

            # Update settings with fresh values from config
            thread_schedules = bc_config.get("thread_schedules", [])
            self.set_setting("thread_schedules", thread_schedules)

            # Update other relevant settings that might have changed
            self.set_setting("notification_hour", bc_config.get("notification_hour", 0))
            self.set_setting("notification_minute", bc_config.get("notification_minute", 0))
            self.set_setting("days_before_notification", bc_config.get("days_before_notification", 1))
            self.set_setting("enabled_leagues", bc_config.get("enabled_leagues", ["Legend", "Champion", "Platinum", "Gold", "Silver"]))
            self.set_setting("paused", bc_config.get("paused", False))

            # Update the defaults
            self.default_hour = self.get_setting("notification_hour")
            self.default_minute = self.get_setting("notification_minute")
            self.default_days_before = self.get_setting("days_before_notification")
            self.enabled_leagues = self.get_setting("enabled_leagues")

            # Count schedules for feedback
            schedule_count = len(thread_schedules)

            await ctx.send(f"✅ Successfully reloaded battle conditions settings. {schedule_count} schedules loaded.")

            # Log the action
            self.logger.info(f"Battle conditions schedules reloaded by {ctx.author}. {schedule_count} schedules loaded.")

        except Exception as e:
            # Log the error
            self.logger.error(f"Error reloading battle conditions schedules: {e}")
            await ctx.send(f"❌ Error reloading schedules: {str(e)}")

    @tasks.loop(minutes=1)  # Check every 1 minute
    async def scheduled_bc_messages(self):
        """Check all schedules and send battle condition messages as needed"""
        await self.bot.wait_until_ready()
        await self.wait_until_ready()

        # Check global pause setting
        if self.get_setting("paused"):
            self.logger.debug("Battle conditions announcements are globally paused")
            return

        try:
            self._active_process = "Battle Conditions Check"
            self._process_start_time = datetime.datetime.utcnow()

            # Get tournament information
            tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info()
            now = datetime.datetime.utcnow()
            current_hour = now.hour
            current_minute = now.minute

            # Get thread schedules from settings
            thread_schedules = self.get_setting("thread_schedules", [])
            enabled_leagues = self.get_setting("enabled_leagues")

            # Process each schedule
            for schedule in thread_schedules:
                thread_id = schedule.get("thread_id")
                leagues = schedule.get("leagues", [])

                # Check if this specific schedule is paused
                if schedule.get("paused", False):
                    self.logger.debug(f"Schedule for thread {thread_id} is paused - skipping")
                    continue

                # Get schedule timing
                hour = schedule.get("hour", self.default_hour)
                minute = schedule.get("minute", self.default_minute)
                days_before = schedule.get("days_before", self.default_days_before)

                # Skip if this is not the right day before tournament
                if days_until != days_before:
                    continue

                # Skip if this is not the right time (with some margin for the 1-minute check)
                time_match = (
                    current_hour == hour and
                    (current_minute >= minute and current_minute < minute + 1)
                )
                if not time_match:
                    continue

                # We've matched both day and time - process this schedule
                self.logger.info(f"Processing schedule for thread {thread_id}, {days_before} days before tournament")

                channel = self.bot.get_channel(int(thread_id))
                if not channel:
                    self.logger.warning(f"Could not find channel with ID {thread_id}")
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

    def format_time_value(self, seconds):
        """Format seconds into a standardized time string

        Args:
            seconds: Number of seconds

        Returns:
            str: Formatted string like "1h 30m 45s (5445 seconds)"
        """
        hours, remainder = divmod(seconds, 3600)
        minutes, remaining_seconds = divmod(remainder, 60)

        parts = []
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0 or hours > 0:
            parts.append(f"{minutes}m")
        parts.append(f"{remaining_seconds}s")

        return f"{' '.join(parts)} ({seconds} seconds)"

    def format_relative_time(self, timestamp):
        """Format a timestamp as a relative time string

        Args:
            timestamp: Datetime object

        Returns:
            str: Human readable relative time
        """
        now = datetime.datetime.utcnow()
        diff = now - timestamp

        seconds = diff.total_seconds()
        if seconds < 60:
            return f"{int(seconds)} seconds ago"
        elif seconds < 3600:
            return f"{int(seconds // 60)} minutes ago"
        elif seconds < 86400:
            return f"{int(seconds // 3600)} hours ago"
        else:
            return f"{int(seconds // 86400)} days ago"

    @scheduled_bc_messages.before_loop
    async def before_scheduled_bc_messages(self):
        """Set up the task before it starts"""
        self.logger.info("Starting battle conditions scheduler with 1-minute interval")

    @bc_group.command(name="status")
    async def show_status(self, ctx):
        """Display current operational status of the Battle Conditions system."""

        # Determine overall status
        if self.paused:
            status_emoji = "⏸️"
            status_text = "Paused"
            embed_color = discord.Color.orange()
        elif self._has_errors:
            status_emoji = "❌"
            status_text = "Error"
            embed_color = discord.Color.red()
        else:
            status_emoji = "✅"
            status_text = "Operational"
            embed_color = discord.Color.blue()

        # Get tournament info for context
        try:
            tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info()
            tournament_info = f"Next tournament: {tourney_date} ({days_until} days away)"
        except Exception as e:
            self.logger.error(f"Error getting tournament info: {e}")
            tournament_info = "Error fetching tournament info"
            self._has_errors = True

        # Create status embed
        embed = discord.Embed(
            title="Battle Conditions Status",
            description=f"Current status: {status_emoji} {status_text}\n{tournament_info}",
            color=embed_color
        )

        # Add dependency information
        dependencies = [
            f"Tournament Predictor: {'✅ Available' if not self._has_errors else '❌ Error'}"
        ]
        embed.add_field(name="Dependencies", value="\n".join(dependencies), inline=False)

        # Add process information
        if self._active_process:
            embed.add_field(
                name="Active Processes",
                value=f"🔄 {self._active_process} (started {self.format_relative_time(self._process_start_time)} ago)",
                inline=False
            )

        # Add statistics
        thread_schedules = self.get_setting("thread_schedules", [])
        active_schedules = sum(1 for s in thread_schedules if not s.get("paused", False))

        stats = [
            f"Operations completed: {self._operation_count}",
            f"Active schedules: {active_schedules}/{len(thread_schedules)}",
            f"Enabled leagues: {len(self.enabled_leagues)}/{5}"
        ]
        embed.add_field(name="Statistics", value="\n".join(stats), inline=False)

        # Add last activity
        if self._last_operation_time:
            embed.add_field(
                name="Last Activity",
                value=f"Last operation: {self.format_relative_time(self._last_operation_time)} ago",
                inline=False
            )

        await ctx.send(embed=embed)

    @bc_group.command(name="help")
    async def bc_help_command(self, ctx):
        """Show help information for Battle Conditions commands."""
        embed = discord.Embed(
            title="Battle Conditions Help",
            description="Commands to manage and view tournament battle conditions.",
            color=discord.Color.blue()
        )

        # Core commands
        embed.add_field(
            name="Core Commands",
            value=(
                "`bc get [league]` - Get battle conditions for a league\n"
                "`bc tourney` - Show next tournament date\n"
                "`bc info` - Show system information\n"
                "`bc status` - Show operational status\n"
                "`bc settings` - Show configuration settings"
            ),
            inline=False
        )

        # Schedule management
        embed.add_field(
            name="Schedule Management",
            value=(
                "`bc schedule_add <channel> [hour] [minute] [days_before] [leagues...]` - Add new schedule\n"
                "`bc schedule_list` - List all schedules\n"
                "`bc schedule_remove <index>` - Remove a schedule\n"
                "`bc schedule_edit <index> <setting> <value>` - Edit schedule settings\n"
                "`bc schedule_pause <index>` - Pause specific schedule\n"
                "`bc schedule_resume <index>` - Resume specific schedule"
            ),
            inline=False
        )

        # System control
        embed.add_field(
            name="System Control",
            value=(
                "`bc pause` - Pause all announcements\n"
                "`bc resume` - Resume all announcements\n"
                "`bc toggle <setting> [value]` - Toggle a setting\n"
                "`bc set <setting> <value>` - Set a configuration value\n"
                "`bc schedules_reload` - Reload schedules from config file"
            ),
            inline=False
        )

        # Add footer with example
        embed.set_footer(text="Example: bc get Legend")

        await ctx.send(embed=embed)


async def setup(bot) -> None:
    await bot.add_cog(BattleConditions(bot))
