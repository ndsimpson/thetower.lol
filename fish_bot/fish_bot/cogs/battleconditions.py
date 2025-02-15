import datetime

from discord.ext import commands, tasks

from fish_bot import const
from fish_bot.util import is_allowed_user

from dtower.tourney_results.bc import predict_future_tournament, get_tournament_info

league_threads = {
    "Legend" : const.legend_bc_thread_id,
    "Champion" : const.champ_bc_thread_id,
    "Platinum" : const.plat_bc_thread_id
}


class BattleConditions(commands.Cog, name="BattleConditions"):
    def __init__(self, bot):
        self.bot = bot
        self.scheduled_bc_messages.start()
        print(f'Init next run {self.scheduled_bc_messages.next_iteration}')
        print("Init done.")

    def cog_unload(self):
        self.scheduled_bc_messages.cancel()

    # @commands.Cog.listener()
    # async def on_message(self, message):
    #     print(f'{message.content}')

    @commands.command()
    async def get_tourneyday(self, ctx):
        tourney_id, tourney_date, days_until = get_tournament_info()
        if days_until == 0:
            await ctx.send("The tournament is today!")
        else:
            await ctx.send(f"The tournament is {days_until} days away and will run on {tourney_date}")

    @commands.command()
    @is_allowed_user(const.id_pog, const.id_fishy)
    async def get_battleconditions(self, ctx, league: str = "Legend"):
        tourney_id, tourney_date, days_until = get_tournament_info()
        battleconditions = predict_future_tournament(tourney_id, league)
        if days_until == 0:
            message = f"The BCs for today's {league} tourney are:\n"
        else:
            message = f"The BCs for the {league} tourney on {tourney_date} are:\n"
        for battlecondition in battleconditions:
            message += f"- {battlecondition}\n"
        await ctx.message.delete()
        await ctx.send(message)

    @tasks.loop(time=datetime.time(hour=0, minute=0))
    async def scheduled_bc_messages(self):
        tourney_id, tourney_date, days_until = get_tournament_info()
        if days_until == 1:
            for league in ["Legend", "Champion", "Platinum"]:
                battleconditions = predict_future_tournament(tourney_id)
                message = f"The BCs for tomorrow's {league} tournament ({tourney_date}) are:\n"
                for battlecondition in battleconditions:
                    message += f"- {battlecondition}\n"
                channel = self.bot.get_channel(league_threads[league])
                await channel.send(message)


async def setup(bot) -> None:
    await bot.add_cog(BattleConditions(bot))
