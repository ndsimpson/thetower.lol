"""
Tourney Role Colors Cog

Allows server owners to configure roles that users can select based on prerequisites.
Categories are mutually exclusive - users can only have one managed role at a time.
"""

from .cog import TourneyRoleColors, setup

__all__ = [
    "TourneyRoleColors",
    "setup",
]
