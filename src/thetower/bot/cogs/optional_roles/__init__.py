"""
Optional Roles Cog

Allows users to opt into community roles with configurable prerequisites.
Categories can be configured as single-selection or multi-selection.
Automatically enforces prerequisites and removes roles when requirements are lost.
"""

from .cog import OptionalRoles

__all__ = ["OptionalRoles"]


async def setup(bot) -> None:
    """Setup function for the Optional Roles cog."""
    await bot.add_cog(OptionalRoles(bot))
