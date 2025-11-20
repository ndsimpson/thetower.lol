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
        self, player, details: dict, title_prefix: str = "Player Profile", show_verification_message: bool = True, discord_display_format: str = "id"
    ) -> discord.Embed:
        """Create player embed with configurable display options.

        Args:
            player: The KnownPlayer object
            details: Player details dictionary
            title_prefix: Prefix for the embed title (e.g., "Player Profile", "Player Details")
            show_verification_message: Whether to show verification message in description
            discord_display_format: "id" for Discord ID, "mention" for Discord mention
        """
        # Create embed with configurable title and description
        description = "✅ Your Discord account is verified!" if show_verification_message else None
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
            formatted_ids.append(f"✅ **{primary_id}** (Primary)")
            ids_list = [pid for pid in ids_list if pid != primary_id]

        formatted_ids.extend(ids_list)

        embed.add_field(
            name=f"Player IDs ({len(details['all_ids'])})", value="\n".join(formatted_ids) if formatted_ids else "No IDs found", inline=False
        )

        return embed

    async def create_profile_embed(self, player, details: dict) -> discord.Embed:
        """Create profile embed for a verified player (legacy method)."""
        return await self.create_player_embed(
            player, details, title_prefix="Player Profile", show_verification_message=True, discord_display_format="id"
        )

    async def create_lookup_embed(self, player, details: dict) -> discord.Embed:
        """Create lookup embed for player details."""
        return await self.create_player_embed(
            player, details, title_prefix="Player Details", show_verification_message=False, discord_display_format="mention"
        )

    async def create_multiple_results_embed(self, results: list, search_term: str) -> discord.Embed:
        """Create embed for multiple search results."""
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
                formatted_ids.append(f"✅ {primary_id}")

            other_ids = [pid.id for pid in player_ids if pid.id != primary_id]
            formatted_ids.extend(other_ids[:2])

            id_list = ", ".join(formatted_ids)
            if len(player_ids) > 3:
                id_list += f" (+{len(player_ids) - 3} more)"

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
        embed.add_field(
            name="How to Get Verified", value="Contact a server administrator to link your player ID to your Discord account.", inline=False
        )
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
        embed = await self.create_profile_embed(player, details)

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
            user_id=int(discord_id),
            guild_id=interaction.guild.id,
        )

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def handle_lookup_command(self, interaction: discord.Interaction, identifier: str = None, user: discord.User = None) -> None:
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
        if user:
            search_term = str(user.id)
            player = await self.cog.get_player_by_discord_id(search_term)
            if player:
                results = [player]
            else:
                results = []
        elif identifier:
            identifier = identifier.strip()
            # Parse Discord mentions to extract user ID
            identifier = self.parse_discord_mention(identifier)
            results = await self.cog.search_player(identifier)
        else:
            await interaction.followup.send("❌ Please provide either an identifier or mention a user.", ephemeral=True)
            return

        if not results:
            search_display = f"<@{user.id}>" if user else f"'{identifier}'"
            await interaction.followup.send(f"No players found matching {search_display}", ephemeral=True)
            return

        if len(results) == 1:
            player = results[0]
            details = await get_player_details(player)
            embed = await self.create_lookup_embed(player, details)
            # Create view with post publicly button
            view = PlayerView(self.cog, show_creator_code_button=False, player=player, details=details, embed_title="Player Details")
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            # Multiple results
            embed = await self.create_multiple_results_embed(results, identifier or str(user))
            await interaction.followup.send(embed=embed, ephemeral=True)
