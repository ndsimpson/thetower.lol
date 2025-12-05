"""Battle Conditions cog - Main implementation."""

import datetime
from typing import List

import discord
from discord import app_commands
from discord.ext import commands, tasks

from thetower.bot.basecog import BaseCog

from .ui import TOWERBCS_AVAILABLE, BattleConditionsCore, BattleConditionsSettingsView, BCManagementView


class BattleConditions(BaseCog, name="Battle Conditions"):
    """Commands for predicting and displaying upcoming battle conditions.

    Provides functionality to:
    - Check upcoming tournament dates
    - Predict battle conditions for different leagues
    - Automatically announce battle conditions
    """

    # Register the settings view class for the modular settings system
    settings_view_class = BattleConditionsSettingsView

    # === Core Methods ===
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.logger.info("Initializing BattleConditions")

        # Store reference on bot
        self.bot.battle_conditions = self

        # Global settings (bot-wide)
        self.global_settings = {
            "bc_view_window_days": None,  # None = always available, or number of days before tourney
            "enabled_leagues": [],
        }

        # Guild-specific settings
        self.guild_settings = {
            # Time Settings
            "notification_hour": 0,
            "notification_minute": 0,
            "days_before_notification": 1,
            # Schedule Settings
            "destination_schedules": [],
        }

    async def _check_additional_interaction_permissions(self, interaction: discord.Interaction) -> bool:
        """Override additional interaction permissions for slash commands.

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
    @app_commands.command(name="battleconditions", description="View and manage battle conditions")
    @app_commands.guild_only()
    async def battleconditions_slash(self, interaction: discord.Interaction) -> None:
        """Battle conditions management UI."""
        # Check permissions for different actions
        can_generate = await self.check_slash_action_permission(interaction, "generate")
        can_run_schedule = await self.check_slash_action_permission(interaction, "run_schedule")
        is_owner = interaction.guild.owner_id == interaction.user.id or await self.bot.is_owner(interaction.user)

        # Create the view with conditional buttons
        view = BCManagementView(self, can_generate, can_run_schedule, is_owner)

        # Get tournament info for display
        if TOWERBCS_AVAILABLE:
            tourney_id, tourney_date, days_until = BattleConditionsCore.get_tournament_info()
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
        return await BattleConditionsCore.get_battle_conditions(league)

    async def send_battle_conditions_embed(self, channel, league, tourney_date, battleconditions) -> bool:
        """Helper method to create and send battle conditions embeds

        Args:
            channel: Channel to send the embed to
            league: League name for the battle conditions
            tourney_date: Tournament date string
            battleconditions: List of battle condition strings

        Returns:
            bool: Whether the message was sent successfully
        """
        return await BattleConditionsCore.send_battle_conditions_embed(channel, league, tourney_date, battleconditions)

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
                tourney_id, tourney_date, days_until = BattleConditionsCore.get_tournament_info()
                now = datetime.datetime.utcnow()
                current_hour = now.hour
                current_minute = now.minute

                # Collect all schedules from all guilds that match current time/day
                # This is more efficient than checking every schedule every minute
                schedules_to_process = []

                # Get global enabled leagues (applies to all guilds)
                enabled_leagues = self.get_setting("enabled_leagues")
                if not enabled_leagues:
                    return  # Skip if no leagues are configured

                for guild in self.bot.guilds:
                    guild_id = guild.id

                    # Get schedules for this guild
                    schedules = self.get_setting("destination_schedules", [], guild_id=guild_id)

                    # Filter schedules that match current time and day
                    for schedule in schedules:
                        # Skip paused schedules immediately
                        if schedule.get("paused", False):
                            continue

                        # Get schedule timing
                        hour = schedule.get("hour", self.guild_settings["notification_hour"])
                        minute = schedule.get("minute", self.guild_settings["notification_minute"])
                        days_before = schedule.get("days_before", self.guild_settings["days_before_notification"])

                        # Check if this schedule should run now
                        time_match = current_hour == hour and (current_minute >= minute and current_minute < minute + 1)
                        day_match = days_until == days_before

                        if time_match and day_match:
                            # Add guild context to schedule for processing
                            schedules_to_process.append(
                                {
                                    "schedule": schedule,
                                    "guild_id": guild_id,
                                }
                            )

                # Process all matching schedules
                for item in schedules_to_process:
                    schedule = item["schedule"]
                    guild_id = item["guild_id"]

                    destination_id = schedule.get("destination_id")
                    leagues = schedule.get("leagues", [])

                    self.logger.info(
                        f"Processing schedule for destination {destination_id} in guild {guild_id}, {schedule.get('days_before')} days before tournament"
                    )

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
                        # Skip leagues that aren't enabled (handle None case)
                        if enabled_leagues is None or league not in enabled_leagues:
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
