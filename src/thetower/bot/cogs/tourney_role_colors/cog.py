"""
Tourney Role Colors Cog

A Discord bot cog for managing tournament-based color role assignments.
Users can select from qualified color roles based on their tournament rankings,
with automatic role management when qualifications change.

This cog follows the unified cog design architecture with:
- Modular UI components separated by function/role
- Integration with global settings system
- Registry-based profile integration
- Automatic qualification monitoring
"""

import discord

from thetower.bot.basecog import BaseCog

from .ui import (
    TourneyRoleColorsCore,
    TourneyRoleColorsSettingsView,
)


class TourneyRoleColors(BaseCog, name="Tourney Role Colors"):
    """
    Tournament-based color role management system.

    Automatically manages color role assignments based on tournament rankings
    and user qualifications, with server-owner configurable categories.
    """

    # Settings view class for the cog manager
    settings_view_class = TourneyRoleColorsSettingsView

    def __init__(self, bot):
        super().__init__(bot)
        self.logger.info("Initializing TourneyRoleColors")

        # Store reference on bot for registry integration
        self.bot.tourney_role_colors = self

        # Initialize core instance variables
        self.core = TourneyRoleColorsCore(self)

    async def cog_initialize(self) -> None:
        """Initialize the cog and start background tasks."""
        self.logger.info("TourneyRoleColors cog initializing")

        # No additional initialization needed - BaseCog handles settings persistence

    async def cog_unload(self) -> None:
        """Clean up when the cog is unloaded."""
        self.logger.info("TourneyRoleColors cog unloading")

    @discord.ext.commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Monitor role changes and adjust color roles automatically."""
        await self.core.handle_member_update(before, after)

    def create_color_selection_view(self, user: discord.Member) -> discord.ui.View:
        """Create color selection view for the user (called by profile registry)."""
        return self.core.create_color_selection_view(user)
