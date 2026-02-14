import datetime

import discord
from asgiref.sync import sync_to_async
from discord import ui


class VerificationModal(ui.Modal, title="Player Verification"):
    """Modal for player verification with player ID input and file upload."""

    player_id_label = ui.Label(
        text="Player ID",
        description="Enter your 13-16 character player ID",
        component=ui.TextInput(
            placeholder="Enter your 13-16 character player ID",
            min_length=13,
            max_length=16,
            required=True,
        ),
    )

    image_upload_label = ui.Label(
        text="Verification Image",
        description="Upload a screenshot showing your player ID",
        component=ui.FileUpload(
            custom_id="image_upload",
            required=True,
        ),
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission and validate the player."""
        # Send immediate acknowledgment
        await interaction.response.send_message("⏳ Verifying user...", ephemeral=True)

        player_id = self.player_id_label.component.value.upper().strip()
        attachment = self.image_upload_label.component.values[0] if self.image_upload_label.component.values else None

        # Get current timestamp for logging
        verification_time = discord.utils.utcnow()
        timestamp_unix = int(verification_time.timestamp())

        # Save the verification image
        image_filename = None
        if attachment:
            # Create filename: verification_{user_id}_{timestamp}_{player_id}.{extension}
            file_extension = attachment.filename.split(".")[-1] if "." in attachment.filename else "png"
            image_filename = f"verification_{interaction.user.id}_{timestamp_unix}_{player_id}.{file_extension}"
            image_path = self.cog.data_directory / image_filename

            try:
                await attachment.save(image_path)
            except Exception as save_exc:
                self.cog.logger.error(f"Failed to save verification image: {save_exc}")

        # Basic validation
        if not self.cog.only_made_of_hex(player_id):
            await self._log_verification_attempt(
                interaction, player_id, verification_time, timestamp_unix, image_filename, success=False, error_message="Invalid player ID format"
            )
            await interaction.edit_original_response(content="❌ Invalid player ID format. Player ID must be 13-16 hexadecimal characters.")
            return

        if len(player_id) < 13 or len(player_id) > 16:
            await self._log_verification_attempt(
                interaction, player_id, verification_time, timestamp_unix, image_filename, success=False, error_message="Invalid player ID length"
            )
            await interaction.edit_original_response(content="❌ Player ID must be between 13 and 16 characters long.")
            return

        if not attachment:
            await self._log_verification_attempt(
                interaction, player_id, verification_time, timestamp_unix, image_filename, success=False, error_message="No image uploaded"
            )
            await interaction.edit_original_response(content="❌ Please upload a screenshot showing your player ID.")
            return

        # Check if the NEW player ID being submitted is banned
        from thetower.backend.sus.models import ModerationRecord

        def check_player_id_banned(pid: str):
            """Check if a specific player ID is actively banned."""
            ban_ids = ModerationRecord.get_active_moderation_ids("ban")
            return pid in ban_ids

        is_new_id_banned = await sync_to_async(check_player_id_banned)(player_id)
        if is_new_id_banned:
            await self._log_verification_attempt(
                interaction,
                player_id,
                verification_time,
                timestamp_unix,
                image_filename,
                success=False,
                error_message="Player ID is actively banned",
            )
            await interaction.edit_original_response(
                content="⚠️ Unable to complete verification with this player ID. Please contact a server moderator for assistance."
            )
            return

        # Check if user has any OTHER previously banned player IDs (from existing linked account)
        discord_id_str = str(interaction.user.id)

        def get_previously_banned_ids(discord_id: str, new_player_id: str):
            """Get list of previously banned player IDs for this Discord user (excluding the new one)."""
            from thetower.backend.sus.models import LinkedAccount

            try:
                linked_account = (
                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=discord_id, active=True)
                    .select_related("player")
                    .first()
                )
                if not linked_account:
                    return []

                player = linked_account.player
                ban_ids = ModerationRecord.get_active_moderation_ids("ban")

                # Get all tower IDs across all game instances, excluding the new one
                player_tower_ids = [
                    pid.id for instance in player.game_instances.all() for pid in instance.player_ids.all() if pid.id != new_player_id
                ]

                # Return only the banned ones
                return [pid for pid in player_tower_ids if pid in ban_ids]
            except Exception:
                return []

        previously_banned_ids = await sync_to_async(get_previously_banned_ids)(discord_id_str, player_id)

        try:
            # Create or update player
            result = await sync_to_async(self.cog._create_or_update_player, thread_sensitive=True)(
                interaction.user.id, interaction.user.name, player_id
            )

            # Check if player ID is already linked to a different account
            if isinstance(result, dict) and result.get("error") == "already_linked":
                # Log the attempt to the role log channel
                existing_discord_id = result.get("existing_discord_id")
                existing_player_name = result.get("existing_player_name")

                # Log to verification log channel
                log_channel_id = self.cog.get_setting("verification_log_channel_id", guild_id=interaction.guild.id)
                if log_channel_id:
                    guild = interaction.guild
                    log_channel = guild.get_channel(log_channel_id)
                    if log_channel:
                        try:
                            embed = discord.Embed(
                                title="🚫 Duplicate Player ID Verification Attempt",
                                description=f"User {interaction.user.mention} ({interaction.user.name}) attempted to verify with player ID `{player_id}`, but it's already linked to {existing_player_name} (<@{existing_discord_id}>).",
                                color=discord.Color.red(),
                                timestamp=verification_time,
                            )
                            embed.add_field(name="Attempted By", value=f"{interaction.user.mention} ({interaction.user.name})", inline=True)
                            embed.add_field(name="Player ID", value=f"`{player_id}`", inline=True)
                            embed.add_field(name="Already Linked To", value=f"{existing_player_name} (<@{existing_discord_id}>)", inline=True)

                            # Attach the verification image if it exists
                            if image_filename:
                                image_path = self.cog.data_directory / image_filename
                                if image_path.exists():
                                    file = discord.File(image_path, filename=image_filename)
                                    await log_channel.send(embed=embed, file=file)
                                else:
                                    await log_channel.send(embed=embed)
                            else:
                                await log_channel.send(embed=embed)

                        except Exception as log_exc:
                            self.cog.logger.error(f"Failed to log duplicate verification attempt to channel {log_channel_id}: {log_exc}")

                # Log the verification attempt as failed
                await self._log_verification_attempt(
                    interaction,
                    player_id,
                    verification_time,
                    timestamp_unix,
                    image_filename,
                    success=False,
                    error_message=f"Player ID already linked to different account ({existing_discord_id})",
                )

                # Tell the user
                await interaction.edit_original_response(
                    content="❌ This player ID is already linked to a different Discord account. If you believe this is an error, please contact a moderator."
                )
                return

            # Assign verified role
            verified_role_id = self.cog.get_setting("verified_role_id", guild_id=interaction.guild.id)
            role_assigned = False
            if verified_role_id:
                guild = interaction.guild
                member = interaction.user
                role = guild.get_role(verified_role_id)
                if role and role not in member.roles:
                    # Track this as a bot action to prevent on_member_update from logging again
                    self.cog._bot_role_changes.add((member.id, guild.id))
                    try:
                        await member.add_roles(role)
                        role_assigned = True

                        # Log successful verification (inside try block so cleanup happens after logging)
                        log_message = await self._log_verification_attempt(
                            interaction,
                            player_id,
                            verification_time,
                            timestamp_unix,
                            image_filename,
                            success=True,
                            role_assigned=role_assigned,
                            previously_banned_ids=previously_banned_ids,
                        )

                        # Send mod notification if user has previously banned IDs
                        if previously_banned_ids and log_message:
                            await self._send_mod_notification_for_banned_history(interaction, player_id, previously_banned_ids, log_message)
                    finally:
                        # Cleanup after logging completes (matching tourney_role_colors pattern)
                        self.cog._bot_role_changes.discard((member.id, guild.id))
            else:
                # No role to assign, but still log the verification
                log_message = await self._log_verification_attempt(
                    interaction,
                    player_id,
                    verification_time,
                    timestamp_unix,
                    image_filename,
                    success=True,
                    role_assigned=role_assigned,
                    previously_banned_ids=previously_banned_ids,
                )

                # Send mod notification if user has previously banned IDs
                if previously_banned_ids and log_message:
                    await self._send_mod_notification_for_banned_history(interaction, player_id, previously_banned_ids, log_message)

            # Create success message with role mention
            success_message = "✅ Verification successful!"
            if role_assigned:
                verified_role_id = self.cog.get_setting("verified_role_id", guild_id=interaction.guild.id)
                if verified_role_id:
                    role = interaction.guild.get_role(verified_role_id)
                    if role:
                        success_message += f" You have been assigned the {role.mention} role."
                    else:
                        success_message += " You have been assigned the verified role."
                else:
                    success_message += " You have been assigned the verified role."
            else:
                success_message += " You have been assigned the verified role."

            await interaction.edit_original_response(content=success_message)

            # Dispatch player_verified event for other cogs to react
            if isinstance(result, dict) and result.get("primary_player_id"):
                primary_player_id = result["primary_player_id"]
                old_primary_player_id = result.get("old_primary_player_id")
                discord_id = str(interaction.user.id)
                guild_id = interaction.guild.id

                if old_primary_player_id:
                    self.cog.bot.dispatch("player_verified", guild_id, discord_id, primary_player_id, old_primary_player_id)
                else:
                    self.cog.bot.dispatch("player_verified", guild_id, discord_id, primary_player_id)

            # Tournament roles will be applied automatically via on_member_update event
            # when the verified role is added (no need to explicitly refresh here)

        except Exception as exc:
            # Log failed verification
            await self._log_verification_attempt(
                interaction, player_id, verification_time, timestamp_unix, image_filename, success=False, error_message=str(exc)
            )

            self.cog.logger.error(f"Verification error: {exc}")
            await interaction.edit_original_response(content=f"❌ Verification failed: {exc}")

    async def _log_verification_attempt(
        self,
        interaction: discord.Interaction,
        player_id: str,
        verification_time: datetime.datetime,
        timestamp_unix: int,
        image_filename: str = None,
        success: bool = False,
        role_assigned: bool = False,
        error_message: str = None,
        previously_banned_ids: list = None,
    ):
        """Log a verification attempt to the configured log channel."""
        log_channel_id = self.cog.get_setting("verification_log_channel_id", guild_id=interaction.guild.id)
        if not log_channel_id:
            return

        log_channel = interaction.guild.get_channel(log_channel_id)
        if not log_channel:
            return

        # Create embed based on success/failure
        if success:
            embed = discord.Embed(
                title="✅ Verification Successful",
                color=discord.Color.green(),
                timestamp=verification_time,
            )
        else:
            embed = discord.Embed(
                title="❌ Verification Failed",
                color=discord.Color.red(),
                timestamp=verification_time,
            )
            if error_message:
                embed.add_field(name="Error", value=error_message, inline=False)

        # Add user information fields
        embed.add_field(name="Discord User", value=f"{interaction.user.mention}\n`{interaction.user.name}`", inline=True)
        embed.add_field(name="Discord ID", value=f"`{interaction.user.id}`", inline=True)
        embed.add_field(name="Player ID", value=f"`{player_id}`", inline=True)

        # Add warning if user has previously banned IDs
        if success and previously_banned_ids:
            banned_ids_str = ", ".join(f"`{pid}`" for pid in previously_banned_ids)
            embed.add_field(
                name="⚠️ Previously Banned IDs",
                value=f"User has previously banned player ID(s): {banned_ids_str}",
                inline=False,
            )
            # Change embed color to orange to highlight this
            embed.color = discord.Color.orange()

        # Add role assignment info for successful verifications
        if success and role_assigned:
            verified_role_id = self.cog.get_setting("verified_role_id", guild_id=interaction.guild.id)
            if verified_role_id:
                role = interaction.guild.get_role(verified_role_id)
                if role:
                    embed.add_field(name="Role Assigned", value=role.mention, inline=True)

        # Set user avatar
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        # Prepare file attachment if image was saved
        file = None
        if success and image_filename and (self.cog.data_directory / image_filename).exists():
            file = discord.File(self.cog.data_directory / image_filename, filename=image_filename)
            embed.set_image(url=f"attachment://{image_filename}")

        log_message = None
        try:
            if file:
                log_message = await log_channel.send(embed=embed, file=file)
            else:
                log_message = await log_channel.send(embed=embed)
            return log_message
        except discord.Forbidden as forbidden_exc:
            # Try plain text if embed fails due to permissions
            self.cog.logger.warning(f"Missing embed permission in verification log channel {log_channel_id}: {forbidden_exc}")
            try:
                status = "✅ **Verification Successful**" if success else "❌ **Verification Failed**"
                text_message = (
                    f"{status}\n"
                    f"**Discord User:** {interaction.user.mention} (`{interaction.user.name}`)\n"
                    f"**Discord ID:** `{interaction.user.id}`\n"
                    f"**Player ID:** `{player_id}`\n"
                )
                if success and previously_banned_ids:
                    banned_ids_str = ", ".join(f"`{pid}`" for pid in previously_banned_ids)
                    text_message += f"**⚠️ Previously Banned IDs:** {banned_ids_str}\n"
                if success and role_assigned:
                    verified_role_id = self.cog.get_setting("verified_role_id", guild_id=interaction.guild.id)
                    if verified_role_id:
                        role = interaction.guild.get_role(verified_role_id)
                        if role:
                            text_message += f"**Role Assigned:** {role.mention}\n"
                if not success and error_message:
                    text_message += f"**Error:** {error_message}\n"

                # Need to re-create the file object since it was already consumed
                new_file = None
                if file and success and image_filename and (self.cog.data_directory / image_filename).exists():
                    new_file = discord.File(self.cog.data_directory / image_filename, filename=image_filename)

                if new_file:
                    log_message = await log_channel.send(content=text_message, file=new_file)
                else:
                    log_message = await log_channel.send(content=text_message)
                return log_message
            except Exception as fallback_exc:
                self.cog.logger.error(f"Failed to send plain text verification log: {fallback_exc}")
                return None
        except Exception as log_exc:
            self.cog.logger.error(f"Failed to log verification to channel {log_channel_id}: {log_exc}")
            return None

    async def _send_mod_notification_for_banned_history(
        self, interaction: discord.Interaction, new_player_id: str, previously_banned_ids: list, log_message: discord.Message
    ):
        """Send a brief notification to the mod channel when a user verifies with a clean ID but has previously banned IDs.

        Args:
            interaction: The interaction context
            new_player_id: The new clean player ID they just verified with
            previously_banned_ids: List of their previously banned player IDs
            log_message: The log channel message to link to
        """
        mod_channel_id = self.cog.get_global_setting("mod_notification_channel_id")
        if not mod_channel_id:
            return

        try:
            mod_channel = self.cog.bot.get_channel(mod_channel_id)
            if not mod_channel:
                self.cog.logger.warning(f"Mod notification channel {mod_channel_id} not found")
                return

            # Create brief notification with link to full log
            banned_ids_str = ", ".join(f"`{pid}`" for pid in previously_banned_ids)
            log_link = log_message.jump_url

            notification_text = (
                f"⚠️ {interaction.user.mention} just verified with player ID `{new_player_id}` "
                f"but has previously banned player ID(s): {banned_ids_str}\n\n"
                f"[View full verification log]({log_link})"
            )

            await mod_channel.send(notification_text)

        except discord.Forbidden:
            self.cog.logger.error(f"Missing permission to send to mod notification channel {mod_channel_id}")
        except Exception as e:
            self.cog.logger.error(f"Failed to send mod notification: {e}")


class VerificationStatusView(discord.ui.View):
    """View for verified users to manage their verification."""

    def __init__(
        self,
        cog,
        verification_info: dict,
        current_discord_id: str,
        has_pending_link: bool = False,
        requesting_user: discord.User = None,
        can_manage_alt_links: bool = False,
    ):
        super().__init__(timeout=900)
        self.cog = cog
        self.verification_info = verification_info
        self.current_discord_id = current_discord_id
        self.requesting_user = requesting_user
        self.can_manage_alt_links = can_manage_alt_links

        # Check if this is the user's own profile
        is_own_profile = requesting_user and str(requesting_user.id) == current_discord_id

        # Only show link/cancel buttons if user doesn't have multiple Discord accounts already linked
        if len(verification_info.get("all_discord_accounts", [])) == 1:
            # Show link management buttons for own profile OR if user can manage alt links
            if is_own_profile or can_manage_alt_links:
                # Admin mode only when managing someone else's links
                is_admin_mode = can_manage_alt_links and not is_own_profile

                if has_pending_link:
                    # Show cancel button if there's a pending request
                    self.add_item(CancelLinkRequestButton(cog, current_discord_id, is_admin_mode))
                else:
                    # Show link button if no pending request
                    self.add_item(LinkAltAccountButton(cog, verification_info["player_id"], current_discord_id, is_admin_mode))

        # Add "Update Player ID" button for own profile only
        if is_own_profile:
            self.add_item(UpdatePlayerIdButton(cog, verification_info, current_discord_id))

        # Add "Manage Roles" button for own profile only if multiple accounts exist
        if is_own_profile and len(verification_info.get("all_discord_accounts", [])) > 1:
            self.add_item(ManageRolesButton(cog, verification_info["player_id"], current_discord_id, verification_info))


class LinkAltAccountButton(discord.ui.Button):
    """Button to initiate alt Discord account linking."""

    def __init__(self, cog, player_id: int, current_discord_id: str, is_admin: bool = False):
        label = "Link Alt Discord Account" if not is_admin else "Link Alt Discord Account (Admin)"
        super().__init__(label=label, style=discord.ButtonStyle.primary, emoji="🔗")
        self.cog = cog
        self.player_id = player_id
        self.current_discord_id = current_discord_id
        self.is_admin = is_admin

    async def callback(self, interaction: discord.Interaction):
        """Show user select to link another Discord account."""
        prefix = "**[Admin] " if self.is_admin else "**"
        view = LinkAltAccountView(self.cog, self.player_id, self.current_discord_id)
        await interaction.response.edit_message(
            content=f"{prefix}Link Alt Discord Account**\n\nSelect the Discord user you want to link to this account:", embed=None, view=view
        )


class CancelLinkRequestButton(discord.ui.Button):
    """Button to cancel pending outgoing link request."""

    def __init__(self, cog, current_discord_id: str, is_admin: bool = False):
        label = "Cancel Link Request" if not is_admin else "Cancel Link Request (Admin)"
        super().__init__(label=label, style=discord.ButtonStyle.danger, emoji="❌")
        self.cog = cog
        self.current_discord_id = current_discord_id
        self.is_admin = is_admin

    async def callback(self, interaction: discord.Interaction):
        """Cancel the pending link request and refresh the status."""
        # Cancel the pending link using the cog's helper method
        removed = await self.cog.cancel_pending_link(self.current_discord_id)

        if removed > 0:
            # Just send a confirmation message
            await interaction.response.send_message("✅ Link request cancelled.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ No pending link request found.", ephemeral=True)


class LinkAltAccountView(discord.ui.View):
    """View with user select for alt account linking."""

    def __init__(self, cog, player_id: int, current_discord_id: str):
        super().__init__(timeout=900)
        self.cog = cog
        self.player_id = player_id
        self.current_discord_id = current_discord_id
        self.add_item(AltAccountUserSelect(cog, player_id, current_discord_id))
        self.add_item(CancelAltLinkButton(cog, current_discord_id))


class CancelAltLinkButton(discord.ui.Button):
    """Button to cancel alt account linking and return to verification status."""

    def __init__(self, cog, current_discord_id: str):
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌", row=1)
        self.cog = cog
        self.current_discord_id = current_discord_id

    async def callback(self, interaction: discord.Interaction):
        """Cancel and return to verification status."""
        # Check if we're in a PlayerView (from player_lookup)
        if hasattr(self.view, "player") and hasattr(self.view, "details"):
            # In player_lookup context - rebuild the view directly
            await interaction.response.defer()

            player_lookup_cog = interaction.client.get_cog("PlayerLookup")
            if player_lookup_cog:
                try:
                    from asgiref.sync import sync_to_async

                    from thetower.backend.sus.models import LinkedAccount
                    from thetower.bot.cogs.player_lookup.ui.core import PlayerView
                    from thetower.bot.cogs.player_lookup.ui.user import get_player_details

                    linked_account = await sync_to_async(
                        LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=self.current_discord_id, active=True)
                        .select_related("player")
                        .first
                    )()
                    if linked_account:
                        player = linked_account.player
                        details = await get_player_details(player, requesting_user=interaction.user, cog=player_lookup_cog)
                        details["is_verified"] = True

                        embed = await player_lookup_cog.user_interactions.create_lookup_embed(player, details, interaction.user)
                        view = await PlayerView.create(
                            player_lookup_cog,
                            requesting_user=interaction.user,
                            player=player,
                            details=details,
                            embed_title="Player Details",
                            guild_id=interaction.guild.id,
                        )

                        await interaction.edit_original_response(content=None, embed=embed, view=view)
                        return
                except Exception as e:
                    self.cog.logger.error(f"Error refreshing player lookup view in CancelAltLinkButton: {e}", exc_info=True)
                    await interaction.followup.send("❌ Could not refresh lookup view.", ephemeral=True)
                    return

        # Default: defer for verification status view
        await interaction.response.defer()

        # Default: Use validation cog's verification status view
        embed, verification_info, has_pending_link = await self.cog.build_verification_status_display(self.current_discord_id)

        if embed is None:
            await interaction.followup.send("❌ Could not load status.", ephemeral=True)
            return

        # Check if requesting user can manage alt links
        can_manage = await self.cog.can_manage_alt_links(interaction.user)

        # Create view with appropriate button
        view = VerificationStatusView(
            self.cog,
            verification_info,
            self.current_discord_id,
            has_pending_link=has_pending_link,
            requesting_user=interaction.user,
            can_manage_alt_links=can_manage,
        )

        # Edit the original message
        await interaction.edit_original_response(content=None, embed=embed, view=view)


class AltAccountUserSelect(discord.ui.UserSelect):
    """User select for choosing alt account to link."""

    def __init__(self, cog, player_id: int, current_discord_id: str):
        super().__init__(placeholder="Select a Discord user to link...", min_values=1, max_values=1)
        self.cog = cog
        self.player_id = player_id
        self.current_discord_id = current_discord_id

    async def callback(self, interaction: discord.Interaction):
        """Handle user selection and save pending link."""
        from thetower.backend.sus.models import KnownPlayer, LinkedAccount

        selected_user = self.values[0]
        alt_discord_id = str(selected_user.id)

        # Check if trying to link to self
        if alt_discord_id == self.current_discord_id:
            await interaction.response.send_message("❌ You cannot link your account to itself.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        def check_existing_link():
            """Check if alt account can be linked (chain limit: 2 accounts max)."""
            # First check: Does requester already have 2 Discord accounts?
            requester_discord_count = LinkedAccount.objects.filter(player_id=self.player_id, platform=LinkedAccount.Platform.DISCORD).count()

            if requester_discord_count >= 2:
                return {"status": "requester_limit", "message": "You already have 2 Discord accounts linked. Cannot add more (chain limit)."}

            # Second check: Is the alt Discord account already linked?
            existing_link = (
                LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=alt_discord_id).select_related("player").first()
            )

            if existing_link:
                if existing_link.player.id == self.player_id:
                    return {"status": "already_linked", "player_name": existing_link.player.name}
                else:
                    # Alt is linked to a different player - check their Discord account count
                    other_player_discord_count = LinkedAccount.objects.filter(
                        player=existing_link.player, platform=LinkedAccount.Platform.DISCORD
                    ).count()

                    if other_player_discord_count >= 2:
                        return {"status": "chain_limit", "player_name": existing_link.player.name, "discord_count": other_player_discord_count}
                    else:
                        # Other player has only 1 Discord account (the alt) - allow transfer
                        return {"status": "transfer_allowed", "player_name": existing_link.player.name, "verified": existing_link.verified}

            # Get current player
            try:
                player = KnownPlayer.objects.get(id=self.player_id)
                return {"status": "ok", "player_name": player.name}
            except KnownPlayer.DoesNotExist:
                return {"status": "error", "message": "Player not found"}

        result = await sync_to_async(check_existing_link)()

        if result["status"] == "already_linked":
            await interaction.followup.send(f"ℹ️ That account is already linked to **{result['player_name']}**.", ephemeral=True)
            return
        elif result["status"] == "requester_limit":
            await interaction.followup.send(f"❌ {result['message']}", ephemeral=True)
            return
        elif result["status"] == "chain_limit":
            await interaction.followup.send(
                f"❌ That Discord account is already part of a {result['discord_count']}-account chain with **{result['player_name']}**.\n"
                f"Cannot link because it would exceed the 2-account limit. They must unlink first.",
                ephemeral=True,
            )
            return
        elif result["status"] == "transfer_allowed":
            # Allow the link request even though account is linked elsewhere
            # This is a transfer scenario - the alt's current player will lose it if they accept
            verified_status = "verified" if result["verified"] else "pending verification"
            await interaction.followup.send(
                f"⚠️ **Note:** That Discord account is currently linked to **{result['player_name']}** ({verified_status}).\n"
                f"If they accept your link request, their account will transfer to your player profile.\n"
                f"Sending link request...",
                ephemeral=True,
            )
            # Continue to send the link request
        elif result["status"] == "error":
            await interaction.followup.send(f"❌ Error: {result.get('message', 'Unknown error')}", ephemeral=True)
            return

        # Check if target already has a pending link request
        def check_existing_pending():
            data = self.cog.load_pending_links_data()
            pending_links = data.get("pending_links", {})
            return alt_discord_id in pending_links

        has_pending = await sync_to_async(check_existing_pending)()
        if has_pending:
            await interaction.followup.send(
                "❌ That Discord account already has a pending link request from another user.\n"
                "Please wait for them to accept or decline the existing request first.",
                ephemeral=True,
            )
            return

        # Save pending link in cog data
        def save_pending_link():
            # BaseCog's load_data() doesn't take arguments when using default file path
            data = self.cog.load_pending_links_data()
            if "pending_links" not in data:
                data["pending_links"] = {}

            # Store: alt_discord_id -> {requester_id, player_id, player_name, timestamp}
            data["pending_links"][alt_discord_id] = {
                "requester_id": self.current_discord_id,
                "player_id": self.player_id,
                "player_name": result["player_name"],
                "timestamp": discord.utils.utcnow().isoformat(),
            }

            self.cog.save_pending_links_data(data)

        await sync_to_async(save_pending_link)()

        # Check if the original view (before LinkAltAccountView) was a PlayerView
        # Try to refresh as player lookup view
        player_lookup_cog = interaction.client.get_cog("PlayerLookup")
        if player_lookup_cog:
            try:
                # Check if this player exists in player_lookup context
                linked_account = await sync_to_async(
                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=self.current_discord_id)
                    .select_related("player")
                    .first
                )()
                if linked_account:
                    player = linked_account.player
                    # Rebuild the lookup view directly (interaction already deferred)
                    from thetower.bot.cogs.player_lookup.ui.core import PlayerView
                    from thetower.bot.cogs.player_lookup.ui.user import get_player_details

                    details = await get_player_details(player, requesting_user=interaction.user, cog=player_lookup_cog)
                    details["is_verified"] = True

                    embed = await player_lookup_cog.user_interactions.create_lookup_embed(player, details, interaction.user)
                    view = await PlayerView.create(
                        player_lookup_cog,
                        requesting_user=interaction.user,
                        player=player,
                        details=details,
                        embed_title="Player Details",
                        guild_id=interaction.guild.id,
                    )

                    await interaction.edit_original_response(content=None, embed=embed, view=view)
                    return
            except Exception as e:
                self.cog.logger.error(f"Error refreshing player lookup view in AltAccountUserSelect: {e}", exc_info=True)
                # Fall through to building verification status manually

        # Regenerate the verification status embed showing the new pending link
        def get_verification_info():
            try:
                linked_account = (
                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=self.current_discord_id)
                    .select_related("player")
                    .first()
                )

                if not linked_account:
                    return None

                player = linked_account.player
                all_linked_accounts = list(
                    LinkedAccount.objects.filter(player=player, platform=LinkedAccount.Platform.DISCORD).values_list(
                        "account_id", "verified", "display_name"
                    )
                )

                game_instances = []
                for instance in player.game_instances.all():
                    tower_ids = list(instance.player_ids.values_list("id", "primary"))
                    game_instances.append({"name": instance.name, "primary": instance.primary, "tower_ids": tower_ids})

                return {
                    "status": "verified",
                    "player_id": player.id,
                    "player_name": player.name,
                    "verified": linked_account.verified,
                    "verified_at": linked_account.verified_at,
                    "all_discord_accounts": all_linked_accounts,
                    "game_instances": game_instances,
                }
            except Exception:
                return None

        verification_info = await sync_to_async(get_verification_info)()

        if not verification_info:
            await interaction.followup.send("❌ Could not refresh status.", ephemeral=True)
            return

        # Rebuild the embed (same logic as verify command)
        embed = discord.Embed(
            title="✅ Verification Status", description=f"**Player:** {verification_info['player_name']}", color=discord.Color.green()
        )

        # Discord accounts
        discord_accounts_text = []
        for account_id, verified, display_name in verification_info["all_discord_accounts"]:
            status = "✅ Verified" if verified else "⏳ Pending"
            is_current = " **(You)**" if account_id == self.current_discord_id else ""
            name_str = f" ({display_name})" if display_name else ""
            discord_accounts_text.append(f"• <@{account_id}>{name_str}: {status}{is_current}")

        embed.add_field(name="Discord Accounts", value="\n".join(discord_accounts_text) if discord_accounts_text else "None", inline=False)

        # Tower IDs (simplified for single instance)
        if len(verification_info["game_instances"]) == 1:
            instance_info = verification_info["game_instances"][0]
            tower_ids_text = []
            for tower_id_data in instance_info["tower_ids"]:
                primary_id_marker = " **(Primary)**" if tower_id_data["primary"] else ""
                tower_ids_text.append(f"• `{tower_id_data['id']}`{primary_id_marker}")
            embed.add_field(name="Tower IDs", value="\n".join(tower_ids_text) if tower_ids_text else "No tower IDs", inline=False)
        else:
            for instance_info in verification_info["game_instances"]:
                primary_marker = " 🌟 (Primary)" if instance_info["primary"] else ""
                tower_ids_text = []
                for tower_id_data in instance_info["tower_ids"]:
                    primary_id_marker = " **(Primary)**" if tower_id_data["primary"] else ""
                    tower_ids_text.append(f"• `{tower_id_data['id']}`{primary_id_marker}")
                embed.add_field(
                    name=f"{instance_info['name']}{primary_marker}",
                    value="\n".join(tower_ids_text) if tower_ids_text else "No tower IDs",
                    inline=False,
                )

        # Verified timestamp
        if verification_info.get("verified_at"):
            verified_at = verification_info["verified_at"]
            if hasattr(verified_at, "timestamp"):
                unix_timestamp = int(verified_at.timestamp())
                if unix_timestamp == 1577836800:
                    embed.add_field(name="Verified", value="Unknown date", inline=False)
                else:
                    embed.add_field(name="Verified", value=f"<t:{unix_timestamp}:f> (<t:{unix_timestamp}:R>)", inline=False)

        # Add pending link field
        embed.add_field(name="⏳ Pending Link Requests", value=f"• {selected_user.mention} (Waiting for approval)", inline=False)

        # Check if we're in a player_lookup context and should return to PlayerView instead
        player_lookup_cog = interaction.client.get_cog("PlayerLookup")
        if player_lookup_cog:
            try:
                linked_account = await sync_to_async(
                    LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=self.current_discord_id)
                    .select_related("player")
                    .first
                )()
                if linked_account:
                    player = linked_account.player
                    # Rebuild as PlayerView instead of VerificationStatusView
                    from thetower.bot.cogs.player_lookup.ui.user import get_player_details

                    details = await get_player_details(player, requesting_user=interaction.user, cog=player_lookup_cog)
                    details["is_verified"] = True

                    # Build updated embed
                    embed = await player_lookup_cog.user_interactions.create_lookup_embed(player, details, interaction.user)

                    # Create updated view
                    from thetower.bot.cogs.player_lookup.ui.core import PlayerView

                    view = await PlayerView.create(
                        player_lookup_cog,
                        requesting_user=interaction.user,
                        player=player,
                        details=details,
                        embed_title="Player Details",
                        guild_id=interaction.guild.id,
                    )

                    await interaction.edit_original_response(content=None, embed=embed, view=view)
                    return
            except Exception as e:
                self.cog.logger.error(f"Error rebuilding player lookup view in AltAccountUserSelect: {e}", exc_info=True)
                # Fall through to validation view

        # Default: Show verification status view
        # Check if requesting user can manage alt links
        can_manage = await self.cog.can_manage_alt_links(interaction.user)

        # Create new view with cancel button (has_pending_link=True)
        view = VerificationStatusView(
            self.cog,
            verification_info,
            self.current_discord_id,
            has_pending_link=True,
            requesting_user=interaction.user,
            can_manage_alt_links=can_manage,
        )

        # Edit the original message
        await interaction.edit_original_response(content=None, embed=embed, view=view)


class GameInstanceSelectView(discord.ui.View):
    """View for selecting which game instance to update the player ID for."""

    def __init__(self, cog, verification_info: dict, current_discord_id: str):
        super().__init__(timeout=900)
        self.cog = cog
        self.verification_info = verification_info
        self.current_discord_id = current_discord_id

        # Add instance selector dropdown
        self.add_item(GameInstanceSelect(cog, verification_info, current_discord_id))
        self.add_item(CancelSelectInstanceButton(cog, verification_info, current_discord_id))


class GameInstanceSelect(discord.ui.Select):
    """Dropdown to select which game instance to update."""

    def __init__(self, cog, verification_info: dict, current_discord_id: str):
        game_instances = verification_info.get("game_instances", [])
        options = []

        for instance in game_instances:
            # Get the primary tower ID for this instance
            primary_id = None
            for tower_id, is_primary in instance.get("tower_ids", []):
                if is_primary:
                    primary_id = tower_id
                    break

            if primary_id:
                options.append(
                    discord.SelectOption(
                        label=primary_id,
                        value=instance["name"],
                        emoji="🎮",
                    )
                )

        super().__init__(placeholder="Select a player ID to update...", options=options, row=0)
        self.cog = cog
        self.verification_info = verification_info
        self.current_discord_id = current_discord_id

    async def callback(self, interaction: discord.Interaction):
        """Handle instance selection."""
        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import PlayerId

        selected_instance_name = self.values[0]

        # Find the selected instance and get its ID
        async def get_instance_id():
            game_instances = self.verification_info.get("game_instances", [])
            for instance in game_instances:
                if instance["name"] == selected_instance_name:
                    # Find the primary ID and get its game_instance ID
                    for tower_id, is_primary in instance.get("tower_ids", []):
                        if is_primary:
                            player_id_obj = await sync_to_async(PlayerId.objects.filter(id=tower_id).select_related("game_instance").first)()
                            return player_id_obj.game_instance.id if player_id_obj else None
            return None

        instance_id = await get_instance_id()

        # Proceed to reason selection
        view = UpdatePlayerIdView(self.cog, self.verification_info, self.current_discord_id, instance_id)
        await interaction.response.edit_message(
            content="**Update Player ID**\n\nSelect the reason for updating your player ID:", embed=None, view=view
        )


class CancelSelectInstanceButton(discord.ui.Button):
    """Button to cancel instance selection and return to verification status."""

    def __init__(self, cog, verification_info: dict, current_discord_id: str):
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌", row=1)
        self.cog = cog
        self.verification_info = verification_info
        self.current_discord_id = current_discord_id

    async def callback(self, interaction: discord.Interaction):
        """Return to verification status view."""
        embed, verification_info, has_pending_link = await self.cog.build_verification_status_display(self.current_discord_id)

        if embed is None:
            await interaction.response.send_message("❌ Could not load status.", ephemeral=True)
            return

        view = VerificationStatusView(
            self.cog,
            verification_info,
            self.current_discord_id,
            has_pending_link=has_pending_link,
            requesting_user=interaction.user,
            can_manage_alt_links=False,
        )

        await interaction.response.edit_message(content=None, embed=embed, view=view)


class UpdatePlayerIdButton(discord.ui.Button):
    """Button to initiate player ID update process."""

    def __init__(self, cog, verification_info: dict, current_discord_id: str):
        super().__init__(style=discord.ButtonStyle.primary, label="Update Player ID", emoji="🔄")
        self.cog = cog
        self.verification_info = verification_info
        self.current_discord_id = current_discord_id

    async def callback(self, interaction: discord.Interaction):
        """Show game instance selection or proceed directly if only one instance."""
        game_instances = self.verification_info.get("game_instances", [])

        if len(game_instances) == 1:
            # Only one instance, auto-select it and proceed to reason selection
            instance_id = None
            # Get the GameInstance ID by finding it from the primary ID
            for pid_data in game_instances[0].get("tower_ids", []):
                if pid_data["primary"]:
                    pid = pid_data["id"]
                    # Extract instance from player lookup

                    async def get_instance_id():
                        from asgiref.sync import sync_to_async

                        from thetower.backend.sus.models import PlayerId

                        player_id_obj = await sync_to_async(PlayerId.objects.filter(id=pid).select_related("game_instance").first)()
                        return player_id_obj.game_instance.id if player_id_obj else None

                    instance_id = await get_instance_id()
                    break

            view = UpdatePlayerIdView(self.cog, self.verification_info, self.current_discord_id, instance_id)
            await interaction.response.edit_message(
                content="**Update Player ID**\n\nSelect the reason for updating your player ID:", embed=None, view=view
            )
        else:
            # Multiple instances, show selector
            view = GameInstanceSelectView(self.cog, self.verification_info, self.current_discord_id)
            primary_ids = [next((tid["id"] for tid in inst.get("tower_ids", []) if tid["primary"]), None) for inst in game_instances]
            id_list = "\n".join([f"• `{pid}`" for pid in primary_ids if pid])
            await interaction.response.edit_message(
                content=f"**Update Player ID**\n\nYou have multiple game instances. Select which player ID you want to update:\n\n{id_list}",
                embed=None,
                view=view,
            )


class ManageRolesButton(discord.ui.Button):
    """Button to manage role sources for Discord accounts."""

    def __init__(self, cog, player_id: int, current_discord_id: str, verification_info: dict):
        super().__init__(label="Manage Roles", style=discord.ButtonStyle.secondary, emoji="🎮", row=2)
        self.cog = cog
        self.player_id = player_id
        self.current_discord_id = current_discord_id
        self.verification_info = verification_info

    async def callback(self, interaction: discord.Interaction):
        """Show role source management view."""
        view = ManageRolesView(
            self.cog,
            self.player_id,
            self.current_discord_id,
            self.verification_info["all_discord_accounts"],
        )
        await interaction.response.edit_message(
            content="**Manage Tournament Roles**\n\nSelect a Discord account to manage its role source:",
            embed=None,
            view=view,
        )


class UpdatePlayerIdView(discord.ui.View):
    """View for selecting reason to update player ID."""

    def __init__(self, cog, verification_info: dict, current_discord_id: str, instance_id: int = None):
        super().__init__(timeout=900)
        self.cog = cog
        self.verification_info = verification_info
        self.current_discord_id = current_discord_id
        self.instance_id = instance_id

        # Show current player IDs in the view
        self.add_item(PlayerIdChangeReasonSelect(cog, verification_info, current_discord_id, instance_id))
        self.add_item(CancelUpdatePlayerIdButton(cog, verification_info, current_discord_id))


class PlayerIdChangeReasonSelect(discord.ui.Select):
    """Dropdown for selecting reason for player ID change."""

    def __init__(self, cog, verification_info: dict, current_discord_id: str, instance_id: int = None):
        options = [
            discord.SelectOption(
                label="Game changed my ID",
                value="game_changed",
                description="The game assigned me a new ID, but I have results on my old ID too.",
                emoji="🎮",
            ),
            discord.SelectOption(
                label="I typed the wrong ID",
                value="typo",
                description="I entered the wrong ID when verifying. My old ID has no data on it.",
                emoji="✏️",
            ),
        ]
        super().__init__(placeholder="Select reason for change...", options=options, row=0)
        self.cog = cog
        self.verification_info = verification_info
        self.current_discord_id = current_discord_id
        self.instance_id = instance_id

    async def callback(self, interaction: discord.Interaction):
        """Handle reason selection and show modal."""
        reason = self.values[0]
        modal = PlayerIdChangeModal(self.cog, self.verification_info, self.current_discord_id, reason, self.instance_id)
        await interaction.response.send_modal(modal)


class CancelUpdatePlayerIdButton(discord.ui.Button):
    """Button to cancel player ID update and return to verification status."""

    def __init__(self, cog, verification_info: dict, current_discord_id: str):
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌", row=1)
        self.cog = cog
        self.verification_info = verification_info
        self.current_discord_id = current_discord_id

    async def callback(self, interaction: discord.Interaction):
        """Return to verification status view."""

        embed, verification_info, has_pending_link = await self.cog.build_verification_status_display(self.current_discord_id)

        if embed is None:
            await interaction.response.send_message("❌ Could not load status.", ephemeral=True)
            return

        can_manage = False  # User viewing their own profile
        view = VerificationStatusView(
            self.cog,
            verification_info,
            self.current_discord_id,
            has_pending_link=has_pending_link,
            requesting_user=interaction.user,
            can_manage_alt_links=can_manage,
        )

        await interaction.response.edit_message(content=None, embed=embed, view=view)


class PlayerIdChangeModal(ui.Modal, title="Update Player ID"):
    """Modal for submitting new player ID with image upload."""

    new_player_id_label = ui.Label(
        text="New Player ID",
        description="Enter your new player ID",
        component=ui.TextInput(
            placeholder="Enter your new player ID",
            min_length=13,
            max_length=16,
            required=True,
        ),
    )

    image_upload_label = ui.Label(
        text="Verification Image",
        description="Upload a screenshot showing your new player ID",
        component=ui.FileUpload(
            custom_id="player_id_change_image",
            required=True,
        ),
    )

    def __init__(self, cog, verification_info: dict, current_discord_id: str, reason: str, instance_id: int = None):
        super().__init__(timeout=900)
        self.cog = cog
        self.verification_info = verification_info
        self.current_discord_id = current_discord_id
        self.reason = reason
        self.instance_id = instance_id

        # Update modal title based on reason
        if reason == "game_changed":
            self.title = "Add New Player ID"
        else:
            self.title = "Change Player ID"

    async def on_submit(self, interaction: discord.Interaction):
        """Process player ID change request."""
        import datetime as dt

        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import GameInstance

        # Get the entered player ID
        new_id = self.new_player_id_label.component.value.strip().upper()

        # Get the uploaded image
        attachment = self.image_upload_label.component.values[0] if self.image_upload_label.component.values else None

        if not attachment:
            await interaction.response.send_message("❌ Please upload a verification image.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Validate player ID format
        if not self.cog.only_made_of_hex(new_id):
            await interaction.followup.send("❌ Invalid player ID format. Must be hexadecimal characters only.", ephemeral=True)
            return

        if len(new_id) < 13 or len(new_id) > 16:
            await interaction.followup.send("❌ Player ID must be between 13 and 16 characters long.", ephemeral=True)
            return

        # Get current primary player ID from selected instance
        current_id = None
        if self.instance_id:
            # Get current ID from the selected instance
            def get_instance_primary_id():
                instance = GameInstance.objects.filter(id=self.instance_id).first()
                if instance:
                    primary_player_id = instance.player_ids.filter(primary=True).first()
                    return primary_player_id.id if primary_player_id else None
                return None

            current_id = await sync_to_async(get_instance_primary_id)()
        else:
            # Fallback to primary instance (shouldn't happen with new flow)
            for instance in self.verification_info.get("game_instances", []):
                if instance.get("primary"):
                    for tower_id_data in instance.get("tower_ids", []):
                        if tower_id_data["primary"]:
                            current_id = tower_id_data["id"]
                            break

        if not current_id:
            await interaction.followup.send("❌ Could not find your current player ID.", ephemeral=True)
            return

        if new_id == current_id:
            await interaction.followup.send("❌ New player ID is the same as your current ID.", ephemeral=True)
            return

        # Check if new ID is already in use
        def check_id_exists():
            from thetower.backend.sus.models import PlayerId

            return PlayerId.objects.filter(id=new_id).exists()

        id_exists = await sync_to_async(check_id_exists)()
        if id_exists:
            await interaction.followup.send("❌ This player ID is already registered to another account.", ephemeral=True)
            return

        # Save the verification image
        timestamp = dt.datetime.now(dt.timezone.utc)
        timestamp_unix = int(timestamp.timestamp())
        file_extension = attachment.filename.split(".")[-1] if "." in attachment.filename else "png"
        image_filename = f"player_id_change_{interaction.user.id}_{timestamp_unix}_{new_id}.{file_extension}"
        image_path = self.cog.data_directory / image_filename

        try:
            await attachment.save(image_path)
        except Exception as save_exc:
            self.cog.logger.error(f"Failed to save player ID change image: {save_exc}")
            await interaction.followup.send("❌ Failed to save verification image. Please try again.", ephemeral=True)
            return

        # Create pending change request and log to channel
        await self.cog.create_player_id_change_request(
            interaction=interaction,
            discord_id=self.current_discord_id,
            old_player_id=current_id,
            new_player_id=new_id,
            reason=self.reason,
            image_filename=image_filename,
            timestamp=timestamp,
            instance_id=self.instance_id,
        )

        reason_text = "the game changed your ID" if self.reason == "game_changed" else "you typed the wrong ID"
        await interaction.followup.send(
            f"✅ **Player ID change request submitted!**\n\n"
            f"Old ID: `{current_id}`\n"
            f"New ID: `{new_id}`\n"
            f"Reason: {reason_text}\n\n"
            f"A moderator will review your request.",
            ephemeral=True,
        )


class PlayerIdChangeImageUploadView(discord.ui.View):
    """View for uploading verification image for player ID change."""

    def __init__(self, cog, verification_info: dict, current_discord_id: str, reason: str, old_id: str, new_id: str):
        super().__init__(timeout=900)
        self.cog = cog
        self.verification_info = verification_info
        self.current_discord_id = current_discord_id
        self.reason = reason
        self.old_id = old_id
        self.new_id = new_id

        # Add button to trigger file upload
        self.add_item(UploadImageButton(cog, verification_info, current_discord_id, reason, old_id, new_id))
        self.add_item(CancelImageUploadButton())


class UploadImageButton(discord.ui.Button):
    """Button that prompts user to upload an image."""

    def __init__(self, cog, verification_info: dict, current_discord_id: str, reason: str, old_id: str, new_id: str):
        super().__init__(label="Upload Image", style=discord.ButtonStyle.primary, emoji="📸")
        self.cog = cog
        self.verification_info = verification_info
        self.current_discord_id = current_discord_id
        self.reason = reason
        self.old_id = old_id
        self.new_id = new_id

    async def callback(self, interaction: discord.Interaction):
        """Request image upload from user."""
        await interaction.response.send_message(
            "📸 **Please upload your verification image**\n\n"
            "Reply to this message with an image attachment showing your new player ID.\n"
            "The bot will detect your image and process your request.",
            ephemeral=True,
        )

        # Store pending state waiting for image
        # User will need to send message with attachment, bot will listen for it
        # TODO: Implement message listener for image upload
        await interaction.followup.send(
            "⚠️ **Image upload via messages is not yet implemented.**\n\n"
            "This feature requires additional bot message handling. For now, please contact a moderator directly "
            "to submit your player ID change request.",
            ephemeral=True,
        )


class CancelImageUploadButton(discord.ui.Button):
    """Button to cancel image upload."""

    def __init__(self):
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")

    async def callback(self, interaction: discord.Interaction):
        """Cancel the upload process."""
        await interaction.response.edit_message(content="❌ Player ID change request cancelled.", view=None, embeds=[])


class PlayerIdChangeApprovalView(discord.ui.View):
    """View for moderators to approve or deny player ID change requests."""

    def __init__(self, cog, discord_id: str, old_player_id: str, new_player_id: str, reason: str, instance_id: int = None):
        super().__init__(timeout=None)  # Persistent view
        self.cog = cog
        self.discord_id = discord_id
        self.old_player_id = old_player_id
        self.new_player_id = new_player_id
        self.reason = reason
        self.instance_id = instance_id

        self.add_item(ApprovePlayerIdChangeButton(cog, discord_id, old_player_id, new_player_id, reason, instance_id))
        self.add_item(DenyPlayerIdChangeButton(cog, discord_id))


class ApprovePlayerIdChangeButton(discord.ui.Button):
    """Button to approve player ID change."""

    def __init__(self, cog, discord_id: str, old_player_id: str, new_player_id: str, reason: str, instance_id: int = None):
        super().__init__(
            label="Approve",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"approve_player_id_change:{discord_id}:{old_player_id}:{new_player_id}",
        )
        self.cog = cog
        self.discord_id = discord_id
        self.old_player_id = old_player_id
        self.new_player_id = new_player_id
        self.reason = reason
        self.instance_id = instance_id

    async def callback(self, interaction: discord.Interaction):
        """Approve the player ID change."""
        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import PlayerId

        # Check permissions
        is_bot_owner = await self.cog.bot.is_owner(interaction.user)
        is_approved_moderator = await self.cog.check_id_change_moderator_permission(interaction.user)

        if not (is_bot_owner or is_approved_moderator):
            await interaction.response.send_message("❌ You need to be in an approved moderator group to approve player ID changes.", ephemeral=True)
            return

        await interaction.response.defer()

        # Get pending change data
        def get_pending_data():
            data = self.cog.load_pending_player_id_changes_data()
            return data.get("pending_changes", {}).get(self.discord_id)

        pending = await sync_to_async(get_pending_data)()
        if not pending:
            await interaction.followup.send("❌ Pending change request not found.", ephemeral=True)
            return

        # Update database: Add new PlayerId and mark it primary
        def update_player_id():
            try:
                from thetower.backend.sus.models import GameInstance, LinkedAccount

                # Find the GameInstance to update
                if self.instance_id:
                    # Use the specified instance
                    game_instance = GameInstance.objects.filter(id=self.instance_id).first()
                    if not game_instance:
                        return {"status": "error", "message": "Could not find specified game instance"}
                else:
                    # Fallback: Find the GameInstance via the old player ID
                    old_player_id_obj = PlayerId.objects.filter(id=self.old_player_id).select_related("game_instance").first()
                    if not old_player_id_obj or not old_player_id_obj.game_instance:
                        return {"status": "error", "message": "Could not find game instance for old player ID"}
                    game_instance = old_player_id_obj.game_instance

                # Unmark all existing primary IDs in this instance
                game_instance.player_ids.filter(primary=True).update(primary=False)

                # Create new PlayerId and mark as primary
                if self.reason == "game_changed":
                    notes = f"Added via player ID change request (game changed ID) on {pending['timestamp']}"
                else:  # typo
                    notes = f"Added via player ID change request (corrected typo) on {pending['timestamp']}"

                PlayerId.objects.create(id=self.new_player_id, game_instance=game_instance, primary=True, notes=notes)

                # If reason is typo, delete the old player ID
                if self.reason == "typo":
                    PlayerId.objects.filter(id=self.old_player_id).delete()

                # Get Discord IDs for event dispatching
                discord_ids = list(
                    LinkedAccount.objects.filter(player=game_instance.player, platform=LinkedAccount.Platform.DISCORD).values_list(
                        "account_id", flat=True
                    )
                )

                return {
                    "status": "success",
                    "player_name": game_instance.player.name,
                    "old_primary": self.old_player_id,
                    "new_primary": self.new_player_id,
                    "discord_ids": discord_ids,
                }
            except Exception as e:
                return {"status": "error", "message": str(e)}

        result = await sync_to_async(update_player_id)()

        if result["status"] == "error":
            await interaction.followup.send(f"❌ Failed to update player ID: {result['message']}", ephemeral=True)
            return

        # Dispatch player_verified event for cache invalidation across all guilds
        if result.get("discord_ids"):
            for discord_id in result["discord_ids"]:
                self.cog.bot.dispatch("player_verified", interaction.guild.id, discord_id, result["new_primary"], result["old_primary"])

        # Remove pending change
        def remove_pending():
            data = self.cog.load_pending_player_id_changes_data()
            if "pending_changes" in data and self.discord_id in data["pending_changes"]:
                del data["pending_changes"][self.discord_id]
                self.cog.save_pending_player_id_changes_data(data)

        await sync_to_async(remove_pending)()

        # Update the log channel message embed
        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if embed:
            # Update status field
            for idx, field in enumerate(embed.fields):
                if field.name == "Status":
                    embed.set_field_at(idx, name="Status", value=f"✅ Approved by {interaction.user.mention}", inline=True)
                    break
            embed.color = discord.Color.green()

            # Remove buttons
            await interaction.message.edit(embed=embed, view=None)

        # Update the mod notification message if it exists
        if pending.get("mod_message_id") and pending.get("mod_channel_id"):
            try:
                mod_channel = self.cog.bot.get_channel(pending["mod_channel_id"])
                if mod_channel:
                    mod_message = await mod_channel.fetch_message(pending["mod_message_id"])
                    if mod_message and mod_message.embeds:
                        mod_embed = mod_message.embeds[0]
                        # Update status field
                        for idx, field in enumerate(mod_embed.fields):
                            if field.name == "Status":
                                mod_embed.set_field_at(idx, name="Status", value=f"✅ Approved by {interaction.user.mention}", inline=True)
                                break
                        mod_embed.color = discord.Color.green()
                        await mod_message.edit(embed=mod_embed, view=None)
            except Exception as e:
                self.cog.logger.warning(f"Could not update mod notification message: {e}")

        # Notify user
        try:
            user = await interaction.client.fetch_user(int(self.discord_id))
            await user.send(
                f"✅ **Player ID Change Approved!**\n\n"
                f"Your player ID has been updated from `{self.old_player_id}` to `{self.new_player_id}`.\n"
                f"Approved by {interaction.user.mention} in {interaction.guild.name}."
            )
        except Exception as e:
            self.cog.logger.warning(f"Could not DM user {self.discord_id} about approval: {e}")

        await interaction.followup.send("✅ Player ID change approved!", ephemeral=True)


class DenyPlayerIdChangeButton(discord.ui.Button):
    """Button to deny player ID change."""

    def __init__(self, cog, discord_id: str):
        super().__init__(label="Deny", style=discord.ButtonStyle.danger, emoji="❌", custom_id=f"deny_player_id_change:{discord_id}")
        self.cog = cog
        self.discord_id = discord_id

    async def callback(self, interaction: discord.Interaction):
        """Deny the player ID change."""
        from asgiref.sync import sync_to_async

        # Check permissions
        is_bot_owner = await self.cog.bot.is_owner(interaction.user)
        is_approved_moderator = await self.cog.check_id_change_moderator_permission(interaction.user)

        if not (is_bot_owner or is_approved_moderator):
            await interaction.response.send_message("❌ You need to be in an approved moderator group to deny player ID changes.", ephemeral=True)
            return

        await interaction.response.defer()

        # Remove pending change
        def remove_pending():
            data = self.cog.load_pending_player_id_changes_data()
            pending = data.get("pending_changes", {}).get(self.discord_id)
            if pending:
                if "pending_changes" in data and self.discord_id in data["pending_changes"]:
                    del data["pending_changes"][self.discord_id]
                    self.cog.save_pending_player_id_changes_data(data)
                return pending
            return None

        pending = await sync_to_async(remove_pending)()

        if not pending:
            await interaction.followup.send("❌ Pending change request not found.", ephemeral=True)
            return

        # Update the log channel message embed
        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if embed:
            # Update status field
            for idx, field in enumerate(embed.fields):
                if field.name == "Status":
                    embed.set_field_at(idx, name="Status", value=f"❌ Denied by {interaction.user.mention}", inline=True)
                    break
            embed.color = discord.Color.red()

            # Remove buttons
            await interaction.message.edit(embed=embed, view=None)

        # Update the mod notification message if it exists
        if pending.get("mod_message_id") and pending.get("mod_channel_id"):
            try:
                mod_channel = self.cog.bot.get_channel(pending["mod_channel_id"])
                if mod_channel:
                    mod_message = await mod_channel.fetch_message(pending["mod_message_id"])
                    if mod_message and mod_message.embeds:
                        mod_embed = mod_message.embeds[0]
                        # Update status field
                        for idx, field in enumerate(mod_embed.fields):
                            if field.name == "Status":
                                mod_embed.set_field_at(idx, name="Status", value=f"❌ Denied by {interaction.user.mention}", inline=True)
                                break
                        mod_embed.color = discord.Color.red()
                        await mod_message.edit(embed=mod_embed, view=None)
            except Exception as e:
                self.cog.logger.warning(f"Could not update mod notification message: {e}")

        # Notify user
        try:
            user = await interaction.client.fetch_user(int(self.discord_id))
            await user.send(
                f"❌ **Player ID Change Denied**\n\n"
                f"Your request to change from `{pending['old_player_id']}` to `{pending['new_player_id']}` was denied.\n"
                f"Denied by {interaction.user.mention} in {interaction.guild.name}.\n\n"
                f"If you believe this was an error, please contact a moderator."
            )
        except Exception as e:
            self.cog.logger.warning(f"Could not DM user {self.discord_id} about denial: {e}")

        await interaction.followup.send("❌ Player ID change denied.", ephemeral=True)


class DiscordAccountSelect(discord.ui.Select):
    """Select for choosing which Discord account to manage role source for."""

    def __init__(self, cog, player_id: int, all_discord_accounts: list, current_discord_id: str):
        # Create options for each linked Discord account
        options = []
        for account in all_discord_accounts:
            account_id = account["account_id"]
            display_name = account["display_name"]
            is_current = account_id == current_discord_id

            label = f"@{account_id}"
            if display_name:
                label += f" ({display_name})"
            if is_current:
                label += " (You)"

            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(account_id),
                    emoji="✅" if is_current else "🔗",
                )
            )

        super().__init__(
            placeholder="Select a Discord account to manage",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.cog = cog
        self.player_id = player_id
        self.current_discord_id = current_discord_id

    async def callback(self, interaction: discord.Interaction):
        """Handle account selection."""
        selected_account_id = self.values[0]

        await interaction.response.defer(ephemeral=True)
        await interaction.edit_original_response(content="⏳ Loading game instances...")

        # Get game instances and current role source for this account
        def get_account_role_config():
            from thetower.backend.sus.models import LinkedAccount

            try:
                linked_account = LinkedAccount.objects.get(
                    player_id=self.player_id,
                    platform=LinkedAccount.Platform.DISCORD,
                    account_id=selected_account_id,
                )

                # Get all game instances for this player
                from thetower.backend.sus.models import KnownPlayer, PlayerId

                player = KnownPlayer.objects.get(id=self.player_id)
                game_instances_raw = list(player.game_instances.all().values("id", "name", "primary"))

                # Add primary game ID to each instance
                game_instances = []
                for instance in game_instances_raw:
                    primary_player_id = PlayerId.objects.filter(game_instance_id=instance["id"], primary=True).first()
                    instance["primary_game_id"] = primary_player_id.id if primary_player_id else "Unknown"
                    game_instances.append(instance)

                return {
                    "status": "success",
                    "linked_account_id": linked_account.id,
                    "current_role_source_id": linked_account.role_source_instance_id,
                    "game_instances": game_instances,
                }
            except Exception as e:
                return {"status": "error", "message": str(e)}

        result = await sync_to_async(get_account_role_config)()

        if result["status"] == "success":
            game_instances = result["game_instances"]

            # Create game instance select view
            view = discord.ui.View(timeout=900)

            class GameInstanceSelect(discord.ui.Select):
                def __init__(self, cog, linked_account_id: int, current_role_source_id: int):
                    options = [discord.SelectOption(label="None (No Roles)", value="none", emoji="❌")]

                    for instance in game_instances:
                        label = instance["primary_game_id"]
                        if instance["primary"]:
                            label += " (Primary)"
                        is_current = instance["id"] == current_role_source_id
                        options.append(
                            discord.SelectOption(
                                label=label,
                                value=str(instance["id"]),
                                emoji="✅" if is_current else "🎮",
                            )
                        )

                    super().__init__(
                        placeholder="Select game instance for roles",
                        options=options,
                        min_values=1,
                        max_values=1,
                    )
                    self.cog = cog
                    self.linked_account_id = linked_account_id

                async def callback(self, interaction: discord.Interaction):
                    """Handle game instance selection."""
                    await interaction.response.defer(ephemeral=True)
                    await interaction.edit_original_response(content="⏳ Updating role source...")

                    selected_value = self.values[0]
                    new_role_source_id = None if selected_value == "none" else int(selected_value)

                    def update_role_source():
                        try:
                            from thetower.backend.sus.models import LinkedAccount

                            linked_account = LinkedAccount.objects.get(id=self.linked_account_id)
                            linked_account.role_source_instance_id = new_role_source_id
                            linked_account.save()
                            return {"status": "success"}
                        except Exception as e:
                            return {"status": "error", "message": str(e)}

                    result = await sync_to_async(update_role_source)()

                    if result["status"] == "success":
                        await interaction.edit_original_response(
                            content="✅ Role source updated. Loading verification info...",
                            view=None,
                        )

                        # Use the cog's helper method to build and display verification status
                        discord_id_str = str(interaction.user.id)
                        embed, verification_info, has_pending_link = await self.cog.build_verification_status_display(discord_id_str)

                        if embed:
                            view = VerificationStatusView(
                                self.cog,
                                verification_info,
                                discord_id_str,
                                has_pending_link=has_pending_link,
                                requesting_user=interaction.user,
                                can_manage_alt_links=False,
                            )

                            await interaction.edit_original_response(
                                content="**Your Verification Information**",
                                embed=embed,
                                view=view,
                            )
                        else:
                            await interaction.edit_original_response(
                                content="✅ Role source updated.",
                            )
                    else:
                        await interaction.edit_original_response(
                            content=f"❌ Error updating role source: {result.get('message', 'Unknown error')}",
                        )

            view.add_item(GameInstanceSelect(self.cog, result["linked_account_id"], result["current_role_source_id"]))

            await interaction.edit_original_response(
                content=f"🎮 **Manage Roles for Account {selected_account_id}**\n\nSelect which game instance this account should use for tournament roles.",
                view=view,
            )
        else:
            await interaction.edit_original_response(
                content=f"❌ Error loading account: {result.get('message', 'Unknown error')}",
            )


class ManageRolesView(discord.ui.View):
    """View for selecting which Discord account to manage role source for."""

    def __init__(self, cog, player_id: int, current_discord_id: str, all_discord_accounts: list):
        super().__init__(timeout=900)
        self.cog = cog
        self.player_id = player_id
        self.current_discord_id = current_discord_id
        self.add_item(DiscordAccountSelect(cog, player_id, all_discord_accounts, current_discord_id))


class CopyRoleSourceView(discord.ui.View):
    """View for asking if user wants to copy role source from another linked account."""

    def __init__(self, cog, new_linked_account_id: int, source_instance_id: int, source_player_id: str):
        super().__init__(timeout=900)
        self.cog = cog
        self.new_linked_account_id = new_linked_account_id
        self.source_instance_id = source_instance_id
        self.source_player_id = source_player_id

    @discord.ui.button(label="Yes, Copy Roles", style=discord.ButtonStyle.success, emoji="✅")
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Copy role source from existing account."""
        from thetower.backend.sus.models import LinkedAccount

        await interaction.response.defer(ephemeral=True)
        await interaction.edit_original_response(content="⏳ Updating role source...")

        def update_role_source():
            try:
                linked_account = LinkedAccount.objects.get(id=self.new_linked_account_id)
                linked_account.role_source_instance_id = self.source_instance_id
                linked_account.save()
                return {"status": "success"}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        result = await sync_to_async(update_role_source)()

        if result["status"] == "success":
            await interaction.edit_original_response(
                content=f"✅ Role source set to player ID **{self.source_player_id}**. Tournament roles will be assigned from this game instance.",
                view=None,
            )
        else:
            await interaction.edit_original_response(content=f"❌ Error updating role source: {result.get('message', 'Unknown error')}", view=None)

    @discord.ui.button(label="No, Keep Separate", style=discord.ButtonStyle.secondary, emoji="❌")
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Don't copy role source."""
        await interaction.response.defer(ephemeral=True)
        await interaction.edit_original_response(content="✅ Okay, your accounts will have separate tournament roles.", view=None)


class AcceptLinkView(discord.ui.View):
    """View for accepting or declining a pending link request."""

    def __init__(self, cog, alt_discord_id: str, pending_link: dict):
        super().__init__(timeout=900)
        self.cog = cog
        self.alt_discord_id = alt_discord_id
        self.pending_link = pending_link

    @discord.ui.button(label="Accept Link", style=discord.ButtonStyle.success, emoji="✅")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Accept the link request and create LinkedAccount."""
        from thetower.backend.sus.models import KnownPlayer, LinkedAccount

        await interaction.response.defer(ephemeral=True)

        # Show immediate processing indicator
        await interaction.edit_original_response(content="⏳ Processing your request...")

        def create_linked_account():
            try:
                player = KnownPlayer.objects.get(id=self.pending_link["player_id"])

                # Create verified LinkedAccount (ensure account_id is a string)
                new_linked_account = LinkedAccount.objects.create(
                    player=player,
                    platform=LinkedAccount.Platform.DISCORD,
                    account_id=str(self.alt_discord_id),
                    verified=True,
                )

                # Remove from pending links
                data = self.cog.load_pending_links_data()
                if "pending_links" in data and self.alt_discord_id in data["pending_links"]:
                    del data["pending_links"][self.alt_discord_id]
                    self.cog.save_pending_links_data(data)

                # Check if we should ask about copying role source
                should_ask_role_source = False
                source_instance_id = None
                source_player_id = None

                # If new account has no role source, check if player has other accounts with role source
                if not new_linked_account.role_source_instance_id:
                    from thetower.backend.sus.models import PlayerId

                    other_linked_accounts = (
                        LinkedAccount.objects.filter(player=player, platform=LinkedAccount.Platform.DISCORD)
                        .exclude(id=new_linked_account.id)
                        .select_related("role_source_instance")
                    )

                    for other_account in other_linked_accounts:
                        if other_account.role_source_instance_id:
                            should_ask_role_source = True
                            source_instance_id = other_account.role_source_instance_id
                            # Get the primary player ID for the source instance
                            primary_player_id = PlayerId.objects.filter(game_instance_id=other_account.role_source_instance_id, primary=True).first()
                            source_player_id = primary_player_id.id if primary_player_id else None
                            break

                # Get primary player ID for the newly linked account (for event dispatching)
                result_primary_player_id = None
                if player.game_instances.exists():
                    primary_instance = player.game_instances.filter(primary=True).first()
                    if primary_instance:
                        primary_pid = PlayerId.objects.filter(game_instance=primary_instance, primary=True).first()
                        result_primary_player_id = primary_pid.id if primary_pid else None

                return {
                    "status": "success",
                    "player_name": player.name,
                    "new_linked_account_id": new_linked_account.id,
                    "should_ask_role_source": should_ask_role_source,
                    "source_instance_id": source_instance_id,
                    "source_player_id": source_player_id,
                    "primary_player_id": result_primary_player_id,
                    "discord_id": str(self.alt_discord_id),
                }
            except Exception as e:
                return {"status": "error", "message": str(e)}

        result = await sync_to_async(create_linked_account)()

        if result["status"] == "success":
            # Assign verified role to the newly linked alt account
            verified_role_id = self.cog.get_setting("verified_role_id", guild_id=interaction.guild.id)
            role_assigned = False
            if verified_role_id:
                guild = interaction.guild
                member = interaction.user
                role = guild.get_role(verified_role_id)
                if role and role not in member.roles:
                    role_assigned = await self.cog._add_verified_role(member, role, "alt account link accepted")

            success_message = f"✅ **Link Accepted!**\n\nYour Discord account is now linked to **{result['player_name']}**."
            if role_assigned:
                success_message += f"\n{role.mention} role has been assigned."
            success_message += "\n\nRun `/verify` again to see your full verification status."

            # Remove buttons and edit the original message
            await interaction.edit_original_response(content=success_message, view=None)

            # Ask about copying role source if applicable
            if result.get("should_ask_role_source"):
                view = CopyRoleSourceView(self.cog, result["new_linked_account_id"], result["source_instance_id"], result["source_player_id"])
                await interaction.followup.send(
                    f"🎮 **Tournament Role Source**\n\n"
                    f"Your other linked account gets tournament roles from player ID **{result['source_player_id']}**.\n\n"
                    f"Would you like this account to also use **{result['source_player_id']}** for tournament roles?\n"
                    f"(If you select 'No', you can link this account to a different game instance later.)",
                    view=view,
                    ephemeral=True,
                )
            else:
                # Dispatch player_verified event for other cogs to react
                # For alt account links, there's no old primary (it's a new link to existing instance)
                if result.get("primary_player_id"):
                    self.cog.bot.dispatch("player_verified", interaction.guild.id, result["discord_id"], result["primary_player_id"])
        else:
            error_message = f"❌ Error creating link: {result.get('message', 'Unknown error')}"

            # Remove buttons and edit the original message
            await interaction.edit_original_response(content=error_message, view=None)

    @discord.ui.button(label="Decline Link", style=discord.ButtonStyle.danger, emoji="❌")
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Decline the link request."""
        await interaction.response.defer(ephemeral=True)

        # Show immediate processing indicator
        await interaction.edit_original_response(content="⏳ Processing your request...")

        def remove_pending_link():
            data = self.cog.load_pending_links_data()
            if "pending_links" in data and self.alt_discord_id in data["pending_links"]:
                del data["pending_links"][self.alt_discord_id]
                self.cog.save_pending_links_data(data)

        await sync_to_async(remove_pending_link)()

        # Remove buttons and edit the original message
        await interaction.edit_original_response(content="❌ Link request declined and removed.", view=None)
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)


