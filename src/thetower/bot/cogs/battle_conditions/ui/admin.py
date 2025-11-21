"""Administrative interfaces for Battle Conditions cog."""

import discord

from .core import ALL_LEAGUES, DEFAULT_ENABLED_LEAGUES

# === Administrative Interface Components ===


class BCSettingsView(discord.ui.View):
    """View for managing BC settings."""

    def __init__(self, cog, is_bot_owner: bool = False):
        super().__init__(timeout=900)
        self.cog = cog

        # Add buttons for different settings
        self.add_item(ConfigureLeaguesButton())
        self.add_item(ConfigurePermissionsButton())
        self.add_item(ManageSchedulesButton())

        # Add global settings button for bot owner only
        if is_bot_owner:
            self.add_item(GlobalSettingsButton())


class ConfigureLeaguesButton(discord.ui.Button):
    """Button to configure enabled leagues."""

    def __init__(self):
        super().__init__(label="Configure Leagues", style=discord.ButtonStyle.primary, emoji="🏆")

    async def callback(self, interaction: discord.Interaction):
        view: BCSettingsView = self.view
        cog = view.cog
        guild_id = interaction.guild.id

        # Get current enabled leagues
        enabled_leagues = cog.get_setting("enabled_leagues", guild_id=guild_id) or DEFAULT_ENABLED_LEAGUES

        # Create select menu with all leagues
        league_select = LeagueSelect(cog, enabled_leagues)
        select_view = discord.ui.View(timeout=900)
        select_view.add_item(league_select)

        await interaction.response.send_message("Select which leagues to enable:", view=select_view, ephemeral=True)


class LeagueSelect(discord.ui.Select):
    """Select menu for choosing enabled leagues."""

    def __init__(self, cog, current_enabled: list):
        options = [discord.SelectOption(label=league, value=league, default=league in current_enabled) for league in ALL_LEAGUES]

        super().__init__(placeholder="Select leagues to enable...", min_values=1, max_values=len(ALL_LEAGUES), options=options)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        selected_leagues = self.values

        # Save to settings
        self.cog.set_setting("enabled_leagues", selected_leagues, guild_id=guild_id)

        await interaction.response.send_message(f"✅ Enabled leagues updated: {', '.join(selected_leagues)}", ephemeral=True)


class ConfigurePermissionsButton(discord.ui.Button):
    """Button to configure action permissions."""

    def __init__(self):
        super().__init__(label="Configure Permissions", style=discord.ButtonStyle.secondary, emoji="🔒")

    async def callback(self, interaction: discord.Interaction):
        # Show permission configuration view
        perm_view = BCPermissionsView(self.view.cog)

        await interaction.response.send_message(
            "**Permission Configuration**\n\n" "Choose which action to configure permissions for:", view=perm_view, ephemeral=True
        )


class ManageSchedulesButton(discord.ui.Button):
    """Button to manage BC schedules."""

    def __init__(self):
        super().__init__(label="Manage Schedules", style=discord.ButtonStyle.primary, emoji="📅")

    async def callback(self, interaction: discord.Interaction):
        view: BCSettingsView = self.view
        cog = view.cog
        guild_id = interaction.guild.id

        # Check manage_schedules permission
        can_manage = await cog.check_slash_action_permission(interaction, "manage_schedules")
        is_owner = interaction.guild.owner_id == interaction.user.id or await cog.bot.is_owner(interaction.user)

        # Get schedules for this guild
        schedules = cog.get_setting("destination_schedules", guild_id=guild_id) or []

        # Show schedule management view
        schedule_view = ScheduleManagementView(cog, guild_id, schedules, can_manage or is_owner)

        if schedules:
            schedule_list = []
            for idx, schedule in enumerate(schedules):
                dest_id = schedule.get("destination_id")
                channel = cog.bot.get_channel(int(dest_id))
                channel_name = channel.mention if channel else f"ID: {dest_id}"
                leagues = ", ".join(schedule.get("leagues", [])[:3])
                paused = "⏸️ " if schedule.get("paused", False) else ""
                time = f"{schedule.get('hour', 0):02d}:{schedule.get('minute', 0):02d}"
                schedule_list.append(f"{paused}**#{idx}**: {channel_name} - {leagues} @ {time} UTC")

            schedule_text = (
                f"**Current Schedules** ({len(schedules)})\n\n"
                + "\n".join(schedule_list[:10])
                + (f"\n\n...and {len(schedules) - 10} more" if len(schedules) > 10 else "")
            )
        else:
            schedule_text = "**No schedules configured**\n\nClick 'Create Schedule' to add one."

        await interaction.response.send_message(schedule_text, view=schedule_view, ephemeral=True)


