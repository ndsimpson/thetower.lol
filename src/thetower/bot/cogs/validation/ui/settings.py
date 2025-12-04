import discord
from discord import ui

from thetower.bot.basecog import BaseCog
from thetower.bot.ui.context import SettingsViewContext


class ValidationSettingsView(discord.ui.View):
    """Settings view for the Validation cog."""

    def __init__(self, context: SettingsViewContext):
        """Initialize the settings view using the unified constructor pattern."""
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context
        self.interaction = context.interaction
        self.is_bot_owner = context.is_bot_owner
        self.guild_id = context.guild_id

        # Add role select for verified role (per-guild)
        self.add_item(VerifiedRoleSelect(self.cog, self.guild_id))

        # Add channel select for verification log channel (per-guild)
        self.add_item(VerificationLogChannelSelect(self.cog, self.guild_id))

        # Add verification enabled/disabled toggle button (per-guild)
        self.add_item(VerificationEnabledButton(self.cog, self.guild_id))

        # Add audit button (per-guild) - only for bot/server owners
        self.add_item(VerificationAuditButton(self.cog, self.guild_id, self.is_bot_owner))

        # Global settings section - only show to bot owners
        if self.is_bot_owner:
            # Add dropdown for configuring approved un-verify groups (global)
            options = [
                discord.SelectOption(
                    label="Approved Un-verify Groups",
                    value="approved_unverify_groups",
                    description="Django groups that can un-verify players",
                ),
            ]

            self.setting_select = discord.ui.Select(
                placeholder="Configure group permissions",
                options=options,
            )
            self.setting_select.callback = self.setting_select_callback
            self.add_item(self.setting_select)

    async def setting_select_callback(self, interaction: discord.Interaction):
        """Handle setting selection for configuration."""
        setting_name = self.setting_select.values[0]

        # Special handling for group settings
        if setting_name == "approved_unverify_groups":
            current_groups = self.cog.config.get_global_cog_setting("validation", setting_name, self.cog.global_settings.get(setting_name, []))
            view = ValidationGroupsSelectView(self.cog, interaction, current_groups, setting_key=setting_name, context=self.context)
            embed = view.create_selection_embed()
            await interaction.response.edit_message(embed=embed, view=view)
            return


class VerificationEnabledButton(ui.Button):
    """Button to toggle verification enabled/disabled."""

    def __init__(self, cog: BaseCog, guild_id: int):
        verification_enabled = cog.get_setting("verification_enabled", guild_id=guild_id)

        if verification_enabled:
            label = "Verification: Enabled"
            style = discord.ButtonStyle.success
            emoji = "✅"
        else:
            label = "Verification: Disabled"
            style = discord.ButtonStyle.danger
            emoji = "❌"

        super().__init__(label=label, style=style, emoji=emoji)
        self.cog = cog
        self.guild_id = guild_id
        self.verification_enabled = verification_enabled

    async def callback(self, interaction: discord.Interaction):
        """Toggle verification enabled/disabled."""
        new_state = not self.verification_enabled
        self.cog.set_setting("verification_enabled", new_state, self.guild_id)

        status = "enabled" if new_state else "disabled"
        emoji = "✅" if new_state else "❌"

        await interaction.response.send_message(f"{emoji} Verification has been **{status}** for this server.", ephemeral=True)


