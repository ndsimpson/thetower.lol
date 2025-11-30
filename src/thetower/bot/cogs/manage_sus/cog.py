# Standard library imports
import datetime
from typing import List, Optional

# Third-party imports
import discord
from discord.ext import commands

# Local application imports
from thetower.bot.basecog import BaseCog

# UI imports
from .ui import (
    ManageSusSettingsView,
)


class ManageSus(BaseCog, name="Manage Sus"):
    """Cog for managing moderation records (sus/ban/shun) in Django.

    Provides functionality for viewing and managing moderation records
    through Discord bot commands with proper permission controls.
    """

    # Settings view class for the cog manager
    settings_view_class = ManageSusSettingsView

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.logger.info("Initializing ManageSus")

        # Define default global settings (stored in bot config under manage_sus)
        self.default_settings = {
            "view_groups": [],  # Django groups that can view moderation records
            "manage_groups": [],  # Django groups that can create/update moderation records
            "privileged_groups_for_full_ids": [],  # Django groups that can see all player IDs
            "show_moderation_records_in_profiles": True,  # Whether to show moderation records in profiles
            "privileged_groups_for_moderation_records": [],  # Django groups that can see moderation records in profiles
        }

        # Store a reference to this cog
        self.bot.manage_sus = self

    async def cog_initialize(self) -> None:
        """Initialize the cog - called by BaseCog during ready process."""
        self.logger.info("Initializing Manage Sus module...")

        try:
            async with self.task_tracker.task_context("Initialization") as tracker:
                # Initialize parent
                self.logger.debug("Initializing parent cog")
                tracker.update_status("Loading data")
                await super().cog_initialize()

                # Register UI extensions for player profiles
                self.register_ui_extensions()

                # Update status variables
                self._last_operation_time = datetime.datetime.utcnow()
                self._operation_count = 0

                # Mark as ready
                self.set_ready(True)
                self.logger.info("Manage Sus initialization complete")

        except Exception as e:
            self._has_errors = True
            self.logger.error(f"Failed to initialize Manage Sus module: {e}", exc_info=True)
            raise

    def register_ui_extensions(self) -> None:
        """Register UI extensions that this cog provides to other cogs."""
        # Register button provider for player profiles
        self.bot.cog_manager.register_ui_extension(
            target_cog="player_lookup", source_cog=self.__class__.__name__, provider_func=self.get_moderation_button_for_player
        )

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded."""
        # Force save any modified data
        if self.is_data_modified():
            self.logger.warning(f"Cog {self.__class__.__name__} has unsaved data on unload")

        # Call parent implementation
        await super().cog_unload()

    # ====================
    # Moderation Commands
    # ====================

    # No direct slash commands - this cog extends /lookup functionality

    def get_moderation_button_for_player(self, player, requesting_user: discord.User, guild_id: int) -> Optional[discord.ui.Button]:
        """Get a moderation management button for a player if the user has permission.

        This method is called by the player_lookup cog to extend /lookup functionality.
        Returns a button that opens the moderation management interface for the player,
        or None if the user doesn't have permission.
        """
        # Check if user has permission to view/manage moderation records
        # We do this synchronously here since it's called from the player_lookup cog
        # The actual permission check will be done asynchronously when the button is clicked
        return ManageSusButton(self, player, requesting_user, guild_id)

    async def _user_can_view_moderation_records(self, user: discord.User) -> bool:
        """Check if a Discord user can view moderation records based on their Django groups."""
        self.logger.info(f"Checking view permissions for user {user.id} ({user.name})")
        try:
            from asgiref.sync import sync_to_async

            from thetower.backend.sus.models import KnownPlayer

            def _check_permissions_sync():
                # Get the KnownPlayer linked to this Discord user by Discord ID
                known_player = KnownPlayer.objects.filter(discord_id=str(user.id)).select_related("django_user").first()
                if not known_player:
                    return False, "No KnownPlayer found"

                # Check if the KnownPlayer has a django_user linked
                django_user = known_player.django_user
                if not django_user:
                    return False, "No django_user linked"

                # Get user's Django groups
                user_groups = list(django_user.groups.values_list("name", flat=True))

                return True, user_groups

            success, result = await sync_to_async(_check_permissions_sync)()

            if not success:
                self.logger.info(f"Permission check failed: {result}")
                return False

            user_groups = result
            self.logger.info(f"User groups: {user_groups}")

            # Get allowed view groups from settings
            view_groups = self.config.get_global_cog_setting("manage_sus", "view_groups", self.default_settings["view_groups"])
            self.logger.info(f"Required view groups: {view_groups}")

            # Check if user is in any of the allowed groups
            has_permission = any(group in view_groups for group in user_groups)
            self.logger.info(f"User has view permission: {has_permission}")

            return has_permission

        except Exception as e:
            self.logger.error(f"Error checking view permissions for user {user.id}: {e}")
            return False

    async def _user_can_manage_moderation_records(self, user: discord.User) -> bool:
        """Check if a Discord user can manage moderation records based on their Django groups."""
        self.logger.info(f"Checking manage permissions for user {user.id} ({user.name})")
        try:
            from asgiref.sync import sync_to_async

            from thetower.backend.sus.models import KnownPlayer

            def _check_permissions_sync():
                # Get the KnownPlayer linked to this Discord user by Discord ID
                known_player = KnownPlayer.objects.filter(discord_id=str(user.id)).select_related("django_user").first()
                if not known_player:
                    return False, "No KnownPlayer found"

                # Check if the KnownPlayer has a django_user linked
                django_user = known_player.django_user
                if not django_user:
                    return False, "No django_user linked"

                # Get user's Django groups
                user_groups = list(django_user.groups.values_list("name", flat=True))

                return True, user_groups

            success, result = await sync_to_async(_check_permissions_sync)()

            if not success:
                self.logger.info(f"Permission check failed: {result}")
                return False

            user_groups = result
            self.logger.info(f"User groups: {user_groups}")

            # Get allowed manage groups from settings
            manage_groups = self.config.get_global_cog_setting("manage_sus", "manage_groups", self.default_settings["manage_groups"])
            self.logger.info(f"Required manage groups: {manage_groups}")

            # Check if user is in any of the allowed groups
            has_permission = any(group in manage_groups for group in user_groups)
            self.logger.info(f"User has manage permission: {has_permission}")

            return has_permission

        except Exception as e:
            self.logger.error(f"Error checking manage permissions for user {user.id}: {e}")
            return False

    async def _user_can_view_full_ids(self, user: discord.User) -> bool:
        """Check if a Discord user can see all player IDs based on their Django groups."""
        self.logger.info(f"Checking full IDs permissions for user {user.id} ({user.name})")
        try:
            from asgiref.sync import sync_to_async

            from thetower.backend.sus.models import KnownPlayer

            def _check_permissions_sync():
                # Get the KnownPlayer linked to this Discord user by Discord ID
                known_player = KnownPlayer.objects.filter(discord_id=str(user.id)).select_related("django_user").first()
                if not known_player:
                    return False, "No KnownPlayer found"

                # Check if the KnownPlayer has a django_user linked
                django_user = known_player.django_user
                if not django_user:
                    return False, "No django_user linked"

                # Get user's Django groups
                user_groups = list(django_user.groups.values_list("name", flat=True))

                return True, user_groups

            success, result = await sync_to_async(_check_permissions_sync)()

            if not success:
                self.logger.info(f"Permission check failed: {result}")
                return False

            user_groups = result
            self.logger.info(f"User groups: {user_groups}")

            # Get allowed privileged groups from settings
            privileged_groups = self.privileged_groups_for_full_ids
            self.logger.info(f"Required privileged groups for full IDs: {privileged_groups}")

            # Check if user is in any of the privileged groups
            has_permission = any(group in privileged_groups for group in user_groups)
            self.logger.info(f"User has full IDs permission: {has_permission}")

            return has_permission

        except Exception as e:
            self.logger.error(f"Error checking full IDs permissions for user {user.id}: {e}")
            return False

    async def _user_can_view_moderation_records_in_profiles(self, user: discord.User) -> bool:
        """Check if a Discord user can see moderation records in profiles based on their Django groups."""
        self.logger.info(f"Checking moderation records in profiles permissions for user {user.id} ({user.name})")
        try:
            from asgiref.sync import sync_to_async

            from thetower.backend.sus.models import KnownPlayer

            def _check_permissions_sync():
                # Get the KnownPlayer linked to this Discord user by Discord ID
                known_player = KnownPlayer.objects.filter(discord_id=str(user.id)).select_related("django_user").first()
                if not known_player:
                    return False, "No KnownPlayer found"

                # Check if the KnownPlayer has a django_user linked
                django_user = known_player.django_user
                if not django_user:
                    return False, "No django_user linked"

                # Get user's Django groups
                user_groups = list(django_user.groups.values_list("name", flat=True))

                return True, user_groups

            success, result = await sync_to_async(_check_permissions_sync)()

            if not success:
                self.logger.info(f"Permission check failed: {result}")
                return False

            user_groups = result
            self.logger.info(f"User groups: {user_groups}")

            # Get allowed privileged groups from settings
            privileged_groups = self.privileged_groups_for_moderation_records
            self.logger.info(f"Required privileged groups for moderation records: {privileged_groups}")

            # Check if user is in any of the privileged groups
            has_permission = any(group in privileged_groups for group in user_groups)
            self.logger.info(f"User has moderation records permission: {has_permission}")

            return has_permission

        except Exception as e:
            self.logger.error(f"Error checking moderation records permissions for user {user.id}: {e}")
            return False

    @property
    def privileged_groups_for_full_ids(self) -> List[str]:
        """Get the list of Django groups that can see all player IDs."""
        return self.config.get_global_cog_setting(
            "manage_sus", "privileged_groups_for_full_ids", self.default_settings["privileged_groups_for_full_ids"]
        )

    @property
    def show_moderation_records_in_profiles(self) -> bool:
        """Get whether moderation records should be shown in profiles."""
        return self.config.get_global_cog_setting(
            "manage_sus", "show_moderation_records_in_profiles", self.default_settings["show_moderation_records_in_profiles"]
        )

    @property
    def privileged_groups_for_moderation_records(self) -> List[str]:
        """Get the list of Django groups that can see moderation records in profiles."""
        return self.config.get_global_cog_setting(
            "manage_sus", "privileged_groups_for_moderation_records", self.default_settings["privileged_groups_for_moderation_records"]
        )


class ManageSusButton(discord.ui.Button):
    """Button to manage moderation records for a specific player."""

    def __init__(self, cog, player, requesting_user: discord.User, guild_id: int):
        super().__init__(label="Manage shun/sus/ban", style=discord.ButtonStyle.danger, emoji="⚖️", custom_id=f"manage_sus_{player.id}", row=1)
        self.cog = cog
        self.player = player
        self.requesting_user = requesting_user
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Handle button click to open moderation management for this player."""
        # Check permissions
        can_view = await self.cog._user_can_view_moderation_records(self.requesting_user)
        can_manage = await self.cog._user_can_manage_moderation_records(self.requesting_user)

        if not can_view and not can_manage:
            await interaction.response.send_message("❌ You don't have permission to view or manage moderation records.", ephemeral=True)
            return

        # Show the player moderation view
        try:
            from .ui.user import PlayerModerationView

            view = PlayerModerationView(self.cog, self.player, self.requesting_user, self.guild_id)
            embed = await view.update_view(interaction)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            self.cog.logger.error(f"Error opening moderation management for player {self.player.id}: {e}")
            await interaction.response.send_message("❌ An error occurred while opening the moderation interface.", ephemeral=True)


# ====================
# Cog Setup
# ====================


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ManageSus(bot))

    # Note: Slash command syncing is now handled automatically by CogManager
    # when cogs are enabled/disabled for guilds
    bot.logger.info("ManageSus cog loaded - slash commands will sync per-guild via CogManager")
    # when cogs are enabled/disabled for guilds
    bot.logger.info("ManageSus cog loaded - slash commands will sync per-guild via CogManager")
    bot.logger.info("ManageSus cog loaded - slash commands will sync per-guild via CogManager")
    bot.logger.info("ManageSus cog loaded - slash commands will sync per-guild via CogManager")
