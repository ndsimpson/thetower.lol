"""
Tourney Role Colors Cog Package
"""

from .cog import TourneyRoleColors

__all__ = ["TourneyRoleColors"]


async def setup(bot) -> None:
    await bot.add_cog(TourneyRoleColors(bot))
