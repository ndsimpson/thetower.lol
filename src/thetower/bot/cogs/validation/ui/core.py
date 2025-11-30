import datetime

import discord
from asgiref.sync import sync_to_async
from discord import ui


class VerificationModal(ui.Modal, title="Player Verification"):
    """Modal for player verification with player ID input and file upload."""

    player_id = ui.TextInput(
        label="Player ID",
        placeholder="Enter your 13-16 character player ID",
        min_length=13,
        max_length=16,
        required=True,
    )

    image_upload = ui.FileUpload()

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission and validate the player."""
        # Defer the response since validation might take time
        await interaction.response.defer(ephemeral=True)

        player_id = self.player_id.value.upper().strip()
        attachment = self.image_upload.attachment

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
            await interaction.followup.send("❌ Invalid player ID format. Player ID must be 13-16 hexadecimal characters.", ephemeral=True)
            return

        if len(player_id) < 13 or len(player_id) > 16:
            await self._log_verification_attempt(
                interaction, player_id, verification_time, timestamp_unix, image_filename, success=False, error_message="Invalid player ID length"
            )
            await interaction.followup.send("❌ Player ID must be between 13 and 16 characters long.", ephemeral=True)
            return

        if not attachment:
            await self._log_verification_attempt(
                interaction, player_id, verification_time, timestamp_unix, image_filename, success=False, error_message="No image uploaded"
            )
            await interaction.followup.send("❌ Please upload a screenshot showing your player ID.", ephemeral=True)
            return

        try:
            # Create or update player
            result = await sync_to_async(self.cog._create_or_update_player, thread_sensitive=True)(
                interaction.user.id, interaction.user.name, player_id
            )

            # Assign verified role
            verified_role_id = self.cog.get_setting("verified_role_id", guild_id=interaction.guild.id)
            role_assigned = False
            if verified_role_id:
                guild = interaction.guild
                member = interaction.user
                role = guild.get_role(verified_role_id)
                if role and role not in member.roles:
                    await member.add_roles(role)
                    role_assigned = True

            # Trigger immediate tournament role update
            tourney_roles_cog = self.cog.bot.get_cog("Tourney Roles")
            if tourney_roles_cog:
                try:
                    result = await tourney_roles_cog.refresh_user_roles_for_user(member.id, guild.id)
                    self.cog.logger.info(f"Applied tournament roles after verification: {result}")
                except Exception as e:
                    self.cog.logger.error(f"Error applying tournament roles after verification: {e}")

            # Log successful verification
            await self._log_verification_attempt(
                interaction, player_id, verification_time, timestamp_unix, image_filename, success=True, role_assigned=role_assigned
            )

            await interaction.followup.send("✅ Verification successful! You have been assigned the verified role.", ephemeral=True)

        except Exception as exc:
            # Log failed verification
            await self._log_verification_attempt(
                interaction, player_id, verification_time, timestamp_unix, image_filename, success=False, error_message=str(exc)
            )

            self.cog.logger.error(f"Verification error: {exc}")
            await interaction.followup.send(f"❌ Verification failed: {exc}", ephemeral=True)

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
                description=f"{interaction.user.mention} successfully verified their account.",
                color=discord.Color.green(),
                timestamp=verification_time,
            )
            if role_assigned:
                verified_role_id = self.cog.get_setting("verified_role_id", guild_id=interaction.guild.id)
                if verified_role_id:
                    role = interaction.guild.get_role(verified_role_id)
                    if role:
                        embed.add_field(name="Role Assigned", value=role.mention, inline=True)
        else:
            embed = discord.Embed(
                title="❌ Verification Failed",
                description=f"{interaction.user.mention} attempted verification but failed.",
                color=discord.Color.red(),
                timestamp=verification_time,
            )
            if error_message:
                embed.add_field(name="Error", value=error_message, inline=False)

        # Add common fields
        embed.add_field(name="Player ID", value=f"`{player_id}`", inline=True)
        embed.add_field(name="Discord Name", value=f"`{interaction.user.name}`", inline=True)
        embed.add_field(name="Discord ID", value=f"`{interaction.user.id}`", inline=True)

        # Add timestamps
        embed.add_field(name="Time (UTC)", value=f"<t:{timestamp_unix}:F>", inline=True)
        embed.add_field(name="Time (Relative)", value=f"<t:{timestamp_unix}:R>", inline=True)

        # Set user avatar
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        # Prepare file attachment if image was saved
        file = None
        if image_filename and (self.cog.data_directory / image_filename).exists():
            file = discord.File(self.cog.data_directory / image_filename, filename=image_filename)

        try:
            if file:
                await log_channel.send(embed=embed, file=file)
            else:
                await log_channel.send(embed=embed)
        except Exception as log_exc:
            self.cog.logger.error(f"Failed to log verification to channel {log_channel_id}: {log_exc}")
            self.cog.logger.error(f"Failed to log verification to channel {log_channel_id}: {log_exc}")
