# Third-party
import re

import discord

# Local
from .core import PlayerView, get_player_details


class UserInteractions:
    """User-facing interaction flows for the Known Players cog."""

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
                ids_list = [pid for pid in ids_list if pid != primary_id]
                formatted_ids.extend(ids_list)
            else:
                # Just show the primary ID without special formatting
                formatted_ids.append(primary_id)
        elif show_all_ids:
            # No primary ID, show all IDs
            formatted_ids.extend(ids_list)

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

            from thetower.backend.sus.models import ModerationRecord

            # Get active moderation records for this player
            active_moderations = await sync_to_async(list)(
                ModerationRecord.objects.filter(known_player=player, resolved_at__isnull=True).order_by(  # Only active (unresolved) records
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
                    value="✅ No active moderation records",
                    inline=False,
                )

        return embed

    async def create_profile_embed(self, player, details: dict, requesting_user: discord.User) -> discord.Embed:
        """Create profile embed for a verified player (legacy method)."""
        # Check if the requesting user can see all IDs (even for their own profile)
        show_all_ids = await self.cog.check_show_all_ids_permission(requesting_user)
        # Check if the requesting user can see moderation records
        show_moderation_records = (
            await self.cog.check_show_moderation_records_permission(requesting_user) and self.cog.show_moderation_records_in_profiles
        )
        return await self.create_player_embed(
            player,
            details,
            title_prefix="Player Profile",
            show_verification_message=True,
            discord_display_format="id",
            show_all_ids=show_all_ids,
            show_moderation_records=show_moderation_records,
        )

    async def create_lookup_embed(self, player, details: dict, requesting_user: discord.User) -> discord.Embed:
        """Create lookup embed for player details."""
        # Check if the requesting user can see all IDs
        show_all_ids = await self.cog.check_show_all_ids_permission(requesting_user)
        # Check if the requesting user can see moderation records
        show_moderation_records = (
            await self.cog.check_show_moderation_records_permission(requesting_user) and self.cog.show_moderation_records_in_profiles
        )

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
        show_all_ids = await self.cog.check_show_all_ids_permission(requesting_user)

        embed = discord.Embed(
            title="Multiple Players Found",
            description=f"Found {len(results)} players matching '{search_term}'. Showing first 5:",
            color=discord.Color.gold(),
        )

        for i, player in enumerate(results[:5], 1):
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
            player_info = f"**Name:** {player.name}\n" f"**Discord:** {discord_mention}\n" f"**Player IDs:** {id_list}"

            embed.add_field(name=f"Player #{i}", value=player_info, inline=False)

        if len(results) > 5:
            embed.set_footer(text=f"{len(results) - 5} more results not shown. Be more specific.")

        return embed

    async def create_unverified_embed(self) -> discord.Embed:
        """Create embed for unverified users."""
        embed = discord.Embed(
            title="Not Verified", description="You don't have a verified player account linked to your Discord ID.", color=discord.Color.orange()
        )
        embed.add_field(name="How to Get Verified", value="Verify your player id in <#", inline=False)
        return embed

    async def handle_profile_command(self, interaction: discord.Interaction) -> None:
        """Handle the /profile slash command."""
        if not await self.cog.wait_until_ready():
            await interaction.response.send_message("⏳ Still initializing, please try again shortly.", ephemeral=True)
            return

        discord_id = str(interaction.user.id)

        # Try to find player by Discord ID
        player = await self.cog.get_player_by_discord_id(discord_id)

        if not player:
            embed = await self.create_unverified_embed()
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Get player details
        details = await get_player_details(player)

        # Create profile embed
        embed = await self.create_profile_embed(player, details, interaction.user)

        # Check if tournament roles button should be shown
        show_tourney_roles_button = False
        tourney_cog = self.cog.bot.get_cog("Tournament Roles")
        if tourney_cog and hasattr(self.cog.bot, "cog_manager"):
            cog_manager = self.cog.bot.cog_manager
            show_tourney_roles_button = cog_manager.can_guild_use_cog("tourney_roles", interaction.guild.id)

        # Check if user can see moderation records for the enhanced button
        can_see_moderation = (
            await self.cog.check_show_moderation_records_permission(interaction.user) and self.cog.show_moderation_records_in_profiles
        )

        # Create view with set creator code button and optionally tournament roles button
        view = PlayerView(
            self.cog,
            show_creator_code_button=True,
            current_code=details.get("creator_code"),
            player=player,
            details=details,
            embed_title="Player Profile",
            show_tourney_roles_button=show_tourney_roles_button,
            user_id=int(discord_id),
            guild_id=interaction.guild.id,
            requesting_user=interaction.user,
            can_see_moderation=can_see_moderation,
        )

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def handle_lookup_command(self, interaction: discord.Interaction, identifier: str = None) -> None:
        """Handle the /lookup slash command."""
        if not await self.cog.wait_until_ready():
            await interaction.response.send_message("⏳ Still initializing, please try again shortly.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Check if lookups are restricted to known users
        if self.cog.restrict_lookups_to_known_users:
            discord_id = str(interaction.user.id)
            known_player = await self.cog.get_player_by_discord_id(discord_id)
            if not known_player:
                embed = await self.create_unverified_embed()
                embed.title = "Access Restricted"
                embed.description = "Player lookups are restricted to verified users only. You must verify your account first."
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

        # Determine what to search for
        if identifier:
            identifier = identifier.strip()
            # Parse Discord mentions to extract user ID
            identifier = self.parse_discord_mention(identifier)
            results = await self.cog.search_player(identifier)
        else:
            await interaction.followup.send("❌ Please provide an identifier.", ephemeral=True)
            return

        if not results:
            search_display = f"'{identifier}'"
            await interaction.followup.send(f"No players found matching {search_display}", ephemeral=True)
            return

        if len(results) == 1:
            player = results[0]
            details = await get_player_details(player)
            embed = await self.create_lookup_embed(player, details, interaction.user)
            # Check if user can see moderation records for the enhanced button
            can_see_moderation = (
                await self.cog.check_show_moderation_records_permission(interaction.user) and self.cog.show_moderation_records_in_profiles
            )
            # Create view with post publicly button
            view = PlayerView(
                self.cog,
                show_creator_code_button=False,
                player=player,
                details=details,
                embed_title="Player Details",
                requesting_user=interaction.user,
                can_see_moderation=can_see_moderation,
            )
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            # Multiple results
            embed = await self.create_multiple_results_embed(results, identifier, interaction.user)
            await interaction.followup.send(embed=embed, ephemeral=True)