class ScheduleManagementView(discord.ui.View):
    """View for managing BC schedules."""

    def __init__(self, cog, guild_id: int, schedules: list, can_manage: bool = False):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild_id = guild_id
        self.schedules = schedules

        # Add management buttons only if user has permission
        if can_manage:
            # Add create button
            self.add_item(CreateScheduleButton())

            # Add edit/delete/pause buttons if schedules exist
            if schedules:
                self.add_item(EditScheduleButton())
                self.add_item(DeleteScheduleButton())
                self.add_item(TogglePauseScheduleButton())


class CreateScheduleButton(discord.ui.Button):
    """Button to create a new schedule."""

    def __init__(self):
        super().__init__(label="Create Schedule", style=discord.ButtonStyle.success, emoji="➕")

    async def callback(self, interaction: discord.Interaction):
        # Step 1: Show channel picker
        channel_view = discord.ui.View(timeout=900)
        channel_view.add_item(ScheduleChannelSelect(self.view.cog, self.view.guild_id))

        await interaction.response.send_message(
            "**Step 1/3:** Select the channel or thread for battle conditions:", view=channel_view, ephemeral=True
        )


class ScheduleChannelSelect(discord.ui.ChannelSelect):
    """Channel select for new schedule."""

    def __init__(self, cog, guild_id: int):
        super().__init__(
            placeholder="Select channel or thread...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.public_thread, discord.ChannelType.private_thread],
        )
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]

        # Step 2: Show time configuration modal
        from .core import ScheduleTimeModal

        modal = ScheduleTimeModal(self.cog, self.guild_id, channel.id)
        await interaction.response.send_modal(modal)


class EditScheduleButton(discord.ui.Button):
    """Button to edit an existing schedule."""

    def __init__(self):
        super().__init__(label="Edit Schedule", style=discord.ButtonStyle.primary, emoji="✏️")

    async def callback(self, interaction: discord.Interaction):
        view: ScheduleManagementView = self.view

        # Show schedule selector
        select_view = discord.ui.View(timeout=900)
        select_view.add_item(EditScheduleSelect(view.cog, view.schedules, view.guild_id))

        await interaction.response.send_message("Select a schedule to edit:", view=select_view, ephemeral=True)


class EditScheduleSelect(discord.ui.Select):
    """Select menu for choosing schedule to edit."""

    def __init__(self, cog, schedules: list, guild_id: int):
        options = []
        for idx, schedule in enumerate(schedules[:25]):  # Discord limit
            dest_id = schedule.get("destination_id")
            channel = cog.bot.get_channel(int(dest_id))
            channel_name = channel.name if channel else f"ID: {dest_id}"

            label = f"#{idx}: {channel_name}"[:100]
            leagues = ", ".join(schedule.get("leagues", [])[:2])
            description = f"{leagues}"[:100]

            options.append(discord.SelectOption(label=label, value=str(idx), description=description))

        super().__init__(placeholder="Choose schedule to edit...", options=options)
        self.cog = cog
        self.schedules = schedules
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        schedule = self.schedules[idx]

        # Show edit modal
        from .core import EditScheduleModal

        modal = EditScheduleModal(self.cog, self.guild_id, idx, schedule)
        await interaction.response.send_modal(modal)


class EditScheduleLeagueSelect(discord.ui.Select):
    """Select menu for choosing leagues when editing a schedule."""

    def __init__(self, cog, guild_id: int, schedule_idx: int, hour: int, minute: int, days_before: int, current_leagues: list):
        options = [discord.SelectOption(label=league, value=league, emoji="🏆", default=league in current_leagues) for league in ALL_LEAGUES]

        super().__init__(placeholder="Select leagues (choose one or more)...", min_values=1, max_values=len(ALL_LEAGUES), options=options)
        self.cog = cog
        self.guild_id = guild_id
        self.schedule_idx = schedule_idx
        self.hour = hour
        self.minute = minute
        self.days_before = days_before

    async def callback(self, interaction: discord.Interaction):
        selected_leagues = self.values

        # Update schedule
        schedules = self.cog.get_setting("destination_schedules", guild_id=self.guild_id) or []
        schedules[self.schedule_idx].update({"hour": self.hour, "minute": self.minute, "days_before": self.days_before, "leagues": selected_leagues})

        self.cog.set_setting("destination_schedules", schedules, guild_id=self.guild_id)
        self.cog.mark_data_modified()

        await interaction.response.send_message(
            f"✅ **Schedule #{self.schedule_idx} Updated!**\n\n"
            f"⏰ Time: {self.hour:02d}:{self.minute:02d} UTC\n"
            f"📅 When: {self.days_before} day(s) before tournament\n"
            f"🏆 Leagues: {', '.join(selected_leagues)}",
            ephemeral=True,
        )


