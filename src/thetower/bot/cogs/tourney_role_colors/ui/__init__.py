"""
UI components for the Tourney Role Colors cog.

This package contains all user interface components:
- core.py: Business logic and shared components
- user.py: User-facing interfaces
- settings.py: Admin settings interfaces
"""

from .core import TourneyRoleColorsCore
from .settings import TourneyRoleColorsSettingsView
from .user import ColorSelectionView

__all__ = [
    "TourneyRoleColorsCore",
    "TourneyRoleColorsSettingsView",
    "ColorSelectionView",
]
