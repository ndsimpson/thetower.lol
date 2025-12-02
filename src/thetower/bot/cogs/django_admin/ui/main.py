# Main UI interface for Django Admin cog

import discord
from asgiref.sync import sync_to_async
from django.contrib.auth.models import Group, User

from thetower.backend.sus.models import KnownPlayer


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
        view = GroupManagementView(self.cog, interaction, self)
        embed = view.create_embed()
        await interaction.response.edit_message(embed=embed, view=view)

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
# Group Management Views
# ====================


class GroupManagementView(discord.ui.View):
    """Group management interface."""

    def __init__(self, cog, interaction: discord.Interaction, parent_view):
        super().__init__(timeout=900)
        self.cog = cog
        self.interaction = interaction
        self.parent_view = parent_view

    def create_embed(self) -> discord.Embed:
        """Create group management embed."""
        embed = discord.Embed(
            title="👥 Group Management",
            description="Select an action to perform on Django groups",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(name="List Groups", value="View all Django groups", inline=True)
        embed.add_field(name="Create Group", value="Create a new group", inline=True)
        embed.add_field(name="Group Info", value="View group details", inline=True)
        embed.add_field(name="Rename Group", value="Rename an existing group", inline=True)
        embed.add_field(name="Delete Group", value="Delete a group", inline=True)
        embed.add_field(name="Manage Members", value="Add/remove users", inline=True)

        return embed

    @discord.ui.button(label="List Groups", style=discord.ButtonStyle.secondary, emoji="📋", row=0)
    async def list_groups(self, interaction: discord.Interaction, button: discord.ui.Button):
        """List all groups."""
        await interaction.response.defer()

        try:

            @sync_to_async
            def get_groups():
                groups = Group.objects.all().order_by("name")
                return [(g.id, g.name, g.user_set.count()) for g in groups]

            groups = await get_groups()

            if not groups:
                embed = discord.Embed(title="No Groups Found", description="There are no Django groups configured.", color=discord.Color.orange())
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            embed = discord.Embed(
                title="Django Groups", description=f"Total: {len(groups)} groups", color=discord.Color.blue(), timestamp=discord.utils.utcnow()
            )

            # Add groups in chunks
            chunk_size = 25
            for i in range(0, len(groups), chunk_size):
                chunk = groups[i : i + chunk_size]
                group_lines = [f"`{gid}` - **{name}** ({count} users)" for gid, name, count in chunk]
                embed.add_field(name=f"Groups {i+1}-{min(i+chunk_size, len(groups))}", value="\n".join(group_lines), inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.cog.logger.error(f"Error listing groups: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    @discord.ui.button(label="Create Group", style=discord.ButtonStyle.success, emoji="➕", row=0)
    async def create_group(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Create a new group."""
        modal = CreateGroupModal(self.cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Group Info", style=discord.ButtonStyle.secondary, emoji="ℹ️", row=1)
    async def group_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        """View group details."""
        modal = GroupInfoModal(self.cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Rename Group", style=discord.ButtonStyle.secondary, emoji="✏️", row=1)
    async def rename_group(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Rename a group."""
        modal = RenameGroupModal(self.cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Delete Group", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def delete_group(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Delete a group."""
        modal = DeleteGroupModal(self.cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Manage Members", style=discord.ButtonStyle.primary, emoji="👥", row=2)
    async def manage_members(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Manage group members."""
        view = GroupMemberManagementView(self.cog, interaction, self)
        embed = view.create_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=2)
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

    def __init__(self, cog, interaction: discord.Interaction, parent_view):
        super().__init__(timeout=900)
        self.cog = cog
        self.interaction = interaction
        self.parent_view = parent_view

    def create_embed(self) -> discord.Embed:
        """Create member management embed."""
        embed = discord.Embed(
            title="👥 Group Member Management",
            description="Add or remove users from groups",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(name="Add to Group", value="Add user to a group", inline=True)
        embed.add_field(name="Remove from Group", value="Remove user from a group", inline=True)
        embed.add_field(name="List User Groups", value="View user's groups", inline=True)

        return embed

    @discord.ui.button(label="Add to Group", style=discord.ButtonStyle.success, emoji="➕", row=0)
    async def add_to_group(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Add user to group."""
        modal = AddToGroupModal(self.cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Remove from Group", style=discord.ButtonStyle.danger, emoji="➖", row=0)
    async def remove_from_group(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Remove user from group."""
        modal = RemoveFromGroupModal(self.cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="List User Groups", style=discord.ButtonStyle.secondary, emoji="📋", row=0)
    async def list_user_groups(self, interaction: discord.Interaction, button: discord.ui.Button):
        """List groups for a user."""
        modal = ListUserGroupsModal(self.cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Return to group management."""
        embed = self.parent_view.create_embed()
        await interaction.response.edit_message(embed=embed, view=self.parent_view)


# ====================
# Modals for Group Operations
# ====================


class CreateGroupModal(discord.ui.Modal):
    """Modal for creating a new group."""

    def __init__(self, cog):
        super().__init__(title="Create Django Group")
        self.cog = cog

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

        except Exception as e:
            self.cog.logger.error(f"Error creating group: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


class GroupInfoModal(discord.ui.Modal):
    """Modal for viewing group information."""

    def __init__(self, cog):
        super().__init__(title="View Group Information")
        self.cog = cog

        self.group_id_input = discord.ui.TextInput(label="Group ID", placeholder="Enter the group ID", required=True, max_length=10)
        self.add_item(self.group_id_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle group info display."""
        await interaction.response.defer(ephemeral=True)

        try:
            group_id = int(self.group_id_input.value.strip())

            @sync_to_async
            def get_group_info():
                try:
                    group = Group.objects.get(id=group_id)
                    users = list(group.user_set.all().order_by("username").values_list("id", "username"))
                    permissions = list(group.permissions.all().values_list("codename", "name"))
                    return group.name, users, permissions, None
                except Group.DoesNotExist:
                    return None, None, None, f"Group with ID {group_id} not found"

            group_name, users, permissions, error = await get_group_info()

            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"Group: {group_name}", description=f"ID: `{group_id}`", color=discord.Color.blue(), timestamp=discord.utils.utcnow()
            )

            if users:
                user_lines = [f"`{uid}` - {username}" for uid, username in users[:20]]
                if len(users) > 20:
                    user_lines.append(f"... and {len(users) - 20} more")
                embed.add_field(name=f"Users ({len(users)})", value="\n".join(user_lines) if user_lines else "None", inline=False)
            else:
                embed.add_field(name="Users", value="No users in this group", inline=False)

            if permissions:
                perm_lines = [f"`{codename}`" for codename, name in permissions[:10]]
                if len(permissions) > 10:
                    perm_lines.append(f"... and {len(permissions) - 10} more")
                embed.add_field(name=f"Permissions ({len(permissions)})", value="\n".join(perm_lines) if perm_lines else "None", inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except ValueError:
            await interaction.followup.send("❌ Invalid group ID", ephemeral=True)
        except Exception as e:
            self.cog.logger.error(f"Error getting group info: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


class RenameGroupModal(discord.ui.Modal):
    """Modal for renaming a group."""

    def __init__(self, cog):
        super().__init__(title="Rename Django Group")
        self.cog = cog

        self.group_id_input = discord.ui.TextInput(label="Group ID", placeholder="Enter the group ID to rename", required=True, max_length=10)
        self.new_name_input = discord.ui.TextInput(label="New Group Name", placeholder="Enter the new name", required=True, max_length=150)
        self.add_item(self.group_id_input)
        self.add_item(self.new_name_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle group rename."""
        await interaction.response.defer(ephemeral=True)

        try:
            group_id = int(self.group_id_input.value.strip())
            new_name = self.new_name_input.value.strip()

            @sync_to_async
            def rename_group():
                try:
                    group = Group.objects.get(id=group_id)
                    old_name = group.name

                    if Group.objects.filter(name=new_name).exclude(id=group_id).exists():
                        return None, None, f"Group with name '{new_name}' already exists"

                    group.name = new_name
                    group.save()
                    return old_name, new_name, None
                except Group.DoesNotExist:
                    return None, None, f"Group with ID {group_id} not found"

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
            embed.add_field(name="Group ID", value=f"`{group_id}`")

            await interaction.followup.send(embed=embed, ephemeral=True)
            self.cog.logger.info(f"Renamed group '{old_name}' to '{new_name_result}' (ID: {group_id}) by {interaction.user}")

        except ValueError:
            await interaction.followup.send("❌ Invalid group ID", ephemeral=True)
        except Exception as e:
            self.cog.logger.error(f"Error renaming group: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


class DeleteGroupModal(discord.ui.Modal):
    """Modal for deleting a group."""

    def __init__(self, cog):
        super().__init__(title="Delete Django Group")
        self.cog = cog

        self.group_id_input = discord.ui.TextInput(label="Group ID", placeholder="Enter the group ID to delete", required=True, max_length=10)
        self.add_item(self.group_id_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle group deletion."""
        await interaction.response.defer(ephemeral=True)

        try:
            group_id = int(self.group_id_input.value.strip())

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

        except ValueError:
            await interaction.followup.send("❌ Invalid group ID", ephemeral=True)
        except Exception as e:
            self.cog.logger.error(f"Error deleting group: {e}", exc_info=True)
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
                    discord_id = user.known_player.discord_id if has_known_player else None

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

    def __init__(self, cog):
        super().__init__(title="Add User to Group")
        self.cog = cog

        self.username_input = discord.ui.TextInput(label="Username", placeholder="Enter the Django username", required=True, max_length=150)
        self.group_id_input = discord.ui.TextInput(label="Group ID", placeholder="Enter the group ID", required=True, max_length=10)
        self.add_item(self.username_input)
        self.add_item(self.group_id_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle adding user to group."""
        await interaction.response.defer(ephemeral=True)

        try:
            username = self.username_input.value.strip()
            group_id = int(self.group_id_input.value.strip())

            @sync_to_async
            def add_user_to_group():
                try:
                    user = User.objects.get(username=username)
                    group = Group.objects.get(id=group_id)

                    if group in user.groups.all():
                        return None, None, f"User '{username}' is already in group '{group.name}'"

                    user.groups.add(group)
                    return user, group, None
                except User.DoesNotExist:
                    return None, None, f"User '{username}' not found"
                except Group.DoesNotExist:
                    return None, None, f"Group with ID {group_id} not found"

            user, group, error = await add_user_to_group()

            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            embed = discord.Embed(
                title="✅ User Added to Group",
                description=f"Successfully added **{user.username}** to group **{group.name}**",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="User ID", value=f"`{user.id}`")
            embed.add_field(name="Group ID", value=f"`{group.id}`")

            await interaction.followup.send(embed=embed, ephemeral=True)
            self.cog.logger.info(f"Added user '{username}' to group '{group.name}' by {interaction.user}")

        except ValueError:
            await interaction.followup.send("❌ Invalid group ID", ephemeral=True)
        except Exception as e:
            self.cog.logger.error(f"Error adding user to group: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


class RemoveFromGroupModal(discord.ui.Modal):
    """Modal for removing a user from a group."""

    def __init__(self, cog):
        super().__init__(title="Remove User from Group")
        self.cog = cog

        self.username_input = discord.ui.TextInput(label="Username", placeholder="Enter the Django username", required=True, max_length=150)
        self.group_id_input = discord.ui.TextInput(label="Group ID", placeholder="Enter the group ID", required=True, max_length=10)
        self.add_item(self.username_input)
        self.add_item(self.group_id_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle removing user from group."""
        await interaction.response.defer(ephemeral=True)

        try:
            username = self.username_input.value.strip()
            group_id = int(self.group_id_input.value.strip())

            @sync_to_async
            def remove_user_from_group():
                try:
                    user = User.objects.get(username=username)
                    group = Group.objects.get(id=group_id)

                    if group not in user.groups.all():
                        return None, None, f"User '{username}' is not in group '{group.name}'"

                    user.groups.remove(group)
                    return user, group, None
                except User.DoesNotExist:
                    return None, None, f"User '{username}' not found"
                except Group.DoesNotExist:
                    return None, None, f"Group with ID {group_id} not found"

            user, group, error = await remove_user_from_group()

            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            embed = discord.Embed(
                title="✅ User Removed from Group",
                description=f"Successfully removed **{user.username}** from group **{group.name}**",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="User ID", value=f"`{user.id}`")
            embed.add_field(name="Group ID", value=f"`{group.id}`")

            await interaction.followup.send(embed=embed, ephemeral=True)
            self.cog.logger.info(f"Removed user '{username}' from group '{group.name}' by {interaction.user}")

        except ValueError:
            await interaction.followup.send("❌ Invalid group ID", ephemeral=True)
        except Exception as e:
            self.cog.logger.error(f"Error removing user from group: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


class ListUserGroupsModal(discord.ui.Modal):
    """Modal for listing a user's groups."""

    def __init__(self, cog):
        super().__init__(title="List User's Groups")
        self.cog = cog

        self.username_input = discord.ui.TextInput(label="Username", placeholder="Enter the Django username", required=True, max_length=150)
        self.add_item(self.username_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle listing user groups."""
        await interaction.response.defer(ephemeral=True)

        try:
            username = self.username_input.value.strip()

            @sync_to_async
            def get_user_groups():
                try:
                    user = User.objects.get(username=username)
                    groups = list(user.groups.all().order_by("name").values_list("id", "name"))
                    return user.id, groups, None
                except User.DoesNotExist:
                    return None, None, f"User '{username}' not found"

            user_id, groups, error = await get_user_groups()

            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"Groups for user: {username}",
                description=f"User ID: `{user_id}`",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow(),
            )

            if groups:
                group_lines = [f"`{gid}` - {name}" for gid, name in groups]
                embed.add_field(name=f"Groups ({len(groups)})", value="\n".join(group_lines), inline=False)
            else:
                embed.add_field(name="Groups", value="User is not in any groups", inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.cog.logger.error(f"Error listing user groups: {e}", exc_info=True)
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
                    discord_id = known_player.discord_id

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
                        return {
                            "user_id": django_user.id,
                            "username": django_user.username,
                            "linked": True,
                            "known_player_name": kp.name,
                            "discord_id": kp.discord_id,
                            "player_id_count": kp.ids.count(),
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
