# UI package for UnifiedAdvertise cog
# This package contains the user interface components split by functionality

from .admin import AdminAdManagementView
from .core import (
    AdvertisementType,
    EditGuildAdvertisementForm,
    GuildAdvertisementForm,
    GuildAdvertisementTemplateForm,
    NotificationView,
    TagSelectionView,
)
from .settings import (
    AdDetailView,
    AdListView,
    AdTypeSelectionView,
    CustomTagsManagementView,
    SettingsView,
    TagGroupOptionsView,
    UnifiedAdvertiseSettingsView,
)
from .user import AdManagementView

__all__ = [
    # Core advertisement creation
    "AdvertisementType",
    "GuildAdvertisementForm",
    "GuildAdvertisementTemplateForm",
    "EditGuildAdvertisementForm",
    "NotificationView",
    "TagSelectionView",
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
    "CustomTagsManagementView",
    "TagGroupOptionsView",
]