class PendingIdChangesListView(discord.ui.View):
    """View for displaying list of pending player ID changes with selection dropdown."""

    def __init__(self, cog, pending_changes: dict, status_message: str = None):
        super().__init__(timeout=900)
        self.cog = cog
        self.pending_changes = pending_changes
        self.status_message = status_message

        # Add user selection dropdown
        if pending_changes:
            self.add_item(PendingIdChangeSelect(cog, pending_changes, status_message))

    def create_list_embed(self) -> discord.Embed:
        """Create embed showing list of pending changes."""
        embed = discord.Embed(
            title="⏳ Pending Player ID Change Requests",
            description="Select a user from the dropdown to review their request.",
            color=discord.Color.orange(),
        )

        # Show status message if provided
        if self.status_message:
            embed.add_field(name="Last Action", value=self.status_message, inline=False)

        # List all pending changes
        pending_list = []
        for discord_id, data in self.pending_changes.items():
            old_id = data.get("old_player_id", "Unknown")
            new_id = data.get("new_player_id", "Unknown")
            reason_emoji = "🎮" if data.get("reason") == "game_changed" else "✏️"
            pending_list.append(f"{reason_emoji} <@{discord_id}>: `{old_id}` → `{new_id}`")

        if pending_list:
            embed.add_field(
                name=f"Pending Requests ({len(pending_list)})",
                value="\n".join(pending_list),
                inline=False,
            )

        return embed


