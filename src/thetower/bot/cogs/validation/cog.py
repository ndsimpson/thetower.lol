import logging

import discord
from discord import app_commands

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
        self.default_settings = {
            "verified_role_id": None,  # Role ID for verified users
            "verification_log_channel_id": None,  # Channel ID for logging verifications
            "approved_unverify_groups": [],  # List of Django group names that can un-verify players
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
        hex_digits = set("0123456789abcdef")
        contents = set(text.strip().lower())
        return contents | hex_digits == hex_digits

    @app_commands.command(name="verify", description="Verify your player ID to gain access to the server")
    @app_commands.guild_only()
    async def verify_slash(self, interaction: discord.Interaction) -> None:
        """Slash command to start the verification process."""
        # Check if user is already verified
        verified_role_id = self.get_setting("verified_role_id", guild_id=interaction.guild.id)
        if verified_role_id:
            member = interaction.user
            role = interaction.guild.get_role(verified_role_id)
            if role and role in member.roles:
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

    def register_ui_extensions(self) -> None:
        """Register UI extensions for other cogs."""
        self.bot.cog_manager.register_ui_extension(
            "player_lookup",
            "Validation",
            self.provide_unverify_button,
        )

    def provide_unverify_button(self, player, requesting_user, guild_id):
        """UI extension provider for un-verify button in player profiles.

        Args:
            player: The KnownPlayer instance
            requesting_user: The Discord user requesting the profile
            guild_id: The guild ID where the request is made

        Returns:
            UnverifyButton if user has permission, None otherwise
        """
        # Check if the requesting user has permission to un-verify
        # Get approved groups from settings
        approved_groups = self.config.get_global_cog_setting("validation", "approved_unverify_groups", [])

        if not approved_groups:
            return None  # No groups configured for un-verification

        # For UI extension providers, we return the button and do permission checking in the callback
        # This avoids async issues when called from the player_lookup cog
        from .ui.core import UnverifyButton

        return UnverifyButton(self, player, requesting_user, guild_id)

    async def cog_unload(self) -> None:
        """Clean up when unloading."""
        pass

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
                "validation", "approved_unverify_groups", self.default_settings["approved_unverify_groups"]
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
                return False

            member = guild.get_member(discord_id)
            if not member:
                return False

            verified_role_id = self.get_setting("verified_role_id", guild_id=guild_id)
            if not verified_role_id:
                return False

            role = guild.get_role(verified_role_id)
            if not role or role not in member.roles:
                return False

            await member.remove_roles(role)
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
        # First, un-verify in database
        db_result = self._unverify_player(discord_id, requesting_user)
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
                        description=f"Player with Discord ID `{discord_id}` has been un-verified.",
                        color=discord.Color.red(),
                        timestamp=discord.utils.utcnow(),
                    )

                    embed.add_field(name="Requested by", value=f"`{requesting_user.username}`", inline=True)
                    embed.add_field(name="Discord ID", value=f"`{discord_id}`", inline=True)

                    # Show role removal results
                    removed_count = sum(1 for result in role_removal_results if result["role_removed"])
                    embed.add_field(name="Roles Removed", value=f"{removed_count} guilds", inline=True)

                    try:
                        await log_channel.send(embed=embed)
                    except Exception as log_exc:
                        logger.error(f"Failed to log un-verification to channel {log_channel_id}: {log_exc}")

                    # Only log to one channel to avoid spam
                    break
