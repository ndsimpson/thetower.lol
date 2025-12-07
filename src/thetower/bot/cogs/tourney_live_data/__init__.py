from .cog import TourneyLiveData

__all__ = ["TourneyLiveData"]


async def setup(bot):
    await bot.add_cog(TourneyLiveData(bot))

    # Note: Slash command syncing is now handled automatically by CogManager
    # when cogs are enabled/disabled for guilds
