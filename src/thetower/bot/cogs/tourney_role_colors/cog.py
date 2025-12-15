"""Tourney Role Colors cog - Allow users to select roles based on prerequisites."""

import logging
from typing import Dict, List, Optional

import discord
from discord.ext import commands

from thetower.bot.basecog import BaseCog

from .ui import TourneyRoleColorsSettingsView

logger = logging.getLogger(__name__)


class TourneyRoleColors(BaseCog, name="Tourney Role Colors"):
    """Manage selectable role colors with prerequisites and mutual exclusivity.

    Server owners can configure:
    - Categories of roles (mutually exclusive groups)
    - Individual role options within categories
    - Prerequisite roles required to select each option
    - Role inheritance (higher tier roles include lower tier prerequisites)
    """

    # Register the settings view class for the modular settings system
    settings_view_class = TourneyRoleColorsSettingsView

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.logger.info("Initializing TourneyRoleColors")

        # Guild-specific settings structure:
        # {
        #     "categories": [
        #         {
        #             "name": "Orange",
        #             "roles": [
        #                 {
        #                     "role_id": 123456789,
        #                     "name": "Orange 100",
        #                     "prerequisite_roles": [111111111, 222222222],  # Top 25, Top 100
        #                     "inherits_from": None  # No inheritance - base tier
        #                 },
        #                 {
        #                     "role_id": 987654321,
        #                     "name": "Orange 200",
        #                     "prerequisite_roles": [333333333],  # Top 200 (direct prereq)
        #                     "inherits_from": 123456789  # Inherits from Orange 100 (single role)
        #                     # Final prereqs: Top 25 OR Top 100 OR Top 200
        #                 },
        #                 {
        #                     "role_id": 555555555,
        #                     "name": "Orange 500",
        #                     "prerequisite_roles": [444444444],  # Top 500
        #                     "inherits_from": 987654321  # Inherits from Orange 200 (nested)
        #                     # Final prereqs: Top 25 OR Top 100 OR Top 200 OR Top 500
        #                 }
        #             ]
        #         },
        #         {
        #             "name": "Yellow",
        #             "roles": [...]
        #         }
        #     ]
        # }
        self.guild_settings = {
            "categories": [],
        }

    async def cog_initialize(self) -> None:
        """Initialize the cog - called by BaseCog during ready process."""
        self.logger.info("Initializing Tourney Role Colors module")

        try:
            async with self.task_tracker.task_context("Initialization") as tracker:
                # Initialize parent
                self.logger.debug("Initializing parent cog")
                await super().cog_initialize()

                tracker.update_status("Marking ready")
                self.set_ready(True)
                self.logger.info("Tourney role colors initialization complete")

        except Exception as e:
            self.logger.error(f"Error during Tourney Role Colors initialization: {e}", exc_info=True)
            self._has_errors = True
            raise

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded."""
        # Call parent implementation for data saving
        await super().cog_unload()
        self.logger.info("Tourney role colors cog unloaded")

    # === Helper Methods ===

    def get_all_managed_roles(self, guild_id: int) -> List[int]:
        """Get all role IDs managed by this cog for a guild.

        Args:
            guild_id: The guild ID to get roles for

        Returns:
            List of all managed role IDs
        """
        categories = self.get_setting("categories", [], guild_id=guild_id)
        all_roles = []

        for category in categories:
            for role_config in category.get("roles", []):
                role_id = role_config.get("role_id")
                if role_id:
                    all_roles.append(role_id)

        return all_roles

    def get_eligible_roles(self, guild_id: int, user_role_ids: List[int]) -> List[Dict]:
        """Get all roles a user is eligible to select based on their current roles.

        Args:
            guild_id: The guild ID
            user_role_ids: List of role IDs the user currently has

        Returns:
            List of role configs the user can select, with resolved prerequisites
        """
        categories = self.get_setting("categories", [], guild_id=guild_id)
        eligible_roles = []

        for category in categories:
            for role_config in category.get("roles", []):
                # Resolve all prerequisites including inherited ones
                all_prereqs = self._resolve_prerequisites(role_config, category.get("roles", []))

                # Check if user has at least one prerequisite
                if not all_prereqs:
                    # No prerequisites means anyone can select it
                    eligible_roles.append(
                        {
                            "category": category.get("name"),
                            "role_id": role_config.get("role_id"),
                            "name": role_config.get("name"),
                            "prerequisites": [],
                        }
                    )
                elif any(prereq in user_role_ids for prereq in all_prereqs):
                    # User has at least one prerequisite
                    eligible_roles.append(
                        {
                            "category": category.get("name"),
                            "role_id": role_config.get("role_id"),
                            "name": role_config.get("name"),
                            "prerequisites": all_prereqs,
                        }
                    )

        return eligible_roles

    def _resolve_prerequisites(self, role_config: Dict, all_roles_in_category: List[Dict], visited: Optional[set] = None) -> List[int]:
        """Recursively resolve all prerequisites for a role including inherited ones.

        Handles nested inheritance (e.g., Orange 500 → Orange 200 → Orange 100).

        Args:
            role_config: The role configuration to resolve prerequisites for
            all_roles_in_category: All role configs in the same category
            visited: Set of role IDs already visited (to prevent circular dependencies)

        Returns:
            List of all prerequisite role IDs (deduplicated)
        """
        if visited is None:
            visited = set()

        # Prevent circular dependencies
        current_role_id = role_config.get("role_id")
        if current_role_id in visited:
            self.logger.warning(f"Circular inheritance detected for role {current_role_id}")
            return []

        visited.add(current_role_id)

        # Start with direct prerequisites
        prereqs = set(role_config.get("prerequisite_roles", []))

        # Add inherited prerequisites (single role inheritance)
        inherits_from = role_config.get("inherits_from")
        if inherits_from:
            # Create a map for quick lookup
            role_map = {r.get("role_id"): r for r in all_roles_in_category}

            if inherits_from in role_map:
                # Recursively resolve prerequisites from inherited role
                inherited_prereqs = self._resolve_prerequisites(role_map[inherits_from], all_roles_in_category, visited.copy())
                prereqs.update(inherited_prereqs)

        return list(prereqs)

    async def assign_role_to_user(self, guild: discord.Guild, member: discord.Member, role_id: int) -> tuple[bool, str]:
        """Assign a role to a user, removing all other managed roles.

        Args:
            guild: The guild where the role assignment happens
            member: The member to assign the role to
            role_id: The role ID to assign

        Returns:
            Tuple of (success: bool, message: str)
        """
        # Check if user is eligible for this role
        user_role_ids = [role.id for role in member.roles]
        eligible_roles = self.get_eligible_roles(guild.id, user_role_ids)

        # Find the requested role in eligible roles
        target_role_config = None
        for eligible in eligible_roles:
            if eligible["role_id"] == role_id:
                target_role_config = eligible
                break

        if not target_role_config:
            return False, "You are not eligible for this role."

        # Get the role object
        role = guild.get_role(role_id)
        if not role:
            return False, "Role not found in server."

        try:
            # Remove all other managed roles from the user
            all_managed_roles = self.get_all_managed_roles(guild.id)
            roles_to_remove = [r for r in member.roles if r.id in all_managed_roles and r.id != role_id]

            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="Tourney role color selection")

            # Add the new role
            if role not in member.roles:
                await member.add_roles(role, reason="Tourney role color selection")

            return True, f"Successfully assigned {role.name}"

        except discord.Forbidden:
            return False, "Bot does not have permission to manage roles."
        except discord.HTTPException as e:
            self.logger.error(f"Error assigning role: {e}")
            return False, "An error occurred while assigning the role."


async def setup(bot: commands.Bot) -> None:
    """Load the TourneyRoleColors cog."""
    await bot.add_cog(TourneyRoleColors(bot))
