"""UI components for the Django Admin cog."""

from .main import DjangoAdminMainView
from .settings import DjangoAdminSettingsView

__all__ = ["DjangoAdminSettingsView", "DjangoAdminMainView"]
