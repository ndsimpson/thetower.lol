from collections import defaultdict

from discord.ext import commands


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


async def setup(bot) -> None:
    await bot.add_cog(Main(bot))