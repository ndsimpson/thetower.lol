"""User-facing interaction flows for Battle Conditions cog."""

import discord

from .core import TOWERBCS_AVAILABLE, BattleConditionsCore

# === User Interface Components ===


class BCManagementView(discord.ui.View):
    """Main view for battle conditions management."""

    def __init__(self, cog, can_generate: bool, can_run_schedule: bool, is_owner: bool):
        super().__init__(timeout=900)
        self.cog = cog

        # Always add View button (anyone can view)
        self.add_item(ViewBCButton())

        # Add Generate button if user has permission
        if can_generate:
            self.add_item(GenerateBCButton())

        # Add Run Schedule button if user has permission
        if can_run_schedule:
            self.add_item(ResendBCButton())
            self.add_item(RunAllSchedulesButton())

        # Add Settings button for owners only
        if is_owner:
            self.add_item(SettingsBCButton())


class ViewBCButton(discord.ui.Button):
    """Button to view current battle conditions."""

    def __init__(self):
        super().__init__(label="View BCs", style=discord.ButtonStyle.primary, emoji="👁️")

    async def callback(self, interaction: discord.Interaction):
        view: BCManagementView = self.view
        cog = view.cog

        if not TOWERBCS_AVAILABLE:
            await interaction.response.send_message("⚠️ Battle conditions package not available.", ephemeral=True)
            return

        # Get tournament info
        tourney_id, tourney_date, days_until = BattleConditionsCore.get_tournament_info()

        # Check if bot owner
        is_bot_owner = await cog.bot.is_owner(interaction.user)

        # Check viewing window (global setting, not per-guild)
        view_window_days = cog.get_global_setting("bc_view_window_days")
        if view_window_days is None:
            view_window_days = cog.guild_settings.get("bc_view_window_days")

        # Check if outside viewing window
        outside_window = False
        if view_window_days is not None and days_until > view_window_days:
            outside_window = True
            if not is_bot_owner:
                await interaction.response.send_message(
                    f"⏰ Battle conditions are not yet available.\n"
                    f"You can view them {view_window_days} day(s) before the tournament.\n"
                    f"Next tournament: {tourney_date} ({days_until} days away)",
                    ephemeral=True,
                )
                return

        # Get enabled leagues (global setting)
        enabled_leagues = cog.get_global_setting("enabled_leagues") or []

        if not enabled_leagues:
            await interaction.response.send_message("No leagues enabled. Use settings to configure.", ephemeral=True)
            return

        # Show league selection dropdown
        select_view = discord.ui.View(timeout=900)
        select_view.add_item(ViewLeagueSelect(cog, enabled_leagues, tourney_date, outside_window))

        warning_msg = ""
        if outside_window and is_bot_owner:
            warning_msg = f"⚠️ **Outside viewing window** (window: {view_window_days} days, current: {days_until} days)\n\n"

        await interaction.response.send_message(f"{warning_msg}Select a league to view battle conditions:", view=select_view, ephemeral=True)


class ViewLeagueSelect(discord.ui.Select):
    """Select menu for choosing which league BCs to view."""

    def __init__(self, cog, enabled_leagues: list, tourney_date: str, outside_window: bool = False):
        options = [discord.SelectOption(label=league, value=league, emoji="🏆") for league in enabled_leagues]

        # Add "All Leagues" option at the top
        options.insert(0, discord.SelectOption(label="All Leagues", value="__all__", emoji="🌟"))

        super().__init__(placeholder="Choose a league...", min_values=1, max_values=1, options=options)
        self.cog = cog
        self.enabled_leagues = enabled_leagues
        self.tourney_date = tourney_date
        self.outside_window = outside_window

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]

        # Defer as this might take a moment
        await interaction.response.defer(ephemeral=True)

        if selected == "__all__":
            # Show all enabled leagues
            embeds = []
            for league in self.enabled_leagues:
                conditions = await BattleConditionsCore.get_battle_conditions(league)

                embed = discord.Embed(
                    title=f"{league} League Battle Conditions", description=f"Tournament on {self.tourney_date}", color=discord.Color.gold()
                )

                bc_text = "\n".join([f"• {bc}" for bc in conditions])
                embed.add_field(name="Predicted Battle Conditions", value=bc_text, inline=False)
                embeds.append(embed)

            # Send up to 10 embeds (Discord limit)
            await interaction.followup.send(embeds=embeds[:10], ephemeral=True)
        else:
            # Show single league
            conditions = await BattleConditionsCore.get_battle_conditions(selected)

            embed = discord.Embed(
                title=f"{selected} League Battle Conditions", description=f"Tournament on {self.tourney_date}", color=discord.Color.gold()
            )

            bc_text = "\n".join([f"• {bc}" for bc in conditions])
            embed.add_field(name="Predicted Battle Conditions", value=bc_text, inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)


