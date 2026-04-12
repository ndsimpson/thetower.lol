"""Optional Roles cog - Allow users to opt into community roles with prerequisites."""

import asyncio
import logging
from typing import Dict, List, Optional, Set, Tuple

import discord
from discord.ext import commands

from thetower.bot.basecog import BaseCog

from .ui import OptionalRolesSettingsView, RoleSelectionButton

logger = logging.getLogger(__name__)


class OptionalRoles(BaseCog, name="Optional Roles"):
    """Manage user-selectable optional roles with prerequisites.

    Server owners can configure:
    - Categories of roles (can be single-selection or multi-selection)
    - Individual role options within categories
    - Prerequisite roles required to opt into each role
    - Automatic enforcement when prerequisites are lost
    """

    # Register the settings view class for the modular settings system
    settings_view_class = OptionalRolesSettingsView

    # Global settings (bot owner only)
    global_settings = {
        "debounce_seconds": 15,  # Wait time before enforcing prerequisite changes
    }

    # Guild-specific settings
    guild_settings = {
        "categories": [],  # List of category configurations
        "auto_enforce_prerequisites": True,  # Auto-remove roles when prereqs lost
        "notify_on_removal": True,  # DM users when auto-removed
    }

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)

        # Track members being updated to prevent feedback loops
        self.updating_members: Set[Tuple[int, int]] = set()

        # Track pending prerequisite checks with debounce
        # Key: (guild_id, user_id), Value: asyncio.Task
        self.pending_prereq_checks: Dict[Tuple[int, int], asyncio.Task] = {}

    async def _initialize_cog_specific(self, tracker) -> None:
        """Initialize cog-specific functionality."""
        tracker.update_status("Registering UI extensions")
        self.register_ui_extensions()

        tracker.update_status("Registering event listeners")
        # Role change monitoring is handled by on_member_update listener

    def register_ui_extensions(self) -> None:
        """Register UI extensions that this cog provides to other cogs."""
        # Register button provider for player profiles
        self.bot.cog_manager.register_ui_extension(
            target_cog="player_lookup", source_cog=self.__class__.__name__, provider_func=self.get_role_button_for_profile
        )

        # Register view provider for post-verification flow
        self.bot.cog_manager.register_ui_extension(
            target_cog="validation", source_cog=self.__class__.__name__, provider_func=self.get_post_verification_view
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

    def get_role_button_for_profile(
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

    def get_user_managed_roles(self, guild_id: int, user_role_ids: List[int]) -> List[int]:
        """Get which managed roles a user currently has.

        Args:
            guild_id: The guild ID
            user_role_ids: List of role IDs the user has

        Returns:
            List of managed role IDs the user has
        """
        managed_roles = self.get_all_managed_roles(guild_id)
        return [role_id for role_id in user_role_ids if role_id in managed_roles]

    def get_eligible_roles(self, guild_id: int, user_role_ids: List[int]) -> List[Dict]:
        """Get all roles a user is eligible to select based on their current roles.

        Args:
            guild_id: The guild ID
            user_role_ids: List of role IDs the user currently has

        Returns:
            List of role configs the user is eligible for, with category info added
        """
        categories = self.get_setting("categories", [], guild_id=guild_id)
        eligible = []

        for category in categories:
            category_name = category.get("name", "Unknown")
            selection_mode = category.get("selection_mode", "single")

            for role_config in category.get("roles", []):
                prerequisite_roles = role_config.get("prerequisite_roles", [])

                # Check if user meets prerequisites (needs at least one)
                has_prereq = not prerequisite_roles or any(prereq_id in user_role_ids for prereq_id in prerequisite_roles)

                if has_prereq:
                    # Add category context to role config
                    role_with_context = role_config.copy()
                    role_with_context["category"] = category_name
                    role_with_context["selection_mode"] = selection_mode
                    eligible.append(role_with_context)

        return eligible

    def get_category_config(self, guild_id: int, category_name: str) -> Optional[Dict]:
        """Get configuration for a specific category.

        Args:
            guild_id: The guild ID
            category_name: Name of the category

        Returns:
            Category configuration dict or None if not found
        """
        categories = self.get_setting("categories", [], guild_id=guild_id)
        for category in categories:
            if category.get("name") == category_name:
                return category
        return None

    def get_role_config(self, guild_id: int, role_id: int) -> Optional[Dict]:
        """Get configuration for a specific role.

        Args:
            guild_id: The guild ID
            role_id: The role ID to look up

        Returns:
            Role configuration dict with category info, or None if not found
        """
        categories = self.get_setting("categories", [], guild_id=guild_id)
        for category in categories:
            for role_config in category.get("roles", []):
                if role_config.get("role_id") == role_id:
                    result = role_config.copy()
                    result["category"] = category.get("name", "Unknown")
                    result["selection_mode"] = category.get("selection_mode", "single")
                    return result
        return None

    async def check_prerequisites(self, member: discord.Member) -> List[int]:
        """Check which optional roles the member has but no longer qualifies for.

        Args:
            member: The member to check

        Returns:
            List of role IDs that should be removed
        """
        user_role_ids = [role.id for role in member.roles]
        managed_roles = self.get_user_managed_roles(member.guild.id, user_role_ids)
        to_remove = []

        for role_id in managed_roles:
            role_config = self.get_role_config(member.guild.id, role_id)
            if not role_config:
                continue

            prerequisite_roles = role_config.get("prerequisite_roles", [])
            # If there are prerequisites, user must have at least one
            if prerequisite_roles:
                has_prereq = any(prereq_id in user_role_ids for prereq_id in prerequisite_roles)
                if not has_prereq:
                    to_remove.append(role_id)

        return to_remove

    async def enforce_prerequisites(self, member: discord.Member, roles_to_remove: List[int]) -> None:
        """Remove roles from a member due to lost prerequisites.

        Args:
            member: The member to update
            roles_to_remove: List of role IDs to remove
        """
        if not roles_to_remove:
            return

        # Prevent feedback loops
        member_key = (member.guild.id, member.id)
        if member_key in self.updating_members:
            return

        self.updating_members.add(member_key)
        try:
            # Get role objects
            roles_objs = [member.guild.get_role(role_id) for role_id in roles_to_remove]
            roles_objs = [r for r in roles_objs if r is not None]

            if not roles_objs:
                return

            # Remove the roles
            await member.remove_roles(*roles_objs, reason="Optional role prerequisites no longer met")

            # Log the removal
            role_names = [r.name for r in roles_objs]
            self.logger.info(f"Removed optional roles from {member} in {member.guild}: {', '.join(role_names)}")

            # Notify user if configured
            if self.get_setting("notify_on_removal", True, guild_id=member.guild.id):
                try:
                    role_list = "\n".join(f"• {name}" for name in role_names)
                    await member.send(
                        f"**Optional Roles Removed**\n\n"
                        f"You no longer meet the requirements for the following optional roles in **{member.guild.name}**:\n"
                        f"{role_list}\n\n"
                        f"These roles were automatically removed because you lost the prerequisite roles needed to keep them."
                    )
                except discord.Forbidden:
                    self.logger.debug(f"Could not DM {member} about role removal (DMs disabled)")

        finally:
            self.updating_members.discard(member_key)

    async def schedule_prerequisite_check(self, member: discord.Member) -> None:
        """Schedule a debounced prerequisite check for a member.

        Args:
            member: The member to check
        """
        member_key = (member.guild.id, member.id)

        # Cancel existing check if any
        if member_key in self.pending_prereq_checks:
            existing_task = self.pending_prereq_checks[member_key]
            if not existing_task.done():
                existing_task.cancel()

        # Schedule new check
        async def delayed_check():
            debounce = self.get_global_setting("debounce_seconds", 15)
            await asyncio.sleep(debounce)

            # Refresh member object in case they left/rejoined
            try:
                guild = self.bot.get_guild(member.guild.id)
                if not guild:
                    return

                fresh_member = guild.get_member(member.id)
                if not fresh_member:
                    return

                # Check prerequisites
                auto_enforce = self.get_setting("auto_enforce_prerequisites", True, guild_id=guild.id)
                if auto_enforce:
                    roles_to_remove = await self.check_prerequisites(fresh_member)
                    await self.enforce_prerequisites(fresh_member, roles_to_remove)

            finally:
                # Clean up task reference
                self.pending_prereq_checks.pop(member_key, None)

        task = asyncio.create_task(delayed_check())
        self.pending_prereq_checks[member_key] = task

    # === UI Extension Providers ===

    def get_post_verification_view(self, interaction: discord.Interaction, **kwargs) -> Optional[discord.ui.View]:
        """Get view with role selection buttons for post-verification flow.

        Called by validation cog after successful verification to add optional role
        selection to the ephemeral verification success message.

        Args:
            interaction: Verification interaction
            **kwargs: Additional context (unused)

        Returns:
            View with role selection buttons, or None if no eligible roles
        """
        try:
            guild = interaction.guild
            if not guild:
                return None

            member = interaction.user
            if not isinstance(member, discord.Member):
                return None

            # Get verification categories
            categories = self.get_setting("categories", [], guild_id=guild.id)
            verification_categories = [cat for cat in categories if cat.get("show_on_verification", False)]

            if not verification_categories:
                self.logger.debug(f"No verification categories configured for guild {guild.id}")
                return None

            # Build list of eligible roles
            user_role_ids = set(role.id for role in member.roles)
            eligible_roles = []

            for category in verification_categories:
                category_name = category.get("name")
                selection_mode = category.get("selection_mode", "single")

                for role_config in category.get("roles", []):
                    if self.check_prerequisites(role_config, user_role_ids):
                        eligible_roles.append(
                            {
                                "role_id": role_config["role_id"],
                                "category": category_name,
                                "selection_mode": selection_mode,
                                "emoji": role_config.get("emoji"),
                            }
                        )

            if not eligible_roles:
                self.logger.debug(f"No eligible roles for {member.id} in guild {guild.id} post-verification")
                return None

            # Import here to avoid circular dependency
            from .ui.user import PostVerificationRoleView

            return PostVerificationRoleView(self, member, guild.id, eligible_roles)

        except Exception as e:
            self.logger.error(f"Error creating post-verification view: {e}", exc_info=True)
            return None

    # === Event Listeners ===

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Monitor role changes to enforce prerequisites.

        Args:
            before: Member state before update
            after: Member state after update
        """
        # Only process if roles changed
        if before.roles == after.roles:
            return

        # Skip if no categories configured
        categories = self.get_setting("categories", [], guild_id=after.guild.id)
        if not categories:
            return

        # Skip if we're the one making changes (prevent loops)
        member_key = (after.guild.id, after.id)
        if member_key in self.updating_members:
            return

        # Check if any managed roles or prerequisite roles changed
        before_role_ids = {role.id for role in before.roles}
        after_role_ids = {role.id for role in after.roles}

        # Get all role IDs we care about (managed + all prerequisites)
        all_managed = set(self.get_all_managed_roles(after.guild.id))
        all_prereqs = set()
        for category in categories:
            for role_config in category.get("roles", []):
                all_prereqs.update(role_config.get("prerequisite_roles", []))

        relevant_roles = all_managed | all_prereqs

        # Check if any relevant roles changed
        changed_roles = (before_role_ids ^ after_role_ids) & relevant_roles
        if changed_roles:
            # Schedule prerequisite check with debounce
            await self.schedule_prerequisite_check(after)