class DeleteScheduleButton(discord.ui.Button):
    """Button to delete a schedule."""

    def __init__(self):
        super().__init__(label="Delete Schedule", style=discord.ButtonStyle.danger, emoji="🗑️")

    async def callback(self, interaction: discord.Interaction):
        view: ScheduleManagementView = self.view

        # Show schedule selector
        select_view = discord.ui.View(timeout=900)
        select_view.add_item(DeleteScheduleSelect(view.cog, view.schedules, view.guild_id))

        await interaction.response.send_message("Select a schedule to delete:", view=select_view, ephemeral=True)


class DeleteScheduleSelect(discord.ui.Select):
    """Select menu for choosing schedule to delete."""

    def __init__(self, cog, schedules: list, guild_id: int):
        options = []
        for idx, schedule in enumerate(schedules[:25]):  # Discord limit
            dest_id = schedule.get("destination_id")
            channel = cog.bot.get_channel(int(dest_id))
            channel_name = channel.name if channel else f"ID: {dest_id}"

            label = f"#{idx}: {channel_name}"[:100]
            leagues = ", ".join(schedule.get("leagues", [])[:2])
            description = f"{leagues}"[:100]

            options.append(discord.SelectOption(label=label, value=str(idx), description=description, emoji="🗑️"))

        super().__init__(placeholder="Choose schedule to delete...", options=options)
        self.cog = cog
        self.schedules = schedules
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        schedule = self.schedules[idx]

        # Get channel for confirmation
        dest_id = schedule.get("destination_id")
        channel = self.cog.bot.get_channel(int(dest_id))
        channel_name = channel.mention if channel else f"ID: {dest_id}"

        # Delete schedule
        schedules = self.cog.get_setting("destination_schedules", guild_id=self.guild_id) or []
        schedules.pop(idx)
        self.cog.set_setting("destination_schedules", schedules, guild_id=self.guild_id)
        self.cog.mark_data_modified()

        await interaction.response.send_message(f"✅ Deleted schedule #{idx} for {channel_name}", ephemeral=True)


class TogglePauseScheduleButton(discord.ui.Button):
    """Button to pause/resume schedules."""

    def __init__(self):
        super().__init__(label="Pause/Resume", style=discord.ButtonStyle.secondary, emoji="⏯️")

    async def callback(self, interaction: discord.Interaction):
        view: ScheduleManagementView = self.view

        # Show schedule selector
        select_view = discord.ui.View(timeout=900)
        select_view.add_item(TogglePauseSelect(view.bc_cog, view.schedules, view.guild_id))

        await interaction.response.send_message("Select a schedule to pause/resume:", view=select_view, ephemeral=True)


class TogglePauseSelect(discord.ui.Select):
    """Select menu for pausing/resuming schedules."""

    def __init__(self, cog, schedules: list, guild_id: int):
        options = []
        for idx, schedule in enumerate(schedules[:25]):  # Discord limit
            dest_id = schedule.get("destination_id")
            channel = cog.bot.get_channel(int(dest_id))
            channel_name = channel.name if channel else f"ID: {dest_id}"
            paused = schedule.get("paused", False)

            label = f"#{idx}: {channel_name}"[:100]
            status = "⏸️ PAUSED" if paused else "▶️ ACTIVE"
            description = f"{status}"[:100]

            options.append(discord.SelectOption(label=label, value=str(idx), description=description, emoji="⏸️" if paused else "▶️"))

        super().__init__(placeholder="Choose schedule to toggle...", options=options)
        self.cog = cog
        self.schedules = schedules
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])

        # Toggle pause state
        schedules = self.cog.get_setting("destination_schedules", guild_id=self.guild_id) or []
        current_paused = schedules[idx].get("paused", False)
        schedules[idx]["paused"] = not current_paused

        self.cog.set_setting("destination_schedules", schedules, guild_id=self.guild_id)
        self.cog.mark_data_modified()

        # Get channel for feedback
        dest_id = schedules[idx].get("destination_id")
        channel = self.cog.bot.get_channel(int(dest_id))
        channel_name = channel.mention if channel else f"ID: {dest_id}"

        action = "Paused" if not current_paused else "Resumed"
        await interaction.response.send_message(f"✅ {action} schedule #{idx} for {channel_name}", ephemeral=True)