class GenerateBCButton(discord.ui.Button):
    """Button to generate battle conditions to current channel."""

    def __init__(self):
        super().__init__(label="Generate to Channel", style=discord.ButtonStyle.success, emoji="📝")

    async def callback(self, interaction: discord.Interaction):
        view: BCManagementView = self.view
        cog = view.cog

        # Check channel permission
        if not await cog.check_slash_channel_permission(interaction, "generate"):
            await interaction.response.send_message("❌ You cannot use generate in this channel.", ephemeral=True)
            return

        if not TOWERBCS_AVAILABLE:
            await interaction.response.send_message("⚠️ Battle conditions package not available.", ephemeral=True)
            return

        # Get enabled leagues (global setting)
        enabled_leagues = cog.get_global_setting("enabled_leagues") or []

        if not enabled_leagues:
            await interaction.response.send_message("No leagues enabled. Use settings to configure.", ephemeral=True)
            return

        # Show league selection dropdown
        select_view = discord.ui.View(timeout=900)
        select_view.add_item(GenerateLeagueSelect(cog, enabled_leagues, interaction.channel))

        await interaction.response.send_message("Select which leagues to generate battle conditions for:", view=select_view, ephemeral=True)


class GenerateLeagueSelect(discord.ui.Select):
    """Select menu for choosing which leagues to generate BCs for."""

    def __init__(self, cog, enabled_leagues: list, channel: discord.TextChannel):
        options = [discord.SelectOption(label=league, value=league, emoji="🏆") for league in enabled_leagues]

        # Add "All Leagues" option at the top
        options.insert(0, discord.SelectOption(label="All Leagues", value="__all__", emoji="🌟"))

        super().__init__(placeholder="Choose league(s) to generate...", min_values=1, max_values=len(options), options=options)
        self.cog = cog
        self.enabled_leagues = enabled_leagues
        self.channel = channel

    async def callback(self, interaction: discord.Interaction):
        selected_values = self.values

        # Handle "All Leagues" selection
        if "__all__" in selected_values:
            selected_leagues = self.enabled_leagues
        else:
            selected_leagues = selected_values

        # Defer as this might take a moment
        await interaction.response.defer(ephemeral=True)

        # Get tournament info
        tourney_id, tourney_date, days_until = BattleConditionsCore.get_tournament_info()

        # Send BCs to channel
        sent_count = 0
        for league in selected_leagues:
            conditions = await BattleConditionsCore.get_battle_conditions(league)
            success = await BattleConditionsCore.send_battle_conditions_embed(self.channel, league, tourney_date, conditions)
            if success:
                sent_count += 1

        # Confirm to user
        league_text = "all leagues" if "__all__" in selected_values else f"{len(selected_leagues)} league(s)"
        await interaction.followup.send(f"✅ Generated battle conditions for {league_text} in {self.channel.mention}", ephemeral=True)


class ResendBCButton(discord.ui.Button):
    """Button to trigger existing schedules."""

    def __init__(self):
        super().__init__(label="Run Schedule", style=discord.ButtonStyle.secondary, emoji="🔄")

    async def callback(self, interaction: discord.Interaction):
        view: BCManagementView = self.view
        cog = view.cog
        guild_id = interaction.guild.id

        if not TOWERBCS_AVAILABLE:
            await interaction.response.send_message("⚠️ Battle conditions package not available.", ephemeral=True)
            return

        # Get all schedules for this guild
        destination_schedules = cog.get_setting("destination_schedules", guild_id=guild_id)
        if not destination_schedules:
            destination_schedules = []

        if not destination_schedules:
            await interaction.response.send_message(
                "❌ No schedules configured for this server.\n" "Use Settings → Manage Schedules to create one.", ephemeral=True
            )
            return

        # Show schedule selection dropdown
        select_view = discord.ui.View(timeout=900)
        select_view.add_item(ScheduleSelect(cog, destination_schedules, guild_id))

        await interaction.response.send_message("Select a schedule to run immediately:", view=select_view, ephemeral=True)