class PendingIdChangeSelect(discord.ui.Select):
    """Dropdown to select a pending ID change request to review."""

    def __init__(self, cog, pending_changes: dict, status_message: str = None):
        options = []
        for discord_id, data in pending_changes.items():
            old_id = data.get("old_player_id", "Unknown")
            new_id = data.get("new_player_id", "Unknown")
            reason_emoji = "🎮" if data.get("reason") == "game_changed" else "✏️"

            options.append(
                discord.SelectOption(
                    label=f"{old_id[:8]}... → {new_id[:8]}...",
                    value=discord_id,
                    description=f"User ID: {discord_id}",
                    emoji=reason_emoji,
                )
            )

        super().__init__(placeholder="Select a user to review...", options=options, row=0)
        self.cog = cog
        self.pending_changes = pending_changes
        self.status_message = status_message

    async def callback(self, interaction: discord.Interaction):
        """Show detail view for selected user."""
        selected_discord_id = self.values[0]
        pending_data = self.pending_changes.get(selected_discord_id)

        if not pending_data:
            await interaction.response.send_message("❌ Pending change not found.", ephemeral=True)
            return

        # Create detail view
        view = PendingIdChangeDetailView(
            self.cog,
            selected_discord_id,
            pending_data,
            self.pending_changes,
            self.status_message,
        )

        # Create embed with details
        embed = view.create_detail_embed(interaction.client)

        # Attach image if available
        file = None
        image_filename = pending_data.get("image_filename")
        if image_filename and (self.cog.data_directory / image_filename).exists():
            file = discord.File(self.cog.data_directory / image_filename, filename=image_filename)
            embed.set_image(url=f"attachment://{image_filename}")

        # Update message to show detail view
        if file:
            await interaction.response.edit_message(embed=embed, view=view, attachments=[file])
        else:
            await interaction.response.edit_message(embed=embed, view=view, attachments=[])


