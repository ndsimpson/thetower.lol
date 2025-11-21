"""
User-facing interaction flows for the Tournament Roles cog.

This module contains:
- User-facing slash commands for managing personal tournament roles
- Views for user interactions
- Personal data management workflows
"""

import discord
from discord import app_commands, ui

from thetower.bot.basecog import BaseCog

from .core import TournamentRolesCore


class UserRoleManagementView(ui.View):
    """Main view for users to manage their tournament roles."""

    def __init__(self, cog: BaseCog, user_id: int, guild_id: int):
        super().__init__(timeout=900)
        self.cog = cog
        self.user_id = user_id
        self.guild_id = guild_id
        self.core = TournamentRolesCore(cog)

    async def get_user_info_embed(self, member: discord.Member) -> discord.Embed:
        """Create an embed with user tournament information."""
        embed = discord.Embed(
            title="Tournament Roles - Your Status", description=f"Tournament role information for {member.display_name}", color=discord.Color.blue()
        )

        # Get player data
        try:
            known_players_cog = self.cog.bot.get_cog("Known Players")
            if known_players_cog:
                discord_mapping = await known_players_cog.get_discord_to_player_mapping()
                player_data = discord_mapping.get(str(member.id))

                if player_data:
                    primary_id = player_data.get("primary_id", "None")
                    all_ids = player_data.get("all_ids", [])
                    id_list = f"✅ {primary_id}" if primary_id and primary_id != "None" else "None"
                    if len(all_ids) > 1:
                        other_ids = [pid for pid in all_ids if pid != primary_id]
                        if other_ids:
                            id_list += f", {', '.join(other_ids[:3])}"
                            if len(other_ids) > 3:
                                id_list += f" (+{len(other_ids) - 3} more)"

                    embed.add_field(
                        name="Player Data", value=f"**Name:** {player_data.get('name', 'Unknown')}\n**Player IDs:** {id_list}", inline=False
                    )

                    # Get tournament stats if available
                    tourney_stats_cog = self.cog.bot.get_cog("Tourney Stats")
                    if tourney_stats_cog:
                        player_stats = await self.core.get_player_tournament_stats(tourney_stats_cog, all_ids)

                        if player_stats.total_tourneys > 0:
                            latest = player_stats.latest_tournament
                            patch = player_stats.latest_patch

                            stats = []
                            if latest.get("league"):
                                stats.append(f"**Latest Tournament:** {latest['league']} (Position: {latest.get('placement', 'N/A')})")
                            if patch.get("max_wave"):
                                stats.append(f"**Best Wave:** {patch['max_wave']}")
                            if patch.get("best_placement"):
                                stats.append(f"**Best Placement:** {patch['best_placement']}")

                            if stats:
                                embed.add_field(name="Tournament Stats", value="\n".join(stats), inline=False)
                else:
                    embed.add_field(name="Player Data", value="❌ No player data found. Use `/player register` to link your account.", inline=False)
            else:
                embed.add_field(name="Player Data", value="❌ Known Players cog not available", inline=False)

        except Exception as e:
            embed.add_field(name="Player Data", value=f"❌ Error loading data: {str(e)}", inline=False)

        # Current roles
        tournament_roles = []
        roles_config = self.core.get_roles_config(self.guild_id)
        managed_role_ids = [config.id for config in roles_config.values()]

        for role in member.roles:
            if str(role.id) in managed_role_ids:
                tournament_roles.append(role.name)

        if tournament_roles:
            embed.add_field(name="Current Tournament Roles", value="\n".join(f"🏆 {role}" for role in tournament_roles), inline=False)
        else:
            embed.add_field(name="Current Tournament Roles", value="None", inline=False)

        # Dry run status
        dry_run = self.core.is_dry_run_enabled(self.guild_id)
        if dry_run:
            embed.add_field(name="Notice", value="🔍 **Dry Run Mode Active** - No actual role changes will be made", inline=False)

        return embed

    @ui.button(label="Update My Roles", style=discord.ButtonStyle.primary, emoji="🔄")
    async def update_roles(self, interaction: discord.Interaction, button: ui.Button):
        """Update the user's tournament roles."""
        await interaction.response.defer(ephemeral=True)

        try:
            member = interaction.guild.get_member(self.user_id)
            if not member:
                await interaction.followup.send("❌ Could not find you in this server", ephemeral=True)
                return

            # Get required cogs
            known_players_cog = self.cog.bot.get_cog("Known Players")
            if not known_players_cog:
                await interaction.followup.send("❌ Known Players cog not available", ephemeral=True)
                return

            tourney_stats_cog = self.cog.bot.get_cog("Tourney Stats")
            if not tourney_stats_cog:
                await interaction.followup.send("❌ Tourney Stats cog not available", ephemeral=True)
                return

            # Get user's player data
            discord_mapping = await known_players_cog.get_discord_to_player_mapping()
            player_data = discord_mapping.get(str(self.user_id))
            if not player_data:
                await interaction.followup.send("❌ No player data found. Use `/player register` to link your account.", ephemeral=True)
                return

            # Get tournament participation data
            player_stats = await self.core.get_player_tournament_stats(tourney_stats_cog, player_data.get("all_ids", []))

            # Get roles config
            roles_config = self.core.get_roles_config(self.guild_id)
            verified_role_id = self.core.get_verified_role_id(self.guild_id)
            dry_run = self.core.is_dry_run_enabled(self.guild_id)

            # Update member's roles
            result = await self.core.update_member_roles(member, player_stats, roles_config, verified_role_id, dry_run)

            # Create response embed
            embed = discord.Embed(
                title="Tournament Roles Updated", description=f"Updated roles for {member.display_name}", color=discord.Color.green()
            )

            # Add role changes
            changes = []
            if result.roles_added > 0:
                changes.append(f"🟢 {result.roles_added} role{'s' if result.roles_added != 1 else ''} {'would be ' if dry_run else ''}added")
            if result.roles_removed > 0:
                changes.append(f"🔴 {result.roles_removed} role{'s' if result.roles_removed != 1 else ''} {'would be ' if dry_run else ''}removed")
            if not changes:
                changes.append("No role changes needed")

            embed.add_field(name="Role Changes" + (" (Dry Run)" if dry_run else ""), value="\n".join(changes), inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.cog.logger.error(f"Error updating roles for user {self.user_id}: {e}")
            await interaction.followup.send(f"❌ Error updating roles: {str(e)}", ephemeral=True)

    @ui.button(label="View My Status", style=discord.ButtonStyle.secondary, emoji="📊")
    async def view_status(self, interaction: discord.Interaction, button: ui.Button):
        """Show the user's current tournament status."""
        await interaction.response.defer(ephemeral=True)

        try:
            member = interaction.guild.get_member(self.user_id)
            if not member:
                await interaction.followup.send("❌ Could not find you in this server", ephemeral=True)
                return

            embed = await self.get_user_info_embed(member)
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ Error loading status: {str(e)}", ephemeral=True)


class UserTournamentRoles(BaseCog):
    """User-facing commands for tournament role management."""

    def __init__(self, bot):
        super().__init__(bot)
        self.core = TournamentRolesCore(self)

    @app_commands.command(name="tournament-roles", description="Manage your tournament roles")
    @app_commands.guild_only()
    async def tournament_roles(self, interaction: discord.Interaction):
        """Main command for users to manage their tournament roles."""
        embed = discord.Embed(
            title="Tournament Roles",
            description="Manage your tournament-based Discord roles based on your competitive performance.",
            color=discord.Color.blue(),
        )

        embed.add_field(
            name="How it works",
            value="Your Discord roles are automatically updated based on your tournament performance. "
            "Roles are assigned based on placement in tournaments and wave progression.",
            inline=False,
        )

        embed.add_field(
            name="Available Actions",
            value="• **Update My Roles**: Manually refresh your tournament roles\n"
            "• **View My Status**: See your current tournament stats and roles",
            inline=False,
        )

        view = UserRoleManagementView(self, interaction.user.id, interaction.guild.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    """Setup function for the user commands cog."""
    await bot.add_cog(UserTournamentRoles(bot))