class RunAllSchedulesButton(discord.ui.Button):
    """Button to trigger all schedules in the guild."""

    def __init__(self):
        super().__init__(label="Run All Schedules", style=discord.ButtonStyle.secondary, emoji="🚀")

    async def callback(self, interaction: discord.Interaction):
        view: BCManagementView = self.view
        cog = view.cog
        guild_id = interaction.guild.id

        if not TOWERBCS_AVAILABLE:
            await interaction.response.send_message("⚠️ Battle conditions package not available.", ephemeral=True)
            return

        # Get all schedules for this guild
        destination_schedules = cog.get_setting("destination_schedules", guild_id=guild_id)
        if not destination_schedules:
            destination_schedules = []

        if not destination_schedules:
            await interaction.response.send_message(
                "❌ No schedules configured for this server.\n" "Use Settings → Manage Schedules to create one.", ephemeral=True
            )
            return

        # Defer as this might take a moment
        await interaction.response.defer(ephemeral=True)

        # Get tournament info
        tourney_id, tourney_date, days_until = BattleConditionsCore.get_tournament_info()

        # Get enabled leagues (global setting)
        enabled_leagues = cog.get_global_setting("enabled_leagues") or []

        # Process all schedules
        total_sent = 0
        schedule_count = 0
        for schedule in destination_schedules:
            schedule_count += 1
            destination_id = schedule.get("destination_id")
            leagues = schedule.get("leagues", [])
            paused = schedule.get("paused", False)

            # Skip paused schedules
            if paused:
                continue

            # Get channel
            channel = cog.bot.get_channel(int(destination_id))
            if not channel:
                cog.logger.warning(f"Could not find destination with ID {destination_id}")
                continue

            # Verify channel is in the correct guild
            if channel.guild.id != guild_id:
                cog.logger.warning(f"Channel {destination_id} guild mismatch: expected {guild_id}, got {channel.guild.id}")
                continue

            # Send BCs to channel
            sent_count = 0
            for league in leagues:
                # Skip leagues that aren't enabled
                if league not in enabled_leagues:
                    continue

                try:
                    conditions = await BattleConditionsCore.get_battle_conditions(league)
                    success = await BattleConditionsCore.send_battle_conditions_embed(channel, league, tourney_date, conditions)
                    if success:
                        sent_count += 1
                        total_sent += 1
                except Exception as e:
                    cog.logger.error(f"Error sending BC for {league}: {e}")

            cog.logger.info(f"Processed schedule for {channel.name}: sent {sent_count} league(s)")

        # Confirm to user
        await interaction.followup.send(
            f"✅ Processed {schedule_count} schedule(s), sent battle conditions for {total_sent} league(s) total.", ephemeral=True
        )


