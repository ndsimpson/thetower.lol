import datetime

from discord.ext import commands, tasks

from fish_bot import const
from fish_bot.util import is_allowed_user

from dtower.tourney_results.bc import predict_future_tournament, get_next_tournament

league_threads = {
    "Legend" : const.legend_bc_thread_id,
    "Champion" : const.champ_bc_thread_id
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
        result = get_next_tournament()
        if result['days_until'] == 0:
            await ctx.send("The tournament is today!")
        else:
            await ctx.send(f"The tournament is {result['days_until']} days away and will run on {result['next_date']}")

    @commands.command()
    @is_allowed_user(const.id_pog, const.id_fishy)
    async def get_battleconditions(self, ctx, league: str = "Legend"):
        result = get_next_tournament()
        battleconditions = predict_future_tournament(result['next_id'], league)
        if result['days_until'] == 0:
            message = f"The BCs for today's {league} tourney are:\n"
        else:
            message = f"The BCs for the {league} tourney on {result['next_date']} are:\n"
        for battlecondition in battleconditions:
            message += f"- {battlecondition}\n"
        await ctx.message.delete()
        await ctx.send(message)

    @tasks.loop(time=datetime.time(hour=0, minute=0))
    async def scheduled_bc_messages(self):
        result = get_next_tournament()
        if result['days_until'] == 1:
            for league in ["Legend", "Champion"]:
                battleconditions = predict_future_tournament(result['next_id'])
                message = f"The BCs for tomorrow's {league} tournament ({result['next_date']}) are:\n"
                for battlecondition in battleconditions:
                    message += f"- {battlecondition}\n"
                channel = self.bot.get_channel(league_threads[league])
                await channel.send(message)


async def setup(bot) -> None:
    await bot.add_cog(BattleConditions(bot))
