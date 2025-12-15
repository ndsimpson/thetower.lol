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


class ColorSelectionButton(discord.ui.Button):
    """Button for color role selection in player profiles."""

    def __init__(self, cog):
        super().__init__(label="🎨 Select Color Role", style=discord.ButtonStyle.primary, emoji="🎨")
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        """Show color selection interface."""
        # Get qualified roles for this user
        qualified_data = self.cog.core.get_qualified_roles_for_user(interaction.user)
        current_role_id = self.cog.core.get_user_current_color_role(interaction.user)

        if not qualified_data:
            embed = discord.Embed(
                title="🎨 No Color Roles Available",
                description="You don't have any color roles available. Complete more tournaments to unlock color roles!",
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Create the color selection view
        view = self.cog.create_color_selection_view(interaction.user)

        embed = discord.Embed(
            title="🎨 Color Role Selection", description="Choose a category to view available color roles:", color=discord.Color.blue()
        )

        # Add current role info
        if current_role_id:
            current_role = interaction.guild.get_role(current_role_id)
            if current_role:
                embed.add_field(name="Current Role", value=current_role.mention, inline=False)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


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

        # Register UI extension for profile integration
        if hasattr(self.bot, "cog_manager"):
            self.bot.cog_manager.register_ui_extension(
                target_cog="player_lookup", source_cog="tourney_role_colors", provider_func=self._provide_color_selection_button
            )
            self.logger.info("Registered color selection UI extension for player profiles")

        # No additional initialization needed - BaseCog handles settings persistence

    async def cog_unload(self) -> None:
        """Clean up when the cog is unloaded."""
        self.logger.info("TourneyRoleColors cog unloading")

        # Unregister UI extension
        if hasattr(self.bot, "cog_manager"):
            self.bot.cog_manager.unregister_ui_extensions_from_source("tourney_role_colors")
            self.logger.info("Unregistered color selection UI extensions")

    @discord.ext.commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Monitor role changes and adjust color roles automatically."""
        await self.core.handle_member_update(before, after)

    def create_color_selection_view(self, user: discord.Member) -> discord.ui.View:
        """Create color selection view for the user (called by profile registry)."""
        return self.core.create_color_selection_view(user)

    def _provide_color_selection_button(self, details, requesting_user, guild_id, permission_context):
        """Provide color selection button for player profiles."""
        # Only show button if user is viewing their own profile
        if str(details.get("discord_id")) != str(requesting_user.id):
            return None

        # Check if user has any qualified color roles
        qualified_data = self.core.get_qualified_roles_for_user(requesting_user)
        if not qualified_data:
            return None

        # Create the button
        button = ColorSelectionButton(self)
        return button
