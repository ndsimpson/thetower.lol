import asyncio
import datetime
import logging
from typing import Optional

import discord
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import commands

from thetower.backend.sus.models import GameInstance, KnownPlayer, LinkedAccount, PlayerId
from thetower.bot.basecog import BaseCog

from .ui import ValidationSettingsView, VerificationModal, VerificationStatusView

logger = logging.getLogger(__name__)


class Validation(BaseCog, name="Validation"):
    """Cog for player verification using slash commands and modals."""

    # Settings view class for the cog manager
    settings_view_class = ValidationSettingsView

    def __init__(self, bot):
        super().__init__(bot)

        # Store reference on bot
        self.bot.validation = self

        # Track bot-initiated role changes to prevent feedback loops
        self._bot_role_changes = set()  # Set of (member_id, guild_id) tuples

        # Global settings (bot-wide)
        self.global_settings = {
            "approved_unverify_groups": [],  # List of Django group names that can un-verify players
            "approved_manage_alt_links_groups": [],  # List of Django group names that can manage alt links for any user
            "mod_notification_channel_id": None,  # Optional channel ID for moderator notifications (bot-wide)
            "approved_id_change_moderator_groups": [],  # List of Django group names that can moderate player ID changes
            "manage_retired_accounts_groups": [],  # List of Django group names that can view/manage retired Discord accounts
        }

        # Guild-specific settings
        self.guild_settings = {
            "verified_role_id": None,  # Role ID for verified users
            "verification_log_channel_id": None,  # Channel ID for logging verifications
            "verification_enabled": True,  # Whether verification is enabled for this guild
        }

    async def cog_load(self):
        """Called when cog is loaded - restore persistent views."""
        await super().cog_load()

        # Restore persistent views for pending player ID changes
        from .ui.core import PlayerIdChangeApprovalView

        data = self.load_pending_player_id_changes_data()
        pending_changes = data.get("pending_changes", {})
        restored_views = 0

        for discord_id, pending_data in pending_changes.items():
            old_player_id = pending_data.get("old_player_id")
            new_player_id = pending_data.get("new_player_id")
            reason = pending_data.get("reason")
            instance_id = pending_data.get("instance_id")

            # Attempt to restore log channel message view
            if pending_data.get("log_message_id") and pending_data.get("log_channel_id"):
                try:
                    log_channel = self.bot.get_channel(pending_data["log_channel_id"])
                    if log_channel:
                        # Try to fetch the message to verify it exists
                        try:
                            await log_channel.fetch_message(pending_data["log_message_id"])
                            view = PlayerIdChangeApprovalView(self, discord_id, old_player_id, new_player_id, reason, instance_id)
                            self.bot.add_view(view, message_id=pending_data["log_message_id"])
                            restored_views += 1
                        except discord.NotFound:
                            self.logger.warning(
                                f"Log message {pending_data['log_message_id']} for pending change (user {discord_id}) not found - buttons won't work but data preserved"
                            )
                        except discord.Forbidden:
                            self.logger.warning(
                                f"Cannot access log message {pending_data['log_message_id']} for pending change (user {discord_id}) - missing permissions"
                            )
                    else:
                        self.logger.warning(f"Log channel {pending_data['log_channel_id']} not found for pending change (user {discord_id})")
                except Exception as e:
                    self.logger.error(f"Error verifying log message for pending change (user {discord_id}): {e}")

            # Attempt to restore mod notification message view
            if pending_data.get("mod_message_id") and pending_data.get("mod_channel_id"):
                try:
                    mod_channel = self.bot.get_channel(pending_data["mod_channel_id"])
                    if mod_channel:
                        try:
                            await mod_channel.fetch_message(pending_data["mod_message_id"])
                            mod_view = PlayerIdChangeApprovalView(self, discord_id, old_player_id, new_player_id, reason, instance_id)
                            self.bot.add_view(mod_view, message_id=pending_data["mod_message_id"])
                            restored_views += 1
                        except discord.NotFound:
                            self.logger.warning(
                                f"Mod notification message {pending_data['mod_message_id']} for pending change (user {discord_id}) not found - buttons won't work but data preserved"
                            )
                        except discord.Forbidden:
                            self.logger.warning(
                                f"Cannot access mod notification message {pending_data['mod_message_id']} for pending change (user {discord_id}) - missing permissions"
                            )
                    else:
                        self.logger.warning(
                            f"Mod notification channel {pending_data['mod_channel_id']} not found for pending change (user {discord_id})"
                        )
                except Exception as e:
                    self.logger.error(f"Error verifying mod notification message for pending change (user {discord_id}): {e}")

        # Log restoration summary
        if pending_changes:
            self.logger.info(
                f"Pending player ID changes: {len(pending_changes)} in data file, {restored_views} view(s) restored to messages. "
                f"Use /pending_id_changes to manage all requests."
            )

    def _create_or_update_player(self, discord_id, author_name, player_id):
        try:
            # Ensure discord_id is a string for consistent comparison
            discord_id_str = str(discord_id)

            # Check if this player_id is already linked to a different Discord account
            existing_player_id = PlayerId.objects.filter(id=player_id).select_related("game_instance__player").first()
            if existing_player_id and existing_player_id.game_instance:
                # Get the KnownPlayer for this tower ID
                existing_player = existing_player_id.game_instance.player
                # Check if this player is already linked to a different ACTIVE Discord account
                existing_linked_account = LinkedAccount.objects.filter(
                    player=existing_player, platform=LinkedAccount.Platform.DISCORD, active=True
                ).first()
                if existing_linked_account and existing_linked_account.account_id != discord_id_str:
                    # Player ID is already linked to a different Discord account
                    return {
                        "error": "already_linked",
                        "existing_discord_id": existing_linked_account.account_id,
                        "existing_player_name": existing_player.name,
                    }

            # Try to find existing player by Discord account (only active accounts)
            linked_account = (
                LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=discord_id_str, active=True)
                .select_related("player")
                .first()
            )

            if linked_account:
                # Existing player verification with new ID
                player = linked_account.player
                created = False

                # If player was unapproved, re-approve them
                if not player.approved:
                    player.approved = True
                    player.save()

                # Get the primary game instance
                primary_instance = player.game_instances.filter(primary=True).first()
                if not primary_instance:
                    # Create a primary instance if somehow missing
                    primary_instance = GameInstance.objects.create(player=player, name="Instance 1", primary=True)

                # Capture old primary player ID before changing it (for cache invalidation)
                old_primary_player_id_obj = PlayerId.objects.filter(game_instance=primary_instance, primary=True).first()
                old_primary_player_id = old_primary_player_id_obj.id if old_primary_player_id_obj else None

                # Set all existing PlayerIds for this instance to non-primary
                PlayerId.objects.filter(game_instance=primary_instance).update(primary=False)

                # Create/update the new PlayerID as primary
                player_id_obj, player_id_created = PlayerId.objects.update_or_create(
                    id=player_id, defaults=dict(game_instance=primary_instance, primary=True)
                )

                # Update role_source_instance to primary instance (ensures roles come from new clean ID)
                # This is especially important if they were previously using a banned ID for roles
                if linked_account.role_source_instance != primary_instance:
                    linked_account.role_source_instance = primary_instance
                    linked_account.save()
            else:
                # New player verification
                player = KnownPlayer.objects.create(name=author_name, approved=True)
                created = True

                # Create primary GameInstance first (needed for role_source_instance)
                primary_instance = GameInstance.objects.create(player=player, name="Instance 1", primary=True)

                # Create LinkedAccount with role_source_instance set to primary instance
                LinkedAccount.objects.create(
                    player=player,
                    platform=LinkedAccount.Platform.DISCORD,
                    account_id=str(discord_id_str),
                    display_name=author_name,
                    verified=True,
                    role_source_instance=primary_instance,
                )

                # Create the PlayerID as primary
                PlayerId.objects.create(id=player_id, game_instance=primary_instance, primary=True)
                old_primary_player_id = None  # New player, no old primary

            # Auto-link any existing orphaned ModerationRecords for this tower_id
            from thetower.backend.sus.models import ModerationRecord

            linked_count = ModerationRecord.objects.filter(tower_id=player_id, game_instance__isnull=True).update(game_instance=primary_instance)
            if linked_count > 0:
                print(f"Auto-linked {linked_count} existing moderation record(s) to new GameInstance for player {player_id}")

            # Return simple values instead of Django model instances to avoid lazy evaluation
            result = {
                "player_id": player.id,
                "player_name": player.name,
                "discord_id": discord_id_str,
                "created": created,
                "primary_player_id": player_id,
                "old_primary_player_id": old_primary_player_id,
            }
            return result
        except Exception as exc:
            raise exc

    def load_pending_links_data(self):
        """Load pending links data - helper for UI components (synchronous wrapper)."""
        # Use a simple file name for pending links data
        file_path = self.data_directory / "pending_links.json"
        # Since this is called from sync context, we need to handle it differently
        # For now, return empty dict with pending_links structure if file doesn't exist
        import json

        if file_path.exists():
            with open(file_path, "r") as f:
                return json.load(f)
        return {"pending_links": {}}

    def save_pending_links_data(self, data):
        """Save pending links data - helper for UI components (synchronous wrapper)."""
        file_path = self.data_directory / "pending_links.json"
        import json

        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)

    def load_pending_player_id_changes_data(self):
        """Load pending player ID changes data."""
        file_path = self.data_directory / "pending_player_id_changes.json"
        import json

        if file_path.exists():
            with open(file_path, "r") as f:
                return json.load(f)
        return {"pending_changes": {}}

    def save_pending_player_id_changes_data(self, data):
        """Save pending player ID changes data."""
        file_path = self.data_directory / "pending_player_id_changes.json"
        import json

        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)

    async def provide_alt_account_info(self, details: dict, requesting_user: discord.User, permission_context) -> list[dict]:
        """Provide alt account information for player lookup embeds.

        Args:
            details: Standardized player details dictionary
            requesting_user: The Discord user requesting the info
            permission_context: Permission context for the requesting user

        Returns:
            List of embed field dictionaries to add to the player embed
        """
        from asgiref.sync import sync_to_async

        try:
            # Get the Discord ID from details
            discord_id_str = details.get("discord_id")
            if not discord_id_str:
                return []

            # Check if user has permission to view retired accounts
            can_view_retired = await self.check_manage_retired_accounts_permission(requesting_user)

            # Get all LinkedAccounts for this player
            def get_all_discord_accounts(discord_id: str, include_retired: bool = False):
                try:
                    linked_account = (
                        LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=discord_id, verified=True, active=True)
                        .select_related("player")
                        .first()
                    )

                    if not linked_account or not linked_account.player:
                        return [], [], []

                    # Get active Discord accounts linked to this player
                    active_accounts = list(
                        LinkedAccount.objects.filter(
                            player=linked_account.player, platform=LinkedAccount.Platform.DISCORD, verified=True, active=True
                        )
                        .exclude(account_id=discord_id)
                        .order_by("verified_at")
                    )

                    # Get retired accounts if user has permission
                    retired_accounts = []
                    if include_retired:
                        retired_accounts = list(
                            LinkedAccount.objects.filter(
                                player=linked_account.player, platform=LinkedAccount.Platform.DISCORD, verified=True, active=False
                            ).order_by("verified_at")
                        )

                    # Get pending outgoing links
                    data = self.load_pending_links_data()
                    pending_links = data.get("pending_links", {})

                    # Find pending links where this Discord ID is the requester
                    pending_outgoing = []
                    for alt_discord_id, link_data in pending_links.items():
                        if link_data.get("requester_id") == discord_id:
                            pending_outgoing.append((alt_discord_id, link_data))

                    return active_accounts, retired_accounts, pending_outgoing
                except Exception as e:
                    self.logger.error(f"Error getting alt accounts for {discord_id}: {e}")
                    return [], [], []

            active_accounts, retired_accounts, pending_outgoing = await sync_to_async(get_all_discord_accounts)(
                discord_id_str, include_retired=can_view_retired
            )

            # Build embed fields
            fields = []

            # Show linked active alt accounts
            if active_accounts:
                account_list = []
                for account in active_accounts:
                    account_list.append(f"<@{account.account_id}>")
                fields.append({"name": "🔗 Linked Alt Accounts", "value": "\n".join(account_list), "inline": False})

            # Show retired accounts to authorized users
            if retired_accounts and can_view_retired:
                retired_list = []
                for account in retired_accounts:
                    retired_list.append(f"🔴 <@{account.account_id}> (Retired)")
                fields.append({"name": "🗃️ Retired Discord Accounts", "value": "\n".join(retired_list), "inline": False})

            # Show pending outgoing link requests - only to authorized users
            if pending_outgoing:
                can_manage = await self.can_manage_alt_links(requesting_user)
                if can_manage:
                    pending_list = []
                    for alt_id, link_data in pending_outgoing:
                        pending_list.append(f"<@{alt_id}> (Pending)")
                    fields.append({"name": "⏳ Pending Link Requests", "value": "\n".join(pending_list), "inline": False})

            return fields

        except Exception as e:
            self.logger.error(f"Error providing alt account info: {e}")
            return []

    async def can_manage_alt_links(self, user: discord.User) -> bool:
        """Check if a user has permission to manage alt links for any user.

        Args:
            user: The Discord user to check

        Returns:
            bool: True if user can manage alt links, False otherwise
        """
        from asgiref.sync import sync_to_async

        approved_groups = self.config.get_global_cog_setting("validation", "approved_manage_alt_links_groups", [])
        if not approved_groups:
            return False

        def get_user_groups():
            try:
                from thetower.backend.sus.models import LinkedAccount

                linked_account = (
                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=str(user.id), active=True)
                    .select_related("player__django_user")
                    .first()
                )
                if not linked_account or not linked_account.player.django_user:
                    return []

                return [group.name for group in linked_account.player.django_user.groups.all()]
            except Exception:
                return []

        user_groups = await sync_to_async(get_user_groups)()
        return any(group in approved_groups for group in user_groups)

    async def check_id_change_moderator_permission(self, user: discord.User) -> bool:
        """Check if a user has permission to moderate player ID change requests.

        Args:
            user: The Discord user to check

        Returns:
            bool: True if user can moderate ID changes, False otherwise
        """
        from asgiref.sync import sync_to_async

        approved_groups = self.config.get_global_cog_setting("validation", "approved_id_change_moderator_groups", [])
        if not approved_groups:
            return False

        def get_user_groups():
            try:
                from thetower.backend.sus.models import LinkedAccount

                linked_account = (
                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=str(user.id), active=True)
                    .select_related("player__django_user")
                    .first()
                )
                if not linked_account or not linked_account.player.django_user:
                    return []

                return [group.name for group in linked_account.player.django_user.groups.all()]
            except Exception:
                return []

        user_groups = await sync_to_async(get_user_groups)()
        return any(group in approved_groups for group in user_groups)

    async def check_manage_retired_accounts_permission(self, user: discord.User) -> bool:
        """Check if a user has permission to view and manage retired Discord accounts.

        Args:
            user: The Discord user to check

        Returns:
            bool: True if user can manage retired accounts, False otherwise
        """
        from asgiref.sync import sync_to_async

        approved_groups = self.config.get_global_cog_setting("validation", "manage_retired_accounts_groups", [])
        if not approved_groups:
            return False

        def get_user_groups():
            try:
                from thetower.backend.sus.models import LinkedAccount

                linked_account = (
                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=str(user.id), active=True)
                    .select_related("player__django_user")
                    .first()
                )
                if not linked_account or not linked_account.player.django_user:
                    return []

                return [group.name for group in linked_account.player.django_user.groups.all()]
            except Exception:
                return []

        user_groups = await sync_to_async(get_user_groups)()
        return any(group in approved_groups for group in user_groups)

    def get_manage_discord_accounts_button_for_player(
        self, details: dict, requesting_user: discord.User, guild_id: int, permission_context
    ) -> Optional[discord.ui.Button]:
        """Get a manage Discord accounts button for a player.

        This method is called by the player_lookup cog to extend /lookup and /profile functionality.
        Returns a button that allows authorized users to manage Discord accounts (mark as active/retired).

        Args:
            details: Player details dictionary
            requesting_user: The Discord user requesting the info
            guild_id: Guild ID where the lookup is being performed
            permission_context: Permission context for the requesting user

        Returns:
            Button if user has manage_retired_accounts permission or is bot owner, None otherwise
        """
        self.logger.info(
            f"get_manage_discord_accounts_button_for_player: user={requesting_user.id}, "
            f"is_bot_owner={permission_context.is_bot_owner}, "
            f"django_groups={permission_context.django_groups}"
        )

        # Bot owner can always see the button
        if permission_context.is_bot_owner:
            self.logger.info("Showing button for bot owner")
            player_id = details.get("player_id")
            if player_id:
                from .ui.core import ManageDiscordAccountsButton

                return ManageDiscordAccountsButton(self, player_id, guild_id)
            return None

        # Check if user has permission to manage retired accounts
        approved_groups = self.config.get_global_cog_setting("validation", "manage_retired_accounts_groups", [])
        self.logger.info(f"manage_retired_accounts_groups configured: {approved_groups}")

        if not approved_groups:
            self.logger.info("No approved groups configured - button hidden")
            return None

        # Check if user is in approved group
        if not permission_context.has_any_group(approved_groups):
            self.logger.info("User not in approved groups - button hidden")
            return None

        self.logger.info("User has permission - showing button")

        # Get player_id from details
        player_id = details.get("player_id")
        if not player_id:
            return None

        # Import button class
        from .ui.core import ManageDiscordAccountsButton

        return ManageDiscordAccountsButton(self, player_id, guild_id)

    async def cancel_pending_link(self, discord_id: str) -> int:
        """Cancel any pending link requests where the given Discord ID is the requester.

        Args:
            discord_id: Discord ID of the user whose pending links should be cancelled

        Returns:
            int: Number of pending links cancelled
        """
        from asgiref.sync import sync_to_async

        def cancel_links():
            data = self.load_pending_links_data()
            pending_links = data.get("pending_links", {})

            # Find and remove any pending links where this user is the requester
            to_remove = [alt_id for alt_id, link_data in pending_links.items() if link_data.get("requester_id") == discord_id]

            for alt_id in to_remove:
                del pending_links[alt_id]

            if to_remove:
                self.save_pending_links_data(data)

            return len(to_remove)

        return await sync_to_async(cancel_links)()

    async def create_player_id_change_request(
        self,
        interaction: discord.Interaction,
        discord_id: str,
        old_player_id: str,
        new_player_id: str,
        reason: str,
        image_filename: str,
        timestamp: datetime.datetime,
        instance_id: int = None,
    ):
        """Create a player ID change request and log it to the verification channel.

        Args:
            interaction: The Discord interaction
            discord_id: Discord ID of the requesting user
            old_player_id: Current player ID
            new_player_id: New player ID
            reason: Reason for change ("game_changed" or "typo")
            image_filename: Filename of the saved verification image
            timestamp: Timestamp of the request
            instance_id: ID of the GameInstance being updated (optional, uses primary if None)
        """
        from asgiref.sync import sync_to_async

        # Log to verification channel with approve/deny buttons
        log_channel_id = self.get_setting("verification_log_channel_id", guild_id=interaction.guild.id)
        if not log_channel_id:
            self.logger.warning(f"No verification log channel configured for guild {interaction.guild.id}")
            return

        log_channel = interaction.guild.get_channel(log_channel_id)
        if not log_channel:
            self.logger.warning(f"Verification log channel {log_channel_id} not found in guild {interaction.guild.id}")
            return

        # Create embed
        reason_display = "Game changed my ID" if reason == "game_changed" else "I typed the wrong ID"
        reason_emoji = "🎮" if reason == "game_changed" else "✏️"

        embed = discord.Embed(title=f"{reason_emoji} Player ID Change Request", color=discord.Color.orange(), timestamp=timestamp)

        embed.add_field(name="Discord User", value=f"{interaction.user.mention}\n`{interaction.user.name}`", inline=True)
        embed.add_field(name="Discord ID", value=f"`{discord_id}`", inline=True)
        embed.add_field(name="Reason", value=reason_display, inline=True)
        embed.add_field(name="Old Player ID", value=f"`{old_player_id}`", inline=True)
        embed.add_field(name="New Player ID", value=f"`{new_player_id}`", inline=True)
        embed.add_field(name="Status", value="⏳ Pending Review", inline=True)

        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        # Attach verification image
        file = None
        if (self.data_directory / image_filename).exists():
            file = discord.File(self.data_directory / image_filename, filename=image_filename)
            embed.set_image(url=f"attachment://{image_filename}")

        # Create view with approve/deny buttons
        from .ui.core import PlayerIdChangeApprovalView

        view = PlayerIdChangeApprovalView(self, discord_id, old_player_id, new_player_id, reason, instance_id)

        # Send to log channel
        log_message = None
        try:
            log_message = await log_channel.send(embed=embed, file=file, view=view)
        except discord.Forbidden:
            self.logger.error(f"Missing permission to send to verification log channel {log_channel_id}")
        except Exception as e:
            self.logger.error(f"Failed to log player ID change request: {e}")

        # Send to mod notification channel if configured
        mod_message = None
        mod_channel_id = self.get_global_setting("mod_notification_channel_id")
        if mod_channel_id:
            try:
                mod_channel = self.bot.get_channel(mod_channel_id)
                if mod_channel:
                    # Create a new file object if we have an image (can't reuse the same file)
                    mod_file = None
                    if (self.data_directory / image_filename).exists():
                        mod_file = discord.File(self.data_directory / image_filename, filename=image_filename)

                    # Create a new view instance for the mod channel
                    mod_view = PlayerIdChangeApprovalView(self, discord_id, old_player_id, new_player_id, reason, instance_id)

                    mod_message = await mod_channel.send(embed=embed.copy(), file=mod_file, view=mod_view)
                else:
                    self.logger.warning(f"Mod notification channel {mod_channel_id} not found")
            except discord.Forbidden:
                self.logger.error(f"Missing permission to send to mod notification channel {mod_channel_id}")
            except Exception as e:
                self.logger.error(f"Failed to send to mod notification channel: {e}")

        # Store pending change with both message IDs
        if log_message:  # Only save if log message was sent successfully

            def save_pending_change():
                data = self.load_pending_player_id_changes_data()
                if "pending_changes" not in data:
                    data["pending_changes"] = {}

                data["pending_changes"][discord_id] = {
                    "old_player_id": old_player_id,
                    "new_player_id": new_player_id,
                    "reason": reason,
                    "image_filename": image_filename,
                    "timestamp": timestamp.isoformat(),
                    "guild_id": interaction.guild.id,
                    "log_message_id": log_message.id,
                    "log_channel_id": log_channel.id,
                    "mod_message_id": mod_message.id if mod_message else None,
                    "mod_channel_id": mod_channel_id if mod_message else None,
                    "instance_id": instance_id,
                }

                self.save_pending_player_id_changes_data(data)

            await sync_to_async(save_pending_change)()

    async def build_verification_status_display(self, discord_id_str: str) -> tuple:
        """Build verification status embed showing complete setup with role assignments.

        Returns:
            Tuple of (embed, verification_info, has_pending_link) or (None, None, False) if not verified
        """
        from asgiref.sync import sync_to_async

        def get_verification_info():
            try:
                from thetower.backend.sus.models import LinkedAccount

                linked_account = (
                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=discord_id_str)
                    .select_related("player", "role_source_instance")
                    .first()
                )

                if not linked_account:
                    return None

                player = linked_account.player

                # Get all Discord LinkedAccounts with their role sources
                from thetower.backend.sus.models import PlayerId

                all_discord_accounts = list(
                    LinkedAccount.objects.filter(player=player, platform=LinkedAccount.Platform.DISCORD)
                    .select_related("role_source_instance")
                    .values(
                        "account_id", "verified", "display_name", "primary", "verified_at", "role_source_instance__id", "role_source_instance__name"
                    )
                )

                # For each account with a role source, get the primary player ID
                for account in all_discord_accounts:
                    if account["role_source_instance__id"]:
                        primary_player_id = PlayerId.objects.filter(game_instance_id=account["role_source_instance__id"], primary=True).first()
                        account["role_source_player_id"] = primary_player_id.id if primary_player_id else None
                    else:
                        account["role_source_player_id"] = None

                # Get all game instances with their tower IDs
                game_instances = []
                for instance in player.game_instances.all():
                    tower_ids = [{"id": pid["id"], "primary": pid["primary"]} for pid in instance.player_ids.values("id", "primary")]
                    game_instances.append({"id": instance.id, "name": instance.name, "primary": instance.primary, "tower_ids": tower_ids})

                return {
                    "status": "verified",
                    "player_id": player.id,
                    "player_name": player.name,
                    "verified": linked_account.verified,
                    "verified_at": linked_account.verified_at,
                    "all_discord_accounts": all_discord_accounts,
                    "game_instances": game_instances,
                }
            except Exception as exc:
                self.logger.error(f"Error getting verification info for {discord_id_str}: {exc}")
                return None

        verification_info = await sync_to_async(get_verification_info)()

        if not verification_info:
            return None, None, False

        # Build embed with comprehensive display
        embed = discord.Embed(
            title="✅ Verification Status", description=f"**Known Player:** {verification_info['player_name']}", color=discord.Color.green()
        )

        # Section 1: Game Instances with Tower IDs
        game_instances = verification_info["game_instances"]
        show_instance_names = len(game_instances) > 1  # Only show instance names if multiple instances

        for instance_info in game_instances:
            primary_marker = " 🌟" if instance_info["primary"] else ""

            if show_instance_names:
                instance_name = f"**{instance_info['name']}**{primary_marker}"
                field_name = f"📋 {instance_name}"
            else:
                # Single instance - just show "Tower IDs" with primary marker if applicable
                field_name = f"📋 Tower IDs{primary_marker}"

            tower_ids_text = []
            for tower_id_data in instance_info["tower_ids"]:
                primary_id_marker = " **(Primary)**" if tower_id_data["primary"] else ""
                tower_ids_text.append(f"• `{tower_id_data['id']}`{primary_id_marker}")

            embed.add_field(name=field_name, value="\n".join(tower_ids_text) if tower_ids_text else "_No Tower IDs_", inline=False)

        # Section 2: Discord Accounts with Role Assignments
        discord_accounts_text = []
        for account in verification_info["all_discord_accounts"]:
            account_id = account["account_id"]
            verified = account["verified"]
            display_name = account["display_name"]
            primary = account["primary"]
            verified_at = account["verified_at"]
            role_instance_id = account["role_source_instance__id"]
            role_instance_name = account["role_source_instance__name"]

            # Build account line
            status_emoji = "✅" if verified else "⏳"
            is_current = " **(You)**" if account_id == discord_id_str else ""
            primary_marker = " 🌟" if primary else ""
            name_str = f" ({display_name})" if display_name else ""

            account_line = f"{status_emoji} <@{account_id}>{name_str}{primary_marker}{is_current}"

            # Add verification timestamp
            if verified and verified_at:
                if hasattr(verified_at, "timestamp"):
                    unix_timestamp = int(verified_at.timestamp())
                    if unix_timestamp == 1577836800:  # Historical placeholder date
                        account_line += " • Verified: _Unknown date_"
                    else:
                        account_line += f" • Verified: <t:{unix_timestamp}:R>"

            # Add role source info
            if role_instance_id:
                role_source_player_id = account.get("role_source_player_id")
                role_value = role_source_player_id if role_source_player_id else role_instance_name
                role_line = f"   └─ Roles: **{role_value}**"
            else:
                role_line = "   └─ Roles: **None**"

            discord_accounts_text.append(f"{account_line}\n{role_line}")

        embed.add_field(
            name="🎮 Discord Accounts", value="\n\n".join(discord_accounts_text) if discord_accounts_text else "_No Discord accounts_", inline=False
        )

        # Check for pending outgoing links
        def check_pending_outgoing_links():
            data = self.load_pending_links_data()
            pending_links = data.get("pending_links", {})
            outgoing = []
            for alt_id, link_data in pending_links.items():
                if link_data.get("requester_id") == discord_id_str:
                    outgoing.append({"alt_discord_id": alt_id, "timestamp": link_data.get("timestamp")})
            return outgoing

        pending_outgoing = await sync_to_async(check_pending_outgoing_links)()

        # Show pending outgoing link requests if any
        if pending_outgoing:
            pending_text = []
            for link in pending_outgoing:
                pending_text.append(f"• <@{link['alt_discord_id']}> (Waiting for approval)")
            embed.add_field(name="⏳ Pending Link Requests", value="\n".join(pending_text), inline=False)

        return embed, verification_info, len(pending_outgoing) > 0

    @staticmethod
    def only_made_of_hex(text: str) -> bool:
        """Check if a string contains only hexadecimal characters."""
        hex_digits = set("0123456789abcdef")
        contents = set(text.strip().lower())
        return contents | hex_digits == hex_digits

    @app_commands.command(name="verify", description="Verify your player ID to gain access to the server")
    @app_commands.guild_only()
    async def verify_slash(self, interaction: discord.Interaction) -> None:
        """Slash command to start the verification process or view verification status."""
        from asgiref.sync import sync_to_async

        # Check if verification is enabled for this guild
        verification_enabled = self.get_setting("verification_enabled", guild_id=interaction.guild.id)
        if not verification_enabled:
            await interaction.response.send_message("❌ Verification is currently disabled. Please contact a server administrator.", ephemeral=True)
            return

        # Check user's current verification status
        discord_id_str = str(interaction.user.id)

        # NOTE: We no longer block verification pre-emptively if user has ANY banned player ID.
        # Instead, we check the specific NEW player ID they submit in the modal.
        # This allows users to verify with a clean player ID even if they have a previously banned ID.

        def get_verification_info():
            """Get comprehensive verification information for this Discord user."""
            try:
                # Check if this Discord account has an active LinkedAccount
                linked_account = (
                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=discord_id_str, active=True)
                    .select_related("player")
                    .first()
                )

                if not linked_account:
                    return {"status": "not_verified"}

                player = linked_account.player

                # Get all LinkedAccounts for this player (to show if verified with alt account)
                all_linked_accounts = list(
                    LinkedAccount.objects.filter(player=player, platform=LinkedAccount.Platform.DISCORD)
                    .select_related("role_source_instance")
                    .values(
                        "account_id", "verified", "display_name", "primary", "verified_at", "role_source_instance__id", "role_source_instance__name"
                    )
                )

                # For each account with a role source, get the primary player ID
                from thetower.backend.sus.models import PlayerId

                for account in all_linked_accounts:
                    if account["role_source_instance__id"]:
                        primary_player_id = PlayerId.objects.filter(game_instance_id=account["role_source_instance__id"], primary=True).first()
                        account["role_source_player_id"] = primary_player_id.id if primary_player_id else None
                    else:
                        account["role_source_player_id"] = None

                # Get all game instances and their tower IDs
                game_instances = []
                for instance in player.game_instances.all():
                    tower_ids = [{"id": pid["id"], "primary": pid["primary"]} for pid in instance.player_ids.values("id", "primary")]
                    game_instances.append({"id": instance.id, "name": instance.name, "primary": instance.primary, "tower_ids": tower_ids})

                return {
                    "status": "verified" if linked_account.verified else "pending",
                    "player_name": player.name,
                    "player_id": player.id,
                    "verified": linked_account.verified,
                    "verified_at": linked_account.verified_at,
                    "all_discord_accounts": all_linked_accounts,
                    "game_instances": game_instances,
                }
            except Exception as exc:
                self.logger.error(f"Error getting verification info for {discord_id_str}: {exc}")
                return {"status": "error", "error": str(exc)}

        verification_info = await sync_to_async(get_verification_info)()

        # If user is already verified, show comprehensive status
        if verification_info["status"] == "verified":
            embed, verification_info, has_pending_link = await self.build_verification_status_display(discord_id_str)

            if embed is None:
                await interaction.response.send_message("❌ Could not load verification status.", ephemeral=True)
                return

            # /verify only shows your own profile, so never admin mode
            view = VerificationStatusView(
                self,
                verification_info,
                discord_id_str,
                has_pending_link=has_pending_link,
                requesting_user=interaction.user,
                can_manage_alt_links=False,
            )
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            return

        # User is not verified - check for pending link requests
        def check_pending_link():
            data = self.load_pending_links_data()
            pending_links = data.get("pending_links", {})
            return pending_links.get(discord_id_str)

        pending_link = await sync_to_async(check_pending_link)()

        if pending_link:
            # User has a pending link request - show option to accept or decline
            from .ui.core import AcceptLinkView

            requester_id = pending_link["requester_id"]
            player_name = pending_link["player_name"]

            view = AcceptLinkView(self, discord_id_str, pending_link)
            await interaction.response.send_message(
                f"📨 **Pending Link Request**\n\n"
                f"<@{requester_id}> has requested to link your Discord account to their player: **{player_name}**\n\n"
                f"If you accept, both Discord accounts will share the same verification and game instances.\n\n"
                f"Choose an option below:",
                view=view,
                ephemeral=True,
            )
            return

        # Check if user has verified role but no LinkedAccount (shouldn't happen, but handle it)
        verified_role_id = self.get_setting("verified_role_id", guild_id=interaction.guild.id)
        if verified_role_id:
            member = interaction.user
            role = interaction.guild.get_role(verified_role_id)
            if role and role in member.roles:
                await interaction.response.send_message(
                    "⚠️ You have the verified role but no linked account. Please contact a moderator.", ephemeral=True
                )
                return

        # Open the verification modal
        modal = VerificationModal(self)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="pending_id_changes", description="View and manage pending player ID change requests")
    @app_commands.guild_only()
    async def pending_id_changes(self, interaction: discord.Interaction) -> None:
        """View all pending player ID change requests with moderation actions."""
        # Check if user has permission (bot owner or approved Django group)
        is_bot_owner = await self.bot.is_owner(interaction.user)
        is_approved_moderator = await self.check_id_change_moderator_permission(interaction.user)

        if not (is_bot_owner or is_approved_moderator):
            await interaction.response.send_message("❌ You need to be in an approved moderator group to use this command.", ephemeral=True)
            return

        from .ui.core import PendingIdChangesListView

        # Load pending changes
        data = self.load_pending_player_id_changes_data()
        pending_changes = data.get("pending_changes", {})

        if not pending_changes:
            await interaction.response.send_message("✅ No pending player ID change requests.", ephemeral=True)
            return

        view = PendingIdChangesListView(self, pending_changes)
        embed = view.create_list_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="check", description="Bot owner: list banned users in this server")
    @app_commands.guild_only()
    async def check_banned(self, interaction: discord.Interaction) -> None:
        """Bot-owner command to list guild members with active bans."""
        from asgiref.sync import sync_to_async

        # Owner-only guard
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to run this command.", ephemeral=True)
            return

        await interaction.response.defer()

        guild = interaction.guild

        def fetch_banned():
            from thetower.backend.sus.models import ModerationRecord
            from thetower.backend.tourney_results.models import TourneyRow

            ban_ids = ModerationRecord.get_active_moderation_ids("ban")

            banned_records = []
            # Get all players with Discord LinkedAccounts
            linked_accounts = (
                LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, verified=True)
                .select_related("player")
                .prefetch_related("player__game_instances__player_ids")
            )

            for linked_account in linked_accounts:
                player = linked_account.player
                primary_instance = player.game_instances.filter(primary=True).first()
                if not primary_instance:
                    continue

                player_ids = list(primary_instance.player_ids.all())
                if not player_ids:
                    continue

                # Check for active ban via any of the player's tower IDs
                if not any(pid.id in ban_ids for pid in player_ids):
                    continue

                primary = next((pid for pid in player_ids if pid.primary), player_ids[0])

                latest_row = TourneyRow.objects.filter(player_id=primary.id).select_related("result").order_by("-result__date").first()
                latest_date = latest_row.result.date if latest_row else None

                banned_records.append(
                    {
                        "discord_id": linked_account.account_id,  # Get from LinkedAccount
                        "player_id": primary.id,
                        "player_name": player.name,
                        "latest_tourney_date": latest_date,
                    }
                )

            return banned_records

        banned_records = await sync_to_async(fetch_banned)()

        # Filter to members of this guild
        members = {}
        for record in banned_records:
            member = guild.get_member(int(record["discord_id"])) if record.get("discord_id") else None
            if member:
                members[member.id] = (member, record)

        if not members:
            await interaction.followup.send("No active bans found for members of this server.")
            return

        lines = []
        for member_id, (member, record) in members.items():
            latest = record["latest_tourney_date"].isoformat() if record["latest_tourney_date"] else "N/A"
            lines.append(
                f"{member.mention} ({member})\n"
                f"• Player ID: `{record['player_id']}`\n"
                f"• Player Name: {record['player_name']}\n"
                f"• Last Tourney Date: {latest}"
            )

        # Discord message length safeguard
        content = "\n\n".join(lines)
        if len(content) > 1800:
            # Chunk if very large
            chunks = []
            chunk = []
            length = 0
            for line in lines:
                if length + len(line) + 2 > 1800:
                    chunks.append("\n\n".join(chunk))
                    chunk = []
                    length = 0
                chunk.append(line)
                length += len(line) + 2
            if chunk:
                chunks.append("\n\n".join(chunk))

            for idx, chunk_text in enumerate(chunks, 1):
                await interaction.followup.send(f"**Banned Members (part {idx}/{len(chunks)})**\n{chunk_text}")
        else:
            await interaction.followup.send(f"**Banned Members**\n{content}")

    async def _check_additional_interaction_permissions(self, interaction: discord.Interaction) -> bool:
        """Override additional interaction permissions for slash commands.

        For the validation cog:
        - The /verify command should be usable in any channel where the bot can respond
        - The /pending_id_changes command requires admin permissions but is allowed in any channel
        """
        # Allow /verify command in any channel (no channel restrictions)
        # Allow /pending_id_changes in any channel
        return True

    async def cog_initialize(self) -> None:
        """Initialize the cog - called by BaseCog during ready process."""
        self.logger.info("Initializing Validation module...")

        try:
            async with self.task_tracker.task_context("Initialization") as tracker:
                # Initialize parent
                self.logger.debug("Initializing parent cog")
                tracker.update_status("Loading settings")
                await super().cog_initialize()

                # UI extensions are registered automatically by BaseCog.__init__
                # No need to call register_ui_extensions() here

                # Register info extension for player lookup (alt account info)
                self.logger.debug("Registering player lookup info extension")
                tracker.update_status("Registering info extensions")
                self.bot.cog_manager.register_info_extension(
                    target_cog="player_lookup", source_cog="validation", provider_func=self.provide_alt_account_info
                )

                # Register UI extension for player lookup (manage Discord accounts button)
                self.logger.debug("Registering player lookup UI extension")
                tracker.update_status("Registering UI extensions")
                self.bot.cog_manager.register_ui_extension(
                    target_cog="player_lookup", source_cog="validation", provider_func=self.get_manage_discord_accounts_button_for_player
                )

                # Run startup reconciliation to fix any role issues that occurred while bot was offline
                tracker.update_status("Running startup reconciliation")
                await self._startup_reconciliation()

                # Mark as ready
                self.set_ready(True)
                self.logger.info("Validation initialization complete")

        except Exception as e:
            self._has_errors = True
            self.logger.error(f"Failed to initialize Validation module: {e}", exc_info=True)
            raise

    async def _startup_reconciliation(self) -> None:
        """Reconcile verified roles with KnownPlayers on startup."""
        from asgiref.sync import sync_to_async

        self.logger.info("Running startup verification reconciliation...")

        for guild in self.bot.guilds:
            try:
                verified_role_id = self.get_setting("verified_role_id", guild_id=guild.id)
                if not verified_role_id:
                    continue

                verified_role = guild.get_role(verified_role_id)
                if not verified_role:
                    continue

                # Get all KnownPlayers with verified Discord LinkedAccounts and approved=True
                def get_known_players():
                    # Get all LinkedAccounts with Discord platform and verified=True
                    linked_accounts = (
                        LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, verified=True, player__approved=True)
                        .select_related("player")
                        .distinct()
                    )
                    return list(linked_accounts)

                linked_accounts = await sync_to_async(get_known_players)()

                roles_added = 0
                roles_removed = 0

                # Check each linked account
                for linked_account in linked_accounts:
                    try:
                        discord_id = int(linked_account.account_id)
                        member = guild.get_member(discord_id)

                        if member:
                            # Member is in guild - should have verified role if not banned
                            if not await self._has_active_ban(str(discord_id)):
                                if verified_role not in member.roles:
                                    await self._add_verified_role(member, verified_role, "startup reconciliation")
                                    roles_added += 1
                    except (ValueError, TypeError):
                        continue

                # Check members with verified role who shouldn't have it
                for member in guild.members:
                    if verified_role in member.roles:
                        discord_id_str = str(member.id)

                        async def get_startup_verification_status():
                            try:
                                linked_account = await sync_to_async(
                                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=discord_id_str, active=True)
                                    .select_related("player")
                                    .first
                                )()

                                if not linked_account:
                                    return {"should_have_role": False, "reason": "not verified"}

                                player = linked_account.player
                                if not player.approved:
                                    return {"should_have_role": False, "reason": "not approved"}

                                if await self._has_active_ban(discord_id_str):
                                    return {"should_have_role": False, "reason": "active ban moderation"}

                                return {"should_have_role": True, "reason": None}
                            except Exception:
                                return {"should_have_role": False, "reason": "not verified"}

                        status = await get_startup_verification_status()
                        if not status["should_have_role"]:
                            reason = f"startup reconciliation - {status['reason']}"
                            await self._remove_verified_role(member, verified_role, reason)
                            roles_removed += 1

                if roles_added > 0 or roles_removed > 0:
                    self.logger.info(f"Startup reconciliation for {guild.name}: Added {roles_added} roles, removed {roles_removed} roles")

            except Exception as exc:
                self.logger.error(f"Error in startup reconciliation for guild {guild.id}: {exc}", exc_info=True)

    async def _add_verified_role(self, member: discord.Member, role: discord.Role, reason: str) -> bool:
        """Add verified role to a member and log it.

        Args:
            member: The member to add the role to
            role: The verified role
            reason: Reason for adding the role

        Returns:
            True if successful, False otherwise
        """
        from asgiref.sync import sync_to_async

        try:
            # Do not add role if member has an active ban
            if await self._has_active_ban(str(member.id)):
                self.logger.info(f"Skipping verified role for {member} ({member.id}) due to active ban")
                return False

            # Track this as a bot action to prevent feedback loop
            self._bot_role_changes.add((member.id, member.guild.id))

            await member.add_roles(role, reason=f"Verification: {reason}")

            # Get player ID for detailed logging
            discord_id_str = str(member.id)

            def get_player_id():
                try:
                    linked_account = (
                        LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=discord_id_str, active=True)
                        .select_related("player")
                        .first()
                    )
                    if not linked_account:
                        return None

                    player = linked_account.player
                    primary_instance = player.game_instances.filter(primary=True).first()
                    if not primary_instance:
                        return None

                    # First try to get primary ID
                    primary_id = primary_instance.player_ids.filter(primary=True).first()
                    if primary_id:
                        return primary_id.id

                    # If no primary ID, just pick any available ID
                    any_id = primary_instance.player_ids.first()
                    return any_id.id if any_id else None
                except Exception:
                    return None

            player_id = await sync_to_async(get_player_id)()

            # Log detailed verification event
            await self._log_detailed_verification(member.guild.id, member, player_id=player_id, reason=reason, success=True)

            # Dispatch custom event for member verification
            self.bot.dispatch("member_verified", member, player_id, reason)

            self.logger.info(f"Added verified role to {member} ({member.id}) in {member.guild.name}: {reason}")
            return True

        except Exception as exc:
            self.logger.error(f"Error adding verified role to {member} ({member.id}): {exc}")
            return False
        finally:
            # Remove from tracking set after a short delay to allow event to fire
            await asyncio.sleep(1)
            self._bot_role_changes.discard((member.id, member.guild.id))

    async def _has_active_ban(self, discord_id_str: str) -> bool:
        """Check if a Discord user has any active ban moderation records."""

        from asgiref.sync import sync_to_async

        def check_ban():
            try:
                from thetower.backend.sus.models import ModerationRecord

                linked_account = (
                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=discord_id_str).select_related("player").first()
                )
                if not linked_account:
                    return False

                player = linked_account.player
                ban_ids = ModerationRecord.get_active_moderation_ids("ban")

                # Get all tower IDs across all game instances
                player_tower_ids = [pid.id for instance in player.game_instances.all() for pid in instance.player_ids.all()]
                return any(pid in ban_ids for pid in player_tower_ids)
            except Exception as exc:  # defensive logging; do not fail hard
                self.logger.error(f"Error checking active ban for {discord_id_str}: {exc}")
                return False

        return await sync_to_async(check_ban)()

    async def _remove_verified_role(self, member: discord.Member, role: discord.Role, reason: str) -> bool:
        """Remove verified role from a member and log it.

        Args:
            member: The member to remove the role from
            role: The verified role
            reason: Reason for removing the role

        Returns:
            True if successful, False otherwise
        """
        from asgiref.sync import sync_to_async

        try:
            # Track this as a bot action to prevent feedback loop
            self._bot_role_changes.add((member.id, member.guild.id))

            await member.remove_roles(role, reason=f"Verification: {reason}")

            # Get player ID for detailed logging
            discord_id_str = str(member.id)

            def get_player_id():
                try:
                    linked_account = (
                        LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=discord_id_str, active=True)
                        .select_related("player")
                        .first()
                    )
                    if not linked_account:
                        return None

                    player = linked_account.player
                    primary_instance = player.game_instances.filter(primary=True).first()
                    if not primary_instance:
                        return None

                    # First try to get primary ID
                    primary_id = primary_instance.player_ids.filter(primary=True).first()
                    if primary_id:
                        return primary_id.id

                    # If no primary ID, just pick any available ID
                    any_id = primary_instance.player_ids.first()
                    return any_id.id if any_id else None
                except Exception:
                    return None

            player_id = await sync_to_async(get_player_id)()

            # Determine if this is a moderation-related removal or a verification failure
            is_moderation_removal = "moderation" in reason.lower() or "ban" in reason.lower()

            # Log detailed verification event (success=False for failures, but moderation removals use different logging)
            if is_moderation_removal:
                # For moderation removals, log in the same structured format as verification logs
                log_channel_id = self.get_setting("verification_log_channel_id", guild_id=member.guild.id)
                if log_channel_id:
                    log_channel = member.guild.get_channel(log_channel_id)
                    if log_channel:
                        embed = discord.Embed(
                            title="🔨 Role Removed (Moderation)",
                            color=discord.Color.orange(),
                            timestamp=discord.utils.utcnow(),
                        )

                        embed.add_field(name="Discord User", value=f"{member.mention}\n`{member.name}`", inline=True)
                        embed.add_field(name="Discord ID", value=f"`{member.id}`", inline=True)
                        if player_id:
                            embed.add_field(name="Player ID", value=f"`{player_id}`", inline=True)

                        embed.add_field(name="Role Removed", value=role.mention, inline=True)
                        if reason:
                            embed.add_field(name="Reason", value=reason, inline=False)

                        embed.set_thumbnail(url=member.display_avatar.url)

                        try:
                            await log_channel.send(embed=embed)
                        except Exception as log_exc:
                            self.logger.error(f"Failed to log moderation role removal to channel {log_channel_id}: {log_exc}")
            else:
                # For actual verification failures/removals, log as unsuccessful verification
                await self._log_detailed_verification(member.guild.id, member, player_id=player_id, reason=reason, success=False)

            # Dispatch custom event for member unverification
            self.bot.dispatch("member_unverified", member, player_id, reason)

            self.logger.info(f"Removed verified role from {member} ({member.id}) in {member.guild.name}: {reason}")
            return True

        except Exception as exc:
            self.logger.error(f"Error removing verified role from {member} ({member.id}): {exc}")
            return False
        finally:
            # Remove from tracking set after a short delay to allow event to fire
            await asyncio.sleep(1)
            self._bot_role_changes.discard((member.id, member.guild.id))

    async def _log_detailed_verification(
        self, guild_id: int, member: discord.Member, player_id: str = None, reason: str = None, image_filename: str = None, success: bool = True
    ) -> None:
        """Log a detailed verification event to the verification log channel.

        Args:
            guild_id: The guild ID
            member: The Discord member
            player_id: The player's ID (optional)
            reason: Reason for verification (optional)
            image_filename: Filename of verification image (optional)
            success: Whether verification was successful
        """
        log_channel_id = self.get_setting("verification_log_channel_id", guild_id=guild_id)
        if not log_channel_id:
            return

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        log_channel = guild.get_channel(log_channel_id)
        if not log_channel:
            return

        # Create embed
        title = "✅ Verification Successful" if success else "❌ Verification Failed"
        color = discord.Color.green() if success else discord.Color.red()
        embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())

        # Add user information fields
        embed.add_field(name="Discord User", value=f"{member.mention}\n`{member.name}`", inline=True)
        embed.add_field(name="Discord ID", value=f"`{member.id}`", inline=True)
        if player_id:
            embed.add_field(name="Player ID", value=f"`{player_id}`", inline=True)

        # Add role assignment info (only for successful verifications)
        if success:
            verified_role_id = self.get_setting("verified_role_id", guild_id=guild_id)
            if verified_role_id:
                role = guild.get_role(verified_role_id)
                if role:
                    embed.add_field(name="Role Assigned", value=role.mention, inline=True)

        # Add reason if provided
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        # Set user avatar
        embed.set_thumbnail(url=member.display_avatar.url)

        # Prepare file attachment if image was provided
        file = None
        if image_filename and (self.data_directory / image_filename).exists():
            file = discord.File(self.data_directory / image_filename, filename=image_filename)
            embed.set_image(url=f"attachment://{image_filename}")

        try:
            if file:
                await log_channel.send(embed=embed, file=file)
            else:
                await log_channel.send(embed=embed)
        except discord.Forbidden as forbidden_exc:
            # Try plain text if embed fails due to permissions
            self.logger.warning(f"Missing embed permission in verification log channel {log_channel_id}: {forbidden_exc}")
            try:
                status = "✅ **Verification Successful**" if success else "❌ **Verification Failed**"
                text_message = f"{status}\n" f"**Discord User:** {member.mention} (`{member.name}`)\n" f"**Discord ID:** `{member.id}`\n"
                if player_id:
                    text_message += f"**Player ID:** `{player_id}`\n"
                if verified_role_id:
                    role = guild.get_role(verified_role_id)
                    if role:
                        text_message += f"**Role Assigned:** {role.mention}\n"
                if reason:
                    text_message += f"**Reason:** {reason}\n"

                # Need to re-create the file object since it was already consumed
                new_file = None
                if file and image_filename and (self.data_directory / image_filename).exists():
                    new_file = discord.File(self.data_directory / image_filename, filename=image_filename)

                if new_file:
                    await log_channel.send(content=text_message, file=new_file)
                else:
                    await log_channel.send(content=text_message)
            except Exception as fallback_exc:
                self.logger.error(f"Failed to send plain text verification log: {fallback_exc}")
        except Exception as log_exc:
            self.logger.error(f"Failed to log verification to channel {log_channel_id}: {log_exc}")

    async def _log_role_change(self, guild_id: int, message: str, color: discord.Color) -> None:
        """Log a role change to the verification log channel.

        Args:
            guild_id: The guild ID
            message: The message to log
            color: The embed color
        """
        log_channel_id = self.get_setting("verification_log_channel_id", guild_id=guild_id)
        if not log_channel_id:
            return

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        log_channel = guild.get_channel(log_channel_id)
        if not log_channel:
            return

        try:
            embed = discord.Embed(description=message, color=color, timestamp=discord.utils.utcnow())
            await log_channel.send(embed=embed)
        except Exception as exc:
            self.logger.error(f"Error logging to verification channel {log_channel_id}: {exc}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Handle member joins - auto-verify known players."""
        from asgiref.sync import sync_to_async

        try:
            verified_role_id = self.get_setting("verified_role_id", guild_id=member.guild.id)
            if not verified_role_id:
                return

            verified_role = member.guild.get_role(verified_role_id)
            if not verified_role:
                return

            # Check if this member should have verified role
            discord_id_str = str(member.id)

            def should_have_verified_role():
                try:
                    linked_account = (
                        LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=discord_id_str, active=True)
                        .select_related("player")
                        .first()
                    )
                    if not linked_account:
                        return False

                    player = linked_account.player
                    if not player.approved:
                        return False

                    # Check for active ban records - banned players don't get verified role
                    from thetower.backend.sus.models import ModerationRecord

                    ban_ids = ModerationRecord.get_active_moderation_ids("ban")
                    # Get all tower IDs across all game instances
                    player_tower_ids = [pid.id for instance in player.game_instances.all() for pid in instance.player_ids.all()]
                    return not any(pid in ban_ids for pid in player_tower_ids)
                except Exception:
                    return False

            if await sync_to_async(should_have_verified_role)():
                # Known player with primary ID rejoining - add verified role
                await self._add_verified_role(member, verified_role, "known player rejoined server")

        except Exception as exc:
            self.logger.error(f"Error in on_member_join for {member} ({member.id}): {exc}", exc_info=True)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Handle member updates - monitor verified role changes."""
        from asgiref.sync import sync_to_async

        try:
            verified_role_id = self.get_setting("verified_role_id", guild_id=after.guild.id)
            if not verified_role_id:
                return

            verified_role = after.guild.get_role(verified_role_id)
            if not verified_role:
                return

            # Check if verified role changed
            had_role = verified_role in before.roles
            has_role = verified_role in after.roles

            if had_role == has_role:
                return  # No change in verified role

            # Check if this was a bot-initiated change
            if (after.id, after.guild.id) in self._bot_role_changes:
                return  # This was our own change, ignore it

            # Role was changed externally - need to correct it
            discord_id_str = str(after.id)

            def get_verification_status():
                try:
                    linked_account = (
                        LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=discord_id_str, active=True)
                        .select_related("player")
                        .first()
                    )
                    if not linked_account:
                        return {"should_have_role": False, "reason": "not verified"}

                    player = linked_account.player

                    # Check if approved
                    if not player.approved:
                        return {"should_have_role": False, "reason": "not approved"}

                    # Check for active ban records
                    from thetower.backend.sus.models import ModerationRecord

                    ban_ids = ModerationRecord.get_active_moderation_ids("ban")
                    # Get all tower IDs across all game instances
                    player_tower_ids = [pid.id for instance in player.game_instances.all() for pid in instance.player_ids.all()]
                    if any(pid in ban_ids for pid in player_tower_ids):
                        return {"should_have_role": False, "reason": "active ban"}

                    return {"should_have_role": True, "reason": None}
                except Exception:
                    return {"should_have_role": False, "reason": "not verified"}

            status = await sync_to_async(get_verification_status)()

            if has_role and not status["should_have_role"]:
                # Role was added but user shouldn't have it - remove it
                reason = f"role added externally without verification, correcting ({status['reason']})"
                await self._remove_verified_role(after, verified_role, reason)

            elif not has_role and status["should_have_role"]:
                # Role was removed but user should have it - add it back
                await self._add_verified_role(after, verified_role, "role removed externally, correcting")

            elif has_role and status["should_have_role"]:
                # Role was added correctly by external source - log confirmation
                self.logger.info(f"Verified role added externally to {after.name} ({after.id}) - confirmed accurate")

                # Get player ID for detailed logging
                def get_player_id():
                    try:
                        from thetower.backend.sus.models import LinkedAccount

                        linked_account = (
                            LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=discord_id_str, active=True)
                            .select_related("player")
                            .first()
                        )
                        if not linked_account:
                            return None

                        player = linked_account.player
                        # Get primary game instance's primary ID
                        primary_instance = player.game_instances.filter(primary=True).first()
                        if primary_instance:
                            primary_id = primary_instance.player_ids.filter(primary=True).first()
                            if primary_id:
                                return primary_id.id
                        # Fallback to any ID from any game instance
                        any_instance = player.game_instances.first()
                        if any_instance:
                            any_id = any_instance.player_ids.first()
                            return any_id.id if any_id else None
                        return None
                    except Exception:
                        return None

                player_id = await sync_to_async(get_player_id)()

                # Log the accurate external addition
                await self._log_detailed_verification(
                    after.guild.id,
                    after,
                    player_id=player_id,
                    reason="role added externally, confirmed accurate",
                    success=True,
                )

        except Exception as exc:
            self.logger.error(f"Error in on_member_update for {after} ({after.id}): {exc}", exc_info=True)

    async def cog_unload(self) -> None:
        """Clean up when unloading."""
        # Call parent's cog_unload to ensure UI extensions are cleaned up
        await super().cog_unload()

    async def remove_verified_role_from_user(self, discord_id: int, guild_id: int, reason: str = "player un-verified") -> bool:
        """Remove the verified role from a Discord user.

        Args:
            discord_id: Discord ID of the user
            guild_id: Guild ID where to remove the role
            reason: Reason for role removal (default: "player un-verified")

        Returns:
            bool: True if role was removed, "not_needed" if user didn't have role, False on error
        """
        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                self.logger.info(f"Guild {guild_id} not found")
                return False

            # Try to get member from cache first, then fetch from API
            member = guild.get_member(discord_id)
            if not member:
                try:
                    member = await guild.fetch_member(discord_id)
                    self.logger.info(f"Fetched member {discord_id} from API")
                except discord.NotFound:
                    self.logger.info(f"Member {discord_id} not found in guild {guild_id}")
                    return False
                except Exception as fetch_exc:
                    self.logger.error(f"Error fetching member {discord_id}: {fetch_exc}")
                    return False

            verified_role_id = self.get_setting("verified_role_id", guild_id=guild_id)
            if not verified_role_id:
                self.logger.info(f"No verified role configured for guild {guild_id}")
                return False

            role = guild.get_role(verified_role_id)
            if not role:
                self.logger.info(f"Verified role {verified_role_id} not found in guild {guild_id}")
                return False

            if role not in member.roles:
                self.logger.info(f"Member {member.name} does not have verified role {role.name}")
                return "not_needed"  # Special return value: user didn't have the role

            # Use helper method for proper tracking and logging
            success = await self._remove_verified_role(member, role, reason)
            return success

        except Exception as exc:
            logger.error(f"Error removing verified role from user {discord_id}: {exc}")
            return False

    @commands.Cog.listener()
    async def on_member_moderated(self, tower_id: str, moderation_type: str, record, requesting_user: discord.User, updated: bool = False):
        """Handle member moderation - remove verified role immediately for bans."""
        try:
            # Only handle bans for now - other moderation types don't affect verification
            if moderation_type != "ban":
                return

            self.logger.info(f"Member banned via moderation: tower_id {tower_id} - checking for verified role removal")

            # Find the Discord user for this Tower ID
            from thetower.backend.sus.models import PlayerId

            def get_discord_id():
                try:
                    # Find the PlayerId for this tower_id
                    player_id_obj = PlayerId.objects.filter(id=tower_id).select_related("game_instance__player").first()
                    if player_id_obj and player_id_obj.game_instance:
                        # Get the primary Discord account from LinkedAccount
                        from thetower.backend.sus.models import LinkedAccount

                        linked_account = LinkedAccount.objects.filter(
                            player=player_id_obj.game_instance.player, platform=LinkedAccount.Platform.DISCORD, primary=True
                        ).first()
                        if linked_account:
                            return linked_account.account_id
                except Exception as e:
                    self.logger.error(f"Error looking up Discord ID for tower_id {tower_id}: {e}")
                return None

            discord_id = await sync_to_async(get_discord_id)()
            if not discord_id:
                self.logger.info(f"No Discord ID found for tower_id {tower_id} - skipping verified role removal")
                return

            # Remove verified role from all guilds the bot is in
            for guild in self.bot.guilds:
                try:
                    success = await self.remove_verified_role_from_user(int(discord_id), guild.id)
                    if success:
                        self.logger.info(f"Removed verified role from user {discord_id} in guild {guild.name} due to ban")
                except Exception as e:
                    self.logger.error(f"Error removing verified role from user {discord_id} in guild {guild.name}: {e}")

        except Exception as e:
            self.logger.error(f"Error handling member moderation event: {e}")
