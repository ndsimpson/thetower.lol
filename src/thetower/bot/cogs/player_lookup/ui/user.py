# Third-party
import re

import discord

# Local
from thetower.backend.tourney_results.formatting import BASE_URL

from .core import PlayerView, get_player_details


class UserInteractions:
    """User-facing interaction flows for the Player Lookup cog."""

    def __init__(self, cog):
        self.cog = cog

    def parse_discord_mention(self, identifier: str) -> str:
        """Parse Discord mention format and extract user ID.

        Handles formats like <@123456789> and <@!123456789>

        Args:
            identifier: The identifier that might contain a Discord mention

        Returns:
            The user ID if a mention was found, otherwise the original identifier
        """
        # Match Discord mention patterns: <@user_id> or <@!user_id>
        mention_pattern = re.compile(r"<@!?(\d+)>")
        match = mention_pattern.match(identifier.strip())

        if match:
            return match.group(1)  # Return the user ID

        return identifier  # Return original if no mention found

    async def create_unverified_embed(self) -> discord.Embed:
        """Create embed for unverified users."""
        embed = discord.Embed(
            title="Account Not Verified",
            description="Your Discord account is not linked to a verified player account.",
            color=discord.Color.orange(),
        )

        embed.add_field(
            name="What is verification?",
            value="Player verification links your Discord account to your in-game player data. This allows you to use personalized features and ensures accurate player identification.",
            inline=False,
        )

        embed.add_field(
            name="How to get verified",
            value="Contact a server administrator or moderator to link your Discord account to your player data.",
            inline=False,
        )

        return embed

    def _build_standardized_details(self, player, details: dict = None) -> dict:
        """Build standardized details dict for verified or unverified players.

        Args:
            player: The KnownPlayer or UnverifiedPlayer object
            details: Player details dictionary (for verified players, None for unverified)

        Returns:
            Standardized details dict with consistent structure
        """
        is_unverified = isinstance(player, self.cog.UnverifiedPlayer)

        if is_unverified:
            # Create consistent details dict for unverified players
            return {
                "name": player.name,
                "primary_id": player.tower_id,
                "player_ids": [{"id": player.tower_id, "primary": True}],
                "is_verified": False,
            }
        else:
            # For verified players, add is_verified flag to existing details
            standardized_details = dict(details)  # Copy existing details
            standardized_details["is_verified"] = True
            return standardized_details

    async def create_player_embed(
        self,
        player,
        details: dict = None,
        title_prefix: str = "Player Profile",
        show_verification_message: bool = True,
        discord_display_format: str = "id",
        show_all_ids: bool = True,
        requesting_user: discord.User = None,
        permission_context=None,
    ) -> discord.Embed:
        """Create player embed with configurable display options.

        Args:
            player: The KnownPlayer or UnverifiedPlayer object
            details: Player details dictionary (required for KnownPlayer, ignored for UnverifiedPlayer)
            title_prefix: Prefix for the embed title (e.g., "Player Profile", "Player Details")
            show_verification_message: Whether to show verification message in description
            discord_display_format: "id" for Discord ID, "mention" for Discord mention
            show_all_ids: Whether to show all player IDs or just the primary ID
            requesting_user: The Discord user requesting the embed (for permission checks)
            permission_context: Permission context for the requesting user (optional, None for public info)
        """
        # Check if this is an unverified player
        is_unverified = isinstance(player, self.cog.UnverifiedPlayer)

        if is_unverified:
            return await self._create_unverified_player_embed(player, title_prefix)

        # Verified player - use GameInstance structure
        return await self._create_verified_player_embed(
            player, details, title_prefix, discord_display_format, show_all_ids, requesting_user, permission_context
        )

    async def _create_unverified_player_embed(self, player, title_prefix: str) -> discord.Embed:
        """Create embed for unverified player (simple layout)."""
        player_name = player.name
        primary_id = player.tower_id

        # Create header with status
        status_emoji = "⚠️"
        embed_description = f"👤 {player_name} {status_emoji}"

        # Create embed
        embed = discord.Embed(
            title=f"{title_prefix}",
            description=embed_description,
            color=discord.Color.orange(),
        )

        # Add player name and ID fields (copyable)
        embed.add_field(
            name="Player Name",
            value=f"`{player_name}`",
            inline=True,
        )

        embed.add_field(
            name="Primary Player ID",
            value=f"`{primary_id}`",
            inline=True,
        )

        # Add player links
        bracket_url = f"https://{BASE_URL}/livebracketview?player_id={primary_id}"
        comparison_url = f"https://{BASE_URL}/comparison?bracket_player={primary_id}"
        placement_url = f"https://{BASE_URL}/liveplacement?player_id={primary_id}"
        player_history_url = f"https://{BASE_URL}/player?player={primary_id}"

        links_value = (
            f"[Player History]({player_history_url})\n"
            f"[Bracket View]({bracket_url}) • [Comparison]({comparison_url}) • [Live Placement Analysis]({placement_url})"
        )
        embed.add_field(name="Player Links", value=links_value, inline=False)

        return embed

    async def _create_verified_player_embed(
        self, player, details: dict, title_prefix: str, discord_display_format: str, show_all_ids: bool, requesting_user, permission_context
    ) -> discord.Embed:
        """Create embed for verified player with GameInstance structure.

        Uses equal treatment for all game instances, with primary marked by ⭐.
        Supports per-instance extension system for other cogs to inject info.
        """
        account_name = details["account_name"]
        creator_code = details.get("creator_code")
        game_instances = details["game_instances"]
        unassigned_discord_accounts = details.get("unassigned_discord_accounts", [])

        # Create header with status
        status_emoji = "✅"
        embed_description = f"👤 {account_name} {status_emoji}"
        if creator_code:
            embed_description += f"\nCreator Code: `{creator_code}`"

        # Create embed
        embed = discord.Embed(
            title=f"{title_prefix}",
            description=embed_description,
            color=discord.Color.green(),
        )

        # Get extension providers once
        info_providers = self.cog.bot.cog_manager.get_info_extensions("player_lookup") if requesting_user else []

        # Loop through all game instances (equal treatment)
        for instance in game_instances:
            instance_name = instance["name"]
            is_primary = instance["primary"]
            discord_accounts = instance["discord_accounts_receiving_roles"]
            primary_player_id = instance["primary_player_id"]
            player_ids = instance["player_ids"]

            # Build instance field value lines
            instance_lines = []

            # Discord accounts receiving roles
            if discord_accounts:
                discord_display = ", ".join(f"<@{did}>" for did in discord_accounts)
                instance_lines.append(f"Discord: {discord_display}")
            else:
                instance_lines.append("Discord: *(no roles assigned)*")

            # Additional IDs if has permission (primary is in field name)
            if show_all_ids and len(player_ids) > 1:
                additional_ids = [pid["id"] for pid in player_ids if not pid["primary"]]
                if additional_ids:
                    additional_ids_display = ", ".join(f"`{pid}`" for pid in additional_ids)
                    instance_lines.append(f"Additional IDs: {additional_ids_display}")

            # Player links for this instance
            bracket_url = f"https://{BASE_URL}/livebracketview?player_id={primary_player_id}"
            comparison_url = f"https://{BASE_URL}/comparison?bracket_player={primary_player_id}"
            placement_url = f"https://{BASE_URL}/liveplacement?player_id={primary_player_id}"
            player_history_url = f"https://{BASE_URL}/player?player={primary_player_id}"

            links = f"[History]({player_history_url}) • [Bracket]({bracket_url}) • [Comparison]({comparison_url}) • [Placement]({placement_url})"
            instance_lines.append(links)

            # Call extension providers for this specific instance
            # This allows other cogs (like tourney_live_data) to inject info per game account
            if info_providers:
                instance_details = {
                    "account_name": account_name,
                    "name": account_name,
                    "primary_id": primary_player_id,
                    "creator_code": creator_code,
                    "is_verified": True,
                    "game_instance": instance,  # Current instance
                    "game_instances": game_instances,  # All instances for context
                }

                for provider_func in info_providers:
                    try:
                        extension_fields = await provider_func(instance_details, requesting_user, permission_context)
                        if extension_fields:
                            # Add extension content as lines within this instance's field
                            for field in extension_fields:
                                # Extract field value and add as lines
                                field_name = field.get("name", "")
                                field_value = field.get("value", "")
                                if field_name and field_value:
                                    instance_lines.append(f"\n**{field_name}**")
                                    instance_lines.append(field_value)
                                elif field_value:
                                    instance_lines.append(f"\n{field_value}")
                    except Exception as e:
                        self.cog.logger.warning(f"Error calling info extension provider {provider_func.__name__}: {e}")

            # Add field for this instance - use primary player ID as field name
            field_name = f"🎮 `{primary_player_id}`"
            if is_primary:
                field_name += " ⭐"

            embed.add_field(
                name=field_name,
                value="\n".join(instance_lines),
                inline=False,
            )

        # Add unassigned Discord accounts section if any exist
        if unassigned_discord_accounts:
            unassigned_display = ", ".join(f"<@{did}> (No roles assigned)" for did in unassigned_discord_accounts)
            embed.add_field(
                name="🔗 Other Linked Discord Accounts",
                value=unassigned_display,
                inline=False,
            )

        return embed

    async def create_lookup_embed(self, player, details: dict, requesting_user: discord.User) -> discord.Embed:
        """Create lookup embed for player details."""
        # Get permission context for the requesting user
        permission_context = await self.cog.get_user_permissions(requesting_user)

        # Check if the requesting user can see all IDs
        show_all_ids = await self._check_show_all_ids_permission(requesting_user)

        # Determine if this is a verified player
        is_verified = not isinstance(player, self.cog.UnverifiedPlayer)

        return await self.create_player_embed(
            player,
            details,
            title_prefix="Player Details",
            show_verification_message=is_verified,  # Always show for verified players
            discord_display_format="mention",
            show_all_ids=show_all_ids,
            requesting_user=requesting_user,
            permission_context=permission_context,
        )

    async def create_multiple_results_embed(self, results: list, search_term: str, requesting_user: discord.User) -> discord.Embed:
        """Create embed for multiple search results."""
        # Check if the requesting user can see all IDs
        show_all_ids = await self._check_show_all_ids_permission(requesting_user)

        embed = discord.Embed(
            title="Multiple Players Found",
            description=f"Found {len(results)} players matching '{search_term}'. Showing first 5:",
            color=discord.Color.gold(),
        )

        for i, player in enumerate(results[:5], 1):
            if isinstance(player, self.cog.UnverifiedPlayer):
                # Handle unverified player
                player_info = f"**Name:** {player.name}\n**Player ID:** {player.tower_id}"
                embed.add_field(name=f"Player #{i} (Unverified)", value=player_info, inline=False)
            else:
                # Handle verified player
                from asgiref.sync import sync_to_async

                from thetower.backend.sus.models import PlayerId

                player_ids = await sync_to_async(list)(PlayerId.objects.filter(game_instance__player=player))
                primary_id = next((pid.id for pid in player_ids if pid.primary), None)

                formatted_ids = []
                if primary_id:
                    if show_all_ids:
                        formatted_ids.append(f"✅ {primary_id}")
                        other_ids = [pid.id for pid in player_ids if pid.id != primary_id]
                        formatted_ids.extend(other_ids[:2])
                    else:
                        # Just show primary ID without special formatting
                        formatted_ids.append(primary_id)
                elif show_all_ids:
                    formatted_ids.extend([pid.id for pid in player_ids[:3]])

                id_list = ", ".join(formatted_ids)
                if show_all_ids and len(player_ids) > 3:
                    id_list += f" (+{len(player_ids) - 3} more)"
                elif not show_all_ids and len(player_ids) > 1:
                    id_list += f" (+{len(player_ids) - 1} more)"

                # Get primary Discord account from LinkedAccount (not deprecated discord_id field)
                from thetower.backend.sus.models import LinkedAccount

                primary_discord_account = await sync_to_async(
                    LinkedAccount.objects.filter(player=player, platform=LinkedAccount.Platform.DISCORD, primary=True).first
                )()
                discord_mention = f"<@{primary_discord_account.account_id}>" if primary_discord_account else "Not set"
                player_info = f"**Name:** {player.name}\n**Discord:** {discord_mention}\n**Player IDs:** {id_list}"

                embed.add_field(name=f"Player #{i}", value=player_info, inline=False)

        if len(results) > 5:
            embed.set_footer(text=f"{len(results) - 5} more results not shown. Be more specific.")

        return embed

    async def _check_show_all_ids_permission(self, discord_user: discord.User) -> bool:
        """Check if a Discord user can see all player IDs."""
        return await self.cog.check_show_all_ids_permission(discord_user)

    async def handle_lookup_command(self, interaction: discord.Interaction, identifier: str) -> None:
        """Handle the /lookup slash command."""
        if not await self.cog.wait_until_ready():
            await interaction.response.send_message("⏳ Still initializing, please try again shortly.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Check if calling user is verified (required to use lookup commands)
        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import LinkedAccount

        user_discord_id = str(interaction.user.id)

        def check_user_verified():
            # Ensure we're checking with the Discord ID as a string
            return LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=str(user_discord_id)).exists()

        is_user_verified = await sync_to_async(check_user_verified)()

        if not is_user_verified:
            # User is not verified - check if validation cog is available
            validation_available = False
            if hasattr(self.cog.bot, "validation"):
                validation_cog = self.cog.bot.validation
                # Check if validation cog is enabled for this guild
                validation_enabled = validation_cog.get_setting("enabled", guild_id=interaction.guild.id, default=True)
                validation_available = validation_enabled

            if validation_available:
                # Validation cog is available - prompt them to verify
                embed = discord.Embed(
                    title="Verification Required",
                    description="You must verify your Discord account before using player lookup commands.\n\n"
                    "Verification links your Discord account to your in-game player data.",
                    color=discord.Color.orange(),
                )
                embed.add_field(
                    name="How to get verified",
                    value="Run the `/verify` command to link your Discord account to your player profile.",
                    inline=False,
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            else:
                # Validation cog not available or not enabled
                embed = discord.Embed(
                    title="Verification Required",
                    description="You must verify your Discord account before using player lookup commands.\n\n"
                    "Player verification is required to access this feature.",
                    color=discord.Color.orange(),
                )
                embed.add_field(
                    name="What to do",
                    value="Contact a server administrator or moderator to get your Discord account verified.",
                    inline=False,
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

        # Determine what to search for
        identifier = identifier.strip()
        # Parse Discord mentions to extract user ID
        identifier = self.parse_discord_mention(identifier)
        # Normalize case: uppercase for potential player IDs, but search handles this internally
        results = await self.cog.search_player(identifier)

        if not results:
            # Check if this looks like a player ID format (hexadecimal 0-9A-F, 12-16 chars)
            # and if the user has moderation permissions, offer to create an unverified entry
            clean_id = identifier.replace(" ", "").upper()
            is_valid_hex = all(c in "0123456789ABCDEF" for c in clean_id)
            is_valid_length = 12 <= len(clean_id) <= 16
            is_player_id_format = is_valid_hex and is_valid_length

            # Check if it looks like they tried to enter a player ID but with invalid characters
            if is_valid_length and not is_valid_hex:
                invalid_chars = [c for c in clean_id if c not in "0123456789ABCDEF"]
                await interaction.followup.send(
                    f"❌ Invalid player ID format. Player IDs can only contain hexadecimal characters (0-9, A-F).\n"
                    f"Invalid characters found: {', '.join(set(invalid_chars))}",
                    ephemeral=True,
                )
                return

            if is_player_id_format:
                # Check if user has moderation permissions
                discord_id = str(interaction.user.id)

                async def check_moderation_permission():
                    try:
                        from thetower.backend.sus.models import LinkedAccount

                        def get_player_and_groups():
                            linked_account = (
                                LinkedAccount.objects.filter(platform=LinkedAccount.Platform.DISCORD, account_id=discord_id)
                                .select_related("player__django_user")
                                .first()
                            )
                            if not linked_account or not linked_account.player or not linked_account.player.django_user:
                                return None, None, None
                            player = linked_account.player
                            user_groups = list(player.django_user.groups.values_list("name", flat=True))
                            return player.name, user_groups, True

                        player_name, user_groups, has_user = await sync_to_async(get_player_and_groups)()

                        if not has_user:
                            return False

                        # Get moderation permission groups from manage_sus cog
                        if hasattr(self.cog.bot, "manage_sus"):
                            manage_groups = self.cog.bot.manage_sus.config.get_global_cog_setting(
                                "manage_sus", "manage_groups", self.cog.bot.manage_sus.global_settings["manage_groups"]
                            )
                            return any(group in manage_groups for group in user_groups)
                        else:
                            return False
                    except Exception as e:
                        self.cog.logger.error(f"Error checking moderation permission: {e}", exc_info=True)
                        return False

                has_mod_permission = await check_moderation_permission()

                if has_mod_permission:
                    # Create an UnverifiedPlayer entry for this ID so moderation buttons work
                    player = self.cog.UnverifiedPlayer(identifier.upper())
                    details = self._build_standardized_details(player, None)
                    embed = await self.create_lookup_embed(player, details, interaction.user)

                    # Add a note that this is a new player ID
                    embed.set_footer(text="⚠️ New player ID - not found in existing records.  Double-check the id before moderation actions.")

                    view = await PlayerView.create(
                        self.cog,
                        requesting_user=interaction.user,
                        player=player,
                        details=details,
                        embed_title="Player Details",
                        guild_id=interaction.guild.id,
                    )
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                    return

            search_display = f"'{identifier}'"
            await interaction.followup.send(f"No players found matching {search_display}", ephemeral=True)
            return

        if len(results) == 1:
            player = results[0]
            if isinstance(player, self.cog.UnverifiedPlayer):
                # Handle unverified player using the same lookup embed flow
                details = self._build_standardized_details(player, None)
                embed = await self.create_lookup_embed(player, None, interaction.user)
                # Create view with same infrastructure as verified lookups
                view = await PlayerView.create(
                    self.cog,
                    requesting_user=interaction.user,
                    player=player,
                    details=details,
                    embed_title="Player Details",
                    guild_id=interaction.guild.id,
                )
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                # Handle verified player
                details = await get_player_details(player)
                # Add is_verified flag for extensions
                details["is_verified"] = True
                embed = await self.create_lookup_embed(player, details, interaction.user)
                # Create view with post publicly button (permissions are now handled automatically)
                view = await PlayerView.create(
                    self.cog,
                    requesting_user=interaction.user,
                    player=player,
                    details=details,
                    embed_title="Player Details",
                    guild_id=interaction.guild.id,
                )
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            # Multiple results - separate verified and unverified
            verified_results = [r for r in results if not isinstance(r, self.cog.UnverifiedPlayer)]
            unverified_results = [r for r in results if isinstance(r, self.cog.UnverifiedPlayer)]

            if len(verified_results) == 1 and not unverified_results:
                # Only one verified result
                player = verified_results[0]
                details = await get_player_details(player)
                details = self._build_standardized_details(player, details)
                embed = await self.create_lookup_embed(player, details, interaction.user)
                # Create view with post publicly button (permissions are now handled automatically)
                view = await PlayerView.create(
                    self.cog,
                    requesting_user=interaction.user,
                    player=player,
                    details=details,
                    embed_title="Player Details",
                    guild_id=interaction.guild.id,
                )
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            elif len(unverified_results) == 1 and not verified_results:
                # Only one unverified result
                player = unverified_results[0]
                details = self._build_standardized_details(player, None)
                # Use the same lookup embed flow for unverified
                embed = await self.create_lookup_embed(player, None, interaction.user)
                # Create view with same infrastructure as verified lookups
                view = await PlayerView.create(
                    self.cog,
                    requesting_user=interaction.user,
                    player=player,
                    details=details,
                    embed_title="Player Details",
                    guild_id=interaction.guild.id,
                )
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                # Multiple results
                embed = await self.create_multiple_results_embed(results, identifier, interaction.user)
                await interaction.followup.send(embed=embed, ephemeral=True)

    async def handle_profile_command(self, interaction: discord.Interaction, identifier: str) -> None:
        """Handle the /profile slash command by routing to lookup with user's Discord ID."""
        # Profile is just a lookup of the user's own Discord ID
        await self.handle_lookup_command(interaction, str(interaction.user.id))