class GlobalSettingsButton(discord.ui.Button):
    """Button to configure global bot settings (bot owner only)."""

    def __init__(self):
        super().__init__(label="Global Settings", style=discord.ButtonStyle.danger, emoji="🌐")

    async def callback(self, interaction: discord.Interaction):
        view: BCSettingsView = self.view
        cog = view.cog

        # Get current global settings
        view_window = cog.get_setting("bc_view_window_days", guild_id=None)
        if view_window is None:
            view_window = cog.default_settings["bc_view_window_days"]

        # Show modal for setting view window
        from .core import ViewWindowModal

        modal = ViewWindowModal(cog, view_window)
        await interaction.response.send_modal(modal)


class BCPermissionsView(discord.ui.View):
    """View for configuring BC action permissions."""

    def __init__(self, cog):
        super().__init__(timeout=900)
        self.cog = cog

        self.add_item(ConfigureGeneratePermButton())
        self.add_item(ConfigureRunSchedulePermButton())
        self.add_item(ConfigureManageSchedulesPermButton())
        self.add_item(ConfigureChannelsPermButton())


class ConfigureGeneratePermButton(discord.ui.Button):
    """Button to configure generate permissions."""

    def __init__(self):
        super().__init__(label="Generate Permissions", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        view: BCPermissionsView = self.view
        cog = view.cog
        guild_id = interaction.guild.id

        # Get current permissions
        perms = cog.get_setting("slash_permissions.generate", guild_id=guild_id) or {}
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

        # Create mentionable select with default values
        mentionable_select = ActionMentionableSelect(cog, "generate", guild_id)
        select_view = discord.ui.View(timeout=900)
        select_view.add_item(mentionable_select)

        await interaction.response.send_message(
            f"{current_text}Select roles/users that can use **Generate to Channel**:\n" "(Select none to clear and revert to owner-only)",
            view=select_view,
            ephemeral=True,
        )


class ConfigureRunSchedulePermButton(discord.ui.Button):
    """Button to configure run schedule permissions."""

    def __init__(self):
        super().__init__(label="Run Schedule Permissions", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        view: BCPermissionsView = self.view
        cog = view.cog
        guild_id = interaction.guild.id

        # Get current permissions
        perms = cog.get_setting("slash_permissions.run_schedule", guild_id=guild_id) or {}
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

        # Create mentionable select with default values
        mentionable_select = ActionMentionableSelect(cog, "run_schedule", guild_id)
        select_view = discord.ui.View(timeout=900)
        select_view.add_item(mentionable_select)

        await interaction.response.send_message(
            f"{current_text}Select roles/users that can use **Run Schedule**:\n" "(Select none to clear and revert to owner-only)",
            view=select_view,
            ephemeral=True,
        )


class ConfigureManageSchedulesPermButton(discord.ui.Button):
    """Button to configure manage schedules permissions."""

    def __init__(self):
        super().__init__(label="Manage Schedules Permissions", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        view: BCPermissionsView = self.view
        cog = view.cog
        guild_id = interaction.guild.id

        # Get current permissions
        perms = cog.get_setting("slash_permissions.manage_schedules", guild_id=guild_id) or {}
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

        # Create mentionable select with default values
        mentionable_select = ActionMentionableSelect(cog, "manage_schedules", guild_id)
        select_view = discord.ui.View(timeout=900)
        select_view.add_item(mentionable_select)

        await interaction.response.send_message(
            f"{current_text}Select roles/users that can use **Manage Schedules** (Create/Edit/Delete/Pause):\n"
            "(Select none to clear and revert to owner-only)",
            view=select_view,
            ephemeral=True,
        )


class ConfigureChannelsPermButton(discord.ui.Button):
    """Button to configure channel restrictions for actions."""

    def __init__(self):
        super().__init__(label="Channel Restrictions", style=discord.ButtonStyle.secondary, emoji="📍")

    async def callback(self, interaction: discord.Interaction):
        view: BCPermissionsView = self.view
        cog = view.cog
        guild_id = interaction.guild.id

        # Get current channel restrictions for all actions
        generate_perms = cog.get_setting("slash_permissions.generate", guild_id=guild_id) or {}
        run_schedule_perms = cog.get_setting("slash_permissions.run_schedule", guild_id=guild_id) or {}
        manage_schedules_perms = cog.get_setting("slash_permissions.manage_schedules", guild_id=guild_id) or {}

        generate_channels = generate_perms.get("allowed_channels", [])
        run_schedule_channels = run_schedule_perms.get("allowed_channels", [])
        manage_schedules_channels = manage_schedules_perms.get("allowed_channels", [])

        # Build current restrictions display
        restrictions = []
        if generate_channels:
            channel_mentions = [f"<#{cid}>" for cid in generate_channels]
            restrictions.append(f"**Generate to Channel:** {', '.join(channel_mentions)}")
        else:
            restrictions.append("**Generate to Channel:** All channels (default)")

        if run_schedule_channels:
            channel_mentions = [f"<#{cid}>" for cid in run_schedule_channels]
            restrictions.append(f"**Run Schedule:** {', '.join(channel_mentions)}")
        else:
            restrictions.append("**Run Schedule:** All channels (default)")

        if manage_schedules_channels:
            channel_mentions = [f"<#{cid}>" for cid in manage_schedules_channels]
            restrictions.append(f"**Manage Schedules:** {', '.join(channel_mentions)}")
        else:
            restrictions.append("**Manage Schedules:** All channels (default)")

        current_text = "**Current Channel Restrictions:**\n" + "\n".join(restrictions) + "\n\n"

        # Show action selector
        action_view = discord.ui.View(timeout=900)
        action_view.add_item(ChannelRestrictionActionSelect(cog, guild_id))

        await interaction.response.send_message(
            f"{current_text}Select which action to configure channel restrictions for:", view=action_view, ephemeral=True
        )


class ActionMentionableSelect(discord.ui.MentionableSelect):
    """Mentionable select for configuring action permissions (roles and users)."""

    def __init__(self, cog, action_name: str, guild_id: int):
        # Get current permissions to set as defaults
        perms = cog.get_setting(f"slash_permissions.{action_name}", guild_id=guild_id) or {}
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
        self.cog = cog
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
        self.cog.set_slash_action_permission(guild_id, self.action_name, allowed_roles=role_ids, allowed_users=user_ids)

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


class ChannelRestrictionActionSelect(discord.ui.Select):
    """Select menu for choosing which action to configure channel restrictions for."""

    def __init__(self, cog, guild_id: int):
        options = [
            discord.SelectOption(
                label="Generate to Channel", value="generate", description="Restrict where 'Generate to Channel' can be used", emoji="📝"
            ),
            discord.SelectOption(label="Run Schedule", value="run_schedule", description="Restrict where 'Run Schedule' can be used", emoji="🔄"),
            discord.SelectOption(
                label="Manage Schedules", value="manage_schedules", description="Restrict where schedule management can be used", emoji="⚙️"
            ),
        ]

        super().__init__(placeholder="Choose action to restrict...", options=options)
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        action_name = self.values[0]

        # Get current channel restrictions for this action
        perms = self.cog.get_setting(f"slash_permissions.{action_name}", guild_id=self.guild_id) or {}
        current_channels = perms.get("allowed_channels", [])

        # Determine current mode
        if not current_channels:
            current_mode = "all"
        else:
            current_mode = "specific"

        # Show restriction mode selector
        mode_view = discord.ui.View(timeout=900)
        mode_view.add_item(ChannelRestrictionModeSelect(self.cog, action_name, self.guild_id, current_mode, current_channels))

        action_display = action_name.replace("_", " ").title()

        # Show current state in the message
        current_state_text = ""
        if current_mode == "all":
            current_state_text = "**Currently:** Allowed in all channels\n\n"
        elif current_mode == "specific":
            if current_channels:
                channel_mentions = [f"<#{cid}>" for cid in current_channels]
                current_state_text = f"**Currently:** Restricted to {', '.join(channel_mentions)}\n\n"
            else:
                current_state_text = "**Currently:** No channels selected (shouldn't happen)\n\n"
        elif current_mode == "none":
            current_state_text = "**Currently:** Disabled (no channels)\n\n"

        await interaction.response.send_message(
            f"Configure channel restrictions for **{action_display}**:\n\n" f"{current_state_text}" "Choose how to restrict this action:",
            view=mode_view,
            ephemeral=True,
        )


class ChannelRestrictionModeSelect(discord.ui.Select):
    """Select menu for choosing the type of channel restriction."""

    def __init__(self, cog, action_name: str, guild_id: int, current_mode: str, current_channels: list):
        options = [
            discord.SelectOption(label="Allow in all channels", value="all", description="No restrictions - action works everywhere", emoji="🌐"),
            discord.SelectOption(label="Restrict to specific channels", value="specific", description="Choose which channels to allow", emoji="📍"),
            discord.SelectOption(label="Disable (no channels)", value="none", description="Completely disable this action", emoji="🚫"),
        ]

        super().__init__(placeholder="Choose restriction type...", options=options)
        self.cog = cog
        self.action_name = action_name
        self.guild_id = guild_id
        self.current_channels = current_channels
        self.current_mode = current_mode

    async def callback(self, interaction: discord.Interaction):
        selected_mode = self.values[0]
        action_display = self.action_name.replace("_", " ").title()

        if selected_mode == "all":
            # Clear all channel restrictions
            self.cog.set_slash_action_permission(self.guild_id, self.action_name, allowed_channels=[])
            await interaction.response.send_message(f"✅ {action_display} now allowed in **all channels**", ephemeral=True)

        elif selected_mode == "none":
            # Set to empty list to disable (though this might not be the best UX)
            # Actually, let's set allowed_channels to None or remove the setting entirely
            perms = self.cog.get_setting(f"slash_permissions.{self.action_name}", guild_id=self.guild_id) or {}
            if "allowed_channels" in perms:
                del perms["allowed_channels"]
                if perms:
                    self.cog.set_setting(f"slash_permissions.{self.action_name}", perms, guild_id=self.guild_id)
                else:
                    self.cog.remove_setting(f"slash_permissions.{self.action_name}", guild_id=self.guild_id)
            await interaction.response.send_message(f"✅ {action_display} **disabled** (no channels allowed)", ephemeral=True)

        elif selected_mode == "specific":
            # Show channel selector
            channel_view = discord.ui.View(timeout=900)
            channel_view.add_item(ActionChannelSelect(self.cog, self.action_name, self.guild_id, self.current_channels))

            current_text = ""
            if self.current_channels:
                channel_mentions = [f"<#{cid}>" for cid in self.current_channels]
                current_text = f"**Current restrictions:** {', '.join(channel_mentions)}\n\n"
            else:
                current_text = "**No current restrictions**\n\n"

            await interaction.response.send_message(
                f"{current_text}Select channels where **{action_display}** can be used:\n" "(Select none to cancel and keep current settings)",
                view=channel_view,
                ephemeral=True,
            )


class ActionChannelSelect(discord.ui.ChannelSelect):
    """Channel select for configuring action channel restrictions."""

    def __init__(self, cog, action_name: str, guild_id: int, current_channels: list):
        # Set default values from current channels
        default_values = [discord.SelectDefaultValue(id=channel_id, type=discord.SelectDefaultValueType.channel) for channel_id in current_channels]

        super().__init__(
            placeholder="Select channels (leave empty for all)...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.public_thread, discord.ChannelType.private_thread],
            min_values=0,
            max_values=25,
            default_values=default_values if default_values else None,
        )
        self.cog = cog
        self.action_name = action_name
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        selected_channels = [channel.id for channel in self.values]

        # If no channels selected, this was likely a cancel action
        if not selected_channels:
            action_display = self.action_name.replace("_", " ").title()
            await interaction.response.send_message(f"❌ Cancelled - {action_display} channel restrictions unchanged", ephemeral=True)
            return

        # Update permissions
        self.cog.set_slash_action_permission(self.guild_id, self.action_name, allowed_channels=selected_channels)

        # Build response message
        action_display = self.action_name.replace("_", " ").title()
        channel_mentions = [f"<#{cid}>" for cid in selected_channels]
        await interaction.response.send_message(f"✅ {action_display} restricted to: {', '.join(channel_mentions)}", ephemeral=True)
