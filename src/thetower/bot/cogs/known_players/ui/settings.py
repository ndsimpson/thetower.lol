# Third-party
from typing import List

import discord

# Local
from thetower.bot.basecog import BaseCog
from thetower.bot.ui.context import SettingsViewContext


class KnownPlayersSettingsView(discord.ui.View):
    """Settings view for Known Players cog that integrates with global settings."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context
        self.interaction = context.interaction
        self.is_bot_owner = context.is_bot_owner
        self.guild_id = str(context.guild_id) if context.guild_id else None

        # Get current global settings (stored in bot config under known_players)
        known_players_config = self.cog.config.config.get("known_players", {})
        self.results_per_page = known_players_config.get("results_per_page", 5)
        self.cache_refresh_interval = known_players_config.get("cache_refresh_interval", 3600)
        self.cache_save_interval = known_players_config.get("cache_save_interval", 300)
        self.info_max_results = known_players_config.get("info_max_results", 3)
        self.refresh_check_interval = known_players_config.get("refresh_check_interval", 900)
        self.auto_refresh = known_players_config.get("auto_refresh", True)
        self.save_on_update = known_players_config.get("save_on_update", True)
        self.allow_partial_matches = known_players_config.get("allow_partial_matches", True)
        self.case_sensitive = known_players_config.get("case_sensitive", False)
        self.restrict_lookups_to_known_users = known_players_config.get("restrict_lookups_to_known_users", False)

        # Get guild-specific profile_post_channels setting
        if self.guild_id:
            self.profile_post_channels = self.get_setting("profile_post_channels", default=[], guild_id=int(self.guild_id))
        else:
            self.profile_post_channels = []

        # Get privileged groups setting
        self.privileged_groups_for_full_ids = known_players_config.get("privileged_groups_for_full_ids", [])

        # Get moderation display setting
        self.show_moderation_records_in_profiles = known_players_config.get("show_moderation_records_in_profiles", False)

        # Get privileged groups for moderation records
        self.privileged_groups_for_moderation_records = known_players_config.get("privileged_groups_for_moderation_records", [])

        # Add toggle buttons for boolean settings
        self.add_toggle_button("Auto Refresh", "auto_refresh", self.auto_refresh)
        self.add_toggle_button("Save on Update", "save_on_update", self.save_on_update)
        self.add_toggle_button("Allow Partial Matches", "allow_partial_matches", self.allow_partial_matches)
        self.add_toggle_button("Case Sensitive", "case_sensitive", self.case_sensitive)

        # Add security toggle for bot owners
        if self.is_bot_owner:
            self.add_toggle_button("Restrict Lookups", "restrict_lookups_to_known_users", self.restrict_lookups_to_known_users, security=True)
            self.add_toggle_button(
                "Show Moderation Records", "show_moderation_records_in_profiles", self.show_moderation_records_in_profiles, security=True
            )

        # Build options list for numeric settings only
        options = [
            discord.SelectOption(label="Results Per Page", value="results_per_page", description="Number of results shown per page"),
            discord.SelectOption(
                label="Cache Refresh Interval", value="cache_refresh_interval", description="How often to refresh player cache (seconds)"
            ),
            discord.SelectOption(label="Cache Save Interval", value="cache_save_interval", description="How often to save cache to disk (seconds)"),
            discord.SelectOption(label="Max Info Results", value="info_max_results", description="Maximum results for info commands"),
            discord.SelectOption(
                label="Refresh Check Interval", value="refresh_check_interval", description="How often to check if cache needs refresh"
            ),
            discord.SelectOption(
                label="Profile Post Channels", value="profile_post_channels", description="Channels where profiles can be posted publicly"
            ),
            discord.SelectOption(
                label="Privileged Groups for Full IDs",
                value="privileged_groups_for_full_ids",
                description="Django groups that can see all player IDs",
            ),
            discord.SelectOption(
                label="Privileged Groups for Moderation Records",
                value="privileged_groups_for_moderation_records",
                description="Django groups that can see moderation records",
            ),
        ]

        # Create the select for numeric settings
        self.setting_select = discord.ui.Select(
            placeholder="Modify numeric settings",
            options=options,
        )
        self.setting_select.callback = self.setting_select_callback
        self.add_item(self.setting_select)

    def get_setting(self, key: str, default=None, guild_id: int = None):
        """Get a setting value, either global or guild-specific."""
        if guild_id is not None:
            # Guild-specific setting
            guild_config = self.cog.config.config.get("guilds", {}).get(str(guild_id), {}).get("known_players", {})
            return guild_config.get(key, default)
        else:
            # Global setting
            known_players_config = self.cog.config.config.get("known_players", {})
            return known_players_config.get(key, default)

    def set_setting(self, key: str, value, guild_id: int = None):
        """Set a setting value, either global or guild-specific."""
        if guild_id is not None:
            # Guild-specific setting
            guilds_config = self.cog.config.config.setdefault("guilds", {})
            guild_config = guilds_config.setdefault(str(guild_id), {})
            known_players_config = guild_config.setdefault("known_players", {})
            known_players_config[key] = value
        else:
            # Global setting
            known_players_config = self.cog.config.config.setdefault("known_players", {})
            known_players_config[key] = value

        self.cog.config.save_config()

    def add_toggle_button(self, label: str, setting_name: str, current_value: bool, security: bool = False):
        """Add a toggle button for a boolean setting."""
        emoji = "✅" if current_value else "❌"
        style = discord.ButtonStyle.success if current_value else discord.ButtonStyle.secondary
        if security:
            style = discord.ButtonStyle.danger if current_value else discord.ButtonStyle.secondary
            emoji = "🔒" if current_value else "🔓"

        button = discord.ui.Button(label=f"{label}: {'ON' if current_value else 'OFF'}", style=style, emoji=emoji, custom_id=f"toggle_{setting_name}")
        button.callback = self.create_toggle_callback(setting_name, security)
        self.add_item(button)

    def create_toggle_callback(self, setting_name: str, security: bool = False):
        """Create a callback for a toggle button."""

        async def toggle_callback(interaction: discord.Interaction):
            # Check security permission
            if security and not await self.cog.bot.is_owner(interaction.user):
                embed = discord.Embed(
                    title="Permission Denied", description="Only bot owners can modify this security setting.", color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Toggle the setting
            current_value = getattr(self, setting_name)
            new_value = not current_value

            # Save the setting
            known_players_config = self.cog.config.config.setdefault("known_players", {})
            known_players_config[setting_name] = new_value
            self.cog.config.save_config()

            # Update the instance variable
            setattr(self, setting_name, new_value)

            # Update the button
            self.update_toggle_button(setting_name, new_value, security)

            # Update the display
            embed = self.create_settings_embed()
            await interaction.response.edit_message(embed=embed, view=self)

        return toggle_callback

    def update_toggle_button(self, setting_name: str, new_value: bool, security: bool = False):
        """Update a toggle button's appearance."""
        emoji = "✅" if new_value else "❌"
        style = discord.ButtonStyle.success if new_value else discord.ButtonStyle.secondary
        if security:
            style = discord.ButtonStyle.danger if new_value else discord.ButtonStyle.secondary
            emoji = "🔒" if new_value else "🔓"

        # Find and update the button
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id == f"toggle_{setting_name}":
                item.label = f"{setting_name.replace('_', ' ').title()}: {'ON' if new_value else 'OFF'}"
                item.style = style
                item.emoji = emoji
                break

    def create_settings_embed(self) -> discord.Embed:
        """Create the settings embed with current values."""
        embed = discord.Embed(title="⚙️ Known Players Settings", color=discord.Color.blue())

        embed.add_field(
            name="📊 Display Settings",
            value=(f"**Results Per Page:** {self.results_per_page}\n" f"**Max Info Results:** {self.info_max_results}"),
            inline=True,
        )

        embed.add_field(
            name="💾 Cache Settings",
            value=(
                f"**Refresh Interval:** {self.cache_refresh_interval}s\n"
                f"**Save Interval:** {self.cache_save_interval}s\n"
                f"**Check Interval:** {self.refresh_check_interval}s"
            ),
            inline=True,
        )

        embed.add_field(
            name="🔐 Permission Settings",
            value=f"**Privileged Groups for Full IDs:** {len(self.privileged_groups_for_full_ids)} groups configured",
            inline=True,
        )

        behavior_parts = [
            f"**Auto Refresh:** {'✅ ON' if self.auto_refresh else '❌ OFF'}",
            f"**Save on Update:** {'✅ ON' if self.save_on_update else '❌ OFF'}",
            f"**Partial Matches:** {'✅ ON' if self.allow_partial_matches else '❌ OFF'}",
            f"**Case Sensitive:** {'✅ ON' if self.case_sensitive else '❌ OFF'}",
        ]

        if self.is_bot_owner:
            behavior_parts.append(f"**Restrict Lookups:** {'🔒 ON' if self.restrict_lookups_to_known_users else '🔓 OFF'} *(Bot Owner Only)*")
            behavior_parts.append(
                f"**Show Moderation Records:** {'🔒 ON' if self.show_moderation_records_in_profiles else '🔓 OFF'} *(Bot Owner Only)*"
            )

        embed.add_field(
            name="🔧 Behavior Settings",
            value="\n".join(behavior_parts),
            inline=False,
        )

        embed.set_footer(text="Use toggle buttons for quick changes • Use dropdown for numeric settings")
        return embed

    async def setting_select_callback(self, interaction: discord.Interaction):
        """Handle setting selection for numeric settings."""
        setting_name = self.setting_select.values[0]

        # Special handling for profile_post_channels
        if setting_name == "profile_post_channels":
            view = ChannelSelectView(self.cog, interaction, self.profile_post_channels)
            embed = view.create_selection_embed()
            await interaction.response.edit_message(embed=embed, view=view)
            return

        # Special handling for privileged_groups_for_full_ids
        if setting_name == "privileged_groups_for_full_ids":
            view = GroupsSelectView(self.cog, interaction, self.privileged_groups_for_full_ids)
            embed = view.create_selection_embed()
            await interaction.response.edit_message(embed=embed, view=view)
            return

        # Special handling for privileged_groups_for_moderation_records
        if setting_name == "privileged_groups_for_moderation_records":
            view = GroupsSelectView(
                self.cog, interaction, self.privileged_groups_for_moderation_records, setting_key="privileged_groups_for_moderation_records"
            )
            embed = view.create_selection_embed()
            await interaction.response.edit_message(embed=embed, view=view)
            return

        # Create a modal for the selected setting
        modal = SettingModal(self.cog, setting_name, getattr(self, setting_name))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Reset to Defaults", style=discord.ButtonStyle.danger, emoji="🔄")
    async def reset_defaults(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Reset all settings to defaults."""
        # Reset all settings to defaults globally
        defaults = self.cog.default_settings
        known_players_config = self.cog.config.config.setdefault("known_players", {})
        for key, value in defaults.items():
            known_players_config[key] = value
        self.cog.config.save_config()

        embed = discord.Embed(
            title="Settings Reset", description="All Known Players settings have been reset to defaults.", color=discord.Color.orange()
        )
        await interaction.response.edit_message(embed=embed, view=None)


class SettingModal(discord.ui.Modal):
    """Modal for editing individual settings."""

    def __init__(self, cog: BaseCog, setting_name: str, current_value):
        # Create appropriate title and input based on setting type
        if setting_name in [
            "auto_refresh",
            "save_on_update",
            "allow_partial_matches",
            "case_sensitive",
            "restrict_lookups_to_known_users",
            "show_moderation_records_in_profiles",
        ]:
            title = f"Set {setting_name.replace('_', ' ').title()}"
            self.input_type = "boolean"
        elif setting_name in ["results_per_page", "cache_refresh_interval", "cache_save_interval", "info_max_results", "refresh_check_interval"]:
            title = f"Set {setting_name.replace('_', ' ').title()}"
            self.input_type = "integer"
        else:
            title = f"Set {setting_name.replace('_', ' ').title()}"
            self.input_type = "string"

        super().__init__(title=title)

        self.cog = cog
        self.setting_name = setting_name
        self.current_value = current_value

        # Create input field based on type
        if self.input_type == "boolean":
            placeholder = f"Enter 'true' or 'false' (current: {current_value})"
        elif self.input_type == "integer":
            placeholder = f"Enter a number (current: {current_value})"
        else:
            placeholder = f"Enter value (current: {current_value})"

        self.value_input = discord.ui.TextInput(
            label=f"New {setting_name.replace('_', ' ').title()}", placeholder=placeholder, default=str(current_value), required=True, max_length=50
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle setting value submission."""
        new_value_str = self.value_input.value.strip()

        try:
            # Check if this is a bot owner only setting
            if self.setting_name in ["restrict_lookups_to_known_users", "show_moderation_records_in_profiles"]:
                # Check if user is bot owner
                if interaction.user.id not in self.cog.bot.owner_ids:
                    embed = discord.Embed(
                        title="Permission Denied", description="Only bot owners can modify this security setting.", color=discord.Color.red()
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return

            # Convert value based on type
            if self.input_type == "boolean":
                if new_value_str.lower() in ["true", "1", "yes", "on"]:
                    new_value = True
                elif new_value_str.lower() in ["false", "0", "no", "off"]:
                    new_value = False
                else:
                    raise ValueError("Boolean values must be true/false, yes/no, 1/0, or on/off")
            elif self.input_type == "integer":
                new_value = int(new_value_str)
                if new_value < 0:
                    raise ValueError("Integer values must be non-negative")
            else:
                new_value = new_value_str

            # Save the setting globally in bot config
            known_players_config = self.cog.config.config.setdefault("known_players", {})
            known_players_config[self.setting_name] = new_value
            self.cog.config.save_config()

            embed = discord.Embed(
                title="Setting Updated",
                description=f"**{self.setting_name.replace('_', ' ').title()}:** {self.current_value} → {new_value}",
                color=discord.Color.green(),
            )

            # Update the view with new settings
            view = KnownPlayersSettingsView(
                self.cog.SettingsViewContext(
                    guild_id=interaction.guild.id if interaction.guild else None,
                    cog_instance=self.cog,
                    interaction=interaction,
                    is_bot_owner=await self.cog.bot.is_owner(interaction.user),
                )
            )
            await interaction.response.edit_message(embed=embed, view=view)

        except ValueError as e:
            embed = discord.Embed(title="Invalid Value", description=f"Error: {str(e)}", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            embed = discord.Embed(title="Error", description=f"Failed to update setting: {str(e)}", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)


class GroupsSelectView(discord.ui.View):
    """View for managing privileged Django groups for full ID access."""

    def __init__(
        self, cog: BaseCog, interaction: discord.Interaction, current_groups: List[str], setting_key: str = "privileged_groups_for_full_ids"
    ):
        super().__init__(timeout=900)
        self.cog = cog
        self.original_interaction = interaction
        self.current_groups = set(current_groups)
        self.selected_groups = self.current_groups.copy()
        self.setting_key = setting_key
        self.available_groups = []

        # Get available Django groups
        self._load_available_groups()

        # Add remove buttons for current groups (max 4 to fit Discord limits)
        # Note: Individual remove buttons removed in favor of single "Remove Groups" button

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
            description="Select one or more Django groups to add to the privileged groups list.",
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
            description="Select one or more Django groups to remove from the privileged groups list.",
            color=discord.Color.red(),
        )

        await interaction.response.send_message(embed=embed, view=temp_view, ephemeral=True)

    def create_selection_embed(self) -> discord.Embed:
        """Create embed showing current group selection."""
        if self.setting_key == "privileged_groups_for_full_ids":
            title = "🔐 Manage Privileged Groups for Full IDs"
            description = "Configure which Django groups can see all player IDs in lookup commands.\n\n**Current Groups:**"
            no_groups_message = "*No groups selected - only primary IDs will be shown*"
        else:
            title = "🔐 Manage Privileged Groups for Moderation Records"
            description = "Configure which Django groups can see moderation records in profiles.\n\n**Current Groups:**"
            no_groups_message = "*No groups selected - moderation records will be hidden*"

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

        # Save the setting globally in bot config
        known_players_config = self.cog.config.config.setdefault("known_players", {})
        known_players_config[self.setting_key] = new_groups
        self.cog.config.save_config()

        setting_name = (
            "Privileged Groups for Full IDs" if self.setting_key == "privileged_groups_for_full_ids" else "Privileged Groups for Moderation Records"
        )
        description = f"**{setting_name}:** {len(new_groups)} groups configured\n"
        if new_groups:
            description += f"**Groups:** {', '.join(new_groups)}"
        else:
            description += "**No groups configured**"

        embed = discord.Embed(
            title=f"{setting_name} Updated",
            description=description,
            color=discord.Color.green(),
        )

        # Return to the main settings view
        view = KnownPlayersSettingsView(
            self.cog.SettingsViewContext(
                guild_id=interaction.guild.id if interaction.guild else None,
                cog_instance=self.cog,
                interaction=interaction,
                is_bot_owner=await self.cog.bot.is_owner(interaction.user),
            )
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌", row=4)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel and return to main settings."""
        embed = discord.Embed(title="Cancelled", description="Group selection cancelled. No changes were made.", color=discord.Color.orange())

        # Return to the main settings view
        view = KnownPlayersSettingsView(
            self.cog.SettingsViewContext(
                guild_id=interaction.guild.id if interaction.guild else None,
                cog_instance=self.cog,
                interaction=interaction,
                is_bot_owner=await self.cog.bot.is_owner(interaction.user),
            )
        )
        await interaction.response.edit_message(embed=embed, view=view)


class GroupsModal(discord.ui.Modal):
    """Modal for editing privileged Django groups for full ID access."""

    def __init__(self, cog: BaseCog, current_groups: List[str]):
        super().__init__(title="Set Privileged Groups for Full IDs")

        self.cog = cog
        self.current_groups = current_groups

        # Create input field for comma-separated group names
        current_value = ", ".join(current_groups) if current_groups else ""
        self.groups_input = discord.ui.TextInput(
            label="Django Group Names",
            placeholder="Enter group names separated by commas (e.g., admin, moderators, staff)",
            default=current_value,
            required=False,
            max_length=500,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.groups_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle group names submission."""
        try:
            # Parse the input
            groups_str = self.groups_input.value.strip()
            if groups_str:
                # Split by comma and clean up whitespace
                new_groups = [group.strip() for group in groups_str.split(",") if group.strip()]
                # Remove duplicates while preserving order
                new_groups = list(dict.fromkeys(new_groups))
            else:
                new_groups = []

            # Save the setting globally in bot config
            known_players_config = self.cog.config.config.setdefault("known_players", {})
            known_players_config["privileged_groups_for_full_ids"] = new_groups
            self.cog.config.save_config()

            description = f"**Privileged Groups for Full IDs:** {len(new_groups)} groups configured\n"
            if new_groups:
                description += f"**Groups:** {', '.join(new_groups)}"
            else:
                description += "**No groups configured**"

            embed = discord.Embed(
                title="Privileged Groups Updated",
                description=description,
                color=discord.Color.green(),
            )

            # Update the view with new settings
            view = KnownPlayersSettingsView(
                self.cog.SettingsViewContext(
                    guild_id=interaction.guild.id if interaction.guild else None,
                    cog_instance=self.cog,
                    interaction=interaction,
                    is_bot_owner=await self.cog.bot.is_owner(interaction.user),
                )
            )
            await interaction.response.edit_message(embed=embed, view=view)

        except Exception as e:
            embed = discord.Embed(title="Error", description=f"Failed to update privileged groups: {str(e)}", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)


class ChannelSelectView(discord.ui.View):
    """View for selecting multiple channels for profile posting."""

    def __init__(self, cog: BaseCog, interaction: discord.Interaction, current_channels: List[int]):
        super().__init__(timeout=900)
        self.cog = cog
        self.original_interaction = interaction
        self.current_channels = set(current_channels)
        self.selected_channels = self.current_channels.copy()

        # Get available text channels from the guild
        guild = interaction.guild
        if guild:
            text_channels = [channel for channel in guild.channels if isinstance(channel, discord.TextChannel)]
            # Sort channels by position
            text_channels.sort(key=lambda c: c.position)

            # Create options for the select (max 25 options for Discord)
            options = []
            for channel in text_channels[:25]:  # Discord limit
                is_selected = channel.id in self.current_channels
                option = discord.SelectOption(label=f"#{channel.name}", value=str(channel.id), description=f"ID: {channel.id}", default=is_selected)
                options.append(option)

            # Create the multi-select
            self.channel_select = discord.ui.Select(
                placeholder="Select channels for profile posting", options=options, max_values=len(options), min_values=0  # Allow selecting all
            )
            self.channel_select.callback = self.channel_select_callback
            self.add_item(self.channel_select)

    def set_setting(self, key: str, value, guild_id: int = None):
        """Set a setting value, either global or guild-specific."""
        if guild_id is not None:
            # Guild-specific setting
            guilds_config = self.cog.config.config.setdefault("guilds", {})
            guild_config = guilds_config.setdefault(str(guild_id), {})
            known_players_config = guild_config.setdefault("known_players", {})
            known_players_config[key] = value
        else:
            # Global setting
            known_players_config = self.cog.config.config.setdefault("known_players", {})
            known_players_config[key] = value

        self.cog.config.save_config()

    async def channel_select_callback(self, interaction: discord.Interaction):
        """Handle channel selection changes."""
        # Update selected channels based on the current selection
        selected_ids = [int(value) for value in self.channel_select.values]
        self.selected_channels = set(selected_ids)

        # Update the select options to reflect current selection
        for option in self.channel_select.options:
            channel_id = int(option.value)
            option.default = channel_id in self.selected_channels

        # Update the embed to show current selection
        embed = self.create_selection_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    def create_selection_embed(self) -> discord.Embed:
        """Create embed showing current channel selection."""
        embed = discord.Embed(
            title="📢 Select Profile Post Channels",
            description="Choose which channels should allow users to post their profiles publicly.",
            color=discord.Color.blue(),
        )

        if self.selected_channels:
            channel_mentions = []
            for channel_id in sorted(self.selected_channels):
                channel = self.original_interaction.guild.get_channel(channel_id)
                if channel:
                    channel_mentions.append(channel.mention)
                else:
                    channel_mentions.append(f"#{channel_id}")

            embed.add_field(name=f"Selected Channels ({len(self.selected_channels)})", value="\n".join(channel_mentions), inline=False)
        else:
            embed.add_field(name="Selected Channels (0)", value="*No channels selected*", inline=False)

        embed.set_footer(text="Use the dropdown above to select/deselect channels • Click Save when done")
        return embed

    @discord.ui.button(label="Save Changes", style=discord.ButtonStyle.success, emoji="💾")
    async def save_changes(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Save the selected channels."""
        new_channels = sorted(list(self.selected_channels))

        # Save the setting using ConfigManager's proper method
        self.set_setting("profile_post_channels", new_channels, guild_id=interaction.guild.id)

        description = f"**New Channels:** {len(new_channels)} channels configured\n"
        if new_channels:
            description += f"**Channels:** {', '.join(f'<#{ch}>' for ch in new_channels)}"
        else:
            description += "**No channels configured**"

        embed = discord.Embed(
            title="Profile Post Channels Updated",
            description=description,
            color=discord.Color.green(),
        )

        # Return to the main settings view
        view = KnownPlayersSettingsView(
            self.cog.SettingsViewContext(
                guild_id=interaction.guild.id if interaction.guild else None,
                cog_instance=self.cog,
                interaction=interaction,
                is_bot_owner=await self.cog.bot.is_owner(interaction.user),
            )
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel and return to main settings."""
        embed = discord.Embed(title="Cancelled", description="Channel selection cancelled. No changes were made.", color=discord.Color.orange())

        # Return to the main settings view
        view = KnownPlayersSettingsView(
            self.cog.SettingsViewContext(
                guild_id=interaction.guild.id if interaction.guild else None,
                cog_instance=self.cog,
                interaction=interaction,
                is_bot_owner=await self.cog.bot.is_owner(interaction.user),
            )
        )
        await interaction.response.edit_message(embed=embed, view=view)
