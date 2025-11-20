"""
Tournament Roles Cog

A modular Discord bot cog for automatically assigning tournament-based roles
based on competitive performance across different leagues.

This cog follows the unified cog design architecture with:
- Modular UI components separated by function/role
- Integration with global settings system
- Slash command-based interface
- Robust background processing and task management
"""

from .cog import TourneyRoles


async def setup(bot) -> None:
    """Setup function for the Tournament Roles cog."""
    await bot.add_cog(TourneyRoles(bot))
