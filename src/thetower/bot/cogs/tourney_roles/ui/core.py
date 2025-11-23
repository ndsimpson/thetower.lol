"""
Core business logic and shared components for the Tournament Roles cog.

This module contains:
- Business logic for role determination and assignment
- Form modals and constants
- Reusable view components
- Core tournament data processing
"""

from typing import Any, Dict, List, Optional

import discord
from discord import ui

from thetower.bot.basecog import BaseCog


class TournamentRoleConfig:
    """Configuration for a tournament role."""

    def __init__(self, role_id: str, method: str, threshold: int, league: str = None):
        self.id = role_id
        self.method = method  # "Champion", "Placement", "Wave"
        self.threshold = threshold
        self.league = league  # Required for Wave method


class TournamentStats:
    """Container for player tournament statistics."""

    def __init__(self, player_tournaments: Dict[str, Any]):
        self.leagues = player_tournaments.get("leagues", {})
        self.latest_tournament = player_tournaments.get("latest_tournament", {})
        self.latest_patch = player_tournaments.get("latest_patch", {})
        self.total_tourneys = player_tournaments.get("total_tourneys", 0)


class RoleAssignmentResult:
    """Result of a role assignment operation."""

    def __init__(self):
        self.roles_added = 0
        self.roles_removed = 0
        self.log_messages = []

    def add_change(self, change_type: str, role_name: str, reason: str = ""):
        """Add a role change to the result."""
        self.log_messages.append(f"{change_type}{role_name}{f' ({reason})' if reason else ''}")

        if change_type.startswith("+"):
            self.roles_added += 1
        elif change_type.startswith("-"):
            self.roles_removed += 1


