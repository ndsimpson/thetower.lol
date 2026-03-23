"""UI components for the Django Admin cog."""

from .core import DjangoAdminMainView
from .settings import DjangoAdminSettingsView

__all__ = ["DjangoAdminSettingsView", "DjangoAdminMainView"]
