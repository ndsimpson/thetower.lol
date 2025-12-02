# Settings interface for the Player Lookup cog

# Third-party
from typing import List

import discord

from thetower.bot.basecog import BaseCog
from thetower.bot.ui.context import SettingsViewContext


class PlayerLookupSettingsView(discord.ui.View):
    """Settings view for Player Lookup cog that integrates with global settings."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)
        self.cog = context.cog_instance
        self.context = context
        self.interaction = context.interaction
        self.is_bot_owner = context.is_bot_owner
        self.guild_id = str(context.guild_id) if context.guild_id else None

        # Get current global settings
        self.results_per_page = self.cog.get_global_setting("results_per_page", 5)
        self.allow_partial_matches = self.cog.get_global_setting("allow_partial_matches", True)
        self.case_sensitive = self.cog.get_global_setting("case_sensitive", False)
        self.restrict_lookups_to_known_users = self.cog.get_global_setting("restrict_lookups_to_known_users", True)

        # Get guild-specific profile_post_channels setting
        if self.guild_id:
            self.profile_post_channels = self.cog.get_setting("profile_post_channels", default=[], guild_id=int(self.guild_id))
        else:
            self.profile_post_channels = []

        # Add toggle buttons for boolean settings
        self.add_toggle_button("Allow Partial Matches", "allow_partial_matches", self.allow_partial_matches)
        self.add_toggle_button("Case Sensitive", "case_sensitive", self.case_sensitive)

        # Add security toggle for bot owners
        if self.is_bot_owner:
            self.add_toggle_button("Restrict Lookups", "restrict_lookups_to_known_users", self.restrict_lookups_to_known_users)

        # Build options list for numeric settings only
        options = [
            discord.SelectOption(label="Results Per Page", value="results_per_page", description="Number of results shown per page"),
            discord.SelectOption(
                label="Profile Post Channels", value="profile_post_channels", description="Channels where profiles can be posted publicly"
            ),
        ]

        # Create the select for numeric settings
        self.setting_select = discord.ui.Select(
            placeholder="Modify settings",
            options=options,
        )
        self.setting_select.callback = self.setting_select_callback
        self.add_item(self.setting_select)

    def get_setting(self, key: str, default=None):
        """Get a global setting value."""
        return self.cog.get_global_setting(key, default)

    def set_setting(self, key: str, value):
        """Set a global setting value."""
        self.cog.set_global_setting(key, value)

    def add_toggle_button(self, label: str, setting_name: str, current_value: bool):
        """Add a toggle button for a boolean setting."""
        emoji = "✅" if current_value else "❌"
        style = discord.ButtonStyle.success if current_value else discord.ButtonStyle.secondary

        button = discord.ui.Button(label=f"{label}: {'ON' if current_value else 'OFF'}", style=style, emoji=emoji, custom_id=f"toggle_{setting_name}")
        button.callback = self.create_toggle_callback(setting_name)
        self.add_item(button)

    def create_toggle_callback(self, setting_name: str):
        """Create a callback for a toggle button."""

        async def toggle_callback(interaction: discord.Interaction):
            # Toggle the setting
            current_value = getattr(self, setting_name)
            new_value = not current_value

            # Save the setting
            self.set_setting(setting_name, new_value)

            # Update the instance variable
            setattr(self, setting_name, new_value)

            # Update the button
            self.update_toggle_button(setting_name, new_value)

            # Update the display
            embed = self.create_settings_embed()
            await interaction.response.edit_message(embed=embed, view=self)

        return toggle_callback

    def update_toggle_button(self, setting_name: str, new_value: bool):
        """Update a toggle button's appearance."""
        emoji = "✅" if new_value else "❌"
        style = discord.ButtonStyle.success if new_value else discord.ButtonStyle.secondary

        # Find and update the button
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id == f"toggle_{setting_name}":
                item.label = f"{setting_name.replace('_', ' ').title()}: {'ON' if new_value else 'OFF'}"
                item.style = style
                item.emoji = emoji
                break

    def create_settings_embed(self) -> discord.Embed:
        """Create the settings embed with current values."""
        embed = discord.Embed(title="🔍 Player Lookup Settings", color=discord.Color.blue())

        embed.add_field(
            name="📊 Display Settings",
            value=f"**Results Per Page:** {self.results_per_page}",
            inline=True,
        )

        embed.add_field(
            name="🔧 Search Settings",
            value=(
                f"**Allow Partial Matches:** {'✅ ON' if self.allow_partial_matches else '❌ OFF'}\n"
                f"**Case Sensitive:** {'✅ ON' if self.case_sensitive else '❌ OFF'}"
            ),
            inline=True,
        )

        embed.add_field(
            name="📢 Profile Posting",
            value=f"**Allowed Channels:** {len(self.profile_post_channels)} channels configured",
            inline=True,
        )

        behavior_parts = []
        if self.is_bot_owner:
            behavior_parts.append(f"**Restrict Lookups:** {'🔒 ON' if self.restrict_lookups_to_known_users else '🔓 OFF'} *(Bot Owner Only)*")

        if behavior_parts:
            embed.add_field(
                name="🔧 Behavior Settings",
                value="\n".join(behavior_parts),
                inline=False,
            )

        embed.set_footer(text="Moderation permissions are configured in the Manage Sus cog")
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

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️")
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Return to cog management."""
        embed = discord.Embed(
            title="Returned to Cog Management",
            description="Use the cog management interface to select another cog or return to the main menu.",
            color=discord.Color.blue(),
        )
        await interaction.response.edit_message(embed=embed, view=None)


class SettingModal(discord.ui.Modal):
    """Modal for editing individual settings."""

    def __init__(self, cog: BaseCog, setting_name: str, current_value):
        # Create appropriate title and input based on setting type
        if setting_name in ["allow_partial_matches", "case_sensitive", "restrict_lookups_to_known_users"]:
            title = f"Set {setting_name.replace('_', ' ').title()}"
            self.input_type = "boolean"
        elif setting_name in ["results_per_page"]:
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
            if self.setting_name in ["restrict_lookups_to_known_users"]:
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
                if new_value < 1:
                    raise ValueError("Results per page must be at least 1")
            else:
                new_value = new_value_str

            # Save the setting globally
            self.cog.set_global_setting(self.setting_name, new_value)

            embed = discord.Embed(
                title="Setting Updated",
                description=f"**{self.setting_name.replace('_', ' ').title()}:** {self.current_value} → {new_value}",
                color=discord.Color.green(),
            )

            # Update the view with new settings
            view = PlayerLookupSettingsView(
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
            await interaction.response.send_message(embed=embed, ephemeral=True)


class ChannelSelectView(discord.ui.View):
    """View for managing channels for profile posting."""

    def __init__(self, cog: BaseCog, interaction: discord.Interaction, current_channels: List[int]):
        super().__init__(timeout=900)
        self.cog = cog
        self.original_interaction = interaction
        self.current_channels = list(current_channels)
        self.guild_id = interaction.guild.id if interaction.guild else None

    def create_selection_embed(self) -> discord.Embed:
        """Create embed showing current channel configuration."""
        embed = discord.Embed(
            title="📢 Manage Profile Post Channels",
            description="Configure which channels allow users to post their profiles publicly.",
            color=discord.Color.blue(),
        )

        if self.current_channels:
            channel_list = []
            for channel_id in sorted(self.current_channels):
                channel = self.original_interaction.guild.get_channel(channel_id)
                if channel:
                    channel_list.append(f"• {channel.mention} (ID: {channel_id})")
                else:
                    channel_list.append(f"• Unknown Channel (ID: {channel_id})")

            embed.add_field(name=f"Configured Channels ({len(self.current_channels)})", value="\n".join(channel_list), inline=False)
        else:
            embed.add_field(name="Configured Channels (0)", value="*No channels configured*\nUse **Add Channel** to add channels.", inline=False)

        embed.set_footer(text="Use the buttons below to add or remove channels")
        return embed

    @discord.ui.button(label="Add Channel", style=discord.ButtonStyle.success, emoji="➕")
    async def add_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Add a channel to the list."""
        modal = AddChannelModal(self.cog, self.guild_id, self.current_channels, self, self.original_interaction)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Remove Channel", style=discord.ButtonStyle.danger, emoji="➖")
    async def remove_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Remove a channel from the list."""
        if not self.current_channels:
            await interaction.response.send_message("❌ No channels to remove.", ephemeral=True)
            return

        modal = RemoveChannelModal(self.cog, self.guild_id, self.current_channels, self, self.original_interaction)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️")
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Return to main settings."""
        from thetower.bot.ui.context import SettingsViewContext

        context = SettingsViewContext(
            guild_id=self.guild_id,
            cog_instance=self.cog,
            interaction=interaction,
            is_bot_owner=await self.cog.bot.is_owner(interaction.user),
        )
        view = PlayerLookupSettingsView(context)
        embed = view.create_settings_embed()
        await interaction.response.edit_message(embed=embed, view=view)