class TournamentRolesCore:
    """Core business logic for tournament role management."""

    def __init__(self, cog: BaseCog):
        self.cog = cog
        self.logger = cog.logger

    def get_league_hierarchy(self, guild_id: int) -> List[str]:
        """Get the league hierarchy for a guild."""
        return self.cog.get_global_setting("league_hierarchy", ["Legend", "Champion", "Platinum", "Gold", "Silver", "Copper"])

    def get_roles_config(self, guild_id: int) -> Dict[str, TournamentRoleConfig]:
        """Get the roles configuration for a guild."""
        roles_config = self.cog.get_setting("roles_config", {}, guild_id=guild_id)
        return {
            name: TournamentRoleConfig(role_id=config["id"], method=config["method"], threshold=config["threshold"], league=config.get("league"))
            for name, config in roles_config.items()
        }

    def get_verified_role_id(self, guild_id: int) -> Optional[str]:
        """Get the verified role ID for a guild."""
        return self.cog.get_setting("verified_role_id", None, guild_id=guild_id)

    def is_dry_run_enabled(self, guild_id: int) -> bool:
        """Check if dry run mode is enabled."""
        return self.cog.get_setting("dry_run", False, guild_id=guild_id)

    def get_update_settings(self, guild_id: int) -> Dict[str, Any]:
        """Get update-related settings."""
        return {
            "update_interval": self.cog.get_setting("update_interval", 6 * 60 * 60, guild_id=guild_id),
            "update_on_startup": self.cog.get_setting("update_on_startup", True, guild_id=guild_id),
        }

    def get_processing_settings(self, guild_id: int) -> Dict[str, Any]:
        """Get processing-related settings."""
        return {
            "process_batch_size": self.cog.get_setting("process_batch_size", 50, guild_id=guild_id),
            "process_delay": self.cog.get_setting("process_delay", 5, guild_id=guild_id),
            "error_retry_delay": self.cog.get_setting("error_retry_delay", 300, guild_id=guild_id),
        }

    def get_logging_settings(self, guild_id: int) -> Dict[str, Any]:
        """Get logging-related settings."""
        return {
            "log_channel_id": self.cog.get_setting("log_channel_id", None, guild_id=guild_id),
            "log_batch_size": self.cog.get_setting("log_batch_size", 10, guild_id=guild_id),
            "immediate_logging": self.cog.get_setting("immediate_logging", True, guild_id=guild_id),
        }

    async def get_player_tournament_stats(self, tourney_stats_cog, player_ids: List[str]) -> TournamentStats:
        """
        Get detailed tournament statistics for a player across all their player IDs.

        Args:
            tourney_stats_cog: The TourneyStats cog instance
            player_ids: List of player IDs associated with the Discord user

        Returns:
            TournamentStats object containing player's tournament data
        """
        # Initialize result dictionary with structure compatible with determine_best_role
        result = {
            "leagues": {},  # Stats by league
            "latest_tournament": {"placement": None, "league": None, "date": None},
            "latest_patch": {"best_placement": float("inf"), "max_wave": 0},
            "total_tourneys": 0,
        }

        latest_tournament_date = None

        # Process each player ID (a Discord user might have multiple player accounts)
        for player_id in player_ids:
            try:
                # Get comprehensive stats for this player across all leagues
                player_stats = await tourney_stats_cog.get_player_stats(player_id)

                # For each league the player has participated in
                for league_name, league_stats in player_stats.items():
                    # Initialize this league if not present
                    if league_name not in result["leagues"]:
                        result["leagues"][league_name] = {
                            "best_wave": 0,
                            "best_position": float("inf"),
                            "position_at_best_wave": 0,
                            "total_tourneys": 0,
                            "avg_wave": 0,
                            "avg_position": 0,
                        }

                    # Skip this league if no tournaments
                    tourney_count = league_stats.get("total_tourneys", 0)
                    if tourney_count == 0:
                        continue

                    # Update tournament counts
                    league_result = result["leagues"][league_name]
                    prev_count = league_result["total_tourneys"]
                    league_result["total_tourneys"] += tourney_count
                    result["total_tourneys"] += tourney_count

                    # Calculate weighted averages for waves and positions
                    if prev_count > 0:
                        total_tourneys = prev_count + tourney_count
                        # Weighted average calculation
                        league_result["avg_wave"] = (
                            (league_result["avg_wave"] * prev_count) + (league_stats.get("avg_wave", 0) * tourney_count)
                        ) / total_tourneys

                        league_result["avg_position"] = (
                            (league_result["avg_position"] * prev_count) + (league_stats.get("avg_position", 0) * tourney_count)
                        ) / total_tourneys
                    else:
                        # First data for this league
                        league_result["avg_wave"] = league_stats.get("avg_wave", 0)
                        league_result["avg_position"] = league_stats.get("avg_position", 0)

                    # Update best wave if higher (for this league)
                    best_wave = league_stats.get("best_wave", 0)
                    if best_wave > league_result["best_wave"]:
                        league_result["best_wave"] = best_wave
                        league_result["position_at_best_wave"] = league_stats.get("position_at_best_wave", 0)

                    # Update best position if better (for this league)
                    best_position = league_stats.get("best_position", float("inf"))
                    if best_position < league_result["best_position"]:
                        league_result["best_position"] = best_position

                    # Update latest patch data (aggregating across all leagues)
                    if best_position < result["latest_patch"]["best_placement"]:
                        result["latest_patch"]["best_placement"] = best_position

                    max_wave = league_stats.get("max_wave", 0)
                    if max_wave > result["latest_patch"]["max_wave"]:
                        result["latest_patch"]["max_wave"] = max_wave

                    # Check for latest tournament
                    latest_date = league_stats.get("latest_date")
                    if latest_date and (latest_tournament_date is None or latest_date > latest_tournament_date):
                        latest_tournament_date = latest_date
                        result["latest_tournament"] = {
                            "league": league_name,
                            "wave": league_stats.get("latest_wave"),
                            "placement": league_stats.get("latest_position"),
                            "date": latest_date,
                        }

                    self.logger.debug(f"Player {player_id}: {tourney_count} tournaments in {league_name}, best wave: {best_wave}")
            except Exception as e:
                self.logger.error(f"Error getting stats for player {player_id}: {e}")

        # Clean up infinity value if no tournaments found
        if result["latest_patch"]["best_placement"] == float("inf"):
            result["latest_patch"]["best_placement"] = None

        return TournamentStats(result)

    def determine_best_role(
        self, player_stats: TournamentStats, roles_config: Dict[str, TournamentRoleConfig], league_hierarchy: List[str], debug_logging: bool = False
    ) -> Optional[str]:
        """
        Determine the best role for a player based on tournament performance.

        Evaluates roles in Champion → Placement → Wave priority order:
        Champion: Latest tournament winner in the top-most league (e.g., "Current Champion")
        Placement: Placement across all tournaments in latest patch (e.g., "Top100")
        Wave: Wave-based across all tournaments in latest patch (e.g., "Champion500")

        Args:
            player_stats: TournamentStats object containing player's tournament data
            roles_config: Dictionary mapping role names to TournamentRoleConfig objects
            league_hierarchy: List of leagues in order from highest to lowest
            debug_logging: Whether to enable debug logging

        Returns:
            str: Role ID to assign, or None if no qualifying role
        """
        if debug_logging:
            self.logger.info("==== ROLE DETERMINATION ANALYSIS ====")
            self.logger.info(f"Player latest tournament: {player_stats.latest_tournament}")
            self.logger.info(f"League hierarchy: {' > '.join(league_hierarchy)}")

        # Champion method: Latest tournament placement-based (highest priority)
        champion_roles = {role_name: config for role_name, config in roles_config.items() if config.method == "Champion"}

        if champion_roles:
            # Check if multiple "Current Champion" roles are configured
            if len(champion_roles) > 1 and debug_logging:
                self.logger.warning(f"Multiple Champion method roles detected: {', '.join(champion_roles.keys())}. Only one should be configured.")

            # Get latest tournament data
            latest_tournament = player_stats.latest_tournament
            if latest_tournament:
                placement = latest_tournament.get("placement")
                league = latest_tournament.get("league")

                if debug_logging:
                    self.logger.info(f"Latest tournament: League={league}, Placement={placement}")

                # Only assign Champion role if the player placed first in the top-most league
                if placement and league:
                    # Check if this is the top league in the hierarchy
                    is_top_league = league == league_hierarchy[0] if league_hierarchy else False

                    if debug_logging:
                        self.logger.info(f"Is top league? {is_top_league} (Top league: {league_hierarchy[0]})")

                    if is_top_league:
                        for role_name, config in champion_roles.items():
                            threshold = config.threshold
                            if debug_logging:
                                self.logger.info(f"Checking champion role '{role_name}' with threshold {threshold}")

                            if placement <= threshold:
                                if debug_logging:
                                    self.logger.info(
                                        f"✅ CHAMPION ROLE MATCH: '{role_name}' - player placed {placement} in {league} (threshold: {threshold})"
                                    )
                                return config.id
                            elif debug_logging:
                                self.logger.info(f"❌ Champion role '{role_name}' not matched - placement {placement} > threshold {threshold}")
                    elif debug_logging:
                        self.logger.info(f"❌ Champion role not applied - {league} is not the top league ({league_hierarchy[0]})")
                elif debug_logging:
                    self.logger.info("❌ Champion role not applied - missing placement or league data")
            elif debug_logging:
                self.logger.info("❌ Champion role not applied - no latest tournament data")

        # Placement method: Placement-based roles respecting league hierarchy
        placement_roles = {role_name: config for role_name, config in roles_config.items() if config.method == "Placement"}

        if placement_roles:
            if debug_logging:
                self.logger.info(f"\nPLACEMENT METHOD: Checking {len(placement_roles)} placement roles")

            # Get the top league from the hierarchy
            top_league = league_hierarchy[0] if league_hierarchy else None

            if debug_logging and top_league:
                self.logger.info(f"Top league in hierarchy: {top_league}")

            # Group roles by league
            league_placement_roles = {}
            for role_name, config in placement_roles.items():
                # If role name starts with "Top", assign to top league
                if role_name.startswith("Top") and top_league:
                    if debug_logging:
                        self.logger.info(f"Role '{role_name}' starts with 'Top', assigning to top league: {top_league}")
                    league = top_league
                else:
                    league = config.league

                if league:
                    if league not in league_placement_roles:
                        league_placement_roles[league] = []
                    league_placement_roles[league].append((role_name, config))

            # Check each league in order of hierarchy
            for league in league_hierarchy:
                if debug_logging:
                    has_roles = league in league_placement_roles
                    has_data = league in player_stats.leagues
                    self.logger.info(f"Checking league {league} - Has roles: {has_roles}, Has player data: {has_data}")

                if league in league_placement_roles and league in player_stats.leagues:
                    league_data = player_stats.leagues[league]
                    best_position = league_data.get("best_position")

                    if best_position and best_position != float("inf"):
                        # Sort roles within this league by threshold (ascending)
                        sorted_roles = sorted(league_placement_roles[league], key=lambda x: x[1].threshold)

                        if debug_logging:
                            role_thresholds = [(r[0], r[1].threshold) for r in sorted_roles]
                            self.logger.info(f"Available roles in {league} (sorted by threshold): {role_thresholds}")

                        # Check if player qualifies for any role in this league
                        for role_name, config in sorted_roles:
                            threshold = config.threshold
                            if debug_logging:
                                self.logger.info(f"Checking placement role '{role_name}' with threshold {threshold}")

                            if best_position <= threshold:
                                if debug_logging:
                                    self.logger.info(
                                        f"✅ PLACEMENT ROLE MATCH: '{role_name}' - player best position {best_position} in {league} (threshold: {threshold})"
                                    )
                                return config.id
                            elif debug_logging:
                                self.logger.info(f"❌ Placement role '{role_name}' not matched - position {best_position} > threshold {threshold}")
                    elif debug_logging:
                        self.logger.info(f"❌ No valid position data for {league}")

        # Wave method: Wave-based across all tournaments in latest patch
        wave_roles = {role_name: config for role_name, config in roles_config.items() if config.method == "Wave"}

        if wave_roles:
            if debug_logging:
                self.logger.info(f"\nWAVE METHOD: Checking {len(wave_roles)} wave roles")

            # Get wave data across all tournaments in the latest patch
            patch_data = player_stats.latest_patch
            if patch_data:
                max_wave = patch_data.get("max_wave", 0)

                if debug_logging:
                    self.logger.info(f"Player's max wave: {max_wave}")

                # Group roles by league
                league_roles = {}
                for role_name, config in wave_roles.items():
                    league = config.league
                    if league:
                        if league not in league_roles:
                            league_roles[league] = []
                        league_roles[league].append((role_name, config))

                # Check each league in order of hierarchy
                for league in league_hierarchy:
                    if debug_logging and league in league_roles:
                        self.logger.info(f"Checking wave roles for league {league}")

                    if league in league_roles:
                        # Sort roles within this league by threshold (descending)
                        sorted_roles = sorted(league_roles[league], key=lambda x: x[1].threshold, reverse=True)

                        if debug_logging:
                            role_thresholds = [(r[0], r[1].threshold) for r in sorted_roles]
                            self.logger.info(f"Available roles in {league} (sorted by threshold desc): {role_thresholds}")

                        # Check if player qualifies for any role in this league
                        for role_name, config in sorted_roles:
                            threshold = config.threshold
                            if debug_logging:
                                self.logger.info(f"Checking wave role '{role_name}' with threshold {threshold}")

                            # Get league-specific best wave instead of global max wave
                            league_data = player_stats.leagues.get(league, {})
                            league_max_wave = league_data.get("best_wave", 0)

                            if league_max_wave >= threshold:
                                if debug_logging:
                                    self.logger.info(
                                        f"✅ WAVE ROLE MATCH: '{role_name}' - player max wave {league_max_wave} in {league} meets threshold of {threshold}"
                                    )
                                return config.id
                            elif debug_logging:
                                self.logger.info(f"❌ Wave role '{role_name}' not matched - wave {league_max_wave} < threshold {threshold}")
            elif debug_logging:
                self.logger.info("❌ No patch data available for wave-based roles")

        # No qualifying role found
        if debug_logging:
            self.logger.info("❌ NO QUALIFYING ROLE FOUND")
            self.logger.info("==== END ROLE DETERMINATION ANALYSIS ====")

        return None

    async def update_member_roles(
        self,
        member: discord.Member,
        player_stats: TournamentStats,
        roles_config: Dict[str, TournamentRoleConfig],
        verified_role_id: Optional[str],
        dry_run: bool = False,
    ) -> RoleAssignmentResult:
        """
        Update a member's roles based on tournament performance

        Args:
            member: Discord member to update
            player_stats: Tournament statistics for this player
            roles_config: Dictionary mapping role names to TournamentRoleConfig objects
            verified_role_id: ID of the verified role requirement, if any
            dry_run: Whether to perform a dry run (no actual changes)

        Returns:
            RoleAssignmentResult containing the changes made
        """
        result = RoleAssignmentResult()

        try:
            # Check if verified role is required
            if verified_role_id:
                verified_role = member.guild.get_role(int(verified_role_id))
                if not verified_role:
                    self.logger.warning(f"Verified role with ID {verified_role_id} not found in guild")
                elif verified_role not in member.roles:
                    # Remove all tournament roles if user isn't verified
                    all_managed_role_ids = [config.id for config in roles_config.values()]

                    roles_removed = 0
                    for role in member.roles:
                        if str(role.id) in all_managed_role_ids:
                            try:
                                if not dry_run:
                                    await member.remove_roles(role, reason="User not verified for tournament roles")
                                roles_removed += 1
                                result.add_change("-", role.name, "not verified")
                                log_msg = (
                                    f"{'Would remove' if dry_run else 'Removed'} {role.name} role from {member.name} ({member.id}) - not verified"
                                )
                                self.logger.info(log_msg)
                            except Exception as e:
                                self.logger.error(f"Error removing role {role.name} from {member.name}: {e}")

                    # Return early if roles were removed
                    return result

            # Continue with normal role assignment
            # Determine the best role for this player
            debug_logging = self.cog.get_setting("debug_logging", False, member.guild.id)
            league_hierarchy = self.get_league_hierarchy(member.guild.id)
            best_role_id = self.determine_best_role(player_stats, roles_config, league_hierarchy, debug_logging)

            # Get all managed role IDs for comparison
            all_managed_role_ids = [config.id for config in roles_config.values()]

            # If player qualifies for a role
            if best_role_id:
                best_role = member.guild.get_role(int(best_role_id))
                if not best_role:
                    self.logger.warning(f"Role with ID {best_role_id} not found in guild")
                    return result

                # Add the role if they don't have it
                if best_role not in member.roles:
                    try:
                        if not dry_run:
                            await member.add_roles(best_role, reason="Tournament participation role update")
                        result.add_change("+", best_role.name)
                        log_msg = f"{'Would add' if dry_run else 'Added'} {best_role.name} role to {member.name} ({member.id})"
                        self.logger.info(log_msg)
                    except Exception as e:
                        self.logger.error(f"Error adding role {best_role.name} to {member.name}: {e}")

            # Remove any other tournament roles they shouldn't have
            for role in member.roles:
                if str(role.id) in all_managed_role_ids and (not best_role_id or str(role.id) != best_role_id):
                    try:
                        if not dry_run:
                            await member.remove_roles(role, reason="Tournament participation role update")
                        result.add_change("-", role.name)
                        log_msg = f"{'Would remove' if dry_run else 'Removed'} {role.name} role from {member.name} ({member.id})"
                        self.logger.info(log_msg)
                    except Exception as e:
                        self.logger.error(f"Error removing role {role.name} from {member.name}: {e}")

            return result

        except Exception as e:
            self.logger.error(f"Error updating roles for member {member.id}: {e}")
            raise


