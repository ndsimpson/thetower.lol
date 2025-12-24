"""Core business logic and shared components for Battle Conditions cog."""

from typing import List, Optional

import discord

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


# === Constants ===

ALL_LEAGUES = ["Legend", "Champion", "Platinum", "Gold", "Silver", "Bronze"]
DEFAULT_ENABLED_LEAGUES = ["Legend", "Champion", "Platinum", "Gold", "Silver"]


# === Core Business Logic ===


class BattleConditionsCore:
    """Core business logic for battle conditions functionality."""

    @staticmethod
    async def get_battle_conditions(league: str) -> List[str]:
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
            return predict_future_tournament(tourney_id, league)
        except Exception as e:
            return ["❌ Error fetching battle conditions"]

    @staticmethod
    async def send_battle_conditions_embed(channel, league, tourney_date, battleconditions) -> bool:
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
            return True
        except Exception:
            return False

    @staticmethod
    def get_tournament_info():
        """Get current tournament information."""
        if TOWERBCS_AVAILABLE:
            return TournamentPredictor.get_tournament_info()
        return None, "Unknown", 0


# === Form Modals ===


class ScheduleTimeModal(discord.ui.Modal, title="Schedule Time Configuration"):
    """Modal for configuring schedule time."""

    def __init__(self, cog: "BattleConditions", guild_id: int, channel_id: int):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.channel_id = channel_id

        self.days_before_input = discord.ui.TextInput(
            label="Days before tournament (0-7)", placeholder="e.g., 1 for day before tournament", default="1", required=True, max_length=1
        )
        self.add_item(self.days_before_input)

        self.hour_input = discord.ui.TextInput(
            label="Hour (0-23, UTC)", placeholder="e.g., 14 for 2 PM UTC", default="0", required=True, max_length=2
        )
        self.add_item(self.hour_input)

        self.minute_input = discord.ui.TextInput(
            label="Minute (0-59)", placeholder="e.g., 30 for half past the hour", default="0", required=True, max_length=2
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

            # Import here to avoid circular imports
            from .user import ScheduleLeagueSelect

            # Step 3: Show league picker
            league_view = discord.ui.View(timeout=900)
            league_view.add_item(ScheduleLeagueSelect(self.cog, self.guild_id, self.channel_id, hour, minute, days_before))

            await interaction.response.send_message(
                f"**Step 3/3:** Select leagues to include in this schedule:\n"
                f"Channel: <#{self.channel_id}>\n"
                f"Time: {hour:02d}:{minute:02d} UTC, {days_before} day(s) before tournament",
                view=league_view,
                ephemeral=True,
            )

        except ValueError:
            await interaction.response.send_message("❌ Invalid input", ephemeral=True)


class EditScheduleModal(discord.ui.Modal, title="Edit BC Schedule"):
    """Modal for editing an existing schedule."""

    def __init__(self, cog: "BattleConditions", guild_id: int, schedule_idx: int, schedule: dict):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.schedule_idx = schedule_idx
        self.current_leagues = schedule.get("leagues", [])

        self.days_before_input = discord.ui.TextInput(
            label="Days before tournament (0-7)", default=str(schedule.get("days_before", 1)), required=True, max_length=1
        )
        self.add_item(self.days_before_input)

        self.hour_input = discord.ui.TextInput(label="Hour (0-23, UTC)", default=str(schedule.get("hour", 0)), required=True, max_length=2)
        self.add_item(self.hour_input)

        self.minute_input = discord.ui.TextInput(label="Minute (0-59)", default=str(schedule.get("minute", 0)), required=True, max_length=2)
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

            # Import here to avoid circular imports
            from .admin import EditScheduleLeagueSelect

            # Show league picker
            league_view = discord.ui.View(timeout=900)
            league_view.add_item(
                EditScheduleLeagueSelect(self.cog, self.guild_id, self.schedule_idx, hour, minute, days_before, self.current_leagues)
            )

            await interaction.response.send_message(
                f"**Final Step:** Select leagues for schedule #{self.schedule_idx}:\n"
                f"Time: {hour:02d}:{minute:02d} UTC, {days_before} day(s) before tournament",
                view=league_view,
                ephemeral=True,
            )

        except ValueError:
            await interaction.response.send_message("❌ Invalid input", ephemeral=True)


class ViewWindowModal(discord.ui.Modal, title="Global BC View Window"):
    """Modal for setting the BC view window."""

    def __init__(self, cog: "BattleConditions", current_value: Optional[int]):
        super().__init__()
        self.cog = cog

        self.view_window_input = discord.ui.TextInput(
            label="Days before tournament (blank = always)",
            placeholder="e.g., 3 for 3 days before tourney, or leave blank",
            default=str(current_value) if current_value is not None else "",
            required=False,
            max_length=3,
        )
        self.add_item(self.view_window_input)

    async def on_submit(self, interaction: discord.Interaction):
        value_str = self.view_window_input.value.strip()

        if not value_str:
            # Blank means always available
            self.cog.set_global_setting("bc_view_window_days", None)
            await interaction.response.send_message("✅ BC view window set to **always available**", ephemeral=True)
        else:
            try:
                days = int(value_str)
                if days < 0:
                    await interaction.response.send_message("❌ Days must be 0 or positive", ephemeral=True)
                    return

                self.cog.set_global_setting("bc_view_window_days", days)
                await interaction.response.send_message(f"✅ BC view window set to **{days} day(s)** before tournament", ephemeral=True)
            except ValueError:
                await interaction.response.send_message("❌ Invalid number. Please enter a valid number of days.", ephemeral=True)


class DefaultScheduleTimingModal(discord.ui.Modal, title="Default Schedule Timing"):
    """Modal for configuring default schedule timing settings."""

    def __init__(self, cog: "BattleConditions", guild_id: int, current_hour: int, current_minute: int, current_days_before: int):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id

        self.days_before_input = discord.ui.TextInput(
            label="Days before tournament (0-7)",
            placeholder="Default days before tournament",
            default=str(current_days_before),
            required=True,
            max_length=1,
        )
        self.add_item(self.days_before_input)

        self.hour_input = discord.ui.TextInput(
            label="Hour (0-23, UTC)",
            placeholder="Default hour in UTC",
            default=str(current_hour),
            required=True,
            max_length=2,
        )
        self.add_item(self.hour_input)

        self.minute_input = discord.ui.TextInput(
            label="Minute (0-59)",
            placeholder="Default minute",
            default=str(current_minute),
            required=True,
            max_length=2,
        )
        self.add_item(self.minute_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Parse and validate inputs
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

            # Check against view window constraint
            view_window = self.cog.get_global_setting("bc_view_window_days")
            if view_window is not None and days_before > view_window:
                await interaction.response.send_message(
                    f"❌ Days before ({days_before}) cannot exceed BC View Window ({view_window} days).\n"
                    f"Either reduce days_before or increase the BC View Window setting.",
                    ephemeral=True,
                )
                return

            # Save settings
            self.cog.set_setting("notification_hour", hour, guild_id=self.guild_id)
            self.cog.set_setting("notification_minute", minute, guild_id=self.guild_id)
            self.cog.set_setting("days_before_notification", days_before, guild_id=self.guild_id)

            await interaction.response.send_message(
                f"✅ Default schedule timing updated:\n" f"⏰ {hour:02d}:{minute:02d} UTC\n" f"📅 {days_before} day(s) before tournament",
                ephemeral=True,
            )

        except ValueError:
            await interaction.response.send_message("❌ Invalid input. Please enter valid numbers.", ephemeral=True)
