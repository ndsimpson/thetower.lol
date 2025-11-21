# UI Context Classes
# This module contains context classes used by UI components
# to avoid circular imports between BaseCog and settings_views

from dataclasses import dataclass
from typing import Any, Optional

import discord


@dataclass
class SettingsViewContext:
    """Context object passed to cog settings views."""

    guild_id: Optional[int]
    cog_instance: Any
    interaction: discord.Interaction
    is_bot_owner: bool
