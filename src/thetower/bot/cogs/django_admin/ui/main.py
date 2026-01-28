# Main UI interface for Django Admin cog

import discord
from asgiref.sync import sync_to_async
from django.contrib.auth.models import Group, User

from thetower.backend.sus.models import KnownPlayer, PlayerId


class DjangoAdminMainView(discord.ui.View):
    """Main navigation view for Django Admin."""

    def __init__(self, cog, interaction: discord.Interaction, parent_view=None):
        super().__init__(timeout=900)
        self.cog = cog
        self.interaction = interaction
        self.parent_view = parent_view

    def create_main_embed(self) -> discord.Embed:
        """Create the main menu embed."""
        embed = discord.Embed(
            title="🔧 Django Administration Panel",
            description="Manage Django users, groups, and user-player linking",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(name="👥 Group Management", value="Create, edit, delete, and view Django groups", inline=False)

        embed.add_field(name="👤 User Management", value="View and create Django users", inline=False)

        embed.add_field(name="🔗 User Linking", value="Link Django users to Discord users and KnownPlayers", inline=False)

        embed.set_footer(text="Select an option below to continue")
        return embed

    @discord.ui.button(label="Back to Settings", style=discord.ButtonStyle.secondary, emoji="⬅️", row=2)
    async def back_to_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Return to settings view."""
        if self.parent_view:
            embed = self.parent_view.create_settings_embed()
            await interaction.response.edit_message(embed=embed, view=self.parent_view)
        else:
            embed = discord.Embed(title="Settings", description="Returned to settings. You can close this message.", color=discord.Color.blue())
            await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="Group Management", style=discord.ButtonStyle.primary, emoji="👥", row=0)
    async def group_management(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open group management interface."""
        await interaction.response.defer()
        view = GroupManagementView(self.cog, interaction, self)
        embed = await view.create_embed()
        await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=view)

    @discord.ui.button(label="User Management", style=discord.ButtonStyle.primary, emoji="👤", row=0)
    async def user_management(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open user management interface."""
        view = UserManagementView(self.cog, interaction, self)
        embed = view.create_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="User Linking", style=discord.ButtonStyle.primary, emoji="🔗", row=0)
    async def user_linking(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open user linking interface."""
        view = UserLinkingView(self.cog, interaction, self)
        embed = view.create_embed()
        await interaction.response.edit_message(embed=embed, view=view)


# ====================
# Group Selection View for Dropdown Actions
# ====================


class GroupSelectView(discord.ui.View):
    """View with dropdown for selecting a group."""

    def __init__(self, cog, parent_view, interaction: discord.Interaction, action: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.parent_view = parent_view
        self.original_interaction = interaction
        self.action = action

        # Add the select menu
        select = GroupSelect(cog, parent_view, action)
        self.add_item(select)


class GroupSelect(discord.ui.Select):
    """Dropdown for selecting a group."""

    def __init__(self, cog, parent_view, action: str):
        self.cog = cog
        self.parent_view = parent_view
        self.action = action

        # Build options from parent_view.groups
        options = []
        for gid, name, count in parent_view.groups[:25]:  # Discord limit of 25 options
            options.append(discord.SelectOption(label=name, value=str(gid), description=f"ID: {gid} | {count} users"))

        super().__init__(
            placeholder="Select a group...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        """Handle group selection."""
        group_id = int(self.values[0])

        if self.action == "rename":
            # Show modal for new name
            modal = RenameGroupModal(self.cog, self.parent_view, group_id)
            await interaction.response.send_modal(modal)
        elif self.action == "delete":
            # Confirm and delete
            await self._handle_delete(interaction, group_id)
        elif self.action == "manage_members":
            # Show member management view
            await self._handle_manage_members(interaction, group_id)

    async def _handle_delete(self, interaction: discord.Interaction, group_id: int):
        """Handle group deletion."""
        await interaction.response.defer(ephemeral=True)

        try:

            @sync_to_async
            def delete_group():
                try:
                    group = Group.objects.get(id=group_id)
                    group_name = group.name
                    user_count = group.user_set.count()
                    group.delete()
                    return group_name, user_count, None
                except Group.DoesNotExist:
                    return None, None, f"Group with ID {group_id} not found"

            group_name, user_count, error = await delete_group()

            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            embed = discord.Embed(
                title="✅ Group Deleted",
                description=f"Successfully deleted group **{group_name}**",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="Group ID", value=f"`{group_id}`")
            embed.add_field(name="Users Affected", value=str(user_count))

            await interaction.followup.send(embed=embed, ephemeral=True)
            self.cog.logger.info(f"Deleted group '{group_name}' (ID: {group_id}) by {interaction.user}")

            # Refresh parent view
            new_embed = await self.parent_view.create_embed()
            await self.parent_view.interaction.edit_original_response(embed=new_embed, view=self.parent_view)

        except Exception as e:
            self.cog.logger.error(f"Error deleting group: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    async def _handle_manage_members(self, interaction: discord.Interaction, group_id: int):
        """Handle member management."""
        await interaction.response.defer()

        try:

            @sync_to_async
            def get_group_info():
                try:
                    group = Group.objects.get(id=group_id)
                    members = list(group.user_set.all().order_by("username").values_list("id", "username"))
                    return group.name, members, None
                except Group.DoesNotExist:
                    return None, None, f"Group with ID {group_id} not found"

            group_name, members, error = await get_group_info()

            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            view = GroupMemberManagementView(self.cog, interaction, self.parent_view, group_id, group_name, members)
            embed = await view.create_embed()
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            self.cog.logger.error(f"Error loading member management: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


# ====================
# Group Management Views
# ====================


class GroupManagementView(discord.ui.View):
    """Group management interface."""

    def __init__(self, cog, interaction: discord.Interaction, parent_view):
        super().__init__(timeout=900)
        self.cog = cog
        self.interaction = interaction
        self.parent_view = parent_view
        self.groups = []  # Will be populated when view is created

    async def create_embed(self) -> discord.Embed:
        """Create group management embed with current groups."""

        # Fetch current groups
        @sync_to_async
        def get_groups():
            groups = Group.objects.all().order_by("name")
            return [(g.id, g.name, g.user_set.count()) for g in groups]

        self.groups = await get_groups()

        embed = discord.Embed(
            title="👥 Group Management",
            description=f"**Current Groups:** {len(self.groups)}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        if self.groups:
            # Show groups sorted
            group_lines = [f"`{gid}` - **{name}** ({count} users)" for gid, name, count in self.groups]
            # Split into multiple fields if needed
            chunk_size = 15
            for i in range(0, len(group_lines), chunk_size):
                chunk = group_lines[i : i + chunk_size]
                field_name = "Groups" if i == 0 else "Groups (continued)"
                embed.add_field(name=field_name, value="\n".join(chunk), inline=False)
        else:
            embed.add_field(name="Groups", value="No groups found", inline=False)

        embed.set_footer(text="Use the buttons below to manage groups")
        return embed

    @discord.ui.button(label="Create Group", style=discord.ButtonStyle.success, emoji="➕", row=0)
    async def create_group(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Create a new group."""
        modal = CreateGroupModal(self.cog, self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Rename Group", style=discord.ButtonStyle.secondary, emoji="✏️", row=0)
    async def rename_group(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Rename a group."""
        if not self.groups:
            await interaction.response.send_message("❌ No groups available to rename.", ephemeral=True)
            return
        view = GroupSelectView(self.cog, self, interaction, "rename")
        await interaction.response.send_message("Select a group to rename:", view=view, ephemeral=True)

    @discord.ui.button(label="Delete Group", style=discord.ButtonStyle.danger, emoji="🗑️", row=0)
    async def delete_group(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Delete a group."""
        if not self.groups:
            await interaction.response.send_message("❌ No groups available to delete.", ephemeral=True)
            return
        view = GroupSelectView(self.cog, self, interaction, "delete")
        await interaction.response.send_message("Select a group to delete:", view=view, ephemeral=True)

    @discord.ui.button(label="Manage Members", style=discord.ButtonStyle.primary, emoji="👥", row=1)
    async def manage_members(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Manage group members."""
        if not self.groups:
            await interaction.response.send_message("❌ No groups available.", ephemeral=True)
            return
        view = GroupSelectView(self.cog, self, interaction, "manage_members")
        await interaction.response.send_message("Select a group to manage:", view=view, ephemeral=True)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄", row=1)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Refresh the group list."""
        await interaction.response.defer()
        embed = await self.create_embed()
        await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=self)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Return to main menu."""
        embed = self.parent_view.create_main_embed()
        await interaction.response.edit_message(embed=embed, view=self.parent_view)


# ====================
# User Management Views
# ====================


class UserManagementView(discord.ui.View):
    """User management interface."""

    def __init__(self, cog, interaction: discord.Interaction, parent_view):
        super().__init__(timeout=900)
        self.cog = cog
        self.interaction = interaction
        self.parent_view = parent_view

    def create_embed(self) -> discord.Embed:
        """Create user management embed."""
        embed = discord.Embed(
            title="👤 User Management",
            description="Select an action to perform on Django users",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(name="List Users", value="View all Django users", inline=True)
        embed.add_field(name="User Info", value="View user details", inline=True)
        embed.add_field(name="Create User", value="Create a new user", inline=True)

        return embed

    @discord.ui.button(label="List Users", style=discord.ButtonStyle.secondary, emoji="📋", row=0)
    async def list_users(self, interaction: discord.Interaction, button: discord.ui.Button):
        """List all users."""
        await interaction.response.defer()

        try:

            @sync_to_async
            def get_users():
                users = User.objects.all().order_by("username")
                return [(u.id, u.username, u.is_active, u.is_staff, u.is_superuser) for u in users]

            users = await get_users()

            if not users:
                embed = discord.Embed(title="No Users Found", description="There are no Django users configured.", color=discord.Color.orange())
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            embed = discord.Embed(
                title="Django Users", description=f"Total: {len(users)} users", color=discord.Color.blue(), timestamp=discord.utils.utcnow()
            )

            # Add users in chunks
            chunk_size = 20
            for i in range(0, len(users), chunk_size):
                chunk = users[i : i + chunk_size]
                user_lines = []
                for uid, username, active, staff, superuser in chunk:
                    flags = []
                    if not active:
                        flags.append("❌")
                    if staff:
                        flags.append("⚙️")
                    if superuser:
                        flags.append("👑")
                    flag_str = " ".join(flags) if flags else "✅"
                    user_lines.append(f"`{uid}` - **{username}** {flag_str}")

                embed.add_field(name=f"Users {i+1}-{min(i+chunk_size, len(users))}", value="\n".join(user_lines), inline=False)

            embed.set_footer(text="✅ Active | ❌ Inactive | ⚙️ Staff | 👑 Superuser")
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.cog.logger.error(f"Error listing users: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    @discord.ui.button(label="User Info", style=discord.ButtonStyle.secondary, emoji="ℹ️", row=0)
    async def user_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        """View user details."""
        modal = UserInfoModal(self.cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Create User", style=discord.ButtonStyle.success, emoji="➕", row=0)
    async def create_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Create a new user."""
        modal = CreateUserModal(self.cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Return to main menu."""
        embed = self.parent_view.create_main_embed()
        await interaction.response.edit_message(embed=embed, view=self.parent_view)


# ====================
# User Linking Views
# ====================


class UserLinkingView(discord.ui.View):
    """User linking interface."""

    def __init__(self, cog, interaction: discord.Interaction, parent_view):
        super().__init__(timeout=900)
        self.cog = cog
        self.interaction = interaction
        self.parent_view = parent_view

    def create_embed(self) -> discord.Embed:
        """Create user linking embed."""
        embed = discord.Embed(
            title="🔗 User Linking",
            description="Link Django users to Discord users and KnownPlayers",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(name="Link User", value="Link Django user to Discord", inline=True)
        embed.add_field(name="Unlink User", value="Remove Discord link", inline=True)
        embed.add_field(name="Check Status", value="View linking status", inline=True)

        return embed

    @discord.ui.button(label="Link User", style=discord.ButtonStyle.success, emoji="🔗", row=0)
    async def link_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Link a user."""
        modal = LinkUserModal(self.cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Unlink User", style=discord.ButtonStyle.danger, emoji="🔓", row=0)
    async def unlink_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Unlink a user."""
        modal = UnlinkUserModal(self.cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Check Status", style=discord.ButtonStyle.secondary, emoji="ℹ️", row=0)
    async def check_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Check link status."""
        modal = LinkStatusModal(self.cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Return to main menu."""
        embed = self.parent_view.create_main_embed()
        await interaction.response.edit_message(embed=embed, view=self.parent_view)


# ====================
# Group Member Management View
# ====================


class GroupMemberManagementView(discord.ui.View):
    """Manage group members."""

    def __init__(self, cog, interaction: discord.Interaction, parent_view, group_id: int, group_name: str, members: list):
        super().__init__(timeout=900)
        self.cog = cog
        self.interaction = interaction
        self.parent_view = parent_view
        self.group_id = group_id
        self.group_name = group_name
        self.members = members  # List of (user_id, username) tuples

    async def create_embed(self) -> discord.Embed:
        """Create member management embed."""
        embed = discord.Embed(
            title=f"👥 Managing Group: {self.group_name}",
            description=f"Group ID: `{self.group_id}` | **{len(self.members)}** members",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        if self.members:
            member_lines = [f"`{uid}` - {username}" for uid, username in self.members[:20]]
            if len(self.members) > 20:
                member_lines.append(f"... and {len(self.members) - 20} more")
            embed.add_field(name="Current Members", value="\n".join(member_lines), inline=False)
        else:
            embed.add_field(name="Current Members", value="No members in this group", inline=False)

        embed.set_footer(text="Use the buttons below to add or remove members")
        return embed

    @discord.ui.button(label="Add Member", style=discord.ButtonStyle.success, emoji="➕", row=0)
    async def add_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Add member to group."""
        modal = AddToGroupModal(self.cog, self, self.group_id, self.group_name)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Remove Member", style=discord.ButtonStyle.danger, emoji="➖", row=0)
    async def remove_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Remove member from group."""
        if not self.members:
            await interaction.response.send_message("❌ No members to remove.", ephemeral=True)
            return
        view = MemberSelectView(self.cog, self, self.group_id, self.group_name, self.members)
        await interaction.response.send_message("Select a member to remove:", view=view, ephemeral=True)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄", row=0)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Refresh member list."""
        await interaction.response.defer()

        try:

            @sync_to_async
            def get_members():
                try:
                    group = Group.objects.get(id=self.group_id)
                    return list(group.user_set.all().order_by("username").values_list("id", "username")), None
                except Group.DoesNotExist:
                    return None, "Group not found"

            members, error = await get_members()

            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            self.members = members
            embed = await self.create_embed()
            await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=self)

        except Exception as e:
            self.cog.logger.error(f"Error refreshing members: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Return to group management."""
        await interaction.response.defer()
        embed = await self.parent_view.create_embed()
        await self.parent_view.interaction.edit_original_response(embed=embed, view=self.parent_view)


class MemberSelectView(discord.ui.View):
    """View for selecting a member to remove."""

    def __init__(self, cog, parent_view, group_id: int, group_name: str, members: list):
        super().__init__(timeout=300)
        self.cog = cog
        self.parent_view = parent_view
        self.group_id = group_id
        self.group_name = group_name

        # Add select menu
        select = MemberSelect(cog, parent_view, group_id, group_name, members)
        self.add_item(select)


class MemberSelect(discord.ui.Select):
    """Dropdown for selecting a member to remove."""

    def __init__(self, cog, parent_view, group_id: int, group_name: str, members: list):
        self.cog = cog
        self.parent_view = parent_view
        self.group_id = group_id
        self.group_name = group_name

        # Build options from members
        options = []
        for uid, username in members[:25]:  # Discord limit of 25 options
            options.append(discord.SelectOption(label=username, value=str(uid), description=f"User ID: {uid}"))

        super().__init__(
            placeholder="Select a member to remove...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        """Handle member removal."""
        user_id = int(self.values[0])
        await interaction.response.defer(ephemeral=True)

        try:

            @sync_to_async
            def remove_user_from_group():
                try:
                    user = User.objects.get(id=user_id)
                    group = Group.objects.get(id=self.group_id)

                    if group not in user.groups.all():
                        return None, None, f"User '{user.username}' is not in group '{group.name}'"

                    user.groups.remove(group)
                    return user, group, None
                except User.DoesNotExist:
                    return None, None, f"User with ID {user_id} not found"
                except Group.DoesNotExist:
                    return None, None, f"Group with ID {self.group_id} not found"

            user, group, error = await remove_user_from_group()

            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            embed = discord.Embed(
                title="✅ Member Removed",
                description=f"Successfully removed **{user.username}** from group **{group.name}**",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="User ID", value=f"`{user.id}`")
            embed.add_field(name="Group ID", value=f"`{group.id}`")

            await interaction.followup.send(embed=embed, ephemeral=True)
            self.cog.logger.info(f"Removed user '{user.username}' from group '{group.name}' by {interaction.user}")

            # Refresh parent view
            @sync_to_async
            def get_updated_members():
                group = Group.objects.get(id=self.group_id)
                return list(group.user_set.all().order_by("username").values_list("id", "username"))

            self.parent_view.members = await get_updated_members()
            new_embed = await self.parent_view.create_embed()
            await self.parent_view.interaction.edit_original_response(embed=new_embed, view=self.parent_view)

        except Exception as e:
            self.cog.logger.error(f"Error removing member: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


# ====================
# Modals for Group Operations
# ====================


class CreateGroupModal(discord.ui.Modal):
    """Modal for creating a new group."""

    def __init__(self, cog, parent_view):
        super().__init__(title="Create Django Group")
        self.cog = cog
        self.parent_view = parent_view

        self.name_input = discord.ui.TextInput(label="Group Name", placeholder="Enter the group name", required=True, max_length=150)
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle group creation."""
        await interaction.response.defer(ephemeral=True)

        try:
            name = self.name_input.value.strip()

            @sync_to_async
            def create_group():
                if Group.objects.filter(name=name).exists():
                    return None, f"Group '{name}' already exists"
                group = Group.objects.create(name=name)
                return group, None

            group, error = await create_group()

            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            embed = discord.Embed(
                title="✅ Group Created",
                description=f"Successfully created group **{group.name}**",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="Group ID", value=f"`{group.id}`")
            embed.add_field(name="Group Name", value=group.name)

            await interaction.followup.send(embed=embed, ephemeral=True)
            self.cog.logger.info(f"Created group '{name}' (ID: {group.id}) by {interaction.user}")

            # Refresh parent view
            new_embed = await self.parent_view.create_embed()
            await self.parent_view.interaction.edit_original_response(embed=new_embed, view=self.parent_view)

        except Exception as e:
            self.cog.logger.error(f"Error creating group: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


class RenameGroupModal(discord.ui.Modal):
    """Modal for renaming a group."""

    def __init__(self, cog, parent_view, group_id: int):
        super().__init__(title="Rename Django Group")
        self.cog = cog
        self.parent_view = parent_view
        self.group_id = group_id

        # Get current group name to pre-populate
        self.new_name_input = discord.ui.TextInput(label="New Group Name", placeholder="Enter the new name", required=True, max_length=150)
        self.add_item(self.new_name_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle group rename."""
        await interaction.response.defer(ephemeral=True)

        try:
            new_name = self.new_name_input.value.strip()

            @sync_to_async
            def rename_group():
                try:
                    group = Group.objects.get(id=self.group_id)
                    old_name = group.name

                    if Group.objects.filter(name=new_name).exclude(id=self.group_id).exists():
                        return None, None, f"Group with name '{new_name}' already exists"

                    group.name = new_name
                    group.save()
                    return old_name, new_name, None
                except Group.DoesNotExist:
                    return None, None, f"Group with ID {self.group_id} not found"

            old_name, new_name_result, error = await rename_group()

            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            embed = discord.Embed(
                title="✅ Group Renamed",
                description=f"Successfully renamed group from **{old_name}** to **{new_name_result}**",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="Group ID", value=f"`{self.group_id}`")

            await interaction.followup.send(embed=embed, ephemeral=True)
            self.cog.logger.info(f"Renamed group '{old_name}' to '{new_name_result}' (ID: {self.group_id}) by {interaction.user}")

            # Refresh parent view
            new_embed = await self.parent_view.create_embed()
            await self.parent_view.interaction.edit_original_response(embed=new_embed, view=self.parent_view)

        except Exception as e:
            self.cog.logger.error(f"Error renaming group: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


# ====================
# Modals for User Operations
# ====================


class UserInfoModal(discord.ui.Modal):
    """Modal for viewing user information."""

    def __init__(self, cog):
        super().__init__(title="View User Information")
        self.cog = cog

        self.username_input = discord.ui.TextInput(label="Username", placeholder="Enter the Django username", required=True, max_length=150)
        self.add_item(self.username_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle user info display."""
        await interaction.response.defer(ephemeral=True)

        try:
            username = self.username_input.value.strip()

            @sync_to_async
            def get_user_info():
                try:
                    user = User.objects.get(username=username)
                    groups = list(user.groups.all().values_list("name", flat=True))

                    has_known_player = hasattr(user, "known_player") and user.known_player is not None
                    known_player_name = user.known_player.name if has_known_player else None

                    # Get discord_id from LinkedAccount (primary Discord account)
                    discord_id = None
                    if has_known_player:
                        from thetower.backend.sus.models import LinkedAccount

                        linked_account = LinkedAccount.objects.filter(
                            player=user.known_player, platform=LinkedAccount.Platform.DISCORD, primary=True
                        ).first()
                        if linked_account:
                            discord_id = linked_account.account_id

                    return {
                        "id": user.id,
                        "username": user.username,
                        "email": user.email,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "is_active": user.is_active,
                        "is_staff": user.is_staff,
                        "is_superuser": user.is_superuser,
                        "date_joined": user.date_joined,
                        "last_login": user.last_login,
                        "groups": groups,
                        "has_known_player": has_known_player,
                        "known_player_name": known_player_name,
                        "discord_id": discord_id,
                    }, None
                except User.DoesNotExist:
                    return None, f"User '{username}' not found"

            user_info, error = await get_user_info()

            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"User: {user_info['username']}",
                description=f"ID: `{user_info['id']}`",
                color=discord.Color.green() if user_info["is_active"] else discord.Color.red(),
                timestamp=discord.utils.utcnow(),
            )

            # Status flags
            status_flags = []
            if user_info["is_active"]:
                status_flags.append("✅ Active")
            else:
                status_flags.append("❌ Inactive")
            if user_info["is_staff"]:
                status_flags.append("⚙️ Staff")
            if user_info["is_superuser"]:
                status_flags.append("👑 Superuser")

            embed.add_field(name="Status", value=" | ".join(status_flags), inline=False)

            if user_info["email"]:
                embed.add_field(name="Email", value=user_info["email"], inline=True)
            if user_info["first_name"] or user_info["last_name"]:
                full_name = f"{user_info['first_name']} {user_info['last_name']}".strip()
                embed.add_field(name="Name", value=full_name, inline=True)

            embed.add_field(name="Joined", value=f"<t:{int(user_info['date_joined'].timestamp())}:R>", inline=True)
            if user_info["last_login"]:
                embed.add_field(name="Last Login", value=f"<t:{int(user_info['last_login'].timestamp())}:R>", inline=True)

            if user_info["groups"]:
                embed.add_field(name=f"Groups ({len(user_info['groups'])})", value=", ".join(user_info["groups"]), inline=False)

            if user_info["has_known_player"]:
                kp_info = f"**{user_info['known_player_name']}**"
                if user_info["discord_id"]:
                    kp_info += f"\nDiscord: <@{user_info['discord_id']}> (`{user_info['discord_id']}`)"
                embed.add_field(name="Linked KnownPlayer", value=kp_info, inline=False)
            else:
                embed.add_field(name="Linked KnownPlayer", value="Not linked", inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.cog.logger.error(f"Error getting user info: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


class CreateUserModal(discord.ui.Modal):
    """Modal for creating a new user."""

    def __init__(self, cog):
        super().__init__(title="Create Django User")
        self.cog = cog

        self.username_input = discord.ui.TextInput(label="Username", placeholder="Enter the username", required=True, max_length=150)
        self.email_input = discord.ui.TextInput(label="Email (optional)", placeholder="Enter the email address", required=False, max_length=254)
        self.add_item(self.username_input)
        self.add_item(self.email_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle user creation."""
        await interaction.response.defer(ephemeral=True)

        try:
            username = self.username_input.value.strip()
            email = self.email_input.value.strip()

            @sync_to_async
            def create_user():
                if User.objects.filter(username=username).exists():
                    return None, f"User '{username}' already exists"

                user = User.objects.create_user(username=username, email=email)
                user.set_unusable_password()
                user.save()

                return user, None

            user, error = await create_user()

            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            embed = discord.Embed(
                title="✅ User Created",
                description=f"Successfully created user **{user.username}**",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="User ID", value=f"`{user.id}`")
            embed.add_field(name="Username", value=user.username)
            if email:
                embed.add_field(name="Email", value=email)
            embed.add_field(name="Password", value="Unusable (user cannot login)", inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)
            self.cog.logger.info(f"Created user '{username}' (ID: {user.id}) by {interaction.user}")

        except Exception as e:
            self.cog.logger.error(f"Error creating user: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


# ====================
# Modals for Group Member Operations
# ====================


class AddToGroupModal(discord.ui.Modal):
    """Modal for adding a user to a group."""

    def __init__(self, cog, parent_view, group_id: int, group_name: str):
        super().__init__(title=f"Add Member to {group_name}")
        self.cog = cog
        self.parent_view = parent_view
        self.group_id = group_id
        self.group_name = group_name

        self.username_input = discord.ui.TextInput(label="Username", placeholder="Enter the Django username", required=True, max_length=150)
        self.add_item(self.username_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle adding user to group."""
        await interaction.response.defer(ephemeral=True)

        try:
            username = self.username_input.value.strip()

            @sync_to_async
            def add_user_to_group():
                try:
                    user = User.objects.get(username=username)
                    group = Group.objects.get(id=self.group_id)

                    if group in user.groups.all():
                        return None, None, f"User '{username}' is already in group '{group.name}'"

                    user.groups.add(group)
                    return user, group, None
                except User.DoesNotExist:
                    return None, None, f"User '{username}' not found"
                except Group.DoesNotExist:
                    return None, None, f"Group with ID {self.group_id} not found"

            user, group, error = await add_user_to_group()

            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            embed = discord.Embed(
                title="✅ Member Added",
                description=f"Successfully added **{user.username}** to group **{group.name}**",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="User ID", value=f"`{user.id}`")
            embed.add_field(name="Group ID", value=f"`{group.id}`")

            await interaction.followup.send(embed=embed, ephemeral=True)
            self.cog.logger.info(f"Added user '{username}' to group '{group.name}' by {interaction.user}")

            # Refresh parent view
            @sync_to_async
            def get_updated_members():
                group = Group.objects.get(id=self.group_id)
                return list(group.user_set.all().order_by("username").values_list("id", "username"))

            self.parent_view.members = await get_updated_members()
            new_embed = await self.parent_view.create_embed()
            await self.parent_view.interaction.edit_original_response(embed=new_embed, view=self.parent_view)

        except Exception as e:
            self.cog.logger.error(f"Error adding user to group: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


# ====================
# Modals for User Linking Operations
# ====================


class LinkUserModal(discord.ui.Modal):
    """Modal for linking a Django user to a Discord user."""

    def __init__(self, cog):
        super().__init__(title="Link Django User to Discord")
        self.cog = cog

        self.username_input = discord.ui.TextInput(label="Django Username", placeholder="Enter the Django username", required=True, max_length=150)
        self.discord_id_input = discord.ui.TextInput(label="Discord User ID", placeholder="Enter the Discord user ID", required=True, max_length=20)
        self.add_item(self.username_input)
        self.add_item(self.discord_id_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle user linking."""
        await interaction.response.defer(ephemeral=True)

        try:
            username = self.username_input.value.strip()
            discord_id = self.discord_id_input.value.strip()

            # Try to get the Discord user object
            try:
                discord_user = await interaction.client.fetch_user(int(discord_id))
            except (ValueError, discord.NotFound, discord.HTTPException):
                discord_user = None

            @sync_to_async
            def link_django_user():
                try:
                    django_user = User.objects.get(username=username)

                    if hasattr(django_user, "known_player") and django_user.known_player is not None:
                        return None, None, f"Django user '{username}' is already linked to KnownPlayer '{django_user.known_player.name}'"

                    known_player, created = KnownPlayer.objects.get_or_create(
                        discord_id=str(discord_id), defaults={"name": discord_user.display_name if discord_user else f"User {discord_id}"}
                    )

                    if known_player.django_user is not None and known_player.django_user != django_user:
                        return None, None, f"Discord user is already linked to Django user '{known_player.django_user.username}'"

                    known_player.django_user = django_user
                    known_player.save()

                    return django_user, known_player, None
                except User.DoesNotExist:
                    return None, None, f"Django user '{username}' not found"

            django_user, known_player, error = await link_django_user()

            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            embed = discord.Embed(
                title="✅ User Linked",
                description=f"Successfully linked Django user **{django_user.username}** to Discord user",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="Django User ID", value=f"`{django_user.id}`")
            if discord_user:
                embed.add_field(name="Discord User", value=f"{discord_user.mention} (`{discord_id}`)")
            else:
                embed.add_field(name="Discord User ID", value=f"`{discord_id}`")
            embed.add_field(name="KnownPlayer", value=known_player.name, inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)
            self.cog.logger.info(f"Linked Django user '{username}' to Discord user {discord_id} by {interaction.user}")

        except ValueError:
            await interaction.followup.send("❌ Invalid Discord user ID", ephemeral=True)
        except Exception as e:
            self.cog.logger.error(f"Error linking user: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


class UnlinkUserModal(discord.ui.Modal):
    """Modal for unlinking a Django user."""

    def __init__(self, cog):
        super().__init__(title="Unlink Django User")
        self.cog = cog

        self.username_input = discord.ui.TextInput(
            label="Django Username", placeholder="Enter the Django username to unlink", required=True, max_length=150
        )
        self.add_item(self.username_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle user unlinking."""
        await interaction.response.defer(ephemeral=True)

        try:
            username = self.username_input.value.strip()

            @sync_to_async
            def unlink_django_user():
                try:
                    django_user = User.objects.get(username=username)

                    if not hasattr(django_user, "known_player") or django_user.known_player is None:
                        return None, None, f"Django user '{username}' is not linked to any KnownPlayer"

                    known_player = django_user.known_player
                    known_player_name = known_player.name

                    # Get discord_id from LinkedAccount (primary Discord account)
                    from thetower.backend.sus.models import LinkedAccount

                    linked_account = LinkedAccount.objects.filter(player=known_player, platform=LinkedAccount.Platform.DISCORD, primary=True).first()
                    discord_id = linked_account.account_id if linked_account else None

                    known_player.django_user = None
                    known_player.save()

                    return django_user, (known_player_name, discord_id), None
                except User.DoesNotExist:
                    return None, None, f"Django user '{username}' not found"

            django_user, kp_info, error = await unlink_django_user()

            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            known_player_name, discord_id = kp_info

            embed = discord.Embed(
                title="✅ User Unlinked",
                description=f"Successfully unlinked Django user **{django_user.username}** from KnownPlayer **{known_player_name}**",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="Django User ID", value=f"`{django_user.id}`")
            if discord_id:
                embed.add_field(name="Discord ID", value=f"`{discord_id}`")

            await interaction.followup.send(embed=embed, ephemeral=True)
            self.cog.logger.info(f"Unlinked Django user '{username}' from KnownPlayer by {interaction.user}")

        except Exception as e:
            self.cog.logger.error(f"Error unlinking user: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


class LinkStatusModal(discord.ui.Modal):
    """Modal for checking linking status."""

    def __init__(self, cog):
        super().__init__(title="Check Linking Status")
        self.cog = cog

        self.username_input = discord.ui.TextInput(label="Django Username", placeholder="Enter the Django username", required=True, max_length=150)
        self.add_item(self.username_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle status check."""
        await interaction.response.defer(ephemeral=True)

        try:
            username = self.username_input.value.strip()

            @sync_to_async
            def get_link_status():
                try:
                    django_user = User.objects.get(username=username)

                    has_known_player = hasattr(django_user, "known_player") and django_user.known_player is not None

                    if has_known_player:
                        kp = django_user.known_player
                        # Get primary Discord account from LinkedAccount
                        from thetower.backend.sus.models import LinkedAccount as LA

                        discord_account = LA.objects.filter(player=kp, platform=LA.Platform.DISCORD, primary=True).first()
                        return {
                            "user_id": django_user.id,
                            "username": django_user.username,
                            "linked": True,
                            "known_player_name": kp.name,
                            "discord_id": discord_account.account_id if discord_account else None,
                            "player_id_count": PlayerId.objects.filter(game_instance__player=kp).count(),
                        }, None
                    else:
                        return {
                            "user_id": django_user.id,
                            "username": django_user.username,
                            "linked": False,
                        }, None
                except User.DoesNotExist:
                    return None, f"Django user '{username}' not found"

            status, error = await get_link_status()

            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            if status["linked"]:
                embed = discord.Embed(
                    title=f"Link Status: {status['username']}",
                    description="✅ **Linked to KnownPlayer**",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow(),
                )
                embed.add_field(name="Django User ID", value=f"`{status['user_id']}`")
                embed.add_field(name="KnownPlayer Name", value=status["known_player_name"])
                if status["discord_id"]:
                    embed.add_field(name="Discord User", value=f"<@{status['discord_id']}> (`{status['discord_id']}`)", inline=False)
                embed.add_field(name="Player IDs", value=str(status["player_id_count"]))
            else:
                embed = discord.Embed(
                    title=f"Link Status: {status['username']}",
                    description="❌ **Not linked to any KnownPlayer**",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow(),
                )
                embed.add_field(name="Django User ID", value=f"`{status['user_id']}`")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.cog.logger.error(f"Error checking link status: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
