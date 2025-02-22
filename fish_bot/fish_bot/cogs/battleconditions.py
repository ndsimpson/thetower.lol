import datetime

from discord.ext import commands, tasks

from fish_bot.basecog import BaseCog
from fish_bot.utils import ConfigManager  # TODO: Remove this import and transition to self.config

from towerbcs.towerbcs import predict_future_tournament, TournamentPredictor

config = ConfigManager()

league_threads = {
    "Legend" : config.get_thread_id("battleconditions", "legend"),
    "Champion" : config.get_thread_id("battleconditions", "champion"),
    "Platinum" : config.get_thread_id("battleconditions", "platinum"),
    "Gold" : config.get_thread_id("battleconditions", "gold"),
    "Silver" : config.get_thread_id("battleconditions", "silver")
}


class BattleConditions(BaseCog, name="Battle Conditions"):
    """Commands for predicting and displaying upcoming battle conditions.

    Provides functionality to:
    - Check upcoming tournament dates
    - Predict battle conditions for different leagues
    - Automatically announce battle conditions
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self.scheduled_bc_messages.start()

    def cog_unload(self):
        self.scheduled_bc_messages.cancel()

    @commands.group(name="bc", invoke_without_command=True)
    async def bc(self, ctx):
        """Battle conditions commands.

        Available subcommands:
        - get_battleconditions: Get predicted BCs for a league
        - get_tourneyday: Get the date of the next tourney
        """
        if ctx.invoked_subcommand is None:
            # List all available subcommands
            commands_list = [command.name for command in self.bc.commands]
            await ctx.send(f"Available subcommands: {', '.join(commands_list)}")

    @bc.command()
    async def get_battleconditions(self, ctx, league: str = "Legend"):
        """Get predicted battle conditions for a specific league.

        Args:
            league (str): League name (Legend, Champion, Platinum, Gold, Silver)
        """
        tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info()
        battleconditions = predict_future_tournament(tourney_id, league)
        message = f"The BCs for the {league} tourney on {tourney_date} are:\n"
        for battlecondition in battleconditions:
            message += f"- {battlecondition}\n"
        try:
            await ctx.message.delete()
        except Exception as e:
            print(e)
            pass
        await ctx.send(message)

    @bc.command()
    async def get_tourneyday(self, ctx):
        """Get the date of the next tourney."""
        tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info()
        if days_until == 0:
            await ctx.send("The tournament is today!")
        else:
            await ctx.send(f"The tournament is {days_until} days away and will run on {tourney_date}")

    @tasks.loop(time=datetime.time(hour=0, minute=0))
    async def scheduled_bc_messages(self):
        tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info()
        if days_until == 1:
            for league in ["Legend", "Champion", "Platinum", "Gold", "Silver"]:
                battleconditions = predict_future_tournament(tourney_id)
                message = f"The BCs for the {league.title()} tournament on {tourney_date} are:\n"
                for battlecondition in battleconditions:
                    message += f"- {battlecondition}\n"
                channel = self.bot.get_channel(league_threads[league])
                await channel.send(message)


async def setup(bot) -> None:
    await bot.add_cog(BattleConditions(bot))
