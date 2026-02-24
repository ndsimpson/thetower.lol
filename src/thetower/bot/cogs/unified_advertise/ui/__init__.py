# UI package for UnifiedAdvertise cog
# This package contains the user interface components split by functionality

from .admin import AdminAdManagementView
from .core import (
    AdTypeSelection,
    AdvertisementType,
    EditGuildAdvertisementForm,
    EditMemberAdvertisementForm,
    GuildAdvertisementForm,
    GuildAdvertisementTemplateForm,
    MemberAdvertisementForm,
    MemberAdvertisementTemplateForm,
    NotificationView,
)
from .settings import AdDetailView, AdListView, AdTypeSelectionView, SettingsView, UnifiedAdvertiseSettingsView
from .user import AdManagementView

__all__ = [
    # Core advertisement creation
    "AdvertisementType",
    "AdTypeSelection",
    "GuildAdvertisementForm",
    "GuildAdvertisementTemplateForm",
    "MemberAdvertisementForm",
    "MemberAdvertisementTemplateForm",
    "EditGuildAdvertisementForm",
    "EditMemberAdvertisementForm",
    "NotificationView",
    # User management
    "AdManagementView",
    # Admin management
    "AdminAdManagementView",
    "AdTypeSelectionView",
    "AdListView",
    "AdDetailView",
    # Settings management
    "SettingsView",
    "UnifiedAdvertiseSettingsView",
]
