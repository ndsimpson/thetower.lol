# Third-party
import re

import discord

# Local
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

        # Create standardized details dict for extensions
        if is_unverified:
            # Create consistent details dict for unverified players
            standardized_details = {
                "name": player.name,
                "primary_id": player.tower_id,
                "all_ids": [{"id": player.tower_id, "primary": True}],
                "is_verified": False,
            }
        else:
            # For verified players, add is_verified flag to existing details
            standardized_details = dict(details)  # Copy existing details
            standardized_details["is_verified"] = True

        # Get values from standardized details
        primary_id = standardized_details["primary_id"]
        player_name = standardized_details["name"]
        discord_id = standardized_details.get("discord_id")
        creator_code = standardized_details.get("creator_code")

        # Format display name for header (Discord name for verified, tourney name for unverified)
        if is_unverified:
            display_name = player_name
        else:
            if discord_id:
                try:
                    # Try to get the Discord user to show their display name
                    discord_user = self.cog.bot.get_user(int(discord_id))
                    if discord_user:
                        display_name = discord_user.display_name
                    else:
                        # User not found, fall back to mention or ID
                        display_name = f"<@{discord_id}>" if discord_display_format == "mention" else discord_id
                except (ValueError, TypeError):
                    # Invalid discord_id, fall back to mention or ID
                    display_name = f"<@{discord_id}>" if discord_display_format == "mention" else discord_id
            else:
                display_name = player_name

        # Create header with name and optional Discord ID
        status_emoji = "⚠️" if is_unverified else "✅"
        if discord_id:
            embed_description = f"👤 {display_name} ({discord_id}) {status_emoji}\n{primary_id}"
        else:
            embed_description = f"👤 {display_name} {status_emoji}\n{primary_id}"

        # Create embed with streamlined title and description
        embed = discord.Embed(
            title=f"{title_prefix}",
            description=embed_description,
            color=discord.Color.orange() if is_unverified else discord.Color.green(),
        )

        # Add creator code field if it exists (only for verified players)
        if not is_unverified and creator_code:
            embed.add_field(
                name="Creator Code",
                value=f"`{creator_code}`",
                inline=True,
            )

        # Add additional player IDs if the verified player has multiple IDs
        if not is_unverified and show_all_ids:
            ids_list = details.get("all_ids", [])
            if len(ids_list) > 1:
                # Show additional IDs (excluding the primary which is already in header)
                additional_ids = [pid["id"] for pid in ids_list if pid["id"] != primary_id]
                if additional_ids:
                    embed.add_field(
                        name=f"Additional Player IDs ({len(additional_ids)})",
                        value="\n".join(additional_ids),
                        inline=False,
                    )

        # Add info extensions from other cogs
        if requesting_user:
            info_providers = self.cog.bot.cog_manager.get_info_extensions("player_lookup")
            for provider_func in info_providers:
                try:
                    extension_fields = await provider_func(standardized_details, requesting_user, permission_context)
                    if extension_fields:
                        for field in extension_fields:
                            embed.add_field(**field)
                except Exception as e:
                    self.cog.logger.warning(f"Error calling info extension provider {provider_func.__name__}: {e}")

        return embed

    async def create_lookup_embed(self, player, details: dict, requesting_user: discord.User) -> discord.Embed:
        """Create lookup embed for player details."""
        # Get permission context for the requesting user
        permission_context = await self.cog.get_user_permissions(requesting_user)

        # Check if the requesting user can see all IDs
        show_all_ids = await self._check_show_all_ids_permission(requesting_user)

        return await self.create_player_embed(
            player,
            details,
            title_prefix="Player Details",
            show_verification_message=False,
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

                player_ids = await sync_to_async(list)(player.ids.all())
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

                discord_mention = f"<@{player.discord_id}>" if player.discord_id else "Not set"
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

        # Check if lookups are restricted to known users
        restrict_lookups = self.cog.restrict_lookups_to_known_users

        if restrict_lookups:
            discord_id = str(interaction.user.id)
            # Check if user has a KnownPlayer record
            from asgiref.sync import sync_to_async

            from thetower.backend.sus.models import KnownPlayer

            known_player = await sync_to_async(KnownPlayer.objects.filter(discord_id=discord_id).first)()
            if not known_player:
                embed = discord.Embed(
                    title="Access Restricted",
                    description="Player lookups are restricted to verified users only. You must verify your account first.",
                    color=discord.Color.red(),
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

        # Determine what to search for
        identifier = identifier.strip()
        # Parse Discord mentions to extract user ID
        identifier = self.parse_discord_mention(identifier)
        results = await self.cog.search_player(identifier)

        if not results:
            search_display = f"'{identifier}'"
            await interaction.followup.send(f"No players found matching {search_display}", ephemeral=True)
            return

        if len(results) == 1:
            player = results[0]
            if isinstance(player, self.cog.UnverifiedPlayer):
                # Handle unverified player
                embed = await self.create_player_embed(player, title_prefix="Player Details", requesting_user=interaction.user)
                await interaction.followup.send(embed=embed, ephemeral=True)
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
                    show_creator_code_button=False,
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
                embed = await self.create_lookup_embed(player, details, interaction.user)
                # Create view with post publicly button (permissions are now handled automatically)
                view = PlayerView(
                    self.cog,
                    show_creator_code_button=False,
                    player=player,
                    details=details,
                    embed_title="Player Details",
                    requesting_user=interaction.user,
                    guild_id=interaction.guild.id,
                )
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            elif len(unverified_results) == 1 and not verified_results:
                # Only one unverified result
                player = unverified_results[0]
                embed = await self.create_player_embed(player, title_prefix="Player Profile", requesting_user=interaction.user)
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                # Multiple results
                embed = await self.create_multiple_results_embed(results, identifier, interaction.user)
                await interaction.followup.send(embed=embed, ephemeral=True)

    async def handle_profile_command(self, interaction: discord.Interaction, identifier: str) -> None:
        """Handle the /profile slash command."""
        if not await self.cog.wait_until_ready():
            await interaction.response.send_message("⏳ Still initializing, please try again shortly.", ephemeral=True)
            return

        # Defer the response to prevent timeout (gives us 15 minutes instead of 3 seconds)
        await interaction.response.defer(ephemeral=True)

        # Parse Discord mentions to extract user ID if needed
        identifier = self.parse_discord_mention(identifier)

        # Try to find player by the identifier (should be Discord ID for profile)
        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import KnownPlayer

        player = await sync_to_async(KnownPlayer.objects.filter(discord_id=identifier).first)()

        if not player:
            embed = await self.create_unverified_embed()
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Get player details
        details = await get_player_details(player)
        # Add is_verified flag for extensions
        details["is_verified"] = True

        # Get permission context for the requesting user
        permission_context = await self.cog.get_user_permissions(interaction.user)

        # Create profile embed (always shows verification message for profiles)
        embed = await self.create_player_embed(
            player,
            details,
            title_prefix="Player Profile",
            show_verification_message=True,
            discord_display_format="id",
            show_all_ids=await self._check_show_all_ids_permission(interaction.user),
            requesting_user=interaction.user,
            permission_context=permission_context,
        )

        # Check if tournament roles button should be shown
        show_tourney_roles_button = False
        tourney_cog = self.cog.bot.get_cog("Tournament Roles")
        if tourney_cog and hasattr(self.cog.bot, "cog_manager"):
            cog_manager = self.cog.bot.cog_manager
            show_tourney_roles_button = cog_manager.can_guild_use_cog("tourney_roles", interaction.guild.id)

        # Check if creator code button should be shown (only if user has required role or no role is required)
        show_creator_code_button = True
        required_role_id = self.cog.creator_code_required_role_id
        if required_role_id is not None:
            # Check if user has the required role
            member = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
            if member:
                show_creator_code_button = any(role.id == required_role_id for role in member.roles)
            else:
                show_creator_code_button = False

        # Create view with set creator code button and optionally tournament roles button
        view = await PlayerView.create(
            self.cog,
            requesting_user=interaction.user,
            show_creator_code_button=show_creator_code_button,
            current_code=details.get("creator_code"),
            player=player,
            details=details,
            embed_title="Player Profile",
            show_tourney_roles_button=show_tourney_roles_button,
            user_id=int(identifier),
            guild_id=interaction.guild.id,
        )

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