class ScheduleSelect(discord.ui.Select):
    """Select menu for choosing which schedule to run."""

    def __init__(self, cog, schedules: list, guild_id: int):
        # Build options from schedules
        options = []
        for idx, schedule in enumerate(schedules):
            destination_id = schedule.get("destination_id", "Unknown")
            leagues = schedule.get("leagues", [])
            paused = schedule.get("paused", False)

            # Get channel name if possible
            channel = cog.bot.get_channel(int(destination_id))
            channel_name = channel.name if channel else f"ID: {destination_id}"

            label = f"#{idx}: {channel_name}"
            description = f"Leagues: {', '.join(leagues[:3])}" + ("..." if len(leagues) > 3 else "")
            if paused:
                description = "⏸️ PAUSED - " + description

            options.append(
                discord.SelectOption(label=label[:100], value=str(idx), description=description[:100], emoji="⏸️" if paused else "📅")  # Discord limit
            )

        super().__init__(placeholder="Choose a schedule to run...", min_values=1, max_values=1, options=options)
        self.cog = cog
        self.schedules = schedules
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        selected_idx = int(self.values[0])
        schedule = self.schedules[selected_idx]

        # Defer as this might take a moment
        await interaction.response.defer(ephemeral=True)

        # Get tournament info
        tourney_id, tourney_date, days_until = BattleConditionsCore.get_tournament_info()

        # Get schedule details
        destination_id = schedule.get("destination_id")
        leagues = schedule.get("leagues", [])
        paused = schedule.get("paused", False)

        # Get channel
        channel = self.cog.bot.get_channel(int(destination_id))
        if not channel:
            await interaction.followup.send(f"❌ Channel with ID {destination_id} not found. It may have been deleted.", ephemeral=True)
            return

        # Verify channel is in the correct guild
        if channel.guild.id != self.guild_id:
            await interaction.followup.send(f"❌ Channel {channel.mention} is not in this server.", ephemeral=True)
            return

        # Get enabled leagues (global setting)
        enabled_leagues = self.cog.get_global_setting("enabled_leagues") or []

        # Send BCs to channel
        sent_count = 0
        for league in leagues:
            # Skip leagues that aren't enabled
            if league not in enabled_leagues:
                continue

            try:
                conditions = await BattleConditionsCore.get_battle_conditions(league)
                success = await BattleConditionsCore.send_battle_conditions_embed(channel, league, tourney_date, conditions)
                if success:
                    sent_count += 1
            except Exception as e:
                self.cog.logger.error(f"Error sending BC for {league}: {e}")

        # Confirm to user
        paused_note = " (⚠️ Note: This schedule is paused)" if paused else ""
        await interaction.followup.send(f"✅ Sent battle conditions for {sent_count} league(s) to {channel.mention}{paused_note}", ephemeral=True)


class SettingsBCButton(discord.ui.Button):
    """Button to manage BC settings (owner only)."""

    def __init__(self):
        super().__init__(label="Settings", style=discord.ButtonStyle.secondary, emoji="⚙️")

    async def callback(self, interaction: discord.Interaction):
        view: BCManagementView = self.view
        cog = view.cog

        # Check if bot owner
        is_bot_owner = await cog.bot.is_owner(interaction.user)

        # Show settings view
        from .admin import BCSettingsView

        settings_view = BCSettingsView(cog, is_bot_owner)

        enabled_leagues = cog.get_global_setting("enabled_leagues") or []

        settings_text = (
            f"**Current Settings**\n\n" f"**Enabled Leagues:** {', '.join(enabled_leagues)}\n\n" f"Use the buttons below to configure settings."
        )

        await interaction.response.send_message(settings_text, view=settings_view, ephemeral=True)


class ScheduleLeagueSelect(discord.ui.Select):
    """Select menu for choosing leagues for the schedule."""

    def __init__(self, cog, guild_id: int, channel_id: int, hour: int, minute: int, days_before: int):
        from .core import ALL_LEAGUES

        options = [discord.SelectOption(label=league, value=league, emoji="🏆") for league in ALL_LEAGUES]

        super().__init__(placeholder="Select leagues (choose one or more)...", min_values=1, max_values=len(ALL_LEAGUES), options=options)
        self.cog = cog
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.hour = hour
        self.minute = minute
        self.days_before = days_before

    async def callback(self, interaction: discord.Interaction):
        selected_leagues = self.values

        # Create the schedule
        schedules = self.cog.get_setting("destination_schedules", guild_id=self.guild_id) or []
        schedules.append(
            {
                "destination_id": str(self.channel_id),
                "destination_type": "channel",
                "guild_id": self.guild_id,
                "leagues": selected_leagues,
                "hour": self.hour,
                "minute": self.minute,
                "days_before": self.days_before,
                "paused": False,
            }
        )

        self.cog.set_setting("destination_schedules", schedules, guild_id=self.guild_id)
        self.cog.mark_data_modified()

        channel = interaction.guild.get_channel(self.channel_id)
        channel_mention = channel.mention if channel else f"<#{self.channel_id}>"

        await interaction.response.send_message(
            f"✅ **Schedule Created!**\n\n"
            f"📍 Channel: {channel_mention}\n"
            f"⏰ Time: {self.hour:02d}:{self.minute:02d} UTC\n"
            f"📅 When: {self.days_before} day(s) before tournament\n"
            f"🏆 Leagues: {', '.join(selected_leagues)}",
            ephemeral=True,
        )