class PendingIdChangeDetailView(discord.ui.View):
    """View for displaying detailed pending ID change with approve/deny/cancel actions."""

    def __init__(self, cog, discord_id: str, pending_data: dict, all_pending: dict, status_message: str = None):
        super().__init__(timeout=900)
        self.cog = cog
        self.discord_id = discord_id
        self.pending_data = pending_data
        self.all_pending = all_pending
        self.status_message = status_message

        # Add action buttons
        self.add_item(
            ApprovePlayerIdChangeFromListButton(
                cog,
                discord_id,
                pending_data.get("old_player_id"),
                pending_data.get("new_player_id"),
                pending_data.get("reason"),
                pending_data.get("instance_id"),
                all_pending,
                status_message,
            )
        )
        self.add_item(DenyPlayerIdChangeFromListButton(cog, discord_id, all_pending, status_message))
        self.add_item(CancelDetailViewButton(cog, all_pending, status_message))

    def create_detail_embed(self, bot) -> discord.Embed:
        """Create embed showing detailed change request."""
        reason_display = "Game changed my ID" if self.pending_data.get("reason") == "game_changed" else "I typed the wrong ID"
        reason_emoji = "🎮" if self.pending_data.get("reason") == "game_changed" else "✏️"

        embed = discord.Embed(
            title=f"{reason_emoji} Player ID Change Request",
            color=discord.Color.orange(),
        )

        # Try to get user mention
        try:
            user = bot.get_user(int(self.discord_id))
            user_display = f"{user.mention}\n`{user.name}`" if user else f"<@{self.discord_id}>"
        except Exception:
            user_display = f"<@{self.discord_id}>"

        embed.add_field(name="Discord User", value=user_display, inline=True)
        embed.add_field(name="Discord ID", value=f"`{self.discord_id}`", inline=True)
        embed.add_field(name="Reason", value=reason_display, inline=True)
        embed.add_field(name="Old Player ID", value=f"`{self.pending_data.get('old_player_id')}`", inline=True)
        embed.add_field(name="New Player ID", value=f"`{self.pending_data.get('new_player_id')}`", inline=True)
        embed.add_field(name="Status", value="⏳ Pending Review", inline=True)

        return embed


