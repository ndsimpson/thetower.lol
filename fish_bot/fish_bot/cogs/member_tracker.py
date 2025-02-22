from collections import defaultdict
from discord.ext import commands
from fish_bot.basecog import BaseCog


class MemberTracker(BaseCog, name="Member Tracker"):
    """Tracks member join/leave events and role changes.

    Monitors and logs all member-related events including:
    - Members joining the server
    - Members leaving the server
    - Role changes for members
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self.members = defaultdict(list)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Log when a member joins the server."""
        print(f'Member joined: {member.id} {member.name} ({member.nick})')

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Log when a member leaves the server."""
        print(f'Member left: {member.id} {member.name} ({member.nick})')

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Log when a member's roles are updated."""
        added_roles = set(after.roles) - set(before.roles)
        removed_roles = set(before.roles) - set(after.roles)
        if len(added_roles) > 0 or len(removed_roles) > 0:
            print(f'Member update for {before.name} ({before.nick}):')
        if len(added_roles) > 0:
            print(f'    Added roles: {added_roles}')
        if len(removed_roles) > 0:
            print(f'    Removed roles: {removed_roles}')


async def setup(bot) -> None:
    await bot.add_cog(MemberTracker(bot))