class VerificationAuditButton(ui.Button):
    """Button to run verification audit."""

    def __init__(self, cog: BaseCog, guild_id: int, is_bot_owner: bool):
        super().__init__(label="Run Verification Audit", style=discord.ButtonStyle.primary, emoji="🔍")
        self.cog = cog
        self.guild_id = guild_id
        self.is_bot_owner = is_bot_owner

    async def callback(self, interaction: discord.Interaction):
        """Run verification audit."""
        from asgiref.sync import sync_to_async

        from thetower.backend.sus.models import KnownPlayer

        # Check if user is bot owner or server owner
        is_guild_owner = interaction.user.id == interaction.guild.owner_id

        if not (self.is_bot_owner or is_guild_owner):
            await interaction.response.send_message("❌ This audit is restricted to bot owners and server owners only.", ephemeral=True)
            return

        # Send immediate response
        await interaction.response.send_message("🔍 Running verification audit... This may take a moment.", ephemeral=True)

        try:
            # Get the verified role for this guild
            verified_role_id = self.cog.get_setting("verified_role_id", guild_id=self.guild_id)
            if not verified_role_id:
                await interaction.edit_original_response(
                    content="❌ No verified role is configured for this server. Please configure one in settings first."
                )
                return

            guild = self.cog.bot.get_guild(self.guild_id)
            if not guild:
                await interaction.edit_original_response(content="❌ Could not find this guild.")
                return

            verified_role = guild.get_role(verified_role_id)
            if not verified_role:
                await interaction.edit_original_response(content=f"❌ Configured verified role (ID: {verified_role_id}) not found in this server.")
                return

            # Get all members with the verified role
            members_with_role = [member for member in guild.members if verified_role in member.roles]

            # Query database for discrepancies
            def check_verified_status():
                """Check verification status for all members with verified role."""
                users_without_player = []
                users_with_multiple_players = []

                for member in members_with_role:
                    discord_id_str = str(member.id)
                    try:
                        # Use filter instead of get to handle multiple entries
                        players = KnownPlayer.objects.filter(discord_id=discord_id_str)
                        player_count = players.count()

                        if player_count == 0:
                            users_without_player.append({"id": member.id, "name": member.display_name, "username": str(member)})
                        elif player_count > 1:
                            # Track users with duplicate KnownPlayer entries
                            player_names = [p.name for p in players]
                            users_with_multiple_players.append(
                                {
                                    "id": member.id,
                                    "name": member.display_name,
                                    "username": str(member),
                                    "player_count": player_count,
                                    "player_names": player_names,
                                }
                            )
                    except Exception as e:
                        # Log any unexpected errors but continue
                        self.cog.logger.error(f"Error checking player for {member.id}: {e}")
                        continue

                return users_without_player, users_with_multiple_players

            def check_missing_roles():
                """Check for KnownPlayers in this guild without verified role."""
                players_without_role = []

                # Get all KnownPlayers with discord_id
                known_players = KnownPlayer.objects.filter(discord_id__isnull=False).exclude(discord_id="")

                for player in known_players:
                    try:
                        discord_id = int(player.discord_id)
                        member = guild.get_member(discord_id)

                        if member and verified_role not in member.roles:
                            players_without_role.append(
                                {
                                    "id": discord_id,
                                    "name": member.display_name,
                                    "username": str(member),
                                    "player_name": player.name,
                                    "player_id": player.id,
                                }
                            )
                    except (ValueError, TypeError):
                        # Invalid discord_id format
                        continue

                return players_without_role

            # Run database queries asynchronously
            users_without_player, users_with_multiple_players = await sync_to_async(check_verified_status)()
            players_without_role = await sync_to_async(check_missing_roles)()

            # Create embed with results
            embed = discord.Embed(
                title="🔍 Verification Audit Results",
                description=f"Audit for {guild.name}",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow(),
            )

            embed.add_field(
                name="📊 Summary",
                value=f"**Verified Role:** {verified_role.mention}\n"
                f"**Total members with role:** {len(members_with_role)}\n"
                f"**Users with role but no KnownPlayer:** {len(users_without_player)}\n"
                f"**Users with multiple KnownPlayers:** {len(users_with_multiple_players)}\n"
                f"**KnownPlayers without role:** {len(players_without_role)}",
                inline=False,
            )

            # Add users with verified role but no KnownPlayer
            if users_without_player:
                users_list = []
                for user in users_without_player[:10]:  # Limit to first 10
                    users_list.append(f"<@{user['id']}> (`{user['username']}`)")

                if len(users_without_player) > 10:
                    users_list.append(f"... and {len(users_without_player) - 10} more")

                embed.add_field(
                    name="⚠️ Users with Verified Role but No KnownPlayer", value="\n".join(users_list) if users_list else "None", inline=False
                )
            else:
                embed.add_field(
                    name="✅ Users with Verified Role but No KnownPlayer",
                    value="None found - all users with verified role have KnownPlayer entries!",
                    inline=False,
                )

            # Add users with multiple KnownPlayer entries
            if users_with_multiple_players:
                users_list = []
                for user in users_with_multiple_players[:10]:  # Limit to first 10
                    player_names_str = ", ".join(user["player_names"][:3])
                    if len(user["player_names"]) > 3:
                        player_names_str += f" +{len(user['player_names']) - 3} more"
                    users_list.append(f"<@{user['id']}> (`{user['username']}`) - {user['player_count']} players: {player_names_str}")

                if len(users_with_multiple_players) > 10:
                    users_list.append(f"... and {len(users_with_multiple_players) - 10} more")

                embed.add_field(
                    name="⚠️ Users with Multiple KnownPlayer Entries (Data Issue)",
                    value="\n".join(users_list) if users_list else "None",
                    inline=False,
                )

            # Add KnownPlayers without verified role
            if players_without_role:
                players_list = []
                for player in players_without_role[:10]:  # Limit to first 10
                    players_list.append(f"<@{player['id']}> (`{player['username']}`) - Player: {player['player_name']}")

                if len(players_without_role) > 10:
                    players_list.append(f"... and {len(players_without_role) - 10} more")

                embed.add_field(name="⚠️ KnownPlayers without Verified Role", value="\n".join(players_list) if players_list else "None", inline=False)
            else:
                embed.add_field(
                    name="✅ KnownPlayers without Verified Role",
                    value="None found - all KnownPlayers in this guild have verified role!",
                    inline=False,
                )

            embed.set_footer(text=f"Requested by {interaction.user}")

            await interaction.edit_original_response(content=None, embed=embed)

        except Exception as exc:
            self.cog.logger.error(f"Error running verification audit: {exc}", exc_info=True)
            await interaction.edit_original_response(content=f"❌ An error occurred while running the audit: {str(exc)}")