class AddChannelModal(discord.ui.Modal, title="Add Profile Post Channel"):
    """Modal for adding a channel to profile post list."""

    channel_input = discord.ui.TextInput(
        label="Channel Name or ID",
        placeholder="Enter channel name or ID",
        required=True,
        max_length=100,
    )

    def __init__(self, cog, guild_id: int, current_channels: List[int], parent_view, original_interaction):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.current_channels = current_channels
        self.parent_view = parent_view
        self.original_interaction = original_interaction

    async def on_submit(self, interaction: discord.Interaction):
        """Handle the modal submission."""
        guild = interaction.guild
        input_value = self.channel_input.value.strip()

        # Try to find the channel
        channel = None

        # First, try as channel ID
        if input_value.isdigit():
            channel = guild.get_channel(int(input_value))

        # If not found, try by name (case-insensitive, with or without #)
        if not channel:
            channel_name = input_value.lstrip("#")
            channel = discord.utils.get(guild.text_channels, name=channel_name)

        # If still not found, try partial match
        if not channel:
            channel_name = input_value.lstrip("#").lower()
            matching_channels = [c for c in guild.text_channels if channel_name in c.name.lower()]
            if len(matching_channels) == 1:
                channel = matching_channels[0]
            elif len(matching_channels) > 1:
                channel_names = ", ".join([f"`#{c.name}`" for c in matching_channels[:5]])
                more = f" and {len(matching_channels) - 5} more" if len(matching_channels) > 5 else ""
                await interaction.response.send_message(
                    f"❌ Multiple channels match '{input_value}': {channel_names}{more}\n" f"Please be more specific or use the channel ID.",
                    ephemeral=True,
                )
                return

        # Validate the channel
        if not channel:
            await interaction.response.send_message(
                f"❌ Could not find channel '{input_value}'\n" f"Please enter a valid channel name or ID.",
                ephemeral=True,
            )
            return

        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("❌ Channel must be a text channel", ephemeral=True)
            return

        # Check if already added
        if channel.id in self.current_channels:
            await interaction.response.send_message(f"❌ {channel.mention} is already in the list", ephemeral=True)
            return

        # Add the channel
        self.current_channels.append(channel.id)
        self.cog.set_setting("profile_post_channels", self.current_channels, guild_id=self.guild_id)

        await interaction.response.send_message(f"✅ Added {channel.mention} to profile post channels", ephemeral=True)

        # Update the embed
        embed = self.parent_view.create_selection_embed()
        await self.original_interaction.edit_original_response(embed=embed, view=self.parent_view)


