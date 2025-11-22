from .cog import PlayerLookup

__all__ = ["PlayerLookup"]


async def setup(bot):
    await bot.add_cog(PlayerLookup(bot))

    # Note: Slash command syncing is now handled automatically by CogManager
    # when cogs are enabled/disabled for guilds
    bot.logger.info("PlayerLookup cog loaded - slash commands will sync per-guild via CogManager")