class ApprovePlayerIdChangeFromListButton(discord.ui.Button):
    """Approve button that returns to list view with status."""

    def __init__(
        self, cog, discord_id: str, old_player_id: str, new_player_id: str, reason: str, instance_id: int, all_pending: dict, status_message: str
    ):
        super().__init__(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
        self.cog = cog
        self.discord_id = discord_id
        self.old_player_id = old_player_id
        self.new_player_id = new_player_id
        self.reason = reason
        self.instance_id = instance_id
        self.all_pending = all_pending
        self.status_message = status_message

    async def callback(self, interaction: discord.Interaction):
        """Approve the change and return to list."""
        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import PlayerId

        await interaction.response.defer()

        # Get pending change data
        def get_pending_data():
            data = self.cog.load_pending_player_id_changes_data()
            return data.get("pending_changes", {}).get(self.discord_id)

        pending = await sync_to_async(get_pending_data)()
        if not pending:
            await interaction.followup.send("❌ Pending change request not found.", ephemeral=True)
            return

        # Reuse existing approval logic from ApprovePlayerIdChangeButton
        def update_player_id():
            try:
                from thetower.backend.sus.models import GameInstance, LinkedAccount

                if self.instance_id:
                    game_instance = GameInstance.objects.filter(id=self.instance_id).first()
                    if not game_instance:
                        return {"status": "error", "message": "Could not find specified game instance"}
                else:
                    old_player_id_obj = PlayerId.objects.filter(id=self.old_player_id).select_related("game_instance").first()
                    if not old_player_id_obj or not old_player_id_obj.game_instance:
                        return {"status": "error", "message": "Could not find game instance for old player ID"}
                    game_instance = old_player_id_obj.game_instance

                game_instance.player_ids.filter(primary=True).update(primary=False)

                if self.reason == "game_changed":
                    notes = f"Added via player ID change request (game changed ID) on {pending['timestamp']}"
                else:
                    notes = f"Added via player ID change request (corrected typo) on {pending['timestamp']}"

                PlayerId.objects.create(id=self.new_player_id, game_instance=game_instance, primary=True, notes=notes)

                if self.reason == "typo":
                    PlayerId.objects.filter(id=self.old_player_id).delete()

                discord_ids = list(
                    LinkedAccount.objects.filter(player=game_instance.player, platform=LinkedAccount.Platform.DISCORD).values_list(
                        "account_id", flat=True
                    )
                )

                return {
                    "status": "success",
                    "player_name": game_instance.player.name,
                    "old_primary": self.old_player_id,
                    "new_primary": self.new_player_id,
                    "discord_ids": discord_ids,
                }
            except Exception as e:
                return {"status": "error", "message": str(e)}

        result = await sync_to_async(update_player_id)()

        if result["status"] == "error":
            await interaction.followup.send(f"❌ Failed to update player ID: {result['message']}", ephemeral=True)
            return

        # Dispatch player_verified event
        if result.get("discord_ids"):
            for discord_id in result["discord_ids"]:
                self.cog.bot.dispatch("player_verified", interaction.guild.id, discord_id, result["new_primary"], result["old_primary"])

        # Remove pending change and update messages
        def remove_pending():
            data = self.cog.load_pending_player_id_changes_data()
            pending_data = data.get("pending_changes", {}).get(self.discord_id)
            if "pending_changes" in data and self.discord_id in data["pending_changes"]:
                del data["pending_changes"][self.discord_id]
                self.cog.save_pending_player_id_changes_data(data)
            return pending_data

        removed_pending = await sync_to_async(remove_pending)()

        # Update both channel messages if they exist
        if removed_pending:
            # Update log channel message
            if removed_pending.get("log_message_id") and removed_pending.get("log_channel_id"):
                try:
                    log_channel = self.cog.bot.get_channel(removed_pending["log_channel_id"])
                    if log_channel:
                        log_message = await log_channel.fetch_message(removed_pending["log_message_id"])
                        if log_message and log_message.embeds:
                            log_embed = log_message.embeds[0]
                            for idx, field in enumerate(log_embed.fields):
                                if field.name == "Status":
                                    log_embed.set_field_at(idx, name="Status", value=f"✅ Approved by {interaction.user.mention}", inline=True)
                                    break
                            log_embed.color = discord.Color.green()
                            await log_message.edit(embed=log_embed, view=None)
                except Exception as e:
                    self.cog.logger.warning(f"Could not update log message: {e}")

            # Update mod notification message
            if removed_pending.get("mod_message_id") and removed_pending.get("mod_channel_id"):
                try:
                    mod_channel = self.cog.bot.get_channel(removed_pending["mod_channel_id"])
                    if mod_channel:
                        mod_message = await mod_channel.fetch_message(removed_pending["mod_message_id"])
                        if mod_message and mod_message.embeds:
                            mod_embed = mod_message.embeds[0]
                            for idx, field in enumerate(mod_embed.fields):
                                if field.name == "Status":
                                    mod_embed.set_field_at(idx, name="Status", value=f"✅ Approved by {interaction.user.mention}", inline=True)
                                    break
                            mod_embed.color = discord.Color.green()
                            await mod_message.edit(embed=mod_embed, view=None)
                except Exception as e:
                    self.cog.logger.warning(f"Could not update mod notification message: {e}")

        # Notify user
        try:
            user = await interaction.client.fetch_user(int(self.discord_id))
            await user.send(
                f"✅ **Player ID Change Approved!**\n\n"
                f"Your player ID has been updated from `{self.old_player_id}` to `{self.new_player_id}`.\n"
                f"Approved by {interaction.user.mention}."
            )
        except Exception as e:
            self.cog.logger.warning(f"Could not DM user {self.discord_id} about approval: {e}")

        # Return to list view with status
        del self.all_pending[self.discord_id]
        status_msg = f"✅ <@{self.discord_id}> ID `{self.old_player_id}` → `{self.new_player_id}` **Approved**"

        if self.all_pending:
            view = PendingIdChangesListView(self.cog, self.all_pending, status_msg)
            embed = view.create_list_embed()
            await interaction.edit_original_response(embed=embed, view=view, attachments=[])
        else:
            await interaction.edit_original_response(content=f"{status_msg}\n\n✅ No more pending requests.", embed=None, view=None, attachments=[])


class DenyPlayerIdChangeFromListButton(discord.ui.Button):
    """Deny button that returns to list view with status."""

    def __init__(self, cog, discord_id: str, all_pending: dict, status_message: str):
        super().__init__(label="Deny", style=discord.ButtonStyle.danger, emoji="❌")
        self.cog = cog
        self.discord_id = discord_id
        self.all_pending = all_pending
        self.status_message = status_message

    async def callback(self, interaction: discord.Interaction):
        """Deny the change and return to list."""
        from asgiref.sync import sync_to_async

        await interaction.response.defer()

        # Remove pending change
        def remove_pending():
            data = self.cog.load_pending_player_id_changes_data()
            pending = data.get("pending_changes", {}).get(self.discord_id)
            if pending:
                if "pending_changes" in data and self.discord_id in data["pending_changes"]:
                    del data["pending_changes"][self.discord_id]
                    self.cog.save_pending_player_id_changes_data(data)
                return pending
            return None

        pending = await sync_to_async(remove_pending)()

        if not pending:
            await interaction.followup.send("❌ Pending change request not found.", ephemeral=True)
            return

        # Update both channel messages
        # Update log channel message
        if pending.get("log_message_id") and pending.get("log_channel_id"):
            try:
                log_channel = self.cog.bot.get_channel(pending["log_channel_id"])
                if log_channel:
                    log_message = await log_channel.fetch_message(pending["log_message_id"])
                    if log_message and log_message.embeds:
                        log_embed = log_message.embeds[0]
                        for idx, field in enumerate(log_embed.fields):
                            if field.name == "Status":
                                log_embed.set_field_at(idx, name="Status", value=f"❌ Denied by {interaction.user.mention}", inline=True)
                                break
                        log_embed.color = discord.Color.red()
                        await log_message.edit(embed=log_embed, view=None)
            except Exception as e:
                self.cog.logger.warning(f"Could not update log message: {e}")

        # Update mod notification message
        if pending.get("mod_message_id") and pending.get("mod_channel_id"):
            try:
                mod_channel = self.cog.bot.get_channel(pending["mod_channel_id"])
                if mod_channel:
                    mod_message = await mod_channel.fetch_message(pending["mod_message_id"])
                    if mod_message and mod_message.embeds:
                        mod_embed = mod_message.embeds[0]
                        for idx, field in enumerate(mod_embed.fields):
                            if field.name == "Status":
                                mod_embed.set_field_at(idx, name="Status", value=f"❌ Denied by {interaction.user.mention}", inline=True)
                                break
                        mod_embed.color = discord.Color.red()
                        await mod_message.edit(embed=mod_embed, view=None)
            except Exception as e:
                self.cog.logger.warning(f"Could not update mod notification message: {e}")

        # Notify user
        try:
            user = await interaction.client.fetch_user(int(self.discord_id))
            await user.send(
                f"❌ **Player ID Change Denied**\n\n"
                f"Your request to change from `{pending['old_player_id']}` to `{pending['new_player_id']}` was denied.\n"
                f"Denied by {interaction.user.mention}.\n\n"
                f"If you believe this was an error, please contact a moderator."
            )
        except Exception as e:
            self.cog.logger.warning(f"Could not DM user {self.discord_id} about denial: {e}")

        # Return to list view with status
        old_id = pending.get("old_player_id", "Unknown")
        new_id = pending.get("new_player_id", "Unknown")
        del self.all_pending[self.discord_id]
        status_msg = f"❌ <@{self.discord_id}> ID `{old_id}` → `{new_id}` **Denied**"

        if self.all_pending:
            view = PendingIdChangesListView(self.cog, self.all_pending, status_msg)
            embed = view.create_list_embed()
            await interaction.edit_original_response(embed=embed, view=view, attachments=[])
        else:
            await interaction.edit_original_response(content=f"{status_msg}\n\n✅ No more pending requests.", embed=None, view=None, attachments=[])


class CancelDetailViewButton(discord.ui.Button):
    """Cancel button to return to list without action."""

    def __init__(self, cog, all_pending: dict, status_message: str):
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary, emoji="↩️")
        self.cog = cog
        self.all_pending = all_pending
        self.status_message = status_message

    async def callback(self, interaction: discord.Interaction):
        """Return to list view without taking action."""
        view = PendingIdChangesListView(self.cog, self.all_pending, self.status_message)
        embed = view.create_list_embed()
        await interaction.response.edit_message(embed=embed, view=view, attachments=[])

        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)


