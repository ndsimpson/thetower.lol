# Verification Backfill Cog Package
from .cog import VerificationBackfill

__all__ = ["VerificationBackfill"]


async def setup(bot):
    """Setup function for Discord.py extension loading."""
    await bot.add_cog(VerificationBackfill(bot))
