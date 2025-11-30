# Validation Cog Package
from .cog import Validation

__all__ = ["Validation"]


async def setup(bot):
    """Setup function for Discord.py extension loading."""
    await bot.add_cog(Validation(bot))