async def _fetch_discord_accounts(player_id: int):
    """Helper function to fetch Discord accounts for a player.

    Args:
        player_id: The KnownPlayer database ID

    Returns:
        Tuple of (accounts_list, error_message)
    """

    def get_discord_accounts():
        try:
            from thetower.backend.sus.models import KnownPlayer, LinkedAccount

            player = KnownPlayer.objects.filter(id=player_id).first()
            if not player:
                return None, "Player not found"

            # Get all Discord LinkedAccounts for this player (including inactive)
            accounts_qs = (
                LinkedAccount.objects.filter(player=player, platform=LinkedAccount.Platform.DISCORD)
                .select_related("role_source_instance")
                .order_by("-verified", "-primary", "account_id")
            )

            accounts = []
            for acc in accounts_qs:
                # Get primary player ID from the role source instance if it exists
                instance_info = None
                if acc.role_source_instance:
                    primary_pid = acc.role_source_instance.player_ids.filter(primary=True).first()
                    instance_info = {
                        "name": acc.role_source_instance.name,
                        "primary_id": primary_pid.id if primary_pid else None,
                    }

                accounts.append(
                    {
                        "id": acc.id,
                        "account_id": acc.account_id,
                        "display_name": acc.display_name,
                        "verified": acc.verified,
                        "primary": acc.primary,
                        "active": acc.active,
                        "verified_at": acc.verified_at,
                        "instance": instance_info,
                    }
                )

            return accounts, None
        except Exception as e:
            return None, str(e)

    return await sync_to_async(get_discord_accounts)()


