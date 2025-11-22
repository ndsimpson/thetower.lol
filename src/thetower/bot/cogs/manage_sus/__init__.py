# Manage Sus Cog
# Cog for managing moderation records in Django

from discord.ext import commands

from .cog import ManageSus

__all__ = ["ManageSus"]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ManageSus(bot))

    # Note: Slash command syncing is now handled automatically by CogManager
    # when cogs are enabled/disabled for guilds
    bot.logger.info("ManageSus cog loaded - slash commands will sync per-guild via CogManager")
    bot.logger.info("ManageSus cog loaded - slash commands will sync per-guild via CogManager")
