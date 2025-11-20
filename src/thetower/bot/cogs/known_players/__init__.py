# Known Players Cog Package
# This package provides modular player identity management for the Tower bot

from .cog import KnownPlayers

__all__ = [
    "KnownPlayers",
]


async def setup(bot) -> None:
    await bot.add_cog(KnownPlayers(bot))