class LeagueHierarchyModal(ui.Modal, title="Set League Hierarchy"):
    """Modal for setting the league hierarchy."""

    def __init__(self, current_hierarchy: List[str]):
        super().__init__()
        self.leagues_input = ui.TextInput(
            label="League Hierarchy (comma-separated)",
            placeholder="Legend, Champion, Platinum, Gold, Silver, Copper",
            default=", ".join(current_hierarchy),
            style=discord.TextStyle.long,
            required=True,
        )
        self.add_item(self.leagues_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission."""
        try:
            # Parse league names from comma-separated string
            league_hierarchy = [name.strip() for name in self.leagues_input.value.split(",")]

            # Validate that we have at least one league
            if not league_hierarchy or not all(league_hierarchy):
                await interaction.response.send_message("❌ Please provide a valid comma-separated list of league names", ephemeral=True)
                return

            # This will be handled by the calling view
            self.result = league_hierarchy
            await interaction.response.send_message(f"✅ League hierarchy set: {', '.join(league_hierarchy)}", ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"❌ Error setting league hierarchy: {str(e)}", ephemeral=True)


class AddRoleModal(ui.Modal, title="Add Tournament Role"):
    """Modal for adding a new tournament role."""

    def __init__(self, available_leagues: List[str]):
        super().__init__()
        self.role_select = ui.TextInput(label="Discord Role", placeholder="@RoleName or Role ID", required=True)
        self.method_select = ui.TextInput(label="Assignment Method", placeholder="Champion, Placement, or Wave", required=True)
        self.threshold_input = ui.TextInput(label="Threshold", placeholder="1 for Champion, 100 for Top100, 500 for Wave500", required=True)
        self.league_input = ui.TextInput(label="League (required for Wave method)", placeholder="Champion, Platinum, etc.", required=False)

        self.add_item(self.role_select)
        self.add_item(self.method_select)
        self.add_item(self.threshold_input)
        self.add_item(self.league_input)

        self.available_leagues = available_leagues

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission."""
        try:
            # Parse role
            role_input = self.role_select.value.strip()
            if role_input.startswith("<@&") and role_input.endswith(">"):
                # Role mention
                role_id = role_input[3:-1]
            elif role_input.isdigit():
                # Role ID
                role_id = role_input
            else:
                # Try to find role by name
                role = discord.utils.find(lambda r: r.name.lower() == role_input.lower(), interaction.guild.roles)
                if not role:
                    await interaction.response.send_message(f"❌ Could not find role: {role_input}", ephemeral=True)
                    return
                role_id = str(role.id)

            # Validate method
            method = self.method_select.value.title()
            valid_methods = ["Champion", "Placement", "Wave"]
            if method not in valid_methods:
                await interaction.response.send_message(f"❌ Invalid method. Use {', '.join(valid_methods)}", ephemeral=True)
                return

            # Parse threshold
            try:
                threshold = int(self.threshold_input.value)
                if threshold < 1:
                    raise ValueError()
            except ValueError:
                await interaction.response.send_message("❌ Threshold must be a positive integer", ephemeral=True)
                return

            # Validate league for Wave method
            league = self.league_input.value.strip() if self.league_input.value else None
            if method == "Wave" and not league:
                await interaction.response.send_message("❌ League parameter is required for Wave method", ephemeral=True)
                return

            if method == "Wave" and league not in self.available_leagues:
                await interaction.response.send_message(f"❌ Invalid league. Must be one of: {', '.join(self.available_leagues)}", ephemeral=True)
                return

            # Generate role name based on method
            if method == "Champion":
                role_name = "Current Champion"
            elif method == "Placement":
                role_name = f"Top{threshold}"
            else:  # method == 'Wave'
                role_name = f"{league}{threshold}"

            # Store result for calling view
            self.result = {"role_id": role_id, "role_name": role_name, "method": method, "threshold": threshold, "league": league}

            await interaction.response.send_message(f"✅ Role '{role_name}' configured successfully", ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"❌ Error configuring role: {str(e)}", ephemeral=True)
