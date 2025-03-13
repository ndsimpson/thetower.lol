from collections import defaultdict

from discord.ext import commands

from functools import partial

from fish_bot import const
from fish_bot.util import is_channel


class Main(commands.Cog, name="Main"):
    def __init__(self, bot):
        self.bot = bot
        self.members = defaultdict(list)
        # bot.settings()

    @commands.Cog.listener()
    async def on_member_join(self, member):
        print(f'Member joined: {member.id} {member.name} ({member.nick})')

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        print(f'Member left: {member.id} {member.name} ({member.nick})')

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        added_roles = set(after.roles) - set(before.roles)
        removed_roles = set(before.roles) - set(after.roles)
        if len(added_roles) > 0 or len(removed_roles) > 0:
            print(f'Member update for {before.name} ({before.nick}):')
        if len(added_roles) > 0:
            print(f'    Added roles: {added_roles}')
        if len(removed_roles) > 0:
            print(f'    Removed roles: {removed_roles}')

    @commands.Cog.listener("on_message")
    async def check_verify_message(self, message):
        is_player_id_please_channel = partial(is_channel, id_=const.verify_channel_id)
        try:
            if is_player_id_please_channel(message.channel) and message.author.id != const.id_towerbot:

                if len(message.content) > 13 and len(message.content) < 17 and message.attachments:

                    await message.add_reaction("👍🏼")
                else:
                    await message.add_reaction("👎🏼")
        except Exception as exc:
            await message.channel.send(f"Something went terribly wrong, please debug me. \n\n {exc}")
            raise exc


async def setup(bot) -> None:
    await bot.add_cog(Main(bot))