class VerifiedRoleSelect(ui.RoleSelect):
    """Role select for choosing the verified role."""

    def __init__(self, cog: BaseCog, guild_id: int):
        current_role_id = cog.get_setting("verified_role_id", guild_id=guild_id)
        placeholder = "Select the verified role..."
        if current_role_id:
            guild = cog.bot.get_guild(guild_id)
            if guild:
                role = guild.get_role(current_role_id)
                if role:
                    placeholder = f"Current: {role.name}"

        super().__init__(placeholder=placeholder, min_values=0, max_values=1)
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Handle role selection."""
        if not self.values:
            # Clear the setting
            self.cog.set_setting("verified_role_id", None, self.guild_id)
            await interaction.response.send_message("✅ Verified role cleared.", ephemeral=True)
            return

        role = self.values[0]
        self.cog.set_setting("verified_role_id", role.id, self.guild_id)

        await interaction.response.send_message(f"✅ Verified role set to {role.mention}.", ephemeral=True)


class VerificationLogChannelSelect(ui.ChannelSelect):
    """Channel select for choosing the verification log channel."""

    def __init__(self, cog: BaseCog, guild_id: int):
        current_channel_id = cog.get_setting("verification_log_channel_id", guild_id=guild_id)
        placeholder = "Select the verification log channel..."
        if current_channel_id:
            guild = cog.bot.get_guild(guild_id)
            if guild:
                channel = guild.get_channel(current_channel_id)
                if channel:
                    placeholder = f"Current: {channel.name}"

        super().__init__(placeholder=placeholder, min_values=0, max_values=1, channel_types=[discord.ChannelType.text])
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        """Handle channel selection."""
        if not self.values:
            # Clear the setting
            self.cog.set_setting("verification_log_channel_id", None, self.guild_id)
            await interaction.response.send_message("✅ Verification log channel cleared.", ephemeral=True)
            return

        channel = self.values[0]
        self.cog.set_setting("verification_log_channel_id", channel.id, self.guild_id)

        await interaction.response.send_message(f"✅ Verification log channel set to {channel.mention}.", ephemeral=True)


class ValidationGroupsSelectView(discord.ui.View):
    """View for managing Django groups for un-verify permissions."""

    def __init__(
        self,
        cog: BaseCog,
        interaction: discord.Interaction,
        current_groups: list,
        setting_key: str = "approved_unverify_groups",
        context: SettingsViewContext = None,
    ):
        super().__init__(timeout=900)
        self.cog = cog
        self.original_interaction = interaction
        self.current_groups = set(current_groups)
        self.selected_groups = self.current_groups.copy()
        self.setting_key = setting_key
        self.context = context
        self.available_groups = []

        # Get available Django groups
        self._load_available_groups()

        # Add the "Add Group" button
        add_button = discord.ui.Button(label="Add Group", style=discord.ButtonStyle.primary, emoji="➕", custom_id="add_group")
        add_button.callback = self.add_group_callback
        self.add_item(add_button)

        # Add the "Remove Groups" button
        if self.current_groups:  # Only show if there are groups to remove
            remove_button = discord.ui.Button(label="Remove Groups", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="remove_groups")
            remove_button.callback = self.remove_groups_callback
            self.add_item(remove_button)

    def _load_available_groups(self):
        """Load available Django groups synchronously."""
        # For now, we'll use common defaults. In a future update, this could query Django directly
        self.available_groups = ["admin", "moderators", "staff", "verified", "premium", "beta_testers", "supporters"]

    async def add_group_callback(self, interaction: discord.Interaction):
        """Handle adding a new group."""
        # Query Django for available groups
        try:
            from asgiref.sync import sync_to_async
            from django.contrib.auth.models import Group

            # Get all Django groups
            django_groups = await sync_to_async(list)(Group.objects.all().order_by("name"))
            available_groups = [group.name for group in django_groups]
        except Exception as e:
            self.cog.logger.warning(f"Could not query Django groups: {e}, using defaults")
            available_groups = self.available_groups

        # Create dropdown of available groups not already selected
        available_options = [g for g in available_groups if g not in self.selected_groups]

        if not available_options:
            embed = discord.Embed(
                title="No Groups Available",
                description="All available Django groups are already selected, or no groups are configured in Django.",
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Create select dropdown
        options = [discord.SelectOption(label=group, value=group) for group in available_options[:25]]  # Discord limit

        select = discord.ui.Select(
            placeholder="Select Django groups to add",
            options=options,
            max_values=len(options),  # Allow selecting multiple
            min_values=1,
            custom_id="add_group_select",
        )

        # Create a temporary view with just the select
        temp_view = discord.ui.View(timeout=300)
        temp_view.add_item(select)

        async def select_callback(select_interaction: discord.Interaction):
            selected_groups = select_interaction.data["values"]
            for group in selected_groups:
                self.selected_groups.add(group)

            # Update the view
            embed = self.create_selection_embed()
            await select_interaction.response.edit_message(embed=embed, view=self)

        select.callback = select_callback

        embed = discord.Embed(
            title="Add Django Groups",
            description="Select one or more Django groups to add to the permission list.",
            color=discord.Color.blue(),
        )

        await interaction.response.send_message(embed=embed, view=temp_view, ephemeral=True)

    async def remove_groups_callback(self, interaction: discord.Interaction):
        """Handle removing multiple groups via dropdown."""
        if not self.selected_groups:
            embed = discord.Embed(
                title="No Groups to Remove",
                description="There are no groups currently selected to remove.",
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Create select dropdown of currently selected groups
        options = [discord.SelectOption(label=group, value=group) for group in sorted(self.selected_groups)[:25]]  # Discord limit

        select = discord.ui.Select(
            placeholder="Select groups to remove",
            options=options,
            max_values=len(options),  # Allow selecting all
            min_values=1,
            custom_id="remove_groups_select",
        )

        # Create a temporary view with just the select
        temp_view = discord.ui.View(timeout=300)
        temp_view.add_item(select)

        async def select_callback(select_interaction: discord.Interaction):
            groups_to_remove = select_interaction.data["values"]
            for group in groups_to_remove:
                self.selected_groups.discard(group)

            # Update the view
            embed = self.create_selection_embed()
            await select_interaction.response.edit_message(embed=embed, view=self)

        select.callback = select_callback

        embed = discord.Embed(
            title="Remove Django Groups",
            description="Select one or more Django groups to remove from the permission list.",
            color=discord.Color.red(),
        )

        await interaction.response.send_message(embed=embed, view=temp_view, ephemeral=True)

    def create_selection_embed(self) -> discord.Embed:
        """Create embed showing current group selection."""
        title = "🔐 Approved Groups for Un-verify"
        description = "Configure which Django groups can un-verify players.\n\n**Current Groups:**"
        no_groups_message = "*No groups selected - no one can un-verify players*"

        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blue(),
        )

        if self.selected_groups:
            group_list = "\n".join(f"• {group}" for group in sorted(self.selected_groups))
            embed.add_field(name=f"Selected Groups ({len(self.selected_groups)})", value=group_list, inline=False)
        else:
            embed.add_field(name="Selected Groups (0)", value=no_groups_message, inline=False)

        embed.set_footer(text="Use 'Add Group' to add more groups • Use 'Remove Groups' to delete groups • Click Save when done")
        return embed

    @discord.ui.button(label="Save Changes", style=discord.ButtonStyle.success, emoji="💾", row=4)
    async def save_changes(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Save the selected groups."""
        new_groups = sorted(list(self.selected_groups))

        # Save the setting globally in bot config (following manage_sus pattern)
        self.cog.config.set_global_cog_setting("validation", self.setting_key, new_groups)

        description = f"**Approved Un-verify Groups:** {len(new_groups)} groups configured\n"
        if new_groups:
            description += f"**Groups:** {', '.join(new_groups)}"
        else:
            description += "**No groups configured**"

        embed = discord.Embed(
            title="Approved Un-verify Groups Updated",
            description=description,
            color=discord.Color.green(),
        )

        # Return to the main settings view
        view = ValidationSettingsView(self.context)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌", row=4)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel and return to main settings."""
        embed = discord.Embed(title="Cancelled", description="Group selection cancelled. No changes were made.", color=discord.Color.orange())

        # Return to the main settings view
        view = ValidationSettingsView(self.context)
        await interaction.response.edit_message(embed=embed, view=view)
        await interaction.response.edit_message(embed=embed, view=view)
