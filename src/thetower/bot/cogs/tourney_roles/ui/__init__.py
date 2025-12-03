"""
UI components for the Tournament Roles cog.

This module provides clean exports for all UI-related functionality.
"""

from .admin import (
    AdminRoleManagementView,
    AdminTournamentRoles,
    ConfirmRemoveView,
)
from .core import (
    AddRoleModal,
    LeagueHierarchyModal,
    RoleAssignmentResult,
    TournamentRoleConfig,
    TournamentRolesCore,
    TournamentStats,
)
from .settings import (
    CoreSettingsView,
    DurationModal,
    LoggingSettingsView,
    ModeSettingsView,
    NumberModal,
    ProcessingSettingsView,
    TournamentRolesSettingsView,
    UpdateSettingsView,
)

__all__ = [
    # Core business logic
    "TournamentRolesCore",
    "TournamentRoleConfig",
    "TournamentStats",
    "RoleAssignmentResult",
    "LeagueHierarchyModal",
    "AddRoleModal",
    # Admin interfaces
    "AdminRoleManagementView",
    "ConfirmRemoveView",
    "AdminTournamentRoles",
    # Settings interfaces
    "TournamentRolesSettingsView",
    "CoreSettingsView",
    "UpdateSettingsView",
    "ProcessingSettingsView",
    "ModeSettingsView",
    "LoggingSettingsView",
    "DurationModal",
    "NumberModal",
]
