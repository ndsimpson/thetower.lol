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
        details: dict,
        title_prefix: str = "Player Profile",
        show_verification_message: bool = True,
        discord_display_format: str = "id",
        show_all_ids: bool = True,
        show_moderation_records: bool = False,
    ) -> discord.Embed:
        """Create player embed with configurable display options.

        Args:
            player: The KnownPlayer object
            details: Player details dictionary
            title_prefix: Prefix for the embed title (e.g., "Player Profile", "Player Details")
            show_verification_message: Whether to show verification message in description
            discord_display_format: "id" for Discord ID, "mention" for Discord mention
            show_all_ids: Whether to show all player IDs or just the primary ID
            show_moderation_records: Whether to show active moderation records
        """
        # Create embed with configurable title and description
        description = "✅ Account is verified" if show_verification_message else None
        embed = discord.Embed(
            title=f"{title_prefix}: {details['name'] or 'Unknown'}",
            description=description,
            color=discord.Color.green() if show_verification_message else discord.Color.blue(),
        )

        # Format Discord display
        if discord_display_format == "mention":
            discord_display = f"<@{details['discord_id']}>" if details["discord_id"] else "Not set"
        else:  # "id" format
            discord_display = details["discord_id"] or "Not set"

        # Build basic info field
        basic_info_parts = [
            f"**Name:** {details['name'] or 'Not set'}",
            f"**Discord:** {discord_display}",
            f"**Creator Code:** {details.get('creator_code') or 'Not set'}",
        ]

        embed.add_field(
            name="Basic Info",
            value="\n".join(basic_info_parts),
            inline=False,
        )

        # Format player IDs
        primary_id = details["primary_id"]
        ids_list = details["all_ids"]

        formatted_ids = []
        if primary_id:
            if show_all_ids:
                formatted_ids.append(f"✅ **{primary_id}** (Primary)")
                # Show all IDs except primary (already added)
                ids_list = [pid["id"] for pid in ids_list if pid["id"] != primary_id]
                formatted_ids.extend(ids_list)
            else:
                # Just show the primary ID without special formatting
                formatted_ids.append(primary_id)
        elif show_all_ids:
            # No primary ID, show all IDs
            formatted_ids.extend([pid["id"] for pid in ids_list])

        # Use singular "Player ID" when showing only primary, plural when showing all
        field_name = "Player IDs" if show_all_ids else "Player ID"
        if show_all_ids:
            field_name += f" ({len(details['all_ids'])})"

        embed.add_field(
            name=field_name,
            value="\n".join(formatted_ids) if formatted_ids else "No IDs found",
            inline=False,
        )

        # Add moderation records if enabled
        if show_moderation_records:
            from asgiref.sync import sync_to_async
            from django.db import models

            from thetower.backend.sus.models import ModerationRecord

            # Get primary tower ID for this player
            primary_tower_id = None
            for pid in details.get("all_ids", []):
                if pid.get("primary"):
                    primary_tower_id = pid["id"]
                    break

            # Get active moderation records for this player (both by known_player and tower_id)
            active_moderations = []
            if primary_tower_id:
                active_moderations = await sync_to_async(list)(
                    ModerationRecord.objects.filter(resolved_at__isnull=True)  # Only active (unresolved) records
                    .filter(models.Q(known_player=player) | models.Q(tower_id=primary_tower_id))
                    .order_by("started_at")
                )

            if active_moderations:
                moderation_lines = []
                for mod in active_moderations:
                    status_emoji = {"sus": "🚨", "ban": "🚫", "shun": "🔇", "soft_ban": "⚠️"}.get(mod.moderation_type, "❓")

                    started_date = mod.started_at.strftime("%Y-%m-%d")
                    reason = mod.reason[:50] + "..." if mod.reason and len(mod.reason) > 50 else mod.reason or "No reason provided"

                    moderation_lines.append(f"{status_emoji} **{mod.get_moderation_type_display()}** - {started_date}")
                    moderation_lines.append(f"   └ {reason}")

                embed.add_field(
                    name=f"Active Moderation ({len(active_moderations)})",
                    value="\n".join(moderation_lines),
                    inline=False,
                )
            else:
                embed.add_field(
                    name="Moderation Status",
                    value="✅ No active moderation records",
                    inline=False,
                )

        return embed

    async def create_lookup_embed(self, player, details: dict, requesting_user: discord.User) -> discord.Embed:
        """Create lookup embed for player details."""
        # Check if the requesting user can see all IDs
        show_all_ids = await self._check_show_all_ids_permission(requesting_user)
        # Check if the requesting user can see moderation records
        # IMPORTANT: Users should NEVER see their own moderation records for privacy
        is_own_profile = str(requesting_user.id) == details.get("discord_id")
        show_moderation_records = not is_own_profile and await self._check_show_moderation_records_permission(requesting_user)

        return await self.create_player_embed(
            player,
            details,
            title_prefix="Player Details",
            show_verification_message=False,
            discord_display_format="mention",
            show_all_ids=show_all_ids,
            show_moderation_records=show_moderation_records,
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
                player_info = f"**Name:** {player.name}\n**Player ID:** {player.tower_id}\n**Status:** Unverified"
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

    async def create_unverified_player_embed(self, player, requesting_user: discord.User) -> discord.Embed:
        """Create embed for an unverified player found through moderation records."""
        embed = discord.Embed(
            title="Unverified Player Found",
            description="This player has moderation records but is not verified in our system.",
            color=discord.Color.orange(),
        )

        embed.add_field(
            name="Player ID",
            value=f"`{player.tower_id}`",
            inline=False,
        )

        # Show moderation records for this unverified player
        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import ModerationRecord

        active_moderations = await sync_to_async(list)(
            ModerationRecord.objects.filter(resolved_at__isnull=True, tower_id=player.tower_id).order_by(  # Only active (unresolved) records
                "started_at"
            )
        )

        if active_moderations:
            moderation_lines = []
            for mod in active_moderations:
                status_emoji = {"sus": "🚨", "ban": "🚫", "shun": "🔇", "soft_ban": "⚠️"}.get(mod.moderation_type, "❓")

                started_date = mod.started_at.strftime("%Y-%m-%d")
                reason = mod.reason[:50] + "..." if mod.reason and len(mod.reason) > 50 else mod.reason or "No reason provided"

                moderation_lines.append(f"{status_emoji} **{mod.get_moderation_type_display()}** - {started_date}")
                moderation_lines.append(f"   └ {reason}")

            embed.add_field(
                name=f"Active Moderation ({len(active_moderations)})",
                value="\n".join(moderation_lines),
                inline=False,
            )
        else:
            embed.add_field(
                name="Moderation Status",
                value="No active moderation records found.",
                inline=False,
            )

        embed.set_footer(text="This player is not verified. Information may be limited.")
        return embed

    async def _check_show_all_ids_permission(self, discord_user: discord.User) -> bool:
        """Check if a Discord user can see all player IDs."""
        return await self.cog.check_show_all_ids_permission(discord_user)

    async def _check_show_moderation_records_permission(self, discord_user: discord.User) -> bool:
        """Check if a Discord user can see moderation records."""
        return await self.cog.check_show_moderation_records_permission(discord_user)

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
                embed = await self.create_unverified_player_embed(player, interaction.user)
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                # Handle verified player
                details = await get_player_details(player)
                embed = await self.create_lookup_embed(player, details, interaction.user)
                # Check if user can see moderation records for the enhanced button
                # IMPORTANT: Users should NEVER see their own moderation records for privacy
                is_own_profile = str(interaction.user.id) == details.get("discord_id")
                can_see_moderation = not is_own_profile and await self._check_show_moderation_records_permission(interaction.user)
                # Create view with post publicly button
                view = PlayerView(
                    self.cog,
                    show_creator_code_button=False,
                    player=player,
                    details=details,
                    embed_title="Player Details",
                    requesting_user=interaction.user,
                    can_see_moderation=can_see_moderation,
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
                # Check if user can see moderation records for the enhanced button
                # IMPORTANT: Users should NEVER see their own moderation records for privacy
                is_own_profile = str(interaction.user.id) == details.get("discord_id")
                can_see_moderation = not is_own_profile and await self._check_show_moderation_records_permission(interaction.user)
                view = PlayerView(
                    self.cog,
                    show_creator_code_button=False,
                    player=player,
                    details=details,
                    embed_title="Player Details",
                    requesting_user=interaction.user,
                    can_see_moderation=can_see_moderation,
                    guild_id=interaction.guild.id,
                )
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            elif len(unverified_results) == 1 and not verified_results:
                # Only one unverified result
                player = unverified_results[0]
                embed = await self.create_unverified_player_embed(player, interaction.user)
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

        # Parse Discord mentions to extract user ID if needed
        identifier = self.parse_discord_mention(identifier)

        # Try to find player by the identifier (should be Discord ID for profile)
        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import KnownPlayer

        player = await sync_to_async(KnownPlayer.objects.filter(discord_id=identifier).first)()

        if not player:
            embed = await self.create_unverified_embed()
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Get player details
        details = await get_player_details(player)

        # Create profile embed (always shows verification message for profiles)
        embed = await self.create_player_embed(
            player,
            details,
            title_prefix="Player Profile",
            show_verification_message=True,
            discord_display_format="id",
            show_all_ids=await self._check_show_all_ids_permission(interaction.user),
            show_moderation_records=False,  # Never show moderation records on own profile
        )

        # Check if tournament roles button should be shown
        show_tourney_roles_button = False
        tourney_cog = self.cog.bot.get_cog("Tournament Roles")
        if tourney_cog and hasattr(self.cog.bot, "cog_manager"):
            cog_manager = self.cog.bot.cog_manager
            show_tourney_roles_button = cog_manager.can_guild_use_cog("tourney_roles", interaction.guild.id)

        # Create view with set creator code button and optionally tournament roles button
        view = PlayerView(
            self.cog,
            show_creator_code_button=True,
            current_code=details.get("creator_code"),
            player=player,
            details=details,
            embed_title="Player Profile",
            show_tourney_roles_button=show_tourney_roles_button,
            user_id=int(identifier),
            guild_id=interaction.guild.id,
            requesting_user=interaction.user,
            can_see_moderation=False,  # Never show moderation buttons on own profile
        )

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
