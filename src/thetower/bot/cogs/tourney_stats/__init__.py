from .cog import TourneyStats

__all__ = ["TourneyStats"]


async def setup(bot) -> None:
    await bot.add_cog(TourneyStats(bot))
