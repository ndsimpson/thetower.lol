# Standard library
import re
from typing import Any, Dict, List, Optional

# Third-party
import discord

# Local
from thetower.backend.sus.models import KnownPlayer


class CreatorCodeModal(discord.ui.Modal, title="Set Creator Code"):
    """Modal for setting creator code."""

    def __init__(self, cog):
        super().__init__()
        self.cog = cog
        self.creator_code_input = discord.ui.TextInput(
            label="Creator Code", placeholder="Enter your creator code (letters and numbers only)", default="", required=False, max_length=50
        )
        self.add_item(self.creator_code_input)

    async def on_submit(self, interaction: discord.Interaction):
        discord_id = str(interaction.user.id)
        creator_code = self.creator_code_input.value.strip() if self.creator_code_input.value else None

        # Validate creator code format if provided
        if creator_code:
            is_valid, error_message = self.cog._validate_creator_code(creator_code)
            if not is_valid:
                embed = discord.Embed(title="Invalid Creator Code Format", description=error_message, color=discord.Color.red())
                embed.add_field(
                    name="Valid Format",
                    value=(
                        "Creator codes must be alphanumeric only:\n"
                        "• Only letters (A-Z, a-z) and numbers (0-9)\n"
                        "• No spaces, punctuation, or special characters\n\n"
                        "Examples:\n"
                        "✅ `thedisasterfish`\n"
                        "✅ `mycreatorcode`\n"
                        "✅ `playername123`\n"
                        "❌ `my code` (no spaces)\n"
                        "❌ `my_code` (no underscores)\n"
                        "❌ `player-name` (no hyphens)"
                    ),
                    inline=False,
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        try:
            # Find the player by Discord ID
            player = await _get_player_by_discord_id_async(discord_id)

            if not player:
                embed = discord.Embed(
                    title="Player Not Found", description="No player account found linked to your Discord ID.", color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Update the creator code
            old_code = player.creator_code
            player.creator_code = creator_code
            await _save_player_async(player)

            # Note: Cache clearing removed as known_players cog no longer exists

            # Create response embed
            if creator_code:
                embed = discord.Embed(
                    title="Creator Code Updated", description=f"Your creator code has been set to: **{creator_code}**", color=discord.Color.green()
                )
                if old_code and old_code != creator_code:
                    embed.add_field(name="Previous Code", value=old_code, inline=False)
            else:
                embed = discord.Embed(title="Creator Code Removed", description="Your creator code has been removed.", color=discord.Color.orange())
                if old_code:
                    embed.add_field(name="Previous Code", value=old_code, inline=False)

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            self.cog.logger.error(f"Error setting creator code for user {discord_id}: {e}")
            await interaction.response.send_message(f"❌ Error updating creator code: {e}", ephemeral=True)


class PlayerView(discord.ui.View):
    """Unified view with conditional buttons for player profiles and lookups."""

    def __init__(
        self,
        cog,
        show_creator_code_button: bool = False,
        current_code: str = None,
        player=None,
        details: dict = None,
        embed_title: str = "Player Profile",
        show_tourney_roles_button: bool = False,
        user_id: int = None,
        guild_id: int = None,
        requesting_user: discord.User = None,
        can_see_moderation: bool = False,
    ):
        super().__init__(timeout=900)
        self.cog = cog
        self.show_creator_code_button = show_creator_code_button
        self.current_code = current_code
        self.player = player
        self.details = details
        self.embed_title = embed_title
        self.show_tourney_roles_button = show_tourney_roles_button
        self.user_id = user_id
        self.guild_id = guild_id
        self.requesting_user = requesting_user
        self.can_see_moderation = can_see_moderation

        # Only add the creator code button if allowed
        if self.show_creator_code_button:
            self.add_item(SetCreatorCodeButton(self.cog, self.current_code))

        # Only add the tournament roles button if allowed and we have the required IDs
        if self.show_tourney_roles_button and self.user_id and self.guild_id:
            self.add_item(RefreshTourneyRolesButton(self.cog, self.user_id, self.guild_id))

        # Only add the post publicly button if user has permission and we have required data
        if self.requesting_user and self.player and self.details:
            # Always add the basic post publicly button
            self.add_item(PostPubliclyButton(self.cog, self.player, self.details, self.embed_title, self.requesting_user, include_moderation=False))

            # Add the enhanced button only if user can see moderation records
            if self.can_see_moderation:
                self.add_item(
                    PostPubliclyButton(self.cog, self.player, self.details, self.embed_title, self.requesting_user, include_moderation=True)
                )

        # Add buttons from registered UI extensions
        if self.requesting_user and self.player and self.guild_id:
            # Get all registered UI extension providers for player profiles
            extension_providers = self.cog.bot.cog_manager.get_ui_extensions("player_lookup")

            # Call each provider and add any buttons they return
            for provider_func in extension_providers:
                try:
                    button = provider_func(self.player, self.requesting_user, self.guild_id)
                    if button:
                        self.add_item(button)
                except Exception as e:
                    self.cog.logger.error(f"Error getting button from UI extension provider: {e}")
                    # Continue with other providers even if one fails


class SetCreatorCodeButton(discord.ui.Button):
    """Button to set creator code."""

    def __init__(self, cog, current_code: str = None):
        super().__init__(label="Set Creator Code", style=discord.ButtonStyle.primary, emoji="✏️")
        self.cog = cog
        self.current_code = current_code

    async def callback(self, interaction: discord.Interaction):
        """Button to open creator code modal."""
        modal = CreatorCodeModal(self.cog)
        if self.current_code:
            modal.creator_code_input.default = self.current_code
        await interaction.response.send_modal(modal)


class RefreshTourneyRolesButton(discord.ui.Button):
    """Button to refresh tournament roles."""

    def __init__(self, cog, user_id: int, guild_id: int):
        super().__init__(label="Update Tournament Roles", style=discord.ButtonStyle.primary, emoji="🔄")
        self.cog = cog
        self.user_id = user_id
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Button to refresh tournament roles."""
        await interaction.response.defer(ephemeral=True)

        try:
            # Get the Tournament Roles cog
            tourney_cog = self.cog.bot.get_cog("Tournament Roles")
            if not tourney_cog:
                await interaction.followup.send("❌ Tournament Roles system unavailable", ephemeral=True)
                return

            # Check if the cog is enabled for this guild
            if hasattr(self.cog.bot, "cog_manager"):
                cog_manager = self.cog.bot.cog_manager
                if not cog_manager.can_guild_use_cog("tourney_roles", self.guild_id):
                    await interaction.followup.send("❌ Tournament Roles not enabled for this server", ephemeral=True)
                    return

            # Call the public method to refresh roles
            result = await tourney_cog.refresh_user_roles_for_user(self.user_id, self.guild_id)

            # Send the result
            await interaction.followup.send(result, ephemeral=True)

        except Exception as e:
            self.cog.logger.error(f"Error refreshing tournament roles for user {self.user_id}: {e}")
            await interaction.followup.send(f"❌ Error updating roles: {str(e)}", ephemeral=True)


class PostPubliclyButton(discord.ui.Button):
    """Button to post profile publicly with permission checks."""

    def __init__(self, cog, player, details: dict, embed_title: str, requesting_user: discord.User, include_moderation: bool = False):
        label = "Post Publicly (with Mod Records)" if include_moderation else "Post Publicly"
        emoji = "🚨" if include_moderation else "📢"
        super().__init__(label=label, style=discord.ButtonStyle.secondary, emoji=emoji)
        self.cog = cog
        self.player = player
        self.details = details
        self.embed_title = embed_title
        self.requesting_user = requesting_user
        self.include_moderation = include_moderation

    async def callback(self, interaction: discord.Interaction):
        """Button to post profile publicly to the channel."""
        guild_id = interaction.guild.id
        channel_id = interaction.channel.id

        # Check if this channel is configured for profile posting
        allowed_channels = []
        if hasattr(self.cog.bot, "player_lookup") and self.cog.bot.player_lookup:
            allowed_channels = self.cog.bot.player_lookup.get_profile_post_channels(guild_id)

        if channel_id not in allowed_channels:
            embed = discord.Embed(
                title="Channel Not Authorized", description="This channel is not configured for public profile posting.", color=discord.Color.red()
            )
            embed.add_field(
                name="What you can do",
                value="• The profile is still visible privately above\n• Ask a server admin to add this channel to the profile posting list\n• Use `/profile` or `/lookup` in authorized channels to post publicly",
                inline=False,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check if user has permission to post in this channel (basic permission check)
        try:
            # Check if user can send messages in this channel
            if not interaction.channel.permissions_for(interaction.user).send_messages:
                embed = discord.Embed(
                    title="Permission Denied", description="You don't have permission to send messages in this channel.", color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
        except Exception as e:
            self.cog.logger.error(f"Error checking channel permissions: {e}")
            await interaction.response.send_message("❌ Error checking permissions. Please try again.", ephemeral=True)
            return

        # Check permissions for what information can be shown publicly
        show_all_ids = False
        if hasattr(self.cog.bot, "player_lookup") and self.cog.bot.player_lookup:
            show_all_ids = await self.cog.bot.player_lookup.check_show_all_ids_permission(self.requesting_user)
        show_moderation_records = self.include_moderation

        # Create embed using the same logic as private profiles but with permission checks
        from .user import UserInteractions

        user_interactions = UserInteractions(self.cog)
        embed = await user_interactions.create_player_embed(
            self.player,
            self.details,
            title_prefix=self.embed_title,
            show_verification_message=True,
            discord_display_format="mention",
            show_all_ids=show_all_ids,
            show_moderation_records=show_moderation_records,
        )

        # Post publicly to the channel
        try:
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            self.cog.logger.error(f"Error posting public profile: {e}")
            await interaction.response.send_message("❌ Failed to post profile publicly. Please try again.", ephemeral=True)


class ProfileView(discord.ui.View):
    """Legacy view - redirects to PlayerView for backward compatibility."""

    def __init__(self, cog, current_code: str = None, player=None, details: dict = None):
        # Redirect to unified PlayerView
        raise DeprecationWarning("ProfileView is deprecated. Use PlayerView instead.")


class LookupView(discord.ui.View):
    """Legacy view - redirects to PlayerView for backward compatibility."""

    def __init__(self, cog, player=None, details: dict = None):
        # Redirect to unified PlayerView
        raise DeprecationWarning("LookupView is deprecated. Use PlayerView instead.")


# Business Logic Functions


async def get_player_details(player: KnownPlayer) -> Dict[str, Any]:
    """Get detailed information about a player"""
    # Fetch player IDs
    player_ids = await _get_player_ids_async(player)

    # Find primary ID
    primary_id = next((pid.id for pid in player_ids if pid.primary), None)

    # Return formatted details
    return {
        "name": player.name,
        "discord_id": player.discord_id,
        "creator_code": player.creator_code,
        "approved": player.approved,
        "primary_id": primary_id,
        "all_ids": [pid.id for pid in player_ids],
        "ids_count": len(player_ids),
    }


async def _get_player_ids_async(player: KnownPlayer) -> List:
    """Async wrapper for getting player IDs"""
    from asgiref.sync import sync_to_async

    return await sync_to_async(list)(player.ids.all())


async def _get_player_by_discord_id_async(discord_id: str) -> Optional[KnownPlayer]:
    """Async wrapper for finding player by Discord ID"""
    from asgiref.sync import sync_to_async

    return await sync_to_async(lambda: KnownPlayer.objects.filter(discord_id=discord_id).first())()


async def _save_player_async(player: KnownPlayer) -> None:
    """Async wrapper for saving player"""
    from asgiref.sync import sync_to_async

    await sync_to_async(player.save)()


def validate_creator_code(code: str) -> tuple[bool, str]:
    """
    Validate creator code format - only one emoji allowed at the end, no punctuation or URLs.

    Args:
        code: The creator code to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not code or not code.strip():
        return True, ""  # Empty codes are allowed (removes code)

    code = code.strip()

    # Check for URLs (basic patterns)
    url_patterns = [r"https?://", r"www\.", r"\.com", r"\.org", r"\.net", r"\.io", r"\.co", r"\.me"]

    for pattern in url_patterns:
        if re.search(pattern, code, re.IGNORECASE):
            return False, "Creator codes cannot contain URLs or web addresses."

    # Check for punctuation and spaces (no punctuation or spaces allowed)
    # Allow only letters and numbers
    forbidden_characters = re.compile(r'[.,;:!?@#$%^&*()+=\[\]{}|\\<>"`~\/\-_\s]')
    if forbidden_characters.search(code):
        forbidden_chars = forbidden_characters.findall(code)
        return False, f"Creator codes can only contain letters and numbers. Found: {', '.join(set(forbidden_chars))}"

    # Regex pattern to match emojis (Unicode ranges for most common emojis)
    emoji_pattern = re.compile(
        r"[\U0001F600-\U0001F64F]|"  # emoticons
        r"[\U0001F300-\U0001F5FF]|"  # symbols & pictographs
        r"[\U0001F680-\U0001F6FF]|"  # transport & map symbols
        r"[\U0001F1E0-\U0001F1FF]|"  # flags (iOS)
        r"[\U00002702-\U000027B0]|"  # dingbats
        r"[\U000024C2-\U0001F251]"  # enclosed characters
    )

    # Find all emojis in the code
    emojis = emoji_pattern.findall(code)

    if len(emojis) == 0:
        return True, ""  # No emojis is fine
    elif len(emojis) > 1:
        return False, f"Only one emoji is allowed. Found {len(emojis)} emojis: {''.join(emojis)}"

    # Check if the single emoji is at the end
    emoji = emojis[0]
    if not code.endswith(emoji):
        return False, f"The emoji '{emoji}' must be at the end of your creator code."

    return True, ""
