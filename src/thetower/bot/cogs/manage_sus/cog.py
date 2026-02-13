# Standard library imports
import datetime
from typing import Any, Dict, List, Optional

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

        # Store a reference to this cog
        self.bot.manage_sus = self

        # Global settings (bot-wide)
        self.global_settings = {
            "view_groups": [],  # Django groups that can view moderation records
            "manage_groups": [],  # Django groups that can create/update moderation records
            "privileged_groups_for_full_ids": [],  # Django groups that can see all player IDs
            "show_moderation_records_in_profiles": True,  # Whether to show moderation records in profiles
            "privileged_groups_for_moderation_records": [],  # Django groups that can see moderation records in profiles
        }

        # Guild-specific settings (none for this cog currently)
        self.guild_settings = {}

    async def cog_initialize(self) -> None:
        """Initialize the cog - called by BaseCog during ready process."""
        self.logger.info("Initializing Manage Sus module...")

        try:
            async with self.task_tracker.task_context("Initialization") as tracker:
                # Initialize parent
                self.logger.debug("Initializing parent cog")
                tracker.update_status("Loading data")
                await super().cog_initialize()

                # UI extensions are registered automatically by BaseCog.__init__
                # No need to call register_ui_extensions() here

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

        # Register info provider for moderation status in player profiles
        self.bot.cog_manager.register_info_extension(
            target_cog="player_lookup", source_cog=self.__class__.__name__, provider_func=self.provide_player_lookup_info
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

    def get_moderation_button_for_player(
        self, details, requesting_user: discord.User, guild_id: int, permission_context
    ) -> Optional[discord.ui.Button]:
        """Get a moderation management button for a player if the user has permission.

        This method is called by the player_lookup cog to extend /lookup functionality.
        Returns a button that opens the moderation management interface for the player,
        or None if the user doesn't have permission or is viewing their own profile.

        Handles three scenarios:
        1. Unverified player: Use primary_id directly (no game instances)
        2. Single game instance: Use primary ID from that instance
        3. Multiple game instances: Button will show dropdown to select which instance
        """
        # Don't show button if user is viewing their own profile
        # TEMPORARILY DISABLED FOR TESTING
        # game_instances = details.get("game_instances", [])
        # if game_instances:
        #     # Check if any Discord account in any instance matches requesting user
        #     for instance in game_instances:
        #         discord_accounts = instance.get("discord_accounts_receiving_roles", [])
        #         if str(requesting_user.id) in [str(did) for did in discord_accounts]:
        #             return None  # User viewing own profile

        # Check if user has permission to view/manage moderation records using the permission context
        # Get allowed groups from settings
        view_groups = self.config.get_global_cog_setting("manage_sus", "view_groups", self.global_settings["view_groups"])
        manage_groups = self.config.get_global_cog_setting("manage_sus", "manage_groups", self.global_settings["manage_groups"])
        allowed_groups = view_groups + manage_groups

        if permission_context.has_any_group(allowed_groups):
            return ManageSusButton(self, details, requesting_user, guild_id)

        return None

    async def provide_player_lookup_info(self, details: dict, requesting_user: discord.User, permission_context) -> List[Dict[str, Any]]:
        """Provide moderation status info for player lookup embeds.

        Args:
            details: Standardized player details dictionary with game_instances or all_ids
            requesting_user: The Discord user requesting the info
            permission_context: Permission context for the requesting user

        Returns:
            List of embed field dictionaries to add to the player embed
        """
        try:
            # IMPORTANT: Users should NEVER see their own moderation records for privacy
            # TEMPORARILY DISABLED FOR TESTING
            # is_own_profile = str(requesting_user.id) == details.get("discord_id")
            # if is_own_profile:
            #     return []

            # Check if user has permission to view moderation records
            view_groups = self.config.get_global_cog_setting("manage_sus", "view_groups", self.global_settings["view_groups"])
            privileged_groups = self.config.get_global_cog_setting(
                "manage_sus", "privileged_groups_for_moderation_records", self.global_settings["privileged_groups_for_moderation_records"]
            )
            allowed_groups = view_groups + privileged_groups

            if not permission_context.has_any_group(allowed_groups):
                return []

            # Extract player IDs from details
            all_player_ids = []
            if "game_instances" in details:
                # New GameInstance structure - extract player IDs from all instances
                for instance in details["game_instances"]:
                    all_player_ids.extend([pid["id"] for pid in instance.get("player_ids", [])])
            elif "game_instance" in details:
                # Single game instance (per-instance extension call)
                instance = details["game_instance"]
                all_player_ids.extend([pid["id"] for pid in instance.get("player_ids", [])])
            elif "player_ids" in details:
                # Unverified player or simplified structure
                all_player_ids = [pid["id"] for pid in details["player_ids"]]
            elif "primary_id" in details:
                # Minimal structure - just primary ID
                all_player_ids = [details["primary_id"]]

            if not all_player_ids:
                return []

            # Query all moderation records for all player IDs (both active and resolved)
            from asgiref.sync import sync_to_async

            from thetower.backend.sus.models import ModerationRecord

            def _get_all_moderation_records():
                return list(ModerationRecord.objects.filter(tower_id__in=all_player_ids).order_by("-created_at"))

            all_records = await sync_to_async(_get_all_moderation_records)()

            if not all_records:
                return []

            # Count active and resolved records by type
            active_counts = {}
            resolved_counts = {}

            for record in all_records:
                mod_type = record.get_moderation_type_display()
                if record.resolved_at is None:
                    # Active record
                    active_counts[mod_type] = active_counts.get(mod_type, 0) + 1
                else:
                    # Resolved record
                    resolved_counts[mod_type] = resolved_counts.get(mod_type, 0) + 1

            # Build the response fields
            fields = []

            # Add active moderation field if there are active records
            if active_counts:
                active_count = sum(active_counts.values())
                active_lines = []

                # Get the actual active records for detailed display
                active_records = [r for r in all_records if r.resolved_at is None]

                for record in active_records:
                    mod_type_display = record.get_moderation_type_display()
                    date_str = record.started_at.strftime("%Y-%m-%d")

                    # Use the same emoji mapping as the original code
                    emoji_map = {"sus": "⚠️", "ban": "🚫", "shun": "🔇", "soft_ban": "⚡"}  # suspicious  # banned  # shunned  # soft banned
                    emoji = emoji_map.get(record.moderation_type, "⚖️")

                    # Format like original: emoji + bold type + date
                    line = f"{emoji} **{mod_type_display}** - {date_str}"

                    # Add reason on separate line with indentation and different emoji
                    reason = record.reason or "No reason provided"
                    if len(reason) > 50:
                        reason = reason[:50] + "..."
                    line += f"\n   └ {reason}"

                    active_lines.append(line)

                fields.append({"name": f"⚖️ Active Moderation ({active_count})", "value": "\n".join(active_lines), "inline": False})

            # Add resolved moderation field if there are resolved records
            if resolved_counts:
                if len(resolved_counts) == 1:
                    mod_type, count = next(iter(resolved_counts.items()))
                    resolved_text = f"{mod_type} ({count})"
                else:
                    resolved_parts = [f"{mod_type}: {count}" for mod_type, count in resolved_counts.items()]
                    resolved_text = ", ".join(resolved_parts)

                fields.append({"name": "✅ Resolved Moderation", "value": resolved_text, "inline": False})

            return fields

        except Exception as e:
            self.logger.warning(f"Error getting moderation info for player {details.get('name', 'unknown')}: {e}")
            return []

    async def _user_can_view_moderation_records(self, user: discord.User) -> bool:
        """Check if a Discord user can view moderation records based on their Django groups."""
        self.logger.info(f"Checking view permissions for user {user.id} ({user.name})")
        try:
            from asgiref.sync import sync_to_async

            from thetower.backend.sus.models import LinkedAccount

            def _check_permissions_sync():
                # Get the active LinkedAccount for this Discord user
                linked_account = (
                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=str(user.id), active=True)
                    .select_related("player__django_user")
                    .first()
                )
                if not linked_account:
                    return False, "No active LinkedAccount found"

                # Check if the player has a django_user linked
                player = linked_account.player
                django_user = player.django_user if player else None
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
            view_groups = self.config.get_global_cog_setting("manage_sus", "view_groups", self.global_settings["view_groups"])
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

            from thetower.backend.sus.models import LinkedAccount

            def _check_permissions_sync():
                # Get the active LinkedAccount for this Discord user
                linked_account = (
                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=str(user.id), active=True)
                    .select_related("player__django_user")
                    .first()
                )
                if not linked_account:
                    return False, "No active LinkedAccount found"

                # Check if the player has a django_user linked
                player = linked_account.player
                django_user = player.django_user if player else None
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
            manage_groups = self.config.get_global_cog_setting("manage_sus", "manage_groups", self.global_settings["manage_groups"])
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

            from thetower.backend.sus.models import LinkedAccount

            def _check_permissions_sync():
                # Get the active LinkedAccount for this Discord user
                linked_account = (
                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=str(user.id), active=True)
                    .select_related("player__django_user")
                    .first()
                )
                if not linked_account:
                    return False, "No active LinkedAccount found"

                # Check if the player has a django_user linked
                player = linked_account.player
                django_user = player.django_user if player else None
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

            from thetower.backend.sus.models import LinkedAccount

            def _check_permissions_sync():
                # Get the active LinkedAccount for this Discord user
                linked_account = (
                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=str(user.id), active=True)
                    .select_related("player__django_user")
                    .first()
                )
                if not linked_account:
                    return False, "No active LinkedAccount found"

                # Check if the player has a django_user linked
                player = linked_account.player
                django_user = player.django_user if player else None
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
            "manage_sus", "privileged_groups_for_full_ids", self.global_settings["privileged_groups_for_full_ids"]
        )

    @property
    def show_moderation_records_in_profiles(self) -> bool:
        """Get whether moderation records should be shown in profiles."""
        return self.config.get_global_cog_setting(
            "manage_sus", "show_moderation_records_in_profiles", self.global_settings["show_moderation_records_in_profiles"]
        )

    @property
    def privileged_groups_for_moderation_records(self) -> List[str]:
        """Get the list of Django groups that can see moderation records in profiles."""
        return self.config.get_global_cog_setting(
            "manage_sus", "privileged_groups_for_moderation_records", self.global_settings["privileged_groups_for_moderation_records"]
        )


