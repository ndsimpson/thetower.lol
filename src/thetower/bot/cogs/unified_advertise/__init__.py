# Unified Advertise Cog Package
from .cog import UnifiedAdvertise

__all__ = ['UnifiedAdvertise']

async def setup(bot):
    """Setup function for Discord.py extension loading."""
    await bot.add_cog(UnifiedAdvertise(bot))
