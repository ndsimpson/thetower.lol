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

        # Add toggle buttons for boolean settings
        self.add_toggle_button("Auto Refresh", "auto_refresh", self.auto_refresh)
        self.add_toggle_button("Save on Update", "save_on_update", self.save_on_update)
        self.add_toggle_button("Allow Partial Matches", "allow_partial_matches", self.allow_partial_matches)
        self.add_toggle_button("Case Sensitive", "case_sensitive", self.case_sensitive)

        # Add security toggle for bot owners
        if self.is_bot_owner:
            self.add_toggle_button("Restrict Lookups", "restrict_lookups_to_known_users", self.restrict_lookups_to_known_users, security=True)

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
            name="📢 Profile Posting",
            value=f"**Allowed Channels:** {len(self.profile_post_channels)} channels configured",
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
        if setting_name in ["auto_refresh", "save_on_update", "allow_partial_matches", "case_sensitive", "restrict_lookups_to_known_users"]:
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
            if self.setting_name == "restrict_lookups_to_known_users":
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
