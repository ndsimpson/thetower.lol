import logging

import discord
from discord import app_commands
from discord.ext import commands

from thetower.backend.sus.models import KnownPlayer, PlayerId
from thetower.bot.basecog import BaseCog

from .ui import ValidationSettingsView, VerificationModal

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
        }

        # Guild-specific settings
        self.guild_settings = {
            "verified_role_id": None,  # Role ID for verified users
            "verification_log_channel_id": None,  # Channel ID for logging verifications
            "verification_enabled": True,  # Whether verification is enabled for this guild
        }

    def _create_or_update_player(self, discord_id, author_name, player_id):
        try:
            player, created = KnownPlayer.objects.get_or_create(discord_id=discord_id, defaults=dict(approved=True, name=author_name))

            # First, set all existing PlayerIds for this player to non-primary
            PlayerId.objects.filter(player_id=player.id).update(primary=False)

            # Then create/update the new PlayerID as primary
            player_id_obj, player_id_created = PlayerId.objects.update_or_create(id=player_id, player_id=player.id, defaults=dict(primary=True))

            # Return simple values instead of Django model instances to avoid lazy evaluation
            return {"player_id": player.id, "player_name": player.name, "discord_id": player.discord_id, "created": created}
        except Exception as exc:
            raise exc

    @staticmethod
    def only_made_of_hex(text: str) -> bool:
        """Check if a string contains only hexadecimal characters."""
        hex_digits = set("0123456789abcdef")
        contents = set(text.strip().lower())
        return contents | hex_digits == hex_digits

    @app_commands.command(name="verify", description="Verify your player ID to gain access to the server")
    @app_commands.guild_only()
    async def verify_slash(self, interaction: discord.Interaction) -> None:
        """Slash command to start the verification process."""
        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import KnownPlayer, PlayerId

        # Check if verification is enabled for this guild
        verification_enabled = self.get_setting("verification_enabled", guild_id=interaction.guild.id)
        if not verification_enabled:
            await interaction.response.send_message("❌ Verification is currently disabled. Please contact a server administrator.", ephemeral=True)
            return

        # Check if user is already verified
        verified_role_id = self.get_setting("verified_role_id", guild_id=interaction.guild.id)
        if verified_role_id:
            member = interaction.user
            role = interaction.guild.get_role(verified_role_id)
            if role and role in member.roles:
                # Check if they have a registered primary ID
                try:
                    discord_id_str = str(interaction.user.id)

                    def get_primary_id():
                        try:
                            player = KnownPlayer.objects.get(discord_id=discord_id_str)
                            primary_id = PlayerId.objects.filter(player=player, primary=True).first()
                            return primary_id.id if primary_id else None
                        except KnownPlayer.DoesNotExist:
                            return None

                    primary_id = await sync_to_async(get_primary_id)()

                    if primary_id:
                        await interaction.response.send_message(
                            f"✅ You are already verified!\n" f"Your registered player ID is: `{primary_id}`", ephemeral=True
                        )
                    else:
                        await interaction.response.send_message("✅ You are already verified!", ephemeral=True)
                except Exception as exc:
                    self.logger.error(f"Error checking primary ID for {interaction.user.id}: {exc}")
                    await interaction.response.send_message("✅ You are already verified!", ephemeral=True)
                return

        # Open the verification modal
        modal = VerificationModal(self)
        await interaction.response.send_modal(modal)

    async def _check_additional_interaction_permissions(self, interaction: discord.Interaction) -> bool:
        """Override additional interaction permissions for slash commands.

        For the validation cog:
        - The /verify command should be usable in any channel where the bot can respond
        """
        # Allow /verify command in any channel (no channel restrictions)
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

        from thetower.backend.sus.models import KnownPlayer, PlayerId

        self.logger.info("Running startup verification reconciliation...")

        for guild in self.bot.guilds:
            try:
                verified_role_id = self.get_setting("verified_role_id", guild_id=guild.id)
                if not verified_role_id:
                    continue

                verified_role = guild.get_role(verified_role_id)
                if not verified_role:
                    continue

                # Get all KnownPlayers with discord_id and at least one primary PlayerId
                def get_known_players():
                    return list(KnownPlayer.objects.filter(discord_id__isnull=False).exclude(discord_id="").filter(playerid__primary=True).distinct())

                known_players = await sync_to_async(get_known_players)()

                roles_added = 0
                roles_removed = 0

                # Check each known player
                for player in known_players:
                    try:
                        discord_id = int(player.discord_id)
                        member = guild.get_member(discord_id)

                        if member:
                            # Member is in guild - should have verified role
                            if verified_role not in member.roles:
                                await self._add_verified_role(member, verified_role, "startup reconciliation")
                                roles_added += 1
                    except (ValueError, TypeError):
                        continue

                # Check members with verified role who shouldn't have it
                for member in guild.members:
                    if verified_role in member.roles:
                        discord_id_str = str(member.id)

                        def should_have_role():
                            try:
                                player = KnownPlayer.objects.get(discord_id=discord_id_str)
                                return PlayerId.objects.filter(player=player, primary=True).exists()
                            except KnownPlayer.DoesNotExist:
                                return False

                        if not await sync_to_async(should_have_role)():
                            await self._remove_verified_role(member, verified_role, "startup reconciliation - no primary PlayerId")
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
        try:
            # Track this as a bot action to prevent feedback loop
            self._bot_role_changes.add((member.id, member.guild.id))

            await member.add_roles(role, reason=f"Verification: {reason}")

            # Log to verification channel
            await self._log_role_change(
                member.guild.id, f"✅ {member.mention} has been verified ({reason}), applying {role.mention}", discord.Color.green()
            )

            self.logger.info(f"Added verified role to {member} ({member.id}) in {member.guild.name}: {reason}")
            return True

        except Exception as exc:
            self.logger.error(f"Error adding verified role to {member} ({member.id}): {exc}")
            return False
        finally:
            # Remove from tracking set after a short delay to allow event to fire
            import asyncio

            await asyncio.sleep(1)
            self._bot_role_changes.discard((member.id, member.guild.id))

    async def _remove_verified_role(self, member: discord.Member, role: discord.Role, reason: str) -> bool:
        """Remove verified role from a member and log it.

        Args:
            member: The member to remove the role from
            role: The verified role
            reason: Reason for removing the role

        Returns:
            True if successful, False otherwise
        """
        try:
            # Track this as a bot action to prevent feedback loop
            self._bot_role_changes.add((member.id, member.guild.id))

            await member.remove_roles(role, reason=f"Verification: {reason}")

            # Log to verification channel
            await self._log_role_change(member.guild.id, f"⚠️ {role.mention} was removed from {member.mention} ({reason})", discord.Color.orange())

            self.logger.info(f"Removed verified role from {member} ({member.id}) in {member.guild.name}: {reason}")
            return True

        except Exception as exc:
            self.logger.error(f"Error removing verified role from {member} ({member.id}): {exc}")
            return False
        finally:
            # Remove from tracking set after a short delay to allow event to fire
            import asyncio

            await asyncio.sleep(1)
            self._bot_role_changes.discard((member.id, member.guild.id))

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

            # Check if this member is a known player
            discord_id_str = str(member.id)

            def has_known_player():
                return KnownPlayer.objects.filter(discord_id=discord_id_str).exists()

            if await sync_to_async(has_known_player)():
                # Known player rejoining - add verified role
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

            def has_known_player():
                return KnownPlayer.objects.filter(discord_id=discord_id_str).exists()

            is_known_player = await sync_to_async(has_known_player)()

            if has_role and not is_known_player:
                # Role was added but user is not a known player - remove it
                await self._remove_verified_role(after, verified_role, "role added externally without verification, correcting")

            elif not has_role and is_known_player:
                # Role was removed but user is a known player - add it back
                await self._add_verified_role(after, verified_role, "role removed externally, correcting")

        except Exception as exc:
            self.logger.error(f"Error in on_member_update for {after} ({after.id}): {exc}", exc_info=True)

    def register_ui_extensions(self) -> None:
        """Register UI extensions for other cogs."""
        self.bot.cog_manager.register_ui_extension(
            "player_lookup",
            "Validation",
            self.provide_unverify_button,
        )

    def provide_unverify_button(self, player, requesting_user, guild_id, permission_context):
        """UI extension provider for un-verify button in player profiles.

        Args:
            player: The KnownPlayer instance
            requesting_user: The Discord user requesting the profile
            guild_id: The guild ID where the request is made
            permission_context: Permission context for the requesting user

        Returns:
            UnverifyButton if user has permission, None otherwise
        """
        # Don't allow users to un-verify themselves
        if player.discord_id and str(player.discord_id) == str(requesting_user.id):
            return None

        # Check if the requesting user has permission to un-verify
        # Get approved groups from settings
        approved_groups = self.config.get_global_cog_setting("validation", "approved_unverify_groups", [])

        if not approved_groups:
            return None  # No groups configured for un-verification

        # Check if user has any of the approved groups
        if permission_context.has_any_group(approved_groups):
            from .ui.core import UnverifyButton

            return UnverifyButton(self, player, requesting_user, guild_id)

        return None

    async def cog_unload(self) -> None:
        """Clean up when unloading."""
        # Call parent's cog_unload to ensure UI extensions are cleaned up
        await super().cog_unload()

    def _unverify_player(self, discord_id, requesting_user):
        """Un-verify a player by marking all their PlayerIds as non-primary.

        Args:
            discord_id: Discord ID of the player to un-verify
            requesting_user: Django user requesting the un-verification

        Returns:
            dict: Result with success status and message
        """
        try:
            # Check if requesting user is in approved groups
            approved_groups = self.config.get_global_cog_setting(
                "validation", "approved_unverify_groups", self.global_settings["approved_unverify_groups"]
            )
            user_groups = [group.name for group in requesting_user.groups.all()]

            if not any(group in approved_groups for group in user_groups):
                return {"success": False, "message": "You don't have permission to un-verify players."}

            # Get the player
            try:
                player = KnownPlayer.objects.get(discord_id=discord_id)
            except KnownPlayer.DoesNotExist:
                return {"success": False, "message": f"No verified player found with Discord ID {discord_id}."}

            # Mark all PlayerIds as non-primary
            updated_count = PlayerId.objects.filter(player_id=player.id).update(primary=False)

            return {
                "success": True,
                "message": f"Successfully un-verified player {player.name} (Discord ID: {discord_id}). {updated_count} player IDs marked as non-primary.",
                "player_id": player.id,
                "player_name": player.name,
                "discord_id": discord_id,
            }

        except Exception as exc:
            logger.error(f"Error un-verifying player {discord_id}: {exc}")
            return {"success": False, "message": f"Error un-verifying player: {exc}"}

    async def remove_verified_role_from_user(self, discord_id: int, guild_id: int) -> bool:
        """Remove the verified role from a Discord user.

        Args:
            discord_id: Discord ID of the user
            guild_id: Guild ID where to remove the role

        Returns:
            bool: True if role was removed, False otherwise
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

            self.logger.info(f"Removing verified role {role.name} from {member.name}")
            await member.remove_roles(role)
            self.logger.info(f"Successfully removed verified role {role.name} from {member.name}")
            return True

        except Exception as exc:
            logger.error(f"Error removing verified role from user {discord_id}: {exc}")
            return False

    async def unverify_player_complete(self, discord_id: int, requesting_user, guild_ids: list = None) -> dict:
        """Complete un-verification process: update database and remove roles.

        Args:
            discord_id: Discord ID of the player to un-verify
            requesting_user: Django user requesting the un-verification
            guild_ids: List of guild IDs to remove roles from (if None, tries all guilds)

        Returns:
            dict: Result with success status, message, and role removal results
        """
        from asgiref.sync import sync_to_async

        # First, un-verify in database (wrap sync method in sync_to_async)
        db_result = await sync_to_async(self._unverify_player)(discord_id, requesting_user)
        if not db_result["success"]:
            return db_result

        # If no specific guilds provided, get all guilds the bot is in
        if guild_ids is None:
            guild_ids = [guild.id for guild in self.bot.guilds]

        # Remove verified role from each guild
        role_removal_results = []
        for guild_id in guild_ids:
            role_removed = await self.remove_verified_role_from_user(discord_id, guild_id)
            role_removal_results.append({"guild_id": guild_id, "role_removed": role_removed})

        # Log the un-verification if log channel is configured
        await self._log_unverification(discord_id, requesting_user, role_removal_results)

        return {
            "success": True,
            "message": db_result["message"],
            "role_removal_results": role_removal_results,
            "player_id": db_result.get("player_id"),
            "player_name": db_result.get("player_name"),
        }

    async def _log_unverification(self, discord_id: int, requesting_user, role_removal_results: list):
        """Log an un-verification event to the configured log channel."""
        # This would log to verification log channels across guilds
        # For now, we'll log to the first configured channel we find
        for guild in self.bot.guilds:
            log_channel_id = self.get_setting("verification_log_channel_id", guild_id=guild.id)
            if log_channel_id:
                log_channel = guild.get_channel(log_channel_id)
                if log_channel:
                    embed = discord.Embed(
                        title="🚫 Player Un-verified",
                        description=f"Player <@{discord_id}> (Discord ID `{discord_id}`) has been un-verified.",
                        color=discord.Color.red(),
                        timestamp=discord.utils.utcnow(),
                    )

                    embed.add_field(name="Requested by", value=f"`{requesting_user.username}`", inline=True)
                    embed.add_field(name="Discord User", value=f"<@{discord_id}>", inline=True)

                    # Show role removal results for this guild
                    guild_result = next((r for r in role_removal_results if r["guild_id"] == guild.id), None)
                    if guild_result:
                        role_removed = guild_result["role_removed"]
                        verified_role_id = self.get_setting("verified_role_id", guild_id=guild.id)
                        if verified_role_id:
                            role = guild.get_role(verified_role_id)
                            if role:
                                if role_removed is True:
                                    status = f"✅ {role.mention}"
                                elif role_removed == "not_needed":
                                    status = f"ℹ️ {role.mention} (already removed)"
                                else:
                                    status = f"❌ {role.mention} (failed to remove)"
                                embed.add_field(name="Role Removed", value=status, inline=True)

                    try:
                        # Check if bot has permission to send messages and embeds
                        permissions = log_channel.permissions_for(guild.me)
                        if not permissions.send_messages:
                            logger.warning(f"Missing 'Send Messages' permission in verification log channel {log_channel.name} ({log_channel_id})")
                            continue
                        if not permissions.embed_links:
                            logger.warning(f"Missing 'Embed Links' permission in verification log channel {log_channel.name} ({log_channel_id})")
                            # Try to send a text message instead
                            guild_result = next((r for r in role_removal_results if r["guild_id"] == guild.id), None)
                            role_status = "Unknown"
                            if guild_result:
                                role_removed = guild_result["role_removed"]
                                verified_role_id = self.get_setting("verified_role_id", guild_id=guild.id)
                                if verified_role_id:
                                    role = guild.get_role(verified_role_id)
                                    if role:
                                        if role_removed is True:
                                            role_status = f"✅ {role.mention}"
                                        elif role_removed == "not_needed":
                                            role_status = f"ℹ️ {role.mention} (already removed)"
                                        else:
                                            role_status = f"❌ {role.mention} (failed to remove)"

                            text_message = (
                                f"🚫 **Player Un-verified**\n"
                                f"Player <@{discord_id}> (Discord ID `{discord_id}`) has been un-verified.\n"
                                f"Requested by: `{requesting_user.username}`\n"
                                f"Role Removed: {role_status if role else 'Unknown'}"
                            )
                            await log_channel.send(text_message)
                        else:
                            await log_channel.send(embed=embed)
                    except discord.Forbidden as forbidden_exc:
                        logger.error(f"Permission denied when logging to channel {log_channel.name} ({log_channel_id}): {forbidden_exc}")
                        logger.error(f"Bot permissions in channel: send_messages={permissions.send_messages}, embed_links={permissions.embed_links}")
                    except Exception as log_exc:
                        logger.error(f"Failed to log un-verification to channel {log_channel_id}: {log_exc}")

                    # Only log to one channel to avoid spam
                    break
                    break