class ManageDiscordAccountsButton(discord.ui.Button):
    """Button for mods to manage Discord accounts (mark as active/retired)."""

    def __init__(self, cog, player_id: int, guild_id: int):
        super().__init__(label="Manage Discord Account(s)", style=discord.ButtonStyle.secondary, emoji="⚙️", row=2)
        self.cog = cog
        self.player_id = player_id
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Open the Discord account management view."""
        await interaction.response.defer(ephemeral=True)

        accounts, error = await _fetch_discord_accounts(self.player_id)

        if error:
            await interaction.followup.send(f"❌ Error loading Discord accounts: {error}", ephemeral=True)
            return

        if not accounts:
            await interaction.followup.send("❌ No Discord accounts found for this player.", ephemeral=True)
            return

        view = ManageDiscordAccountsView(self.cog, self.player_id, accounts, self.guild_id)
        embed = view.create_embed()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class ManageDiscordAccountsView(discord.ui.View):
    """View for selecting a Discord account to manage."""

    def __init__(self, cog, player_id: int, accounts: list, guild_id: int):
        super().__init__(timeout=600)
        self.cog = cog
        self.player_id = player_id
        self.accounts = accounts
        self.guild_id = guild_id

        # Add account selection dropdown
        self.add_item(AccountSelectDropdown(self.cog, self.player_id, self.accounts, self.guild_id))

        # Add refresh button
        self.add_item(RefreshAccountsButton(self.cog, self.player_id, self.guild_id))

    def create_embed(self) -> discord.Embed:
        """Create embed showing all Discord accounts."""
        embed = discord.Embed(
            title="🔧 Manage Discord Accounts",
            description="Select a Discord account from the dropdown to enable or disable it.",
            color=discord.Color.blue(),
        )

        for account in self.accounts:
            account_id = account["account_id"]
            display_name = account["display_name"]
            verified = account["verified"]
            primary = account["primary"]
            active = account["active"]
            verified_at = account["verified_at"]
            instance = account.get("instance")

            # Build field name: emoji mention (display_name) primary_marker
            verified_emoji = "✅" if verified else "❓"
            primary_marker = " 🌟" if primary else ""

            if display_name:
                field_name = f"{verified_emoji} <@{account_id}> ({display_name}){primary_marker}"
            else:
                field_name = f"{verified_emoji} <@{account_id}>{primary_marker}"

            # Build status and verification on same line
            active_status = "🟢 Active" if active else "🔴 Retired"

            if verified and verified_at:
                if hasattr(verified_at, "timestamp"):
                    unix_timestamp = int(verified_at.timestamp())
                    if unix_timestamp == 1577836800:  # Historical placeholder date
                        verified_text = "Unknown date"
                    else:
                        verified_text = f"<t:{unix_timestamp}:R>"
                else:
                    verified_text = "Unknown date"
            else:
                verified_text = "Not verified"

            # Build instance info
            instance_text = ""
            if instance:
                instance_name = instance["name"]
                instance_primary_id = instance["primary_id"]
                if instance_primary_id:
                    instance_text = f"\nRoles from: {instance_name} (`{instance_primary_id}`)"
                else:
                    instance_text = f"\nRoles from: {instance_name}"
            else:
                instance_text = "\nRoles from: _Not assigned_"

            field_value = f"Status: {active_status} • Verified: {verified_text}{instance_text}"
            embed.add_field(name=field_name, value=field_value, inline=False)

        embed.set_footer(text="Retired accounts are hidden from regular users but visible to mods.")
        return embed


class AccountSelectDropdown(discord.ui.Select):
    """Dropdown to select a Discord account to manage."""

    def __init__(self, cog, player_id: int, accounts: list, guild_id: int):
        self.cog = cog
        self.player_id = player_id
        self.accounts = accounts
        self.guild_id = guild_id

        # Build options for dropdown
        options = []
        for account in accounts:
            account_id = account["account_id"]
            display_name = account["display_name"]
            active = account["active"]
            primary = account["primary"]

            # Build label
            label = display_name if display_name else f"Discord ID {account_id[:12]}..."
            if primary:
                label += " 🌟"

            # Build description
            status = "Active" if active else "Retired"
            description = f"Status: {status}"

            # Add emoji
            emoji = "🟢" if active else "🔴"

            options.append(discord.SelectOption(label=label, value=str(account["id"]), description=description, emoji=emoji))

        super().__init__(placeholder="Select a Discord account to manage...", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        """Handle account selection."""
        selected_id = int(self.values[0])
        selected_account = next((acc for acc in self.accounts if acc["id"] == selected_id), None)

        if not selected_account:
            await interaction.response.send_message("❌ Account not found.", ephemeral=True)
            return

        # Show confirmation view
        view = AccountConfirmationView(self.cog, self.player_id, selected_account, self.accounts, self.guild_id)
        embed = view.create_embed()
        await interaction.response.edit_message(embed=embed, view=view)


class AccountConfirmationView(discord.ui.View):
    """View for confirming enable/disable of a Discord account."""

    def __init__(self, cog, player_id: int, account: dict, all_accounts: list, guild_id: int):
        super().__init__(timeout=600)
        self.cog = cog
        self.player_id = player_id
        self.account = account
        self.all_accounts = all_accounts
        self.guild_id = guild_id

        # Add toggle button
        self.add_item(ConfirmToggleButton(self.cog, self.player_id, self.account, self.all_accounts, self.guild_id))

        # Add cancel button
        self.add_item(CancelButton(self.cog, self.player_id, self.all_accounts, self.guild_id))

    def create_embed(self) -> discord.Embed:
        """Create confirmation embed."""
        account_id = self.account["account_id"]
        display_name = self.account["display_name"]
        active = self.account["active"]
        verified = self.account["verified"]
        instance = self.account.get("instance")

        # Use display name or mention
        account_display = display_name if display_name else f"<@{account_id}>"

        # Determine action
        if active:
            action = "Disable"
            color = discord.Color.orange()
            description = "⚠️ **This account will be disabled.**\n\nThe Discord user will lose:\n• Verification role\n• Tournament roles\n• Access to verified channels"
        else:
            action = "Enable"
            color = discord.Color.green()
            description = "✅ **This account will be enabled.**\n\nThe Discord user will gain:\n• Verification role\n• Tournament roles\n• Access to verified channels"

        embed = discord.Embed(title=f"{action} Discord Account", description=description, color=color)

        # Add account info
        status = "🟢 Active" if active else "🔴 Retired"
        verified_status = "✅ Verified" if verified else "⏳ Not verified"

        info_text = f"**Discord:** {account_display}\n**Current Status:** {status}\n**Verification:** {verified_status}"

        if instance:
            instance_name = instance["name"]
            instance_primary_id = instance["primary_id"]
            if instance_primary_id:
                info_text += f"\n**Roles from:** {instance_name} (`{instance_primary_id}`)"
            else:
                info_text += f"\n**Roles from:** {instance_name}"
        else:
            info_text += "\n**Roles from:** _Not assigned_"

        embed.add_field(name="Account Information", value=info_text, inline=False)

        return embed


class ConfirmToggleButton(discord.ui.Button):
    """Button to confirm the toggle action."""

    def __init__(self, cog, player_id: int, account: dict, all_accounts: list, guild_id: int):
        active = account["active"]
        label = "Disable Account" if active else "Enable Account"
        style = discord.ButtonStyle.danger if active else discord.ButtonStyle.success
        emoji = "🔴" if active else "🟢"

        super().__init__(label=label, style=style, emoji=emoji, row=0)
        self.cog = cog
        self.player_id = player_id
        self.account = account
        self.all_accounts = all_accounts
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Execute the toggle action."""
        await interaction.response.defer(ephemeral=True)

        account_id = self.account["account_id"]
        linked_account_id = self.account["id"]
        current_active = self.account["active"]
        new_active = not current_active

        def toggle_active():
            try:
                from thetower.backend.sus.models import LinkedAccount

                linked_account = LinkedAccount.objects.get(id=linked_account_id)
                linked_account.active = new_active
                linked_account.save()
                return True, None, linked_account
            except Exception as e:
                return False, str(e), None

        success, error, linked_account = await sync_to_async(toggle_active)()

        if not success:
            await interaction.followup.send(f"❌ Error updating account: {error}", ephemeral=True)
            return

        # Update local account data in all_accounts
        for acc in self.all_accounts:
            if acc["id"] == linked_account_id:
                acc["active"] = new_active
                break

        # Dispatch custom event for validation cog to listen to
        # Pass the Discord account ID (as string) and the guild ID
        self.cog.bot.dispatch("discord_account_status_changed", account_id, self.guild_id, linked_account)

        # Return to main view
        view = ManageDiscordAccountsView(self.cog, self.player_id, self.all_accounts, self.guild_id)
        embed = view.create_embed()

        display_name = self.account["display_name"]
        account_display = display_name if display_name else f"<@{account_id}>"
        status_msg = f"✅ Account **{account_display}** has been **{'enabled' if new_active else 'disabled'}**."

        await interaction.edit_original_response(content=status_msg, embed=embed, view=view)


class CancelButton(discord.ui.Button):
    """Button to cancel and return to account list."""

    def __init__(self, cog, player_id: int, all_accounts: list, guild_id: int):
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌", row=0)
        self.cog = cog
        self.player_id = player_id
        self.all_accounts = all_accounts
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Return to main account list."""
        view = ManageDiscordAccountsView(self.cog, self.player_id, self.all_accounts, self.guild_id)
        embed = view.create_embed()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class RefreshAccountsButton(discord.ui.Button):
    """Button to refresh the Discord accounts list."""

    def __init__(self, cog, player_id: int, guild_id: int):
        super().__init__(label="Refresh", style=discord.ButtonStyle.primary, emoji="🔄", row=4)
        self.cog = cog
        self.player_id = player_id
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Refresh the accounts list."""
        await interaction.response.defer(ephemeral=True)

        accounts, error = await _fetch_discord_accounts(self.player_id)

        if error:
            await interaction.followup.send(f"❌ Error loading Discord accounts: {error}", ephemeral=True)
            return

        view = ManageDiscordAccountsView(self.cog, self.player_id, accounts, self.guild_id)
        embed = view.create_embed()
        await interaction.edit_original_response(embed=embed, view=view)
