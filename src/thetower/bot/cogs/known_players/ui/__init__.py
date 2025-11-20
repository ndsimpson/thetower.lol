# UI Module Exports
# This module provides clean API exports for the Known Players UI components

from .core import LookupView  # Deprecated, use PlayerView
from .core import ProfileView  # Deprecated, use PlayerView
from .core import (
    CreatorCodeModal,
    PlayerView,
    get_player_details,
    validate_creator_code,
)
from .settings import (
    KnownPlayersSettingsView,
)
from .user import (
    UserInteractions,
)

__all__ = [
    # Core components
    "CreatorCodeModal",
    "PlayerView",
    "ProfileView",  # Deprecated, use PlayerView
    "LookupView",  # Deprecated, use PlayerView
    "get_player_details",
    "validate_creator_code",
    # User interactions
    "UserInteractions",
    # Settings
    "KnownPlayersSettingsView",
]
