"""Tourney Role Colors cog - Allow users to select roles based on prerequisites."""

import asyncio
import logging
import random
from typing import Dict, List, Optional, Set, Tuple

import discord
from discord.ext import commands

from thetower.bot.basecog import BaseCog

from .ui import RoleSelectionButton, TourneyRoleColorsSettingsView

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

    # Global settings (bot owner only)
    global_settings = {
        "debounce_seconds": 15,  # Wait time before enforcing prerequisite changes
    }

    # Guild-specific settings
    guild_settings = {
        "categories": [],
        "auto_enforce_prerequisites": True,  # Auto-demote when prereqs lost
        "notify_on_demotion": False,  # DM users when auto-demoted
    }

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)

        # Track members being updated to prevent feedback loops
        self.updating_members: Set[Tuple[int, int]] = set()

        # Track pending prerequisite checks with debounce
        # Key: (guild_id, user_id), Value: asyncio.Task
        self.pending_prereq_checks: Dict[Tuple[int, int], asyncio.Task] = {}

        # Global settings (bot owner only)
        self.global_settings = {
            "debounce_seconds": 15,  # Wait time before enforcing prerequisite changes
        }

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
            "auto_enforce_prerequisites": True,  # Auto-demote when prereqs lost
            "notify_on_demotion": False,  # DM users when auto-demoted
        }

    async def _initialize_cog_specific(self, tracker) -> None:
        """Initialize cog-specific functionality."""
        # Register UI extensions
        tracker.update_status("Registering UI extensions")
        self.register_ui_extensions()

        # Run startup audit if enabled (defaults to False)
        # Check setting for each guild since this is a per-guild setting
        tracker.update_status("Checking startup audit settings")
        for guild in self.bot.guilds:
            if self.get_setting("enable_startup_audit", False, guild_id=guild.id):
                tracker.update_status(f"Auditing color roles for {guild.name}")
                await self.audit_guild_color_roles(guild)

    def register_ui_extensions(self) -> None:
        """Register UI extensions that this cog provides to other cogs."""
        # Register button provider for player profiles
        self.bot.cog_manager.register_ui_extension(
            target_cog="player_lookup", source_cog=self.__class__.__name__, provider_func=self.get_role_selection_button_for_profile
        )

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded."""
        # Cancel all pending prerequisite checks
        for task in self.pending_prereq_checks.values():
            if not task.done():
                task.cancel()
        self.pending_prereq_checks.clear()

        # Call parent implementation for data saving
        await super().cog_unload()
        self.logger.info("Tourney role colors cog unloaded")

    def get_role_selection_button_for_profile(
        self, details: dict, requesting_user: discord.User, guild_id: int, permission_context
    ) -> Optional[discord.ui.Button]:
        """Get a role selection button for player profiles.

        This method is called by the player_lookup cog to extend /profile functionality.
        Returns a button that opens the role selection interface, or None if there are
        no configured categories for this guild.

        Args:
            details: Player details dictionary (game_instances structure)
            requesting_user: The user viewing the profile
            guild_id: The guild ID where the profile is being viewed
            permission_context: Permission context for the requesting user

        Returns:
            A button that opens role selection, or None if not applicable
        """
        # Only show button if user is viewing their own profile (verified players only)
        if details.get("is_verified") is False:
            return None

        # Check if the requesting user is one of the player's linked Discord accounts
        # by checking all game instances and unassigned accounts
        all_discord_accounts = set()
        for instance in details.get("game_instances", []):
            all_discord_accounts.update(instance.get("discord_accounts_receiving_roles", []))
        all_discord_accounts.update(details.get("unassigned_discord_accounts", []))

        if all_discord_accounts and str(requesting_user.id) not in all_discord_accounts:
            return None

        # Check if there are any configured categories
        categories = self.get_setting("categories", [], guild_id=guild_id)
        if not categories:
            return None

        # Check if any categories have roles
        has_roles = any(cat.get("roles") for cat in categories)
        if not has_roles:
            return None

        # Create and return the button
        return RoleSelectionButton(self)

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

    def _find_descendant_roles(self, role_id: int, all_roles_in_category: List[Dict]) -> List[Dict]:
        """Find all roles that inherit from the given role (directly or indirectly).

        Returns roles in order from immediate children to deeper descendants.

        Args:
            role_id: The parent role ID to find descendants for
            all_roles_in_category: All role configs in the same category

        Returns:
            List of role configs that inherit from this role, ordered by distance
        """
        descendants = []

        # Find direct children
        direct_children = [role for role in all_roles_in_category if role.get("inherits_from") == role_id]

        # Add direct children first
        descendants.extend(direct_children)

        # Recursively find descendants of each child
        for child in direct_children:
            child_descendants = self._find_descendant_roles(child.get("role_id"), all_roles_in_category)
            descendants.extend(child_descendants)

        return descendants

    async def _find_demotion_role(
        self, member: discord.Member, current_role: discord.Role, guild_id: int, user_role_ids: List[int]
    ) -> Optional[discord.Role]:
        """Find the first descendant role the user qualifies for.

        Args:
            member: The member being checked
            current_role: The current role they no longer qualify for
            guild_id: The guild ID
            user_role_ids: List of role IDs the user currently has

        Returns:
            Discord role object if a qualifying descendant is found, None otherwise
        """
        # Find which category the current role belongs to
        categories = self.get_setting("categories", [], guild_id=guild_id)
        current_category = None
        current_role_config = None

        for category in categories:
            for role_config in category.get("roles", []):
                if role_config.get("role_id") == current_role.id:
                    current_category = category
                    current_role_config = role_config
                    break
            if current_category:
                break

        if not current_category or not current_role_config:
            return None

        # Find all descendants of the current role
        all_roles_in_category = current_category.get("roles", [])
        descendants = self._find_descendant_roles(current_role.id, all_roles_in_category)

        if not descendants:
            return None

        # Check each descendant in order (immediate children first)
        for descendant_config in descendants:
            descendant_role_id = descendant_config.get("role_id")

            # Check if user qualifies for this descendant
            # For demotion, only check the descendant's DIRECT prerequisites,
            # not inherited ones (since we already know they don't meet parent prereqs)
            direct_prereqs = descendant_config.get("prerequisite_roles", [])

            # User qualifies if they have no direct prerequisites or at least one direct prerequisite (OR logic)
            if not direct_prereqs or any(prereq in user_role_ids for prereq in direct_prereqs):
                # Get the actual Discord role object
                descendant_role = member.guild.get_role(descendant_role_id)
                if descendant_role:
                    return descendant_role

        return None

    async def _send_demotion_dm(self, member: discord.Member, old_role: discord.Role, new_role: discord.Role) -> None:
        """Send a DM to a user notifying them of their role demotion.

        Args:
            member: The member who was demoted
            old_role: The role they lost
            new_role: The role they were demoted to
        """
        try:
            embed = discord.Embed(
                title="🔄 Color Role Changed",
                description=(
                    f"Your **{old_role.name}** color role in **{member.guild.name}** has been "
                    f"changed to **{new_role.name}** because you no longer have the required "
                    f"tournament placement roles.\\n\\n"
                    f"You can select a different color from the available options using "
                    f"the role selection button on your profile."
                ),
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow(),
            )
            embed.set_footer(text=member.guild.name, icon_url=member.guild.icon.url if member.guild.icon else None)

            await member.send(embed=embed)
            self.logger.debug(f"Sent demotion DM to {member.display_name}")
        except discord.Forbidden:
            self.logger.debug(f"Could not DM {member.display_name} - DMs disabled")
        except discord.HTTPException as e:
            self.logger.error(f"Error sending demotion DM to {member.display_name}: {e}")

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
                # Log removals
                for removed_role in roles_to_remove:
                    await self.log_role_change(guild, member, removed_role, "removed", "User selected a different role")

            # Add the new role
            if role not in member.roles:
                await member.add_roles(role, reason="Tourney role color selection")
                # Log addition
                await self.log_role_change(guild, member, role, "added", "User selection")

            return True, f"Successfully assigned {role.name}"

        except discord.Forbidden:
            return False, "Bot does not have permission to manage roles."
        except discord.HTTPException as e:
            self.logger.error(f"Error assigning role: {e}")
            return False, "An error occurred while assigning the role."

    async def log_role_change(self, guild: discord.Guild, member: discord.Member, role: discord.Role, action: str, reason: str = "") -> None:
        """Log a role color change to the configured logging channel.

        Args:
            guild: The guild where the change happened
            member: The member whose role changed
            role: The role that was added or removed
            action: "added" or "removed"
            reason: Optional reason for the change
        """
        # Check if logging channel is configured
        log_channel_id = self.get_setting("role_color_log_channel_id", guild_id=guild.id)
        if not log_channel_id:
            return  # No logging channel configured

        channel = guild.get_channel(log_channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return  # Channel not found or not a text channel

        # Create log embed
        color = discord.Color.green() if action == "added" else discord.Color.red()
        embed = discord.Embed(title=f"Role Color {action.capitalize()}", color=color, timestamp=discord.utils.utcnow())
        embed.add_field(name="User", value=f"{member.mention} ({member.display_name})", inline=False)
        embed.add_field(name="Role", value=role.mention, inline=False)
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)

        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            self.logger.warning(f"Missing permissions to send to log channel {channel.name} in {guild.name}")
        except discord.HTTPException as e:
            self.logger.error(f"Error sending to log channel: {e}")

    async def audit_user_color_role(self, member: discord.Member) -> bool:
        """Audit a single user's color role and remove if prerequisites not met.

        Args:
            member: The member to audit (should have fresh data from fetch_member)

        Returns:
            True if a role was removed, False otherwise
        """
        guild_id = member.guild.id
        member_key = (guild_id, member.id)

        # Prevent feedback loops
        if member_key in self.updating_members:
            return False

        # Get all color roles this user has from our cog
        all_managed_roles = self.get_all_managed_roles(guild_id)
        user_color_roles = [role for role in member.roles if role.id in all_managed_roles]

        if not user_color_roles:
            return False  # No color roles to audit

        # If user has multiple color roles, resolve which to keep
        if len(user_color_roles) > 1:
            role_to_keep = self._resolve_multiple_color_roles(member, user_color_roles, guild_id)
            roles_to_remove = [r for r in user_color_roles if r.id != role_to_keep.id]
        else:
            role_to_keep = user_color_roles[0]
            roles_to_remove = []

        # Check if user still meets prerequisites for the role to keep
        user_role_ids = [role.id for role in member.roles]
        eligible_roles = self.get_eligible_roles(guild_id, user_role_ids)
        eligible_role_ids = [r["role_id"] for r in eligible_roles]

        if role_to_keep.id not in eligible_role_ids:
            # User no longer meets prerequisites
            # Check if auto-enforcement is enabled
            auto_enforce = self.get_setting("auto_enforce_prerequisites", True, guild_id=guild_id)

            if auto_enforce:
                # Try to find a descendant role they qualify for (demotion)
                demotion_role = await self._find_demotion_role(member, role_to_keep, guild_id, user_role_ids)

                if demotion_role:
                    # Demote to descendant role
                    try:
                        self.updating_members.add(member_key)
                        await member.remove_roles(role_to_keep, reason="Auto-demoted: prerequisites no longer met")
                        await member.add_roles(demotion_role, reason="Auto-demoted to qualifying descendant role")

                        self.logger.info(f"Auto-demoted {member.display_name} in {member.guild.name}: " f"{role_to_keep.name} → {demotion_role.name}")

                        # Log the change
                        await self.log_role_change(member.guild, member, role_to_keep, "removed", f"Auto-demoted to {demotion_role.name}")
                        await self.log_role_change(member.guild, member, demotion_role, "added", f"Auto-demoted from {role_to_keep.name}")

                        # Send DM notification if enabled
                        if self.get_setting("notify_on_demotion", False, guild_id=guild_id):
                            await self._send_demotion_dm(member, role_to_keep, demotion_role)

                        return True
                    except discord.Forbidden:
                        self.logger.error(f"Missing permissions to demote {member.display_name}")
                    except discord.HTTPException as e:
                        self.logger.error(f"Error demoting {member.display_name}: {e}")
                    finally:
                        self.updating_members.discard(member_key)

                    return False

            # No demotion possible or auto-enforcement disabled - remove the role
            roles_to_remove.append(role_to_keep)

        # Remove any roles that need to be removed
        if roles_to_remove:
            try:
                self.updating_members.add(member_key)
                await member.remove_roles(*roles_to_remove, reason="Tourney role color audit: prerequisites not met")
                self.logger.info(
                    f"Removed {len(roles_to_remove)} invalid color role(s) from {member.display_name} "
                    f"in {member.guild.name}: {', '.join(r.name for r in roles_to_remove)}"
                )
                # Log each removal
                for removed_role in roles_to_remove:
                    await self.log_role_change(member.guild, member, removed_role, "removed", "Prerequisites no longer met")
                return True
            except discord.Forbidden:
                self.logger.error(f"Missing permissions to remove roles from {member.display_name}")
            except discord.HTTPException as e:
                self.logger.error(f"Error removing roles from {member.display_name}: {e}")
            finally:
                self.updating_members.discard(member_key)

        return False

    def _resolve_multiple_color_roles(self, member: discord.Member, color_roles: List[discord.Role], guild_id: int) -> discord.Role:
        """Resolve which color role to keep when user has multiple.

        Logic:
        1. Group roles by category, keep category with most roles
        2. If tied, randomly pick a category
        3. Within winning category, keep most foundational role (required by others)

        Args:
            member: The member with multiple color roles
            color_roles: List of color roles the user has
            guild_id: The guild ID

        Returns:
            The role to keep
        """
        categories = self.get_setting("categories", [], guild_id=guild_id)

        # Build category map: category_name -> list of (role_id, role_config)
        category_roles: Dict[str, List[Tuple[int, Dict, discord.Role]]] = {}

        for role in color_roles:
            for category in categories:
                for role_config in category.get("roles", []):
                    if role_config.get("role_id") == role.id:
                        cat_name = category.get("name")
                        if cat_name not in category_roles:
                            category_roles[cat_name] = []
                        category_roles[cat_name].append((role.id, role_config, role))
                        break

        # Find category with most roles
        max_count = max(len(roles) for roles in category_roles.values())
        top_categories = [cat for cat, roles in category_roles.items() if len(roles) == max_count]

        # If tied, pick random category
        winning_category = random.choice(top_categories) if len(top_categories) > 1 else top_categories[0]

        # Within winning category, find most foundational role
        winning_roles = category_roles[winning_category]

        if len(winning_roles) == 1:
            return winning_roles[0][2]  # Return the discord.Role object

        # Count how many other roles each role is prerequisite for
        role_scores: Dict[int, int] = {}

        for role_id, role_config, role_obj in winning_roles:
            score = 0
            # Check how many OTHER roles user has that inherit from this role
            for other_id, other_config, _ in winning_roles:
                if other_id == role_id:
                    continue
                # Check if role_id is in other role's inherited prerequisites
                other_category = next(c for c in categories if c.get("name") == winning_category)
                inherited_prereqs = self._get_inherited_prerequisite_ids(other_config, other_category.get("roles", []))
                if role_id in inherited_prereqs:
                    score += 1
            role_scores[role_id] = score

        # Keep role with highest score (most foundational)
        winning_role_id = max(role_scores, key=role_scores.get)
        return next(role_obj for rid, _, role_obj in winning_roles if rid == winning_role_id)

    def _get_inherited_prerequisite_ids(self, role_config: Dict, all_roles_in_category: List[Dict]) -> List[int]:
        """Get all role IDs from inherited prerequisites (not external prerequisites).

        Args:
            role_config: The role configuration
            all_roles_in_category: All role configs in the same category

        Returns:
            List of role IDs that are inherited from other color roles
        """
        inherited_ids = []
        role_map = {r.get("role_id"): r for r in all_roles_in_category}

        # Traverse inheritance chain
        current_role = role_config
        visited = set()

        while current_role:
            current_id = current_role.get("role_id")
            if current_id in visited:
                break  # Prevent cycles
            visited.add(current_id)

            inherits_from = current_role.get("inherits_from")
            if inherits_from and inherits_from in role_map:
                inherited_ids.append(inherits_from)
                current_role = role_map[inherits_from]
            else:
                break

        return inherited_ids

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Monitor role changes and enforce prerequisite requirements.

        When a prerequisite role is removed, start a debounce timer.
        If another qualified prerequisite is added within that time, cancel the timer.
        Otherwise, audit and potentially remove the color role.
        """
        # Only process if roles changed
        if before.roles == after.roles:
            return

        guild_id = after.guild.id
        member_key = (guild_id, after.id)

        # Skip if we're currently updating this member (prevent feedback loops)
        if member_key in self.updating_members:
            return

        # Check if member has any color roles from our cog
        all_managed_roles = self.get_all_managed_roles(guild_id)
        has_color_role = any(role.id in all_managed_roles for role in after.roles)

        if not has_color_role:
            return  # Nothing to monitor

        # Get roles that were removed and added
        removed_roles = set(before.roles) - set(after.roles)
        added_roles = set(after.roles) - set(before.roles)

        # Check if a qualified prerequisite was added
        if added_roles:
            after_role_ids = [role.id for role in after.roles]
            # Check if user now has any eligible roles (meaning they have prerequisites)
            has_eligible_roles = bool(self.get_eligible_roles(guild_id, after_role_ids))

            # If user now has prerequisites for their color role, cancel any pending check
            if has_eligible_roles and member_key in self.pending_prereq_checks:
                self.pending_prereq_checks[member_key].cancel()
                del self.pending_prereq_checks[member_key]
                self.logger.debug(f"Cancelled prerequisite check for {after.display_name}: qualified role added")
            return

        # Check if any prerequisite roles were removed
        if removed_roles:
            # Cancel any existing pending check and start a new one
            if member_key in self.pending_prereq_checks:
                self.pending_prereq_checks[member_key].cancel()

            # Start new debounce timer
            task = asyncio.create_task(self._debounced_prerequisite_check(after.guild, after.id))
            self.pending_prereq_checks[member_key] = task
            debounce = self.get_global_setting("debounce_seconds", 15)
            self.logger.debug(f"Started {debounce}s prerequisite check for {after.display_name} after role removal")

    async def _debounced_prerequisite_check(self, guild: discord.Guild, user_id: int) -> None:
        """Wait for configured debounce period then audit the user's color role.

        Args:
            guild: The guild
            user_id: The user ID to check
        """
        member_key = (guild.id, user_id)

        try:
            # Wait for configured debounce time for role changes to settle
            debounce_seconds = self.get_global_setting("debounce_seconds", 15)
            await asyncio.sleep(debounce_seconds)

            # Fetch fresh member data
            member = await guild.fetch_member(user_id)

            # Audit the member's color role
            removed = await self.audit_user_color_role(member)

            if removed:
                self.logger.info(f"Debounced audit removed color role from {member.display_name} " f"in {guild.name} due to missing prerequisites")

        except asyncio.CancelledError:
            # Task was cancelled (new role added or another removal happened)
            self.logger.debug(f"Prerequisite check cancelled for user {user_id} in {guild.name}")
        except discord.NotFound:
            self.logger.warning(f"Member {user_id} not found in {guild.name} during audit")
        except Exception as e:
            self.logger.error(f"Error in debounced prerequisite check for user {user_id} in {guild.name}: {e}", exc_info=True)
        finally:
            # Clean up the pending check
            self.pending_prereq_checks.pop(member_key, None)

    async def audit_guild_color_roles(self, guild: discord.Guild) -> None:
        """Audit all users with color roles in a specific guild.

        Removes color roles from users who no longer meet prerequisites.
        Individual removals are logged to the configured channel.

        Args:
            guild: The guild to audit
        """
        try:
            categories = self.get_setting("categories", [], guild_id=guild.id)
            if not categories:
                return

            # Iterate through all color roles and check their members
            for category in categories:
                for role_config in category.get("roles", []):
                    role_id = role_config.get("role_id")
                    if not role_id:
                        continue

                    role = guild.get_role(role_id)
                    if not role:
                        continue

                    # Audit each member with this role
                    for member in role.members:
                        await self.audit_user_color_role(member)

            self.logger.info(f"Startup audit complete for {guild.name}")

        except Exception as e:
            self.logger.error(f"Error auditing color roles in {guild.name}: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_tourney_role_added(self, member: discord.Member, role: discord.Role) -> None:
        """Handle tournament role additions - check if user now qualifies for color roles."""
        try:
            guild_id = member.guild.id
            member_key = (guild_id, member.id)

            # Skip if we're currently updating this member (prevent feedback loops)
            if member_key in self.updating_members:
                return

            # Check if member has any color roles from our cog
            all_managed_roles = self.get_all_managed_roles(guild_id)
            has_color_role = any(role.id in all_managed_roles for role in member.roles)

            if not has_color_role:
                return  # Nothing to check

            # User has a color role - check if they still qualify with the new tournament role
            after_role_ids = [role.id for role in member.roles]
            has_eligible_roles = bool(self.get_eligible_roles(guild_id, after_role_ids))

            # If user no longer has prerequisites, start debounced check
            if not has_eligible_roles:
                # Cancel any existing pending check and start a new one
                if member_key in self.pending_prereq_checks:
                    self.pending_prereq_checks[member_key].cancel()

                # Start new debounce timer
                task = asyncio.create_task(self._debounced_prerequisite_check(member.guild, member.id))
                self.pending_prereq_checks[member_key] = task
                self.logger.debug(f"Started 15s prerequisite check for {member.display_name} after tournament role addition")

        except Exception as e:
            self.logger.error(f"Error handling tourney_role_added for {member.display_name}: {e}")

    @commands.Cog.listener()
    async def on_tourney_role_removed(self, member: discord.Member, role: discord.Role) -> None:
        """Handle tournament role removals - check if user still qualifies for color roles."""
        try:
            guild_id = member.guild.id
            member_key = (guild_id, member.id)

            # Skip if we're currently updating this member (prevent feedback loops)
            if member_key in self.updating_members:
                return

            # Check if member has any color roles from our cog
            all_managed_roles = self.get_all_managed_roles(guild_id)
            has_color_role = any(role.id in all_managed_roles for role in member.roles)

            if not has_color_role:
                return  # Nothing to check

            # User has a color role - check if they still qualify after tournament role removal
            after_role_ids = [role.id for role in member.roles]
            has_eligible_roles = bool(self.get_eligible_roles(guild_id, after_role_ids))

            # If user no longer has prerequisites, start debounced check
            if not has_eligible_roles:
                # Cancel any existing pending check and start a new one
                if member_key in self.pending_prereq_checks:
                    self.pending_prereq_checks[member_key].cancel()

                # Start new debounce timer
                task = asyncio.create_task(self._debounced_prerequisite_check(member.guild, member.id))
                self.pending_prereq_checks[member_key] = task
                self.logger.debug(f"Started 15s prerequisite check for {member.display_name} after tournament role removal")

        except Exception as e:
            self.logger.error(f"Error handling tourney_role_removed for {member.display_name}: {e}")

    async def audit_all_color_roles(self) -> None:
        """Audit all users with color roles on startup for all guilds.

        Removes color roles from users who no longer meet prerequisites.
        Individual removals are logged to the configured channel.
        """
        for guild in self.bot.guilds:
            await self.audit_guild_color_roles(guild)

        self.logger.info("Startup audit complete for all guilds")


async def setup(bot: commands.Bot) -> None:
    """Load the TourneyRoleColors cog."""
    await bot.add_cog(TourneyRoleColors(bot))