class ManageSusButton(discord.ui.Button):
    """Button to manage moderation records for a specific player.

    Handles three scenarios:
    1. Unverified player: Use primary_id directly (no game instances)
    2. Single game instance: Use primary ID from that instance
    3. Multiple game instances: Show dropdown to select which instance
    """

    def __init__(self, cog, details: dict, requesting_user: discord.User, guild_id: int):
        # Determine label based on whether dropdown is needed
        game_instances = details.get("game_instances", [])
        if len(game_instances) > 1:
            label = "Manage shun/sus/ban (select ID)"
        else:
            label = "Manage shun/sus/ban"

        player_id = details.get("primary_id", "unknown")
        super().__init__(label=label, style=discord.ButtonStyle.danger, emoji="⚖️", custom_id=f"manage_sus_{player_id}", row=1)
        self.cog = cog
        self.details = details
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

        try:
            game_instances = self.details.get("game_instances", [])

            # Scenario 1: Unverified player (no game instances) - use primary_id directly
            if not game_instances:
                player_id = self.details.get("primary_id")
                if not player_id:
                    await interaction.response.send_message("❌ No player ID found.", ephemeral=True)
                    return

                from .ui.user import PlayerModerationView

                view = PlayerModerationView(self.cog, self.details, self.requesting_user, self.guild_id)
                embed = await view.update_view(interaction)
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
                return

            # Scenario 2: Single game instance - use primary ID from that instance
            if len(game_instances) == 1:
                player_id = game_instances[0]["primary_player_id"]

                # Update details with the player ID for the moderation view
                moderation_details = {**self.details, "primary_id": player_id}

                from .ui.user import PlayerModerationView

                view = PlayerModerationView(self.cog, moderation_details, self.requesting_user, self.guild_id)
                embed = await view.update_view(interaction)
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
                return

            # Scenario 3: Multiple game instances - show dropdown to select
            from .ui.user import GameInstanceSelectionView

            selection_view = GameInstanceSelectionView(self.cog, self.details, self.requesting_user, self.guild_id, game_instances)

            embed = discord.Embed(
                title="Select Game Account",
                description="This player has multiple game accounts. Select which one to manage:",
                color=discord.Color.blue(),
            )

            # List the game instances
            for idx, instance in enumerate(game_instances, 1):
                instance_name = instance["account_name"]
                primary_id = instance["primary_player_id"]
                is_primary = instance["primary"]
                marker = " ⭐" if is_primary else ""
                embed.add_field(name=f"{idx}. {instance_name}{marker}", value=f"`{primary_id}`", inline=False)

            await interaction.response.send_message(embed=embed, view=selection_view, ephemeral=True)

        except Exception as e:
            player_id = self.details.get("primary_id", "unknown")
            self.cog.logger.error(f"Error opening moderation management for player {player_id}: {e}")
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