class RemoveChannelModal(discord.ui.Modal, title="Remove Profile Post Channel"):
    """Modal for removing a channel from profile post list."""

    channel_input = discord.ui.TextInput(
        label="Channel Name or ID",
        placeholder="Enter channel name or ID to remove",
        required=True,
        max_length=100,
    )

    def __init__(self, cog, guild_id: int, current_channels: List[int], parent_view, original_interaction):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.current_channels = current_channels
        self.parent_view = parent_view
        self.original_interaction = original_interaction

    async def on_submit(self, interaction: discord.Interaction):
        """Handle the modal submission."""
        guild = interaction.guild
        input_value = self.channel_input.value.strip()

        # Try to find the channel
        channel = None

        # First, try as channel ID
        if input_value.isdigit():
            channel_id = int(input_value)
            if channel_id in self.current_channels:
                channel = guild.get_channel(channel_id)
                if not channel:
                    # Channel exists in list but not in guild anymore
                    self.current_channels.remove(channel_id)
                    self.cog.set_setting("profile_post_channels", self.current_channels, guild_id=self.guild_id)
                    await interaction.response.send_message(f"✅ Removed channel (ID: {channel_id}) from profile post channels", ephemeral=True)
                    embed = self.parent_view.create_selection_embed()
                    await self.original_interaction.edit_original_response(embed=embed, view=self.parent_view)
                    return

        # If not found by ID, try by name (case-insensitive, with or without #)
        if not channel:
            channel_name = input_value.lstrip("#")
            # Find among current channels only
            for channel_id in self.current_channels:
                ch = guild.get_channel(channel_id)
                if ch and ch.name.lower() == channel_name.lower():
                    channel = ch
                    break

        # If still not found, try partial match among current channels
        if not channel:
            channel_name = input_value.lstrip("#").lower()
            matching_channels = []
            for channel_id in self.current_channels:
                ch = guild.get_channel(channel_id)
                if ch and channel_name in ch.name.lower():
                    matching_channels.append(ch)

            if len(matching_channels) == 1:
                channel = matching_channels[0]
            elif len(matching_channels) > 1:
                channel_names = ", ".join([f"`#{c.name}`" for c in matching_channels[:5]])
                more = f" and {len(matching_channels) - 5} more" if len(matching_channels) > 5 else ""
                await interaction.response.send_message(
                    f"❌ Multiple channels match '{input_value}': {channel_names}{more}\n" f"Please be more specific or use the channel ID.",
                    ephemeral=True,
                )
                return

        # Validate the channel
        if not channel:
            await interaction.response.send_message(
                f"❌ Could not find channel '{input_value}' in the configured list\n" f"Please enter a valid channel name or ID from the list above.",
                ephemeral=True,
            )
            return

        # Check if in list
        if channel.id not in self.current_channels:
            await interaction.response.send_message(f"❌ {channel.mention} is not in the list", ephemeral=True)
            return

        # Remove the channel
        self.current_channels.remove(channel.id)
        self.cog.set_setting("profile_post_channels", self.current_channels, guild_id=self.guild_id)

        await interaction.response.send_message(f"✅ Removed {channel.mention} from profile post channels", ephemeral=True)

        # Update the embed
        embed = self.parent_view.create_selection_embed()
        await self.original_interaction.edit_original_response(embed=embed, view=self.parent_view)
