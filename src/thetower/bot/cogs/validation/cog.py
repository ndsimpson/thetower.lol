import asyncio
import logging

import discord
from asgiref.sync import sync_to_async
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
            # Ensure discord_id is a string for consistent comparison (KnownPlayer.discord_id is CharField)
            discord_id_str = str(discord_id)

            # Check if this player_id is already linked to a different Discord account
            existing_player_id = PlayerId.objects.filter(id=player_id).select_related("player").first()
            if existing_player_id and existing_player_id.player.discord_id != discord_id_str:
                # Player ID is already linked to a different Discord account
                return {
                    "error": "already_linked",
                    "existing_discord_id": existing_player_id.player.discord_id,
                    "existing_player_name": existing_player_id.player.name,
                }

            player, created = KnownPlayer.objects.get_or_create(discord_id=discord_id_str, defaults=dict(approved=True, name=author_name))

            # If player already exists but was unapproved, re-approve them
            if not created and not player.approved:
                player.approved = True
                player.save()

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

        # Block verification if user has an active ban moderation
        try:
            if await self._has_active_ban(str(interaction.user.id)):
                # Log the blocked attempt to the verification log channel for moderator awareness
                try:
                    await self._log_detailed_verification(
                        interaction.guild.id,
                        interaction.user,
                        player_id=None,
                        reason="Verification blocked due to active ban",
                        success=False,
                    )
                except Exception as log_exc:
                    self.logger.error(f"Failed to log blocked verification attempt for {interaction.user.id}: {log_exc}")

                await interaction.response.send_message(
                    "❌ Verification blocked: you have an active ban on your account. Please contact a moderator.",
                    ephemeral=True,
                )
                return
        except Exception as exc:
            self.logger.error(f"Error checking active ban for {interaction.user.id}: {exc}")
            await interaction.response.send_message(
                "❌ Verification could not proceed due to an internal error. Please contact a moderator.",
                ephemeral=True,
            )
            return

        # Open the verification modal
        modal = VerificationModal(self)
        await interaction.response.send_modal(modal)

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
            players = KnownPlayer.objects.filter(discord_id__isnull=False).exclude(discord_id="").select_related().prefetch_related("ids")

            for player in players:
                player_ids = list(player.ids.all())
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
                        "discord_id": player.discord_id,
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

        from thetower.backend.sus.models import KnownPlayer

        self.logger.info("Running startup verification reconciliation...")

        for guild in self.bot.guilds:
            try:
                verified_role_id = self.get_setting("verified_role_id", guild_id=guild.id)
                if not verified_role_id:
                    continue

                verified_role = guild.get_role(verified_role_id)
                if not verified_role:
                    continue

                # Get all KnownPlayers with discord_id and approved=True
                def get_known_players():
                    return list(KnownPlayer.objects.filter(discord_id__isnull=False).exclude(discord_id="").filter(approved=True).distinct())

                known_players = await sync_to_async(get_known_players)()

                roles_added = 0
                roles_removed = 0

                # Check each known player
                for player in known_players:
                    try:
                        discord_id = int(player.discord_id)
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
                                player = await sync_to_async(KnownPlayer.objects.get)(discord_id=discord_id_str)

                                if not player.approved:
                                    return {"should_have_role": False, "reason": "not approved"}

                                if await self._has_active_ban(discord_id_str):
                                    return {"should_have_role": False, "reason": "active ban moderation"}

                                return {"should_have_role": True, "reason": None}
                            except KnownPlayer.DoesNotExist:
                                return {"should_have_role": False, "reason": "not approved"}

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

        from thetower.backend.sus.models import KnownPlayer, PlayerId

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
                    player = KnownPlayer.objects.get(discord_id=discord_id_str)
                    # First try to get primary ID
                    primary_id = PlayerId.objects.filter(player=player, primary=True).first()
                    if primary_id:
                        return primary_id.id

                    # If no primary ID, just pick any available ID
                    any_id = PlayerId.objects.filter(player=player).first()
                    return any_id.id if any_id else None
                except KnownPlayer.DoesNotExist:
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

                player = KnownPlayer.objects.get(discord_id=discord_id_str)
                ban_ids = ModerationRecord.get_active_moderation_ids("ban")
                player_tower_ids = [pid.id for pid in player.ids.all()]
                return any(pid in ban_ids for pid in player_tower_ids)
            except KnownPlayer.DoesNotExist:
                return False
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

        from thetower.backend.sus.models import KnownPlayer, PlayerId

        try:
            # Track this as a bot action to prevent feedback loop
            self._bot_role_changes.add((member.id, member.guild.id))

            await member.remove_roles(role, reason=f"Verification: {reason}")

            # Get player ID for detailed logging
            discord_id_str = str(member.id)

            def get_player_id():
                try:
                    player = KnownPlayer.objects.get(discord_id=discord_id_str)
                    # First try to get primary ID
                    primary_id = PlayerId.objects.filter(player=player, primary=True).first()
                    if primary_id:
                        return primary_id.id

                    # If no primary ID, just pick any available ID
                    any_id = PlayerId.objects.filter(player=player).first()
                    return any_id.id if any_id else None
                except KnownPlayer.DoesNotExist:
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

        from thetower.backend.sus.models import KnownPlayer

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
                    player = KnownPlayer.objects.get(discord_id=discord_id_str)
                    if not player.approved:
                        return False

                    # Check for active ban records - banned players don't get verified role
                    from thetower.backend.sus.models import ModerationRecord

                    ban_ids = ModerationRecord.get_active_moderation_ids("ban")
                    player_tower_ids = [pid.id for pid in player.ids.all()]
                    return not any(pid in ban_ids for pid in player_tower_ids)
                except KnownPlayer.DoesNotExist:
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

        from thetower.backend.sus.models import KnownPlayer

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
                    player = KnownPlayer.objects.get(discord_id=discord_id_str)

                    # Check if approved
                    if not player.approved:
                        return {"should_have_role": False, "reason": "not approved"}

                    # Check for active ban records
                    from thetower.backend.sus.models import ModerationRecord

                    ban_ids = ModerationRecord.get_active_moderation_ids("ban")
                    player_tower_ids = [pid.id for pid in player.ids.all()]
                    if any(pid in ban_ids for pid in player_tower_ids):
                        return {"should_have_role": False, "reason": "active ban"}

                    return {"should_have_role": True, "reason": None}
                except KnownPlayer.DoesNotExist:
                    return {"should_have_role": False, "reason": "not approved"}

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
                        player = KnownPlayer.objects.get(discord_id=discord_id_str)
                        primary_id = PlayerId.objects.filter(player=player, primary=True).first()
                        if primary_id:
                            return primary_id.id
                        any_id = PlayerId.objects.filter(player=player).first()
                        return any_id.id if any_id else None
                    except KnownPlayer.DoesNotExist:
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

    def register_ui_extensions(self) -> None:
        """Register UI extensions for other cogs."""
        self.bot.cog_manager.register_ui_extension(
            "player_lookup",
            "Validation",
            self.provide_unverify_button,
        )

    def provide_unverify_button(self, details, requesting_user, guild_id, permission_context):
        """UI extension provider for un-verify button in player profiles.

        Args:
            details: The player details dictionary
            requesting_user: The Discord user requesting the profile
            guild_id: The guild ID where the request is made
            permission_context: Permission context for the requesting user

        Returns:
            UnverifyButton if user has permission, None otherwise
        """
        # Only show for verified players
        if not details.get("is_verified", False):
            return None

        # Don't allow users to un-verify themselves
        if details.get("discord_id") and str(details["discord_id"]) == str(requesting_user.id):
            return None

        # Check if the requesting user has permission to un-verify
        # Get approved groups from settings
        approved_groups = self.config.get_global_cog_setting("validation", "approved_unverify_groups", [])

        if not approved_groups:
            return None  # No groups configured for un-verification

        # Check if user has any of the approved groups
        if permission_context.has_any_group(approved_groups):
            from .ui.core import UnverifyButton

            return UnverifyButton(self, details["discord_id"], details["name"], requesting_user, guild_id)

        return None

    async def cog_unload(self) -> None:
        """Clean up when unloading."""
        # Call parent's cog_unload to ensure UI extensions are cleaned up
        await super().cog_unload()

    def _unverify_player(self, discord_id, requesting_user):
        """Un-verify a player by marking their KnownPlayer as unapproved.

        Args:
            discord_id: Discord ID of the player to un-verify
            requesting_user: Django user requesting the un-verification

        Returns:
            dict: Result with success status and message
        """
        try:
            # Ensure discord_id is a string for consistent comparison (KnownPlayer.discord_id is CharField)
            discord_id_str = str(discord_id)

            # Check if requesting user is in approved groups
            approved_groups = self.config.get_global_cog_setting(
                "validation", "approved_unverify_groups", self.global_settings["approved_unverify_groups"]
            )
            user_groups = [group.name for group in requesting_user.groups.all()]

            if not any(group in approved_groups for group in user_groups):
                return {"success": False, "message": "You don't have permission to un-verify players."}

            # Get the player
            try:
                player = KnownPlayer.objects.get(discord_id=discord_id_str)
            except KnownPlayer.DoesNotExist:
                return {"success": False, "message": f"No verified player found with Discord ID {discord_id_str}."}

            # Mark the player as unapproved
            player.approved = False
            player.save()

            return {
                "success": True,
                "message": f"Successfully un-verified player {player.name} (Discord ID: {discord_id_str}). Player marked as unapproved.",
                "player_id": player.id,
                "player_name": player.name,
                "discord_id": discord_id_str,
            }

        except Exception as exc:
            logger.error(f"Error un-verifying player {discord_id_str}: {exc}")
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
                    player_id_obj = PlayerId.objects.filter(id=tower_id).select_related("player").first()
                    if player_id_obj and player_id_obj.player.discord_id:
                        return player_id_obj.player.discord_id
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
