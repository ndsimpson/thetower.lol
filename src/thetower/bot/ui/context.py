# UI Context Classes
# This module contains context classes used by UI components
# to avoid circular imports between BaseCog and settings_views

from dataclasses import dataclass
from typing import Any, Optional

import discord
from discord.ui import View


@dataclass
class SettingsViewContext:
    """Context object passed to cog settings views."""

    guild_id: Optional[int]
    cog_instance: Any
    interaction: discord.Interaction
    is_bot_owner: bool


class BaseSettingsView(View):
    """Base class for cog settings views with standardized context access.

    This class provides a consistent interface for all cog settings views,
    eliminating the need for repetitive `bot = interaction.client` patterns
    and providing convenient property access to common attributes.

    All cog settings views should inherit from this class and pass the
    SettingsViewContext object to the parent constructor.

    Example:
        class MyCogSettingsView(BaseSettingsView):
            def __init__(self, context: SettingsViewContext):
                super().__init__(context)
                # Add your buttons/UI components here

            async def update_display(self, interaction: discord.Interaction):
                # Access bot, guild_id, cog, etc. via properties
                enabled = self.bot.cog_manager.config.get_guild_enabled_cogs(self.guild_id)
    """

    def __init__(self, context: SettingsViewContext, timeout: int = 900):
        """Initialize the base settings view.

        Args:
            context: SettingsViewContext containing guild, cog, interaction, and permission info
            timeout: View timeout in seconds (default: 900 = 15 minutes)
        """
        super().__init__(timeout=timeout)
        self.ctx = context
        self.cog = context.cog_instance
        self.guild_id = context.guild_id
        self.interaction = context.interaction
        self.is_bot_owner = context.is_bot_owner

    @property
    def bot(self):
        """Quick access to bot instance from interaction.

        Returns:
            The Discord bot/client instance
        """
        return self.interaction.client
