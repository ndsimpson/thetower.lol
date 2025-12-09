"""
Core business logic and shared components for the Tourney Role Colors cog.

This module contains:
- Business logic for role qualification and assignment
- Data structures for color categories and roles
- Automatic role management
- User interface creation
"""

from typing import Any, Dict, List, Optional, Set

import discord
from discord import ui

from thetower.bot.basecog import BaseCog

from .user import ColorSelectionView


class TourneyRoleColorsCore:
    """Core business logic for tournament role colors management."""

    def __init__(self, cog: BaseCog):
        self.cog = cog
        self.logger = cog.logger

    def get_color_categories(self, guild_id: int) -> Dict[str, Dict[str, Any]]:
        """Get color categories configuration for a guild."""
        return self.cog.get_setting("color_categories", {}, guild_id=guild_id)

    def set_color_categories(self, guild_id: int, categories: Dict[str, Dict[str, Any]]) -> None:
        """Set color categories configuration for a guild."""
        self.cog.set_setting("color_categories", categories, guild_id=guild_id)

    def get_all_color_role_ids(self, guild_id: int) -> Set[int]:
        """Get all color role IDs across all categories."""
        categories = self.get_color_categories(guild_id)
        role_ids = set()

        for category_data in categories.values():
            role_ids.update(category_data.get("roles", {}).keys())

        return role_ids

    def get_user_current_color_role(self, user: discord.Member) -> Optional[int]:
        """Get the user's current color role ID, if any."""
        color_role_ids = self.get_all_color_role_ids(user.guild.id)

        for role in user.roles:
            if role.id in color_role_ids:
                return role.id

        return None

    def get_all_prerequisites(self, guild_id: int, role_id: int, visited: Optional[Set[int]] = None) -> List[str]:
        """Recursively collect all prerequisites for a role."""
        if visited is None:
            visited = set()

        if role_id in visited:
            return []  # Prevent cycles

        visited.add(role_id)

        categories = self.get_color_categories(guild_id)
        prerequisites = []

        # Find the role in categories
        for category_data in categories.values():
            roles = category_data.get("roles", {})
            if role_id in roles:
                role_config = roles[role_id]

                # Add this role's additional prerequisites
                prerequisites.extend(role_config.get("additional_prerequisites", []))

                # Recursively add inherited prerequisites
                inherits_from = role_config.get("inherits_from")
                if inherits_from:
                    inherited = self.get_all_prerequisites(guild_id, inherits_from, visited)
                    prerequisites.extend(inherited)

                break

        return list(set(prerequisites))  # Remove duplicates

    def user_qualifies_for_role(self, user: discord.Member, role_id: int) -> bool:
        """Check if user qualifies for a specific color role."""
        all_prerequisites = self.get_all_prerequisites(user.guild.id, role_id)

        # User qualifies if they have ANY of the prerequisite roles
        for prereq_name in all_prerequisites:
            prereq_role_id = self._get_role_id_by_name(user.guild, prereq_name)
            if prereq_role_id and user.get_role(prereq_role_id):
                return True

        return False

    def get_qualified_roles_for_user(self, user: discord.Member) -> List[Dict[str, Any]]:
        """Get all color roles the user qualifies for, organized by category."""
        categories = self.get_color_categories(user.guild.id)
        qualified_roles = []

        for category_name, category_data in categories.items():
            category_roles = []

            for role_id, role_config in category_data.get("roles", {}).items():
                if self.user_qualifies_for_role(user, role_id):
                    # Get role name for display
                    role = user.guild.get_role(role_id)
                    role_name = role.name if role else f"Role {role_id}"

                    category_roles.append(
                        {"role_id": role_id, "role_name": role_name, "prerequisites": self.get_all_prerequisites(user.guild.id, role_id)}
                    )

            if category_roles:
                qualified_roles.append({"category_name": category_name, "roles": category_roles})

        return qualified_roles

    async def assign_color_role(self, user: discord.Member, role_id: int) -> bool:
        """Assign a color role to user, removing any existing color roles."""
        try:
            # Remove current color role if any
            current_role_id = self.get_user_current_color_role(user)
            if current_role_id and current_role_id != role_id:
                current_role = user.guild.get_role(current_role_id)
                if current_role:
                    await user.remove_roles(current_role, reason="Color role change")

            # Add new color role
            new_role = user.guild.get_role(role_id)
            if new_role:
                await user.add_roles(new_role, reason="Color role selection")
                return True

        except discord.Forbidden:
            self.logger.error(f"Missing permissions to manage roles for user {user}")
        except Exception as e:
            self.logger.error(f"Error assigning color role {role_id} to user {user}: {e}")

        return False

    async def remove_color_role(self, user: discord.Member) -> bool:
        """Remove any color role from user."""
        try:
            current_role_id = self.get_user_current_color_role(user)
            if current_role_id:
                current_role = user.guild.get_role(current_role_id)
                if current_role:
                    await user.remove_roles(current_role, reason="Color role removal")
                    return True

        except discord.Forbidden:
            self.logger.error(f"Missing permissions to manage roles for user {user}")
        except Exception as e:
            self.logger.error(f"Error removing color role from user {user}: {e}")

        return False

    async def handle_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Handle automatic role adjustments when user roles change."""
        # Check if roles actually changed
        if before.roles == after.roles:
            return

        # Check if user has a color role
        current_color_role_id = self.get_user_current_color_role(after)
        if not current_color_role_id:
            return  # User doesn't have a color role, nothing to adjust

        # Check if user still qualifies for their current color role
        if not self.user_qualifies_for_role(after, current_color_role_id):
            # Find the highest-tier role they now qualify for
            qualified_data = self.get_qualified_roles_for_user(after)

            if qualified_data:
                # Find the "highest" qualified role (deepest inheritance)
                best_role = None
                max_depth = 0

                for category in qualified_data:
                    for role_info in category["roles"]:
                        depth = self._get_inheritance_depth(after.guild.id, role_info["role_id"])
                        if depth > max_depth:
                            max_depth = depth
                            best_role = role_info["role_id"]

                if best_role and best_role != current_color_role_id:
                    # Demote to qualified role
                    await self.assign_color_role(after, best_role)
                    self.logger.info(f"Demoted user {after} from role {current_color_role_id} to {best_role}")
                elif not best_role:
                    # Remove color role entirely
                    await self.remove_color_role(after)
                    self.logger.info(f"Removed color role {current_color_role_id} from user {after} - no longer qualified")
            else:
                # No qualified roles, remove color role
                await self.remove_color_role(after)
                self.logger.info(f"Removed color role {current_color_role_id} from user {after} - no longer qualified")

    def create_color_selection_view(self, user: discord.Member) -> ui.View:
        """Create the color selection view for the user."""
        qualified_data = self.get_qualified_roles_for_user(user)
        current_role_id = self.get_user_current_color_role(user)

        return ColorSelectionView(self.cog, qualified_data, current_role_id)

    def _get_inheritance_depth(self, guild_id: int, role_id: int, visited: Optional[Set[int]] = None) -> int:
        """Get inheritance depth for a role."""
        if visited is None:
            visited = set()

        if role_id in visited:
            return 0  # Prevent cycles

        visited.add(role_id)

        categories = self.get_color_categories(guild_id)

        # Find the role
        for category_data in categories.values():
            roles = category_data.get("roles", {})
            if role_id in roles:
                role_config = roles[role_id]
                inherits_from = role_config.get("inherits_from")

                if inherits_from:
                    parent_depth = self._get_inheritance_depth(guild_id, inherits_from, visited)
                    return parent_depth + 1
                else:
                    return 1  # Base level

        return 0  # Role not found

    def _get_role_id_by_name(self, guild: discord.Guild, role_name: str) -> Optional[int]:
        """Get role ID by name."""
        role = discord.utils.get(guild.roles, name=role_name)
        return role.id if role else None

    # Management methods for settings UI

    async def add_color_category(self, guild_id: int, category_name: str, description: str = "") -> bool:
        """Add a new color category."""
        try:
            categories = self.get_color_categories(guild_id)
            if category_name in categories:
                return False  # Category already exists

            categories[category_name] = {"description": description, "roles": {}}
            self.set_color_categories(guild_id, categories)
            return True
        except Exception as e:
            self.logger.error(f"Error adding color category {category_name}: {e}")
            return False

    async def remove_color_category(self, guild_id: int, category_name: str) -> bool:
        """Remove a color category."""
        try:
            categories = self.get_color_categories(guild_id)
            if category_name not in categories:
                return False  # Category doesn't exist

            del categories[category_name]
            self.set_color_categories(guild_id, categories)
            return True
        except Exception as e:
            self.logger.error(f"Error removing color category {category_name}: {e}")
            return False

    async def add_color_role(self, guild_id: int, category_name: str, role_id: int, additional_prerequisites: List[str]) -> bool:
        """Add a color role to a category."""
        try:
            categories = self.get_color_categories(guild_id)
            if category_name not in categories:
                return False  # Category doesn't exist

            category = categories[category_name]
            if str(role_id) in category["roles"]:
                return False  # Role already in category

            category["roles"][str(role_id)] = {"additional_prerequisites": additional_prerequisites, "inherits_from": None}
            self.set_color_categories(guild_id, categories)
            return True
        except Exception as e:
            self.logger.error(f"Error adding color role {role_id} to category {category_name}: {e}")
            return False

    async def remove_color_role_from_category(self, guild_id: int, category_name: str, role_id: int) -> bool:
        """Remove a color role from a category."""
        try:
            categories = self.get_color_categories(guild_id)
            if category_name not in categories:
                return False  # Category doesn't exist

            category = categories[category_name]
            if str(role_id) not in category["roles"]:
                return False  # Role not in category

            del category["roles"][str(role_id)]
            self.set_color_categories(guild_id, categories)
            return True
        except Exception as e:
            self.logger.error(f"Error removing color role {role_id} from category {category_name}: {e}")
            return False

    async def set_role_inheritance(self, guild_id: int, category_name: str, role_id: int, inherits_from_id: int) -> bool:
        """Set inheritance for a color role."""
        try:
            categories = self.get_color_categories(guild_id)
            if category_name not in categories:
                return False  # Category doesn't exist

            category = categories[category_name]
            if str(role_id) not in category["roles"]:
                return False  # Role not in category

            # Check for circular inheritance
            if self._would_create_inheritance_cycle(guild_id, role_id, inherits_from_id):
                return False  # Would create cycle

            category["roles"][str(role_id)]["inherits_from"] = inherits_from_id
            self.set_color_categories(guild_id, categories)
            return True
        except Exception as e:
            self.logger.error(f"Error setting inheritance for role {role_id}: {e}")
            return False

    def _would_create_inheritance_cycle(self, guild_id: int, role_id: int, inherits_from_id: int) -> bool:
        """Check if setting inheritance would create a cycle."""
        visited = set()
        current = inherits_from_id

        while current is not None:
            if current == role_id:
                return True  # Cycle detected
            if current in visited:
                return True  # Already visited (shouldn't happen in normal case)
            visited.add(current)

            # Find the role that current inherits from
            categories = self.get_color_categories(guild_id)
            for cat_data in categories.values():
                for role_str, role_data in cat_data["roles"].items():
                    if int(role_str) == current:
                        current = role_data.get("inherits_from")
                        break
                else:
                    continue
                break
            else:
                current = None  # Role not found, end chain

        return False
        return False
