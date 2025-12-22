# Standard library
import re
from typing import Any, Dict, List, Optional

# Third-party
import discord

# Local
from thetower.backend.sus.models import KnownPlayer
from thetower.bot.basecog import PermissionContext


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
        permission_context: PermissionContext,
        show_creator_code_button: bool = False,
        current_code: str = None,
        player=None,
        details: dict = None,
        embed_title: str = "Player Profile",
        show_tourney_roles_button: bool = False,
        user_id: int = None,
        guild_id: int = None,
        requesting_user: discord.User = None,
    ):
        super().__init__(timeout=900)
        self.cog = cog
        self.permission_context = permission_context
        self.show_creator_code_button = show_creator_code_button
        self.current_code = current_code
        self.player = player
        self.details = details
        self.embed_title = embed_title
        self.show_tourney_roles_button = show_tourney_roles_button
        self.user_id = user_id
        self.guild_id = guild_id
        self.requesting_user = requesting_user

        self.cog.logger.info(f"PlayerView.__init__ called with requesting_user={requesting_user}, details={bool(details)}, guild_id={guild_id}")

        # Extract player_id for extensions
        if player and hasattr(player, "tower_id"):
            self.player_id = player.tower_id
        elif details and details.get("primary_id"):
            self.player_id = details.get("primary_id")
        else:
            self.player_id = None

        # Determine if this is the user's own profile (only for verified players with discord_id)
        is_own_profile = False
        if self.player and self.requesting_user and details:
            player_discord_id = details.get("discord_id")
            is_own_profile = str(player_discord_id) == str(self.requesting_user.id) if player_discord_id else False

        # Only add the creator code button if this is the user's own profile and they meet role requirements
        if is_own_profile and details and details.get("is_verified"):
            show_button = True
            required_role_id = self.cog.creator_code_required_role_id
            if required_role_id is not None and guild_id:
                # Check if user has the required role
                guild = self.cog.bot.get_guild(guild_id)
                if guild:
                    member = guild.get_member(self.requesting_user.id)
                    if member:
                        show_button = any(role.id == required_role_id for role in member.roles)
                    else:
                        show_button = False
                else:
                    show_button = False

            if show_button:
                current_code = details.get("creator_code")
                self.add_item(SetCreatorCodeButton(self.cog, current_code))

        # Only add the tournament roles button if allowed and we have the required IDs
        # Note: Tournament roles button is now provided via UI extension registry

        # Only add the post publicly button if user has permission and we have required data
        if self.requesting_user and self.player and self.details:
            # Always add the basic post publicly button
            self.add_item(PostPubliclyButton(self.cog, self.player, self.details, self.embed_title, self.requesting_user, include_moderation=False))

            # Add the enhanced button only if user can see moderation records
            # Get the privileged groups from manage_sus cog settings
            privileged_groups = []
            if hasattr(self.cog.bot, "manage_sus") and self.cog.bot.manage_sus:
                privileged_groups = self.cog.bot.manage_sus.config.get_global_cog_setting(
                    "manage_sus",
                    "privileged_groups_for_moderation_records",
                    self.cog.bot.manage_sus.global_settings.get("privileged_groups_for_moderation_records", []),
                )

            can_see_moderation = self.permission_context.has_any_group(privileged_groups)
            # Don't show moderation records for own profile (privacy protection)
            is_own_profile = str(self.player.discord_id) == str(self.requesting_user.id) if self.player.discord_id else False
            if can_see_moderation and not is_own_profile:
                self.add_item(
                    PostPubliclyButton(self.cog, self.player, self.details, self.embed_title, self.requesting_user, include_moderation=True)
                )

        # Add buttons from registered UI extensions
        if self.requesting_user and self.details and self.guild_id:
            # Get all registered UI extension providers for player profiles
            extension_providers = self.cog.bot.cog_manager.get_ui_extensions("player_lookup")
            self.cog.logger.info(f"PlayerView: Found {len(extension_providers)} UI extensions for player_lookup")

            # Call each provider with permission context
            for provider_func in extension_providers:
                try:
                    self.cog.logger.info(f"PlayerView: Calling UI extension {provider_func.__name__}")
                    button = provider_func(self.details, self.requesting_user, self.guild_id, self.permission_context)
                    if button:
                        self.cog.logger.info(f"PlayerView: Adding button from {provider_func.__name__}")
                        self.add_item(button)
                    else:
                        self.cog.logger.info(f"PlayerView: No button returned from {provider_func.__name__}")
                except Exception as e:
                    self.cog.logger.error(f"Error getting button from UI extension provider {provider_func.__name__}: {e}", exc_info=True)
                    # Continue with other providers even if one fails

    @classmethod
    async def create(
        cls,
        cog,
        requesting_user: discord.User,
        show_creator_code_button: bool = False,
        current_code: str = None,
        player=None,
        details: dict = None,
        embed_title: str = "Player Profile",
        show_tourney_roles_button: bool = False,
        user_id: int = None,
        guild_id: int = None,
    ):
        """
        Async factory method to create PlayerView with automatic permission fetching.

        Args:
            cog: The cog instance
            requesting_user: The Discord user requesting the view
            ... (other parameters same as __init__)

        Returns:
            PlayerView: Initialized view with permission context
        """
        cog.logger.info(f"PlayerView.create called with requesting_user={requesting_user}, details={bool(details)}, guild_id={guild_id}")

        # Fetch permissions for the requesting user
        permission_context = await cog.get_user_permissions(requesting_user)

        return cls(
            cog=cog,
            permission_context=permission_context,
            show_creator_code_button=show_creator_code_button,
            current_code=current_code,
            player=player,
            details=details,
            embed_title=embed_title,
            show_tourney_roles_button=show_tourney_roles_button,
            user_id=user_id,
            guild_id=guild_id,
            requesting_user=requesting_user,
        )


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

        # Check if posting everywhere is allowed or if this channel is in the allowed list
        allow_everywhere = False
        allowed_channels = []
        if hasattr(self.cog.bot, "player_lookup") and self.cog.bot.player_lookup:
            allow_everywhere = self.cog.bot.player_lookup.is_post_publicly_allowed_everywhere(guild_id)
            allowed_channels = self.cog.bot.player_lookup.get_profile_post_channels(guild_id)

        if not allow_everywhere and channel_id not in allowed_channels:
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

        # Defer immediately to keep the interaction token alive; followup will send the embed
        try:
            await interaction.response.defer()
        except Exception as e:
            self.cog.logger.error(f"Failed to defer interaction for public profile: {e}")
            return

        # Check permissions for what information can be shown publicly
        show_all_ids = False
        if hasattr(self.cog.bot, "player_lookup") and self.cog.bot.player_lookup:
            show_all_ids = await self.cog.bot.player_lookup.check_show_all_ids_permission(self.requesting_user)

        # Create embed using the same logic as private profiles but with permission checks
        from .user import UserInteractions

        user_interactions = UserInteractions(self.cog)
        # Fetch permission context so info extensions (e.g., moderation) can be included
        permission_context = await self.cog.get_user_permissions(self.requesting_user)
        embed = await user_interactions.create_player_embed(
            self.player,
            self.details,
            title_prefix=self.embed_title,
            show_verification_message=True,
            discord_display_format="mention",
            show_all_ids=show_all_ids,
            requesting_user=self.requesting_user,
            permission_context=permission_context,
        )

        # Post publicly to the channel via followup (response was deferred)
        try:
            await interaction.followup.send(embed=embed)
        except Exception as e:
            self.cog.logger.error(f"Error posting public profile: {e}")
            try:
                await interaction.followup.send("❌ Failed to post profile publicly. Please try again.", ephemeral=True)
            except Exception as e2:
                self.cog.logger.error(f"Followup error response failed: {e2}")


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
        "all_ids": [{"id": pid.id, "primary": pid.primary} for pid in player_ids],
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
