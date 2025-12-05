"""Settings management views for global Battle Conditions integration."""

import discord

from thetower.bot.ui.context import SettingsViewContext


class BattleConditionsSettingsView(discord.ui.View):
    """Settings view for Battle Conditions cog."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context
        self.guild_id = context.guild_id

        # Configure leagues button
        self.add_item(BattleConditionsConfigureLeaguesButton(self.cog))

        # Configure permissions button
        self.add_item(BattleConditionsConfigurePermissionsButton(self.cog))

        # Manage schedules button
        self.add_item(BattleConditionsManageSchedulesButton(self.cog))

        # Back button
        back_btn = discord.ui.Button(label="Back to Cog Settings", style=discord.ButtonStyle.gray, emoji="⬅️", custom_id="back_to_cog_settings")
        back_btn.callback = self.back_to_cog_settings
        self.add_item(back_btn)

    async def update_display(self, interaction: discord.Interaction):
        """Update the embed with current battle conditions settings."""
        embed = discord.Embed(
            title="⚙️ Battle Conditions Settings", description="Configure battle conditions for this server", color=discord.Color.blue()
        )

        # Current enabled leagues (global setting)
        enabled_leagues = self.cog.get_global_setting("enabled_leagues") or []

        embed.add_field(name="Enabled Leagues (Global)", value=", ".join(enabled_leagues) if enabled_leagues else "None configured", inline=False)

        # Current schedules
        schedules = self.cog.get_setting("destination_schedules", guild_id=self.guild_id) or []
        if schedules:
            schedule_info = []
            for i, schedule in enumerate(schedules):
                dest_id = schedule.get("destination_id")
                channel = self.cog.bot.get_channel(int(dest_id))
                channel_name = channel.mention if channel else f"ID: {dest_id}"
                leagues = ", ".join(schedule.get("leagues", [])[:3])
                paused = " (⏸️)" if schedule.get("paused", False) else ""
                schedule_info.append(f"#{i}: {channel_name} - {leagues}{paused}")

            embed.add_field(name=f"Schedules ({len(schedules)})", value="\n".join(schedule_info[:5]), inline=False)  # Limit to 5 for embed size
        else:
            embed.add_field(name="Schedules", value="No schedules configured", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

    async def back_to_cog_settings(self, interaction: discord.Interaction):
        """Go back to the cog settings selection view."""
        # Import here to avoid circular imports
        from thetower.bot.ui.settings_views import CogSettingsView

        # Recreate the cog settings view
        view = CogSettingsView(self.guild_id)
        await view.update_display(interaction)


class BattleConditionsConfigureLeaguesButton(discord.ui.Button):
    """Button to configure enabled leagues for battle conditions."""

    def __init__(self, bc_cog):
        super().__init__(label="Configure Leagues", style=discord.ButtonStyle.primary, emoji="🏆")
        self.bc_cog = bc_cog

    async def callback(self, interaction: discord.Interaction):
        # Get current enabled leagues (global setting)
        enabled_leagues = self.cog.get_global_setting("enabled_leagues") or []

        # Create select menu with all leagues
        league_select = BattleConditionsLeagueSelect(self.bc_cog, enabled_leagues)
        select_view = discord.ui.View(timeout=900)
        select_view.add_item(league_select)

        await interaction.response.send_message(
            "Select which leagues to enable for battle conditions (applies globally):", view=select_view, ephemeral=True
        )


class BattleConditionsLeagueSelect(discord.ui.Select):
    """Select menu for choosing enabled leagues."""

    def __init__(self, bc_cog, current_enabled: list):
        from .core import ALL_LEAGUES

        # Show items as checked only if they're in the config
        options = [discord.SelectOption(label=league, value=league, default=league in current_enabled) for league in ALL_LEAGUES]

        super().__init__(placeholder="Select leagues to enable...", min_values=0, max_values=len(ALL_LEAGUES), options=options)
        self.bc_cog = bc_cog

    async def callback(self, interaction: discord.Interaction):
        selected_leagues = self.values

        # Save to global settings
        self.bc_cog.set_global_setting("enabled_leagues", selected_leagues)

        if selected_leagues:
            await interaction.response.send_message(f"✅ Enabled leagues updated globally: {', '.join(selected_leagues)}", ephemeral=True)
        else:
            await interaction.response.send_message("✅ Enabled leagues updated globally: (none selected)", ephemeral=True)


class BattleConditionsConfigurePermissionsButton(discord.ui.Button):
    """Button to configure battle conditions permissions."""

    def __init__(self, bc_cog):
        super().__init__(label="Configure Permissions", style=discord.ButtonStyle.secondary, emoji="🔒")
        self.bc_cog = bc_cog

    async def callback(self, interaction: discord.Interaction):
        # Show permission configuration view
        perm_view = BattleConditionsPermissionsView(self.bc_cog)

        await interaction.response.send_message(
            "**Permission Configuration**\n\n" "Choose which action to configure permissions for:", view=perm_view, ephemeral=True
        )


class BattleConditionsManageSchedulesButton(discord.ui.Button):
    """Button to manage battle conditions schedules."""

    def __init__(self, bc_cog):
        super().__init__(label="Manage Schedules", style=discord.ButtonStyle.primary, emoji="📅")
        self.bc_cog = bc_cog

    async def callback(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id

        # Check manage_schedules permission
        can_manage = await self.bc_cog.check_slash_action_permission(interaction, "manage_schedules")
        is_owner = interaction.guild.owner_id == interaction.user.id or await self.bc_cog.bot.is_owner(interaction.user)

        # Get schedules for this guild
        schedules = self.bc_cog.get_setting("destination_schedules", guild_id=guild_id) or []

        # Show schedule management view
        schedule_view = BattleConditionsScheduleManagementView(self.bc_cog, guild_id, schedules, can_manage or is_owner)

        if schedules:
            schedule_list = []
            for idx, schedule in enumerate(schedules):
                dest_id = schedule.get("destination_id")
                channel = self.bc_cog.bot.get_channel(int(dest_id))
                channel_name = channel.mention if channel else f"ID: {dest_id}"
                leagues = ", ".join(schedule.get("leagues", [])[:3])
                paused = "⏸️ " if schedule.get("paused", False) else ""
                schedule_list.append(f"{paused}**#{idx}**: {channel_name} - {leagues}")

            schedule_text = (
                f"**Current Schedules** ({len(schedules)})\n\n"
                + "\n".join(schedule_list[:10])
                + (f"\n\n...and {len(schedules) - 10} more" if len(schedules) > 10 else "")
            )
        else:
            schedule_text = "**No schedules configured**\n\nClick 'Create Schedule' to add one."

        await interaction.response.send_message(schedule_text, view=schedule_view, ephemeral=True)


class BattleConditionsPermissionsView(discord.ui.View):
    """View for configuring BC action permissions."""

    def __init__(self, bc_cog):
        super().__init__(timeout=900)
        self.bc_cog = bc_cog

        self.add_item(BattleConditionsConfigureGeneratePermButton(self.bc_cog))
        self.add_item(BattleConditionsConfigureRunSchedulePermButton(self.bc_cog))
        self.add_item(BattleConditionsConfigureManageSchedulesPermButton(self.bc_cog))


class BattleConditionsConfigureGeneratePermButton(discord.ui.Button):
    """Button to configure generate permissions."""

    def __init__(self, bc_cog):
        super().__init__(label="Generate Permissions", style=discord.ButtonStyle.primary)
        self.bc_cog = bc_cog

    async def callback(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id

        # Get current permissions
        perms = self.bc_cog.get_setting("slash_permissions.generate", guild_id=guild_id) or {}
        current_users = perms.get("allowed_users", [])
        current_roles = perms.get("allowed_roles", [])

        # Build current permissions display
        current_mentions = []
        if current_roles:
            current_mentions.extend([f"<@&{rid}>" for rid in current_roles])
        if current_users:
            current_mentions.extend([f"<@{uid}>" for uid in current_users])

        if current_mentions:
            current_text = f"**Current permissions:** {', '.join(current_mentions)}\n\n"
        else:
            current_text = "**Current permissions:** Owner only (default)\n\n"

        # Create mentionable select
        mentionable_select = BattleConditionsActionMentionableSelect(self.bc_cog, "generate", guild_id)
        select_view = discord.ui.View(timeout=900)
        select_view.add_item(mentionable_select)

        await interaction.response.send_message(
            f"{current_text}Select roles/users that can use **Generate to Channel**:\n" "(Select none to clear and revert to owner-only)",
            view=select_view,
            ephemeral=True,
        )


class BattleConditionsConfigureRunSchedulePermButton(discord.ui.Button):
    """Button to configure run schedule permissions."""

    def __init__(self, bc_cog):
        super().__init__(label="Run Schedule Permissions", style=discord.ButtonStyle.primary)
        self.bc_cog = bc_cog

    async def callback(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id

        # Get current permissions
        perms = self.bc_cog.get_setting("slash_permissions.run_schedule", guild_id=guild_id) or {}
        current_users = perms.get("allowed_users", [])
        current_roles = perms.get("allowed_roles", [])

        # Build current permissions display
        current_mentions = []
        if current_roles:
            current_mentions.extend([f"<@&{rid}>" for rid in current_roles])
        if current_users:
            current_mentions.extend([f"<@{uid}>" for uid in current_users])

        if current_mentions:
            current_text = f"**Current permissions:** {', '.join(current_mentions)}\n\n"
        else:
            current_text = "**Current permissions:** Owner only (default)\n\n"

        # Create mentionable select
        mentionable_select = BattleConditionsActionMentionableSelect(self.bc_cog, "run_schedule", guild_id)
        select_view = discord.ui.View(timeout=900)
        select_view.add_item(mentionable_select)

        await interaction.response.send_message(
            f"{current_text}Select roles/users that can use **Run Schedule**:\n" "(Select none to clear and revert to owner-only)",
            view=select_view,
            ephemeral=True,
        )


class BattleConditionsConfigureManageSchedulesPermButton(discord.ui.Button):
    """Button to configure manage schedules permissions."""

    def __init__(self, bc_cog):
        super().__init__(label="Manage Schedules Permissions", style=discord.ButtonStyle.primary)
        self.bc_cog = bc_cog

    async def callback(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id

        # Get current permissions
        perms = self.bc_cog.get_setting("slash_permissions.manage_schedules", guild_id=guild_id) or {}
        current_users = perms.get("allowed_users", [])
        current_roles = perms.get("allowed_roles", [])

        # Build current permissions display
        current_mentions = []
        if current_roles:
            current_mentions.extend([f"<@&{rid}>" for rid in current_roles])
        if current_users:
            current_mentions.extend([f"<@{uid}>" for uid in current_users])

        if current_mentions:
            current_text = f"**Current permissions:** {', '.join(current_mentions)}\n\n"
        else:
            current_text = "**Current permissions:** Owner only (default)\n\n"

        # Create mentionable select
        mentionable_select = BattleConditionsActionMentionableSelect(self.bc_cog, "manage_schedules", guild_id)
        select_view = discord.ui.View(timeout=900)
        select_view.add_item(mentionable_select)

        await interaction.response.send_message(
            f"{current_text}Select roles/users that can use **Manage Schedules** (Create/Edit/Delete/Pause):\n"
            "(Select none to clear and revert to owner-only)",
            view=select_view,
            ephemeral=True,
        )


class BattleConditionsActionMentionableSelect(discord.ui.MentionableSelect):
    """Mentionable select for configuring action permissions."""

    def __init__(self, bc_cog, action_name: str, guild_id: int):
        # Get current permissions to set as defaults
        perms = bc_cog.get_setting(f"slash_permissions.{action_name}", guild_id=guild_id) or {}
        current_users = perms.get("allowed_users", [])
        current_roles = perms.get("allowed_roles", [])

        # Create default values from current permissions
        default_values = []
        for role_id in current_roles:
            default_values.append(discord.SelectDefaultValue(id=role_id, type=discord.SelectDefaultValueType.role))
        for user_id in current_users:
            default_values.append(discord.SelectDefaultValue(id=user_id, type=discord.SelectDefaultValueType.user))

        super().__init__(
            placeholder=f"Select roles/users for {action_name.replace('_', ' ')}...",
            min_values=0,
            max_values=25,
            default_values=default_values if default_values else None,
        )
        self.bc_cog = bc_cog
        self.action_name = action_name

    async def callback(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id

        # Separate roles and users from the selected values
        role_ids = []
        user_ids = []

        for value in self.values:
            if isinstance(value, discord.Role):
                role_ids.append(value.id)
            elif isinstance(value, (discord.Member, discord.User)):
                user_ids.append(value.id)

        # Save to permissions
        self.bc_cog.set_slash_action_permission(guild_id, self.action_name, allowed_roles=role_ids, allowed_users=user_ids)

        # Build response message
        mentions = []
        if role_ids:
            mentions.extend([f"<@&{rid}>" for rid in role_ids])
        if user_ids:
            mentions.extend([f"<@{uid}>" for uid in user_ids])

        if mentions:
            mention_list = ", ".join(mentions)
            await interaction.response.send_message(
                f"✅ {self.action_name.replace('_', ' ').title()} permissions updated for: {mention_list}", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"✅ {self.action_name.replace('_', ' ').title()} permissions cleared (owner-only default)", ephemeral=True
            )


class BattleConditionsScheduleManagementView(discord.ui.View):
    """View for managing BC schedules."""

    def __init__(self, bc_cog, guild_id: int, schedules: list, can_manage: bool = False):
        super().__init__(timeout=900)
        self.bc_cog = bc_cog
        self.guild_id = guild_id
        self.schedules = schedules

        # Add management buttons only if user has permission
        if can_manage:
            # Add create button
            self.add_item(BattleConditionsCreateScheduleButton())

            # Add edit/delete/pause buttons if schedules exist
            if schedules:
                self.add_item(BattleConditionsEditScheduleButton())
                self.add_item(BattleConditionsDeleteScheduleButton())
                self.add_item(BattleConditionsTogglePauseScheduleButton())


class BattleConditionsCreateScheduleButton(discord.ui.Button):
    """Button to create a new schedule."""

    def __init__(self):
        super().__init__(label="Create Schedule", style=discord.ButtonStyle.success, emoji="➕")

    async def callback(self, interaction: discord.Interaction):
        # Step 1: Show channel picker
        channel_view = discord.ui.View(timeout=900)
        channel_view.add_item(BattleConditionsScheduleChannelSelect(self.view.bc_cog, self.view.guild_id))

        await interaction.response.send_message(
            "**Step 1/3:** Select the channel or thread for battle conditions:", view=channel_view, ephemeral=True
        )


class BattleConditionsScheduleChannelSelect(discord.ui.ChannelSelect):
    """Channel select for new schedule."""

    def __init__(self, bc_cog, guild_id: int):
        super().__init__(
            placeholder="Select channel or thread...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.public_thread, discord.ChannelType.private_thread],
        )
        self.bc_cog = bc_cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]

        # Step 2: Show time configuration modal
        from .core import ScheduleTimeModal

        modal = ScheduleTimeModal(self.bc_cog, self.guild_id, channel.id)
        await interaction.response.send_modal(modal)


class BattleConditionsEditScheduleButton(discord.ui.Button):
    """Button to edit an existing schedule."""

    def __init__(self):
        super().__init__(label="Edit Schedule", style=discord.ButtonStyle.primary, emoji="✏️")

    async def callback(self, interaction: discord.Interaction):
        view: BattleConditionsScheduleManagementView = self.view

        # Show schedule selector
        select_view = discord.ui.View(timeout=900)
        select_view.add_item(BattleConditionsEditScheduleSelect(view.bc_cog, view.schedules, view.guild_id))

        await interaction.response.send_message("Select a schedule to edit:", view=select_view, ephemeral=True)


class BattleConditionsEditScheduleSelect(discord.ui.Select):
    """Select menu for choosing schedule to edit."""

    def __init__(self, bc_cog, schedules: list, guild_id: int):
        options = []
        for idx, schedule in enumerate(schedules[:25]):  # Discord limit
            dest_id = schedule.get("destination_id")
            channel = bc_cog.bot.get_channel(int(dest_id))
            channel_name = channel.name if channel else f"ID: {dest_id}"

            label = f"#{idx}: {channel_name}"[:100]
            leagues = ", ".join(schedule.get("leagues", [])[:2])
            description = f"{leagues}"[:100]

            options.append(discord.SelectOption(label=label, value=str(idx), description=description))

        super().__init__(placeholder="Choose schedule to edit...", options=options)
        self.bc_cog = bc_cog
        self.schedules = schedules
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        schedule = self.schedules[idx]

        # Show edit modal
        from .core import EditScheduleModal

        modal = EditScheduleModal(self.bc_cog, self.guild_id, idx, schedule)
        await interaction.response.send_modal(modal)


class BattleConditionsDeleteScheduleButton(discord.ui.Button):
    """Button to delete a schedule."""

    def __init__(self):
        super().__init__(label="Delete Schedule", style=discord.ButtonStyle.danger, emoji="🗑️")

    async def callback(self, interaction: discord.Interaction):
        view: BattleConditionsScheduleManagementView = self.view

        # Show schedule selector
        select_view = discord.ui.View(timeout=900)
        select_view.add_item(BattleConditionsDeleteScheduleSelect(view.bc_cog, view.schedules, view.guild_id))

        await interaction.response.send_message("Select a schedule to delete:", view=select_view, ephemeral=True)


class BattleConditionsDeleteScheduleSelect(discord.ui.Select):
    """Select menu for choosing schedule to delete."""

    def __init__(self, bc_cog, schedules: list, guild_id: int):
        options = []
        for idx, schedule in enumerate(schedules[:25]):  # Discord limit
            dest_id = schedule.get("destination_id")
            channel = bc_cog.bot.get_channel(int(dest_id))
            channel_name = channel.name if channel else f"ID: {dest_id}"

            label = f"#{idx}: {channel_name}"[:100]
            leagues = ", ".join(schedule.get("leagues", [])[:2])
            description = f"{leagues}"[:100]

            options.append(discord.SelectOption(label=label, value=str(idx), description=description, emoji="🗑️"))

        super().__init__(placeholder="Choose schedule to delete...", options=options)
        self.bc_cog = bc_cog
        self.schedules = schedules
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        schedule = self.schedules[idx]

        # Get channel for confirmation
        dest_id = schedule.get("destination_id")
        channel = self.bc_cog.bot.get_channel(int(dest_id))
        channel_name = channel.mention if channel else f"ID: {dest_id}"

        # Delete schedule
        schedules = self.cog.get_setting("destination_schedules", guild_id=self.guild_id) or []
        schedules.pop(idx)
        self.cog.set_setting("destination_schedules", schedules, guild_id=self.guild_id)
        self.cog.mark_data_modified()

        await interaction.response.send_message(f"✅ Deleted schedule #{idx} for {channel_name}", ephemeral=True)


class BattleConditionsTogglePauseScheduleButton(discord.ui.Button):
    """Button to pause/resume schedules."""

    def __init__(self):
        super().__init__(label="Pause/Resume", style=discord.ButtonStyle.secondary, emoji="⏯️")

    async def callback(self, interaction: discord.Interaction):
        view: BattleConditionsScheduleManagementView = self.view

        # Show schedule selector
        select_view = discord.ui.View(timeout=900)
        select_view.add_item(BattleConditionsTogglePauseSelect(view.bc_cog, view.schedules, view.guild_id))

        await interaction.response.send_message("Select a schedule to pause/resume:", view=select_view, ephemeral=True)


class BattleConditionsTogglePauseSelect(discord.ui.Select):
    """Select menu for pausing/resuming schedules."""

    def __init__(self, bc_cog, schedules: list, guild_id: int):
        options = []
        for idx, schedule in enumerate(schedules[:25]):  # Discord limit
            dest_id = schedule.get("destination_id")
            channel = bc_cog.bot.get_channel(int(dest_id))
            channel_name = channel.name if channel else f"ID: {dest_id}"
            paused = schedule.get("paused", False)

            label = f"#{idx}: {channel_name}"[:100]
            status = "⏸️ PAUSED" if paused else "▶️ ACTIVE"
            description = f"{status}"[:100]

            options.append(discord.SelectOption(label=label, value=str(idx), description=description, emoji="⏸️" if paused else "▶️"))

        super().__init__(placeholder="Choose schedule to toggle...", options=options)
        self.bc_cog = bc_cog
        self.schedules = schedules
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])

        # Toggle pause state
        schedules = self.bc_cog.get_setting("destination_schedules", guild_id=self.guild_id) or []
        current_paused = schedules[idx].get("paused", False)
        schedules[idx]["paused"] = not current_paused

        self.bc_cog.set_setting("destination_schedules", schedules, guild_id=self.guild_id)
        self.bc_cog.mark_data_modified()

        # Get channel for feedback
        dest_id = schedules[idx].get("destination_id")
        channel = self.bc_cog.bot.get_channel(int(dest_id))
        channel_name = channel.mention if channel else f"ID: {dest_id}"

        action = "Paused" if not current_paused else "Resumed"
        await interaction.response.send_message(f"✅ {action} schedule #{idx} for {channel_name}", ephemeral=True)
