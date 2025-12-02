"""Django Admin cog for managing Django users and groups."""

from discord.ext import commands

from .cog import DjangoAdmin

__all__ = ["DjangoAdmin", "setup"]


async def setup(bot: commands.Bot) -> None:
    """Load the Django Admin cog.
    
    Args:
        bot: The Discord bot instance.
    """
    await bot.add_cog(DjangoAdmin(bot))
