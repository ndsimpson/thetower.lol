# Standard library imports
from typing import Optional

import discord
from discord import ui
from discord.ui import Button, View

# Local imports
# Note: This will be imported by bot.py, so we need to be careful about circular imports
from thetower.bot.ui.context import SettingsViewContext


class SettingsMainView(View):
    """Main settings view that branches based on user permissions."""

    def __init__(self, is_bot_owner: bool, guild_id: Optional[int] = None):
        super().__init__(timeout=900)  # 15 minute timeout
        self.is_bot_owner = is_bot_owner
        self.guild_id = guild_id

        # Add appropriate buttons based on permissions
        if is_bot_owner:
            # Bot owner gets full access
            bot_settings_btn = Button(label="Bot Settings", style=discord.ButtonStyle.primary, emoji="🤖", custom_id="bot_settings")
            bot_settings_btn.callback = self.show_bot_settings
            self.add_item(bot_settings_btn)

            if guild_id:
                # Bot owner can also manage guild settings
                guild_settings_btn = Button(label="Server Settings", style=discord.ButtonStyle.secondary, emoji="🏰", custom_id="guild_settings")
                guild_settings_btn.callback = self.show_guild_settings
                self.add_item(guild_settings_btn)
        else:
            # Guild owner gets guild-specific settings
            if guild_id:
                guild_settings_btn = Button(label="Server Settings", style=discord.ButtonStyle.primary, emoji="🏰", custom_id="guild_settings")
                guild_settings_btn.callback = self.show_guild_settings
                self.add_item(guild_settings_btn)

    async def show_bot_settings(self, interaction: discord.Interaction):
        """Show bot-wide settings for bot owner."""
        # Import here to avoid circular imports
        bot = interaction.client

        embed = discord.Embed(title="🤖 Bot Settings", description="Global bot configuration", color=discord.Color.blue())

        # Basic bot info
        embed.add_field(
            name="Bot Information", value=f"**Name:** {bot.user.name}\n**ID:** {bot.user.id}\n**Servers:** {len(bot.guilds)}", inline=False
        )

        # Configuration settings
        default_prefixes = bot.config.get("prefixes", [])
        prefix_display = ", ".join([f"`{p}`" for p in default_prefixes]) if default_prefixes else "None configured"
        error_channel_id = bot.config.get("error_log_channel", None)
        error_channel = bot.get_channel(int(error_channel_id)) if error_channel_id else None

        config_info = [
            f"**Default Prefixes:** {prefix_display}",
            f"**Error Log Channel:** {error_channel.mention if error_channel else 'Not set'}",
            f"**Load All Cogs:** {'Yes' if bot.config.get('load_all_cogs', False) else 'No'}",
        ]
        embed.add_field(name="Configuration", value="\n".join(config_info), inline=False)

        # Create bot settings view
        view = BotOwnerSettingsView()

        await interaction.response.edit_message(embed=embed, view=view)

    async def show_guild_settings(self, interaction: discord.Interaction):
        """Show guild-specific settings."""
        if not self.guild_id:
            await interaction.response.send_message("❌ Guild context not available.", ephemeral=True)
            return

        # Import here to avoid circular imports
        bot = interaction.client
        guild = bot.get_guild(self.guild_id)

        if not guild:
            await interaction.response.send_message("❌ Guild not found.", ephemeral=True)
            return

        # Create guild settings view and update display
        view = GuildOwnerSettingsView(self.guild_id)
        await view.update_display(interaction)


class BotOwnerSettingsView(View):
    """Settings view for bot owners with full access."""

    def __init__(self):
        super().__init__(timeout=900)

        # Set default prefix button
        prefix_btn = Button(label="Set Default Prefix", style=discord.ButtonStyle.primary, emoji="🔤", custom_id="set_default_prefix")
        prefix_btn.callback = self.set_default_prefix
        self.add_item(prefix_btn)

        # Cog management button
        cog_mgmt_btn = Button(label="Cog Management", style=discord.ButtonStyle.secondary, emoji="⚙️", custom_id="cog_management")
        cog_mgmt_btn.callback = self.show_cog_management
        self.add_item(cog_mgmt_btn)

        # Error log channel button
        error_channel_btn = Button(label="Set Error Channel", style=discord.ButtonStyle.secondary, emoji="📝", custom_id="set_error_channel")
        error_channel_btn.callback = self.set_error_channel
        self.add_item(error_channel_btn)

        # Back button
        back_btn = Button(label="Back", style=discord.ButtonStyle.gray, emoji="⬅️", custom_id="back_to_main")
        back_btn.callback = self.back_to_main
        self.add_item(back_btn)

    async def set_default_prefix(self, interaction: discord.Interaction):
        """Show the default prefix management interface."""
        # Create prefix management view
        view = BotPrefixManagementView()
        await view.update_display(interaction)

    async def show_cog_management(self, interaction: discord.Interaction):
        """Show the cog management interface."""
        # Create cog management view
        view = CogManagementView()

        # Populate the view and create initial embed
        bot = interaction.client
        all_cogs = bot.cog_manager.get_all_cogs_with_config()

        # Populate cog selector
        view.cog_select.options = []
        if all_cogs:
            for cog_name in sorted(all_cogs.keys()):
                config = all_cogs[cog_name]
                enabled = config.get("enabled", False)
                loaded = f"thetower.bot.cogs.{cog_name}" in bot.extensions
                public = config.get("public", False)

                # Create description showing status
                status_parts = []
                if enabled:
                    status_parts.append("✅")
                else:
                    status_parts.append("❌")

                if loaded:
                    status_parts.append("🟢")
                else:
                    status_parts.append("🔴")

                if public:
                    status_parts.append("🌐")
                else:
                    status_parts.append("🔒")

                description = " ".join(status_parts)

                option = discord.SelectOption(label=cog_name, value=cog_name, description=description)
                view.cog_select.options.append(option)
        else:
            # Add placeholder option when no cogs exist
            option = discord.SelectOption(label="No cogs available", value="none", description="No cogs found in the system")
            view.cog_select.options.append(option)

        # Create initial embed
        embed = discord.Embed(
            title="⚙️ Cog Management",
            description="View all cogs and their status. Select a cog from the dropdown to manage it.",
            color=discord.Color.blue(),
        )

        # Show all cogs status
        if all_cogs:
            cog_status_lines = []
            for cog_name in sorted(all_cogs.keys()):
                config = all_cogs[cog_name]
                enabled = config.get("enabled", False)
                loaded = f"thetower.bot.cogs.{cog_name}" in bot.extensions
                public = config.get("public", False)

                # Create status indicators
                status_parts = []
                if enabled:
                    status_parts.append("✅")
                else:
                    status_parts.append("❌")

                if loaded:
                    status_parts.append("🟢")
                else:
                    status_parts.append("🔴")

                if public:
                    status_parts.append("🌐")
                else:
                    status_parts.append("🔒")

                status = " ".join(status_parts)

                cog_status_lines.append(f"`{cog_name}` {status}")

            embed.add_field(name=f"All Cogs ({len(all_cogs)})", value="\n".join(cog_status_lines), inline=False)
        else:
            embed.add_field(name="Cogs", value="No cogs found in the system", inline=False)

        # Enable/disable action buttons based on available cogs
        has_cogs = len(all_cogs) > 0
        view.cog_select.disabled = not has_cogs
        view.enable_btn.disabled = not has_cogs
        view.visibility_btn.disabled = not has_cogs
        view.control_btn.disabled = not has_cogs

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def set_error_channel(self, interaction: discord.Interaction):
        """Set the error logging channel."""
        # Create channel selector
        view = View(timeout=900)
        channel_select = ui.ChannelSelect(
            placeholder="Select channel for error logs", channel_types=[discord.ChannelType.text], min_values=0, max_values=1
        )

        async def channel_callback(select_interaction: discord.Interaction):
            if channel_select.values:
                channel = channel_select.values[0]
                # Import here to avoid circular imports
                bot = interaction.client
                bot.config.config["error_log_channel"] = str(channel.id)
                bot.config.save_config()
                await select_interaction.response.send_message(f"✅ Error log channel set to {channel.mention}", ephemeral=True)
            else:
                # Clear the channel
                bot = interaction.client
                if "error_log_channel" in bot.config.config:
                    del bot.config.config["error_log_channel"]
                bot.config.save_config()
                await select_interaction.response.send_message("✅ Error log channel cleared", ephemeral=True)

        channel_select.callback = channel_callback
        view.add_item(channel_select)

        await interaction.response.send_message("Select a text channel for error logging (or select nothing to clear):", view=view, ephemeral=True)

    async def back_to_main(self, interaction: discord.Interaction):
        """Go back to main settings view."""
        # Get the original interaction data to recreate the main view
        is_bot_owner = await interaction.client.is_owner(interaction.user)
        guild_id = interaction.guild.id if interaction.guild else None

        embed = discord.Embed(title="⚙️ Settings", description="Select a category to manage", color=discord.Color.blue())

        if is_bot_owner:
            embed.add_field(name="👑 Bot Owner", value="You have full access to all settings", inline=False)

        # Create main settings view
        view = SettingsMainView(is_bot_owner, guild_id)

        await interaction.response.edit_message(embed=embed, view=view)


class GuildPrefixManagementView(View):
    """View for managing guild-specific prefixes."""

    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = guild_id
        self.selected_prefix_index = None
        self.status_message = None

        # Add prefix button
        add_btn = Button(label="Add Prefix", style=discord.ButtonStyle.success, emoji="➕", custom_id="add_prefix")
        add_btn.callback = self.add_prefix
        self.add_item(add_btn)

        # Edit prefix button
        edit_btn = Button(label="Edit Prefix", style=discord.ButtonStyle.primary, emoji="✏️", custom_id="edit_prefix", disabled=True)
        edit_btn.callback = self.edit_prefix
        self.add_item(edit_btn)

        # Delete prefix button
        delete_btn = Button(label="Delete Prefix", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="delete_prefix", disabled=True)
        delete_btn.callback = self.delete_prefix
        self.add_item(delete_btn)

        # Prefix selector dropdown
        self.prefix_select = ui.Select(
            placeholder="Select a prefix to manage...",
            options=[
                discord.SelectOption(label="Loading...", value="loading", description="Please wait while prefixes are loaded")
            ],  # Will be populated dynamically
            custom_id="prefix_selector",
        )
        self.prefix_select.callback = self.select_prefix
        self.add_item(self.prefix_select)

        # Refresh button
        refresh_btn = Button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="refresh_prefixes")
        refresh_btn.callback = self.refresh_prefixes
        self.add_item(refresh_btn)

        # Back button
        back_btn = Button(label="Back", style=discord.ButtonStyle.gray, emoji="⬅️", custom_id="back_to_guild_settings")
        back_btn.callback = self.back_to_guild_settings
        self.add_item(back_btn)

    async def update_display(self, interaction: discord.Interaction):
        """Update the embed and populate prefix selector."""
        bot = interaction.client

        # Get guild prefixes
        guild_config = bot.config.config.setdefault("guilds", {}).setdefault(str(self.guild_id), {})
        guild_prefixes = guild_config.get("prefixes", [])

        # Populate prefix selector
        self.prefix_select.options = []
        if guild_prefixes:
            for i, prefix in enumerate(guild_prefixes):
                option = discord.SelectOption(label=f"Prefix {i+1}: {prefix}", value=str(i), description=f"Command prefix: {prefix}")
                self.prefix_select.options.append(option)
        else:
            # Add placeholder option when no prefixes exist
            option = discord.SelectOption(label="No custom prefixes", value="none", description="Using default bot prefixes")
            self.prefix_select.options.append(option)

        # Update embed
        embed = discord.Embed(title="🔤 Server Prefixes", description="Manage custom command prefixes for this server", color=discord.Color.blue())

        # Show status message if any
        if self.status_message:
            embed.add_field(name="Status", value=self.status_message, inline=False)
            self.status_message = None  # Clear after displaying

        # Show current prefixes
        if guild_prefixes:
            prefix_list = []
            for i, prefix in enumerate(guild_prefixes):
                if self.selected_prefix_index == i:
                    prefix_list.append(f"**`{prefix}`** ← Selected")
                else:
                    prefix_list.append(f"`{prefix}`")

            embed.add_field(name=f"Server Prefixes ({len(guild_prefixes)})", value="\n".join(prefix_list), inline=False)
        else:
            embed.add_field(name="Server Prefixes", value="No custom prefixes set. Using default bot prefixes.", inline=False)

        # Show default bot prefixes for reference
        default_prefixes = bot.config.get("prefixes", [])
        if default_prefixes:
            default_display = ", ".join([f"`{p}`" for p in default_prefixes])
            embed.add_field(name="Default Bot Prefixes", value=default_display, inline=False)

        # Enable/disable buttons based on selection and available prefixes
        has_prefixes = len(guild_prefixes) > 0
        has_selection = self.selected_prefix_index is not None and has_prefixes
        self.prefix_select.disabled = not has_prefixes
        self.children[1].disabled = not has_selection  # edit_btn
        self.children[2].disabled = not has_selection  # delete_btn

        await interaction.response.edit_message(embed=embed, view=self)

    async def select_prefix(self, interaction: discord.Interaction):
        """Handle prefix selection."""
        selected_value = self.prefix_select.values[0] if self.prefix_select.values else None
        if selected_value in ["none", "loading"]:
            self.selected_prefix_index = None
        else:
            self.selected_prefix_index = int(selected_value)
        await self.update_display(interaction)

    async def add_prefix(self, interaction: discord.Interaction):
        """Add a new prefix."""
        modal = GuildPrefixModal(is_edit=False)
        await interaction.response.send_modal(modal)

    async def edit_prefix(self, interaction: discord.Interaction):
        """Edit the selected prefix."""
        if self.selected_prefix_index is None:
            await interaction.response.send_message("❌ No prefix selected.", ephemeral=True)
            return

        bot = interaction.client

        guild_config = bot.config.config.setdefault("guilds", {}).setdefault(str(self.guild_id), {})
        guild_prefixes = guild_config.get("prefixes", [])

        if self.selected_prefix_index >= len(guild_prefixes):
            await interaction.response.send_message("❌ Selected prefix no longer exists.", ephemeral=True)
            return

        current_prefix = guild_prefixes[self.selected_prefix_index]
        modal = GuildPrefixModal(is_edit=True, current_prefix=current_prefix, prefix_index=self.selected_prefix_index)
        await interaction.response.send_modal(modal)

    async def delete_prefix(self, interaction: discord.Interaction):
        """Delete the selected prefix."""
        if self.selected_prefix_index is None:
            await interaction.response.send_message("❌ No prefix selected.", ephemeral=True)
            return

        bot = interaction.client

        guild_config = bot.config.config.setdefault("guilds", {}).setdefault(str(self.guild_id), {})
        guild_prefixes = guild_config.get("prefixes", [])

        if self.selected_prefix_index >= len(guild_prefixes):
            await interaction.response.send_message("❌ Selected prefix no longer exists.", ephemeral=True)
            return

        deleted_prefix = guild_prefixes.pop(self.selected_prefix_index)

        if guild_prefixes:
            guild_config["prefixes"] = guild_prefixes
        else:
            # Remove the prefixes key if empty
            if "prefixes" in guild_config:
                del guild_config["prefixes"]

        bot.config.save_config()

        self.status_message = f"✅ Server prefix `{deleted_prefix}` deleted."
        self.selected_prefix_index = None  # Clear selection

        # Refresh display
        await self.update_display(interaction)

    async def refresh_prefixes(self, interaction: discord.Interaction):
        """Refresh the display."""
        await self.update_display(interaction)

    async def back_to_guild_settings(self, interaction: discord.Interaction):
        """Go back to guild settings."""
        # Create a detailed server settings view
        view = GuildOwnerSettingsView(self.guild_id)

        guild = interaction.guild
        embed = discord.Embed(title=f"🏰 {guild.name} Settings", description="Server-specific configuration", color=discord.Color.blue())

        # Server Information
        server_info = [
            f"**Name:** {guild.name}",
            f"**ID:** {guild.id}",
            f"**Members:** {guild.member_count}",
            f"**Owner:** {guild.owner.mention if guild.owner else 'Unknown'}",
        ]
        embed.add_field(name="Server Information", value="\n".join(server_info), inline=False)

        # Server Configuration
        bot = interaction.client

        # Get current prefix for this guild
        guild_config = bot.config.config.get("guilds", {}).get(str(self.guild_id), {})
        guild_prefixes = guild_config.get("prefixes", [])

        if guild_prefixes:
            current_prefix = f"{guild_prefixes[0]} (custom)"
        else:
            default_prefixes = bot.config.get("prefixes", [])
            if default_prefixes:
                current_prefix = f"{default_prefixes[0]} (default)"
            else:
                current_prefix = "No prefix configured"

        embed.add_field(name="Server Configuration", value=f"**Command Prefix:** {current_prefix}", inline=False)

        # Enabled Features
        enabled_cogs = []
        all_cogs = bot.cog_manager.get_all_cogs_with_config()
        for cog_name, config in all_cogs.items():
            if config.get("enabled", False):
                enabled_cogs.append(cog_name)

        if enabled_cogs:
            cogs_list = ", ".join(enabled_cogs)
            embed.add_field(name="Enabled Features", value=f"**Cogs:** {len(enabled_cogs)} enabled\n**List:** {cogs_list}", inline=False)
        else:
            embed.add_field(name="Enabled Features", value="**Cogs:** 0 enabled", inline=False)

        await interaction.response.edit_message(embed=embed, view=view)


class GuildPrefixModal(ui.Modal, title="Manage Server Prefix"):
    """Modal for adding or editing guild prefixes."""

    def __init__(self, is_edit: bool = False, current_prefix: str = "", prefix_index: int = None):
        super().__init__()
        self.is_edit = is_edit
        self.prefix_index = prefix_index

        title_text = "Edit Server Prefix" if is_edit else "Add Server Prefix"
        self.title = title_text

        self.prefix_input = ui.TextInput(
            label="Prefix", placeholder="Enter command prefix (e.g., ! or >)", required=True, max_length=5, default=current_prefix
        )
        self.add_item(self.prefix_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle prefix add/edit."""
        new_prefix = self.prefix_input.value.strip()

        if not new_prefix:
            await interaction.response.send_message("❌ Prefix cannot be empty", ephemeral=True)
            return

        bot = interaction.client

        guild_config = bot.config.config.setdefault("guilds", {}).setdefault(str(interaction.guild.id), {})
        guild_prefixes = guild_config.get("prefixes", [])

        if self.is_edit and self.prefix_index is not None:
            # Edit existing prefix
            if self.prefix_index >= len(guild_prefixes):
                await interaction.response.send_message("❌ Prefix no longer exists.", ephemeral=True)
                return
            old_prefix = guild_prefixes[self.prefix_index]
            guild_prefixes[self.prefix_index] = new_prefix
            action = f"updated from `{old_prefix}` to `{new_prefix}`"
        else:
            # Add new prefix
            if new_prefix in guild_prefixes:
                await interaction.response.send_message(f"❌ Prefix `{new_prefix}` already exists for this server.", ephemeral=True)
                return
            guild_prefixes.append(new_prefix)
            action = f"added: `{new_prefix}`"

        guild_config["prefixes"] = guild_prefixes
        bot.config.save_config()

        await interaction.response.send_message(
            f"✅ Server prefix {action}\n\n*Click 'Refresh' in the prefix management view to see the updated list.*", ephemeral=True
        )


class GuildOwnerSettingsView(View):
    """Settings view for guild owners with limited access."""

    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = guild_id

        # Set guild prefix button - now opens management view
        prefix_btn = Button(label="Manage Server Prefixes", style=discord.ButtonStyle.primary, emoji="🔤", custom_id="manage_prefixes")
        prefix_btn.callback = self.manage_prefixes
        self.add_item(prefix_btn)

        # Cog settings button
        cog_settings_btn = Button(label="Cog Settings", style=discord.ButtonStyle.secondary, emoji="⚙️", custom_id="cog_settings")
        cog_settings_btn.callback = self.manage_cog_settings
        self.add_item(cog_settings_btn)

        # Clear guild prefix button
        clear_prefix_btn = Button(label="Use Default Prefix", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="clear_prefix")
        clear_prefix_btn.callback = self.clear_prefix
        self.add_item(clear_prefix_btn)

        # Back button
        back_btn = Button(label="Back", style=discord.ButtonStyle.gray, emoji="⬅️", custom_id="back_to_main")
        back_btn.callback = self.back_to_main
        self.add_item(back_btn)

    async def update_display(self, interaction: discord.Interaction):
        """Update the embed with detailed server information."""
        guild = interaction.guild
        embed = discord.Embed(title=f"🏰 {guild.name} Settings", description="Server-specific configuration", color=discord.Color.blue())

        # Server Information
        server_info = [
            f"**Name:** {guild.name}",
            f"**ID:** {guild.id}",
            f"**Members:** {guild.member_count}",
            f"**Owner:** {guild.owner.mention if guild.owner else 'Unknown'}",
        ]
        embed.add_field(name="Server Information", value="\n".join(server_info), inline=False)

        # Server Configuration
        bot = interaction.client

        # Get current prefix for this guild
        guild_config = bot.config.config.get("guilds", {}).get(str(self.guild_id), {})
        guild_prefixes = guild_config.get("prefixes", [])

        if guild_prefixes:
            current_prefix = f"{guild_prefixes[0]} (custom)"
        else:
            default_prefixes = bot.config.get("prefixes", [])
            if default_prefixes:
                current_prefix = f"{default_prefixes[0]} (default)"
            else:
                current_prefix = "No prefix configured"

        embed.add_field(name="Server Configuration", value=f"**Command Prefix:** {current_prefix}", inline=False)

        # Enabled Features
        enabled_cogs = bot.cog_manager.config.get_guild_enabled_cogs(self.guild_id)

        if enabled_cogs:
            cogs_list = ", ".join(enabled_cogs)
            embed.add_field(name="Enabled Features", value=f"**Cogs:** {len(enabled_cogs)} enabled\n**List:** {cogs_list}", inline=False)
        else:
            embed.add_field(name="Enabled Features", value="**Cogs:** 0 enabled", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

    async def manage_prefixes(self, interaction: discord.Interaction):
        """Open guild prefix management view."""
        view = GuildPrefixManagementView(self.guild_id)

        # Populate the view before sending the message
        bot = interaction.client

        # Get guild prefixes
        guild_config = bot.config.config.setdefault("guilds", {}).setdefault(str(view.guild_id), {})
        guild_prefixes = guild_config.get("prefixes", [])

        # Populate prefix selector
        view.prefix_select.options = []
        if guild_prefixes:
            for i, prefix in enumerate(guild_prefixes):
                option = discord.SelectOption(label=f"Prefix {i+1}: {prefix}", value=str(i), description=f"Command prefix: {prefix}")
                view.prefix_select.options.append(option)
        else:
            # Add placeholder option when no prefixes exist
            option = discord.SelectOption(label="No custom prefixes", value="none", description="Using default bot prefixes")
            view.prefix_select.options.append(option)

        # Create embed with populated data
        embed = discord.Embed(title="🔤 Server Prefixes", description="Manage custom command prefixes for this server", color=discord.Color.blue())

        # Show current prefixes
        if guild_prefixes:
            prefix_list = []
            for i, prefix in enumerate(guild_prefixes):
                prefix_list.append(f"`{prefix}`")

            embed.add_field(name=f"Server Prefixes ({len(guild_prefixes)})", value="\n".join(prefix_list), inline=False)
        else:
            embed.add_field(name="Server Prefixes", value="No custom prefixes set. Using default bot prefixes.", inline=False)

        # Show default bot prefixes for reference
        default_prefixes = bot.config.get("prefixes", [])
        if default_prefixes:
            default_display = ", ".join([f"`{p}`" for p in default_prefixes])
            embed.add_field(name="Default Bot Prefixes", value=default_display, inline=False)

        # Enable/disable buttons based on available prefixes
        has_prefixes = len(guild_prefixes) > 0
        view.prefix_select.disabled = not has_prefixes
        view.children[1].disabled = not has_prefixes  # edit_btn
        view.children[2].disabled = not has_prefixes  # delete_btn

        await interaction.response.edit_message(embed=embed, view=view)

    async def manage_cog_settings(self, interaction: discord.Interaction):
        """Open cog settings management view."""
        # Create cog settings view
        view = CogSettingsView(self.guild_id)

        # Populate the view and create initial embed
        bot = interaction.client
        cog_status_list, _ = bot.cog_manager.get_cog_status_list(self.guild_id)
        available_cogs = [status for status in cog_status_list if status["guild_can_use"]]

        # Populate cog selector
        view.cog_select.options = []
        if available_cogs:
            for status in available_cogs:
                cog_name = status["name"]
                enabled = status["guild_enabled"]
                has_settings = cog_name in bot.cog_manager.cog_settings_registry

                # Create description showing status
                status_parts = []
                if enabled:
                    status_parts.append("✅")
                else:
                    status_parts.append("❌")

                if has_settings:
                    status_parts.append("⚙️")
                else:
                    status_parts.append("🚫")

                description = " ".join(status_parts)

                option = discord.SelectOption(label=cog_name.replace("_", " ").title(), value=cog_name, description=description)
                view.cog_select.options.append(option)
        else:
            # Add placeholder option when no cogs are available
            option = discord.SelectOption(label="No cogs enabled", value="none", description="No cogs are enabled for this server")
            view.cog_select.options.append(option)

        # Create initial embed
        embed = discord.Embed(
            title="⚙️ Cog Settings",
            description="Manage cogs for this server. Select a cog to enable/disable it or configure its settings.",
            color=discord.Color.blue(),
        )

        if available_cogs:
            cog_list = []
            for status in available_cogs:
                cog_name = status["name"]
                enabled = status["guild_enabled"]
                has_settings = cog_name in bot.cog_manager.cog_settings_registry

                display_name = cog_name.replace("_", " ").title()

                # Create status indicators
                status_parts = []
                if enabled:
                    status_parts.append("✅")
                else:
                    status_parts.append("❌")

                if has_settings:
                    status_parts.append("⚙️")
                else:
                    status_parts.append("🚫")

                status_str = " ".join(status_parts)

                cog_list.append(f"`{display_name}` {status_str}")

            embed.add_field(name=f"Available Cogs ({len(available_cogs)})", value="\n".join(cog_list), inline=False)

            # Show legend
            legend = [
                "✅ = Enabled for this server",
                "❌ = Disabled for this server",
                "⚙️ = Has configurable settings",
                "🚫 = No configurable settings",
            ]
            embed.add_field(name="Legend", value="\n".join(legend), inline=False)
        else:
            embed.add_field(
                name="No Cogs Available",
                value="No cogs are currently available for this server.\n\n" "Contact the bot owner if you believe this is an error.",
                inline=False,
            )

        # Enable/disable buttons based on available cogs
        has_cogs = len(available_cogs) > 0
        view.cog_select.disabled = not has_cogs
        view.toggle_btn.disabled = not has_cogs
        view.configure_btn.disabled = True  # No selection yet

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def clear_prefix(self, interaction: discord.Interaction):
        """Clear guild-specific prefix to use default."""
        bot = interaction.client

        # Remove guild-specific prefix
        guild_config = bot.config.config.setdefault("guilds", {}).setdefault(str(self.guild_id), {})
        if "prefix" in guild_config:
            del guild_config["prefix"]
        bot.config.save_config()

        default_prefixes = bot.config.get("prefixes", [])
        if default_prefixes:
            default_prefix = default_prefixes[0]
            message = f"✅ Server prefix cleared. Now using default prefix: `{default_prefix}`"
        else:
            message = "✅ Server prefix cleared. Now using default (no prefix configured)"
        await interaction.response.send_message(message, ephemeral=True)

    async def back_to_main(self, interaction: discord.Interaction):
        """Go back to main settings view."""
        # Get the original interaction data to recreate the main view
        is_bot_owner = await interaction.client.is_owner(interaction.user)
        guild_id = interaction.guild.id if interaction.guild else None

        embed = discord.Embed(title="⚙️ Settings", description="Select a category to manage", color=discord.Color.blue())

        if is_bot_owner:
            embed.add_field(name="👑 Bot Owner", value="You have full access to all settings", inline=False)

        # Create main settings view
        view = SettingsMainView(is_bot_owner, guild_id)

        await interaction.response.edit_message(embed=embed, view=view)


class CogSettingsView(View):
    """View for managing cog enable/disable and settings for a guild."""

    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = guild_id
        self.selected_cog = None
        self.status_message = None

        # Cog selector dropdown
        self.cog_select = ui.Select(
            placeholder="Select a cog to manage...",
            options=[discord.SelectOption(label="Loading...", value="loading", description="Please wait while cogs are loaded")],
            custom_id="cog_settings_selector",
        )
        self.cog_select.callback = self.select_cog
        self.add_item(self.cog_select)

        # Enable/Disable button
        self.toggle_btn = Button(label="Enable/Disable", style=discord.ButtonStyle.primary, emoji="🔄", custom_id="toggle_cog_guild", disabled=True)
        self.toggle_btn.callback = self.toggle_cog
        self.add_item(self.toggle_btn)

        # Configure button (only for enabled cogs with settings)
        self.configure_btn = Button(
            label="Configure Settings", style=discord.ButtonStyle.secondary, emoji="⚙️", custom_id="configure_cog", disabled=True
        )
        self.configure_btn.callback = self.configure_cog
        self.add_item(self.configure_btn)

        # Back button
        back_btn = Button(label="Back", style=discord.ButtonStyle.gray, emoji="⬅️", custom_id="back_to_guild_settings")
        back_btn.callback = self.back_to_guild_settings
        self.add_item(back_btn)

    async def update_display(self, interaction: discord.Interaction):
        """Update the embed and populate cog selector."""
        bot = interaction.client

        # Get all cogs available to this guild
        cog_status_list, _ = bot.cog_manager.get_cog_status_list(self.guild_id)
        available_cogs = [status for status in cog_status_list if status["guild_can_use"]]

        # Populate cog selector
        self.cog_select.options = []
        if available_cogs:
            for status in available_cogs:
                cog_name = status["name"]
                enabled = status["guild_enabled"]
                has_settings = cog_name in bot.cog_manager.cog_settings_registry

                # Create description showing status
                status_parts = []
                if enabled:
                    status_parts.append("✅")
                else:
                    status_parts.append("❌")

                if has_settings:
                    status_parts.append("⚙️")
                else:
                    status_parts.append("🚫")

                description = " ".join(status_parts)

                option = discord.SelectOption(label=cog_name.replace("_", " ").title(), value=cog_name, description=description)
                self.cog_select.options.append(option)
        else:
            # Add placeholder option when no cogs are available
            option = discord.SelectOption(label="No cogs enabled", value="none", description="No cogs are enabled for this server")
            self.cog_select.options.append(option)

        # Update embed
        embed = discord.Embed(
            title="⚙️ Cog Settings",
            description="Manage cogs for this server. Select a cog to enable/disable it or configure its settings.",
            color=discord.Color.blue(),
        )

        # Show status message if any
        if self.status_message:
            embed.add_field(name="Status", value=self.status_message, inline=False)
            self.status_message = None  # Clear after displaying

        if available_cogs:
            cog_list = []
            for status in available_cogs:
                cog_name = status["name"]
                enabled = status["guild_enabled"]
                has_settings = cog_name in bot.cog_manager.cog_settings_registry

                display_name = cog_name.replace("_", " ").title()

                # Create status indicators
                status_parts = []
                if enabled:
                    status_parts.append("✅")
                else:
                    status_parts.append("❌")

                if has_settings:
                    status_parts.append("⚙️")
                else:
                    status_parts.append("🚫")

                status_str = " ".join(status_parts)

                # Highlight selected cog
                if self.selected_cog == cog_name:
                    cog_list.append(f"**`{display_name}`** {status_str} ← Selected")
                else:
                    cog_list.append(f"`{display_name}` {status_str}")

            embed.add_field(name=f"Available Cogs ({len(available_cogs)})", value="\n".join(cog_list), inline=False)

            # Show legend
            legend = [
                "✅ = Enabled for this server",
                "❌ = Disabled for this server",
                "⚙️ = Has configurable settings",
                "🚫 = No configurable settings",
            ]
            embed.add_field(name="Legend", value="\n".join(legend), inline=False)

            if self.selected_cog:
                selected_status = next((s for s in available_cogs if s["name"] == self.selected_cog), None)
                if selected_status:
                    enabled = selected_status["guild_enabled"]
                    has_settings = self.selected_cog in bot.cog_manager.cog_settings_registry

                    embed.add_field(
                        name=f"Selected: {self.selected_cog.replace('_', ' ').title()}",
                        value=f"**Status:** {'✅ Enabled' if enabled else '❌ Disabled'}\n"
                        f"**Settings:** {'⚙️ Available' if has_settings else '🚫 Not available'}\n\n"
                        f"Use 'Enable/Disable' to toggle this cog for this server.\n"
                        f"{'Use \'Configure Settings\' to access its settings.' if enabled and has_settings else ''}",
                        inline=False,
                    )
        else:
            embed.add_field(
                name="No Cogs Available",
                value="No cogs are currently available for this server.\n\n" "Contact the bot owner if you believe this is an error.",
                inline=False,
            )

        # Enable/disable buttons based on selection and cog status
        has_selection = self.selected_cog is not None and any(s["name"] == self.selected_cog for s in available_cogs)
        has_cogs = len(available_cogs) > 0

        self.cog_select.disabled = not has_cogs
        self.toggle_btn.disabled = not (has_selection and has_cogs)

        # Configure button only enabled for selected cog that is enabled and has settings
        if has_selection:
            selected_status = next((s for s in available_cogs if s["name"] == self.selected_cog), None)
            if selected_status:
                enabled = selected_status["guild_enabled"]
                has_settings = self.selected_cog in bot.cog_manager.cog_settings_registry
                self.configure_btn.disabled = not (enabled and has_settings)
            else:
                self.configure_btn.disabled = True
        else:
            self.configure_btn.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)

    async def select_cog(self, interaction: discord.Interaction):
        """Handle cog selection."""
        selected_value = self.cog_select.values[0] if self.cog_select.values else None
        if selected_value in ["none", "loading"]:
            self.selected_cog = None
        else:
            self.selected_cog = selected_value
        await self.update_display(interaction)

    async def toggle_cog(self, interaction: discord.Interaction):
        """Toggle a cog's enabled/disabled status for this guild."""
        if not self.selected_cog:
            await interaction.response.send_message("❌ No cog selected.", ephemeral=True)
            return

        bot = interaction.client

        # Get current status
        cog_status_list, _ = bot.cog_manager.get_cog_status_list(self.guild_id)
        selected_status = next((s for s in cog_status_list if s["name"] == self.selected_cog), None)

        if not selected_status:
            await interaction.response.send_message("❌ Selected cog is no longer available.", ephemeral=True)
            return

        currently_enabled = selected_status["guild_enabled"]

        # Defer the response for potentially long-running operations
        await interaction.response.defer()

        # Toggle the cog
        if currently_enabled:
            success_msg, error_msg = await bot.cog_manager.disable_cog(self.selected_cog, self.guild_id)
        else:
            success_msg, error_msg = await bot.cog_manager.enable_cog(self.selected_cog, self.guild_id)

        # Set status message
        if success_msg:
            self.status_message = success_msg
        if error_msg:
            self.status_message = error_msg

        # Send follow-up with updated display
        embed = discord.Embed(
            title="⚙️ Cog Settings",
            description="Manage cogs for this server. Select a cog to enable/disable it or configure its settings.",
            color=discord.Color.blue(),
        )

        # Add status message
        if self.status_message:
            embed.add_field(name="Status", value=self.status_message, inline=False)
            self.status_message = None  # Clear after displaying

        # Re-populate cog selector
        cog_status_list, _ = bot.cog_manager.get_cog_status_list(self.guild_id)
        available_cogs = [status for status in cog_status_list if status["guild_can_use"]]

        self.cog_select.options = []
        if available_cogs:
            for status in available_cogs:
                cog_name = status["name"]
                enabled = status["guild_enabled"]
                has_settings = cog_name in bot.cog_manager.cog_settings_registry

                # Create description showing status
                status_parts = []
                if enabled:
                    status_parts.append("✅")
                else:
                    status_parts.append("❌")

                if has_settings:
                    status_parts.append("⚙️")
                else:
                    status_parts.append("🚫")

                description = " ".join(status_parts)

                option = discord.SelectOption(label=cog_name.replace("_", " ").title(), value=cog_name, description=description)
                self.cog_select.options.append(option)

        if available_cogs:
            cog_list = []
            for status in available_cogs:
                cog_name = status["name"]
                enabled = status["guild_enabled"]
                has_settings = cog_name in bot.cog_manager.cog_settings_registry

                display_name = cog_name.replace("_", " ").title()

                # Create status indicators
                status_parts = []
                if enabled:
                    status_parts.append("✅")
                else:
                    status_parts.append("❌")

                if has_settings:
                    status_parts.append("⚙️")
                else:
                    status_parts.append("🚫")

                status_str = " ".join(status_parts)

                # Highlight selected cog
                if self.selected_cog == cog_name:
                    cog_list.append(f"**`{display_name}`** {status_str} ← Selected")
                else:
                    cog_list.append(f"`{display_name}` {status_str}")

            embed.add_field(name=f"Available Cogs ({len(available_cogs)})", value="\n".join(cog_list), inline=False)

            # Show legend
            legend = [
                "✅ = Enabled for this server",
                "❌ = Disabled for this server",
                "⚙️ = Has configurable settings",
                "🚫 = No configurable settings",
            ]
            embed.add_field(name="Legend", value="\n".join(legend), inline=False)

            if self.selected_cog:
                selected_status = next((s for s in available_cogs if s["name"] == self.selected_cog), None)
                if selected_status:
                    enabled = selected_status["guild_enabled"]
                    has_settings = self.selected_cog in bot.cog_manager.cog_settings_registry

                    embed.add_field(
                        name=f"Selected: {self.selected_cog.replace('_', ' ').title()}",
                        value=f"**Status:** {'✅ Enabled' if enabled else '❌ Disabled'}\n"
                        f"**Settings:** {'⚙️ Available' if has_settings else '🚫 Not available'}\n\n"
                        f"Use 'Enable/Disable' to toggle this cog for this server.\n"
                        f"{'Use \'Configure Settings\' to access its settings.' if enabled and has_settings else ''}",
                        inline=False,
                    )

        # Enable/disable buttons based on selection and cog status
        has_selection = self.selected_cog is not None and any(s["name"] == self.selected_cog for s in available_cogs)
        has_cogs = len(available_cogs) > 0

        self.cog_select.disabled = not has_cogs
        self.toggle_btn.disabled = not (has_selection and has_cogs)

        # Configure button only enabled for selected cog that is enabled and has settings
        if has_selection:
            selected_status = next((s for s in available_cogs if s["name"] == self.selected_cog), None)
            if selected_status:
                enabled = selected_status["guild_enabled"]
                has_settings = self.selected_cog in bot.cog_manager.cog_settings_registry
                self.configure_btn.disabled = not (enabled and has_settings)
            else:
                self.configure_btn.disabled = True
        else:
            self.configure_btn.disabled = True

        await interaction.followup.send(embed=embed, view=self)

    async def configure_cog(self, interaction: discord.Interaction):
        """Open the settings view for the selected cog."""
        if not self.selected_cog:
            await interaction.response.send_message("❌ No cog selected.", ephemeral=True)
            return

        bot = interaction.client

        # Get the settings view class for this cog
        settings_view_class = bot.cog_manager.get_cog_settings_view(self.selected_cog)
        if not settings_view_class:
            await interaction.response.send_message(f"❌ Settings view not available for cog `{self.selected_cog}`.", ephemeral=True)
            return

        # Get the cog instance
        cog_instance = bot.cog_manager.get_cog_by_filename(self.selected_cog)
        if not cog_instance:
            await interaction.response.send_message(f"❌ Cog instance not found for `{self.selected_cog}`.", ephemeral=True)
            return

        # Create and display the cog's settings view
        try:
            # Check if user is bot owner for settings that need it
            is_bot_owner = await interaction.client.is_owner(interaction.user)

            # Create context object
            context = SettingsViewContext(guild_id=self.guild_id, cog_instance=cog_instance, interaction=interaction, is_bot_owner=is_bot_owner)

            # Try the new unified constructor first
            try:
                view = settings_view_class(context)
            except TypeError:
                # Fallback to old signature-guessing logic for backwards compatibility
                # Try different constructor signatures in order of preference
                view = None

                # Try 1: (guild_id, cog_instance) - for views that need guild and cog context
                try:
                    view = settings_view_class(self.guild_id, cog_instance)
                except TypeError:
                    # Try 2: (cog_instance, interaction, is_bot_owner) - for views that need user context and owner status
                    try:
                        view = settings_view_class(cog_instance, interaction, is_bot_owner)
                    except TypeError:
                        # Try 3: (cog_instance, interaction) - for views that need user context
                        try:
                            view = settings_view_class(cog_instance, interaction)
                        except TypeError:
                            # Try 4: (cog_instance, guild_id) - for views that need guild context
                            try:
                                view = settings_view_class(cog_instance, self.guild_id)
                            except TypeError:
                                # Try 5: (guild_id) - for views that only need guild context
                                try:
                                    view = settings_view_class(self.guild_id)
                                except TypeError:
                                    # Try 6: (cog_instance) - for views that only need cog context
                                    try:
                                        view = settings_view_class(cog_instance)
                                    except TypeError as e:
                                        raise TypeError(f"Could not determine constructor signature for {settings_view_class.__name__}: {e}")

            # Call update_display if it exists
            if hasattr(view, "update_display"):
                await view.update_display(interaction)
            # Check if view has update_view method that returns an embed
            elif hasattr(view, "update_view"):
                embed = await view.update_view(interaction)
                await interaction.response.edit_message(embed=embed, view=view)
            # Special handling for KnownPlayersSettingsView - create embed and show immediately
            elif settings_view_class.__name__ == "KnownPlayersSettingsView":
                embed = view.create_settings_embed()
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                # Fallback: create a basic embed and show the view
                embed = discord.Embed(
                    title=f"⚙️ {self.selected_cog.replace('_', ' ').title()} Settings",
                    description="Configure settings for this cog",
                    color=discord.Color.blue(),
                )
                await interaction.response.edit_message(embed=embed, view=view)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to open settings for cog `{self.selected_cog}`: {str(e)}", ephemeral=True)

    async def back_to_guild_settings(self, interaction: discord.Interaction):
        """Go back to guild settings."""
        # Create a detailed server settings view
        view = GuildOwnerSettingsView(self.guild_id)

        guild = interaction.guild
        embed = discord.Embed(title=f"🏰 {guild.name} Settings", description="Server-specific configuration", color=discord.Color.blue())

        # Server Information
        server_info = [
            f"**Name:** {guild.name}",
            f"**ID:** {guild.id}",
            f"**Members:** {guild.member_count}",
            f"**Owner:** {guild.owner.mention if guild.owner else 'Unknown'}",
        ]
        embed.add_field(name="Server Information", value="\n".join(server_info), inline=False)

        # Server Configuration
        bot = interaction.client

        # Get current prefix for this guild
        guild_config = bot.config.config.get("guilds", {}).get(str(self.guild_id), {})
        guild_prefixes = guild_config.get("prefixes", [])

        if guild_prefixes:
            current_prefix = f"{guild_prefixes[0]} (custom)"
        else:
            default_prefixes = bot.config.get("prefixes", [])
            if default_prefixes:
                current_prefix = f"{default_prefixes[0]} (default)"
            else:
                current_prefix = "No prefix configured"

        embed.add_field(name="Server Configuration", value=f"**Command Prefix:** {current_prefix}", inline=False)

        # Enabled Features
        enabled_cogs = bot.cog_manager.config.get_guild_enabled_cogs(self.guild_id)

        if enabled_cogs:
            cogs_list = ", ".join(enabled_cogs)
            embed.add_field(name="Enabled Features", value=f"**Cogs:** {len(enabled_cogs)} enabled\n**List:** {cogs_list}", inline=False)
        else:
            embed.add_field(name="Enabled Features", value="**Cogs:** 0 enabled", inline=False)

        await interaction.response.edit_message(embed=embed, view=view)


class CogVisibilityView(View):
    """View for managing cog visibility and server authorizations."""

    def __init__(self, cog_name: str):
        super().__init__(timeout=900)
        self.cog_name = cog_name
        self.selected_guild = None
        self.status_message = None

        # Initialize buttons (will be managed dynamically)
        self.public_btn = None
        self.private_btn = None
        self.authorize_btn = None
        self.revoke_btn = None

        # Guild selector dropdown
        self.guild_select = ui.Select(
            placeholder="Select a server to manage...",
            options=[discord.SelectOption(label="Loading...", value="loading", description="Please wait while servers are loaded")],
            custom_id="guild_selector",
        )
        self.guild_select.callback = self.select_guild
        self.add_item(self.guild_select)

        # Back button
        back_btn = Button(label="Back to Cog Management", style=discord.ButtonStyle.gray, emoji="⬅️", custom_id="back_to_cog_mgmt")
        back_btn.callback = self.back_to_cog_management
        self.add_item(back_btn)

    async def update_display(self, interaction: discord.Interaction):
        """Update the embed and dynamically manage buttons."""
        bot = interaction.client

        # Get current cog config
        config = bot.cog_manager.config.get_bot_owner_cog_config(self.cog_name)
        is_public = config.get("public", False)

        # Get guild authorizations
        guild_auth = bot.cog_manager.config.get_cog_guild_authorizations(self.cog_name)

        # Clear all children and recreate the view completely
        self.clear_items()

        # Re-add guild selector
        self.guild_select = ui.Select(placeholder="Select a server to manage...", options=[], custom_id="guild_selector")
        self.guild_select.callback = self.select_guild
        self.add_item(self.guild_select)

        # Add visibility buttons based on current state
        if not is_public:
            # Cog is private, show "Make Public" button
            self.public_btn = Button(label="Make Public", style=discord.ButtonStyle.success, emoji="🌐", custom_id="make_public")
            self.public_btn.callback = self.make_public
            self.add_item(self.public_btn)
        else:
            # Cog is public, show "Make Private" button
            self.private_btn = Button(label="Make Private", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="make_private")
            self.private_btn.callback = self.make_private
            self.add_item(self.private_btn)

        # Add server authorization buttons only for private cogs
        if not is_public:
            # Determine server authorization status
            server_authorized = False
            server_disallowed = False
            if self.selected_guild:
                try:
                    guild_id = int(self.selected_guild)
                    server_authorized = guild_id in guild_auth["allowed"]
                    server_disallowed = guild_id in guild_auth["disallowed"]
                except ValueError:
                    pass

            # Add appropriate authorization button
            if server_authorized:
                # Server is authorized, show revoke option
                self.revoke_btn = Button(label="Revoke Authorization", style=discord.ButtonStyle.danger, emoji="❌", custom_id="revoke_guild")
                self.revoke_btn.callback = self.revoke_guild
                self.add_item(self.revoke_btn)
            elif server_disallowed:
                # Server is disallowed, show both options
                self.authorize_btn = Button(
                    label="Authorize Server", style=discord.ButtonStyle.primary, emoji="✅", custom_id="authorize_guild_disallowed"
                )
                self.authorize_btn.callback = self.authorize_guild
                self.add_item(self.authorize_btn)

                self.revoke_btn = Button(
                    label="Remove Disallow", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="revoke_guild_disallowed"
                )
                self.revoke_btn.callback = self.revoke_guild
                self.add_item(self.revoke_btn)
            elif self.selected_guild:
                # Server has default status, show authorize option
                self.authorize_btn = Button(label="Authorize Server", style=discord.ButtonStyle.primary, emoji="✅", custom_id="authorize_guild")
                self.authorize_btn.callback = self.authorize_guild
                self.add_item(self.authorize_btn)

        # Re-add back button
        back_btn = Button(label="Back to Cog Management", style=discord.ButtonStyle.gray, emoji="⬅️", custom_id="back_to_cog_mgmt")
        back_btn.callback = self.back_to_cog_management
        self.add_item(back_btn)

        # Populate guild selector with bot's guilds
        self.guild_select.options = []
        for guild in sorted(bot.guilds, key=lambda g: g.name):
            authorized = guild.id in guild_auth["allowed"]
            disallowed = guild.id in guild_auth["disallowed"]

            # Create description showing authorization status
            if authorized:
                status = "✅ Authorized"
            elif disallowed:
                status = "🚫 Disallowed"
            else:
                status = "⏸️ Default (follows public/private setting)"

            option = discord.SelectOption(label=f"{guild.name} ({guild.id})", value=str(guild.id), description=status)
            self.guild_select.options.append(option)

        # Update embed
        embed = discord.Embed(
            title=f"👁️ Visibility: {self.cog_name}", description="Manage who can use this cog across servers", color=discord.Color.blue()
        )

        # Show status message if any
        if self.status_message:
            embed.add_field(name="Status", value=self.status_message, inline=False)
            self.status_message = None  # Clear after displaying

        # Show current visibility setting
        visibility_status = "🌐 **Public** - Available to all servers" if is_public else "🔒 **Private** - Requires authorization"
        embed.add_field(name="Current Visibility", value=visibility_status, inline=False)

        # Show server authorizations if private
        if not is_public:
            authorized_servers = []
            disallowed_servers = []

            for guild in bot.guilds:
                if guild.id in guild_auth["allowed"]:
                    authorized_servers.append(f"✅ {guild.name}")
                elif guild.id in guild_auth["disallowed"]:
                    disallowed_servers.append(f"🚫 {guild.name}")

            if authorized_servers:
                embed.add_field(
                    name=f"Authorized Servers ({len(authorized_servers)})",
                    value="\n".join(authorized_servers[:10]),  # Limit to 10 for display
                    inline=False,
                )

            if disallowed_servers:
                embed.add_field(
                    name=f"Disallowed Servers ({len(disallowed_servers)})",
                    value="\n".join(disallowed_servers[:10]),  # Limit to 10 for display
                    inline=False,
                )

            if not authorized_servers and not disallowed_servers:
                embed.add_field(
                    name="Server Authorizations",
                    value="No specific server authorizations set.\nAll servers are denied access to this private cog.",
                    inline=False,
                )

        # Show selected guild details if any
        if self.selected_guild:
            try:
                guild_id = int(self.selected_guild)
                guild = bot.get_guild(guild_id)
                if guild:
                    auth_status = (
                        "✅ Authorized"
                        if guild_id in guild_auth["allowed"]
                        else "🚫 Disallowed" if guild_id in guild_auth["disallowed"] else "⏸️ Default"
                    )
                    embed.add_field(
                        name=f"Selected: {guild.name}",
                        value=f"**ID:** {guild.id}\n**Status:** {auth_status}\n**Members:** {guild.member_count}",
                        inline=False,
                    )
            except ValueError:
                pass

        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.NotFound:
            # Interaction has expired, ignore the error
            pass

    async def select_guild(self, interaction: discord.Interaction):
        """Handle guild selection."""
        selected_value = self.guild_select.values[0] if self.guild_select.values else None
        if selected_value in ["loading"]:
            self.selected_guild = None
        else:
            self.selected_guild = selected_value
        await self.update_display(interaction)

    async def make_public(self, interaction: discord.Interaction):
        """Make the cog public (available to all servers)."""
        bot = interaction.client

        bot.cog_manager.config.set_bot_owner_cog_public(self.cog_name, True)
        self.status_message = f"✅ Cog `{self.cog_name}` is now **public** and available to all servers."

        # Refresh display
        await self.update_display(interaction)

    async def make_private(self, interaction: discord.Interaction):
        """Make the cog private (requires authorization)."""
        bot = interaction.client

        bot.cog_manager.config.set_bot_owner_cog_public(self.cog_name, False)
        self.status_message = f"🔒 Cog `{self.cog_name}` is now **private**. Use server authorization to control access."

        # Refresh display
        await self.update_display(interaction)

    async def authorize_guild(self, interaction: discord.Interaction):
        """Authorize the selected guild to use this cog."""
        if not self.selected_guild:
            await interaction.response.send_message("❌ No server selected.", ephemeral=True)
            return

        try:
            guild_id = int(self.selected_guild)
        except ValueError:
            await interaction.response.send_message("❌ Invalid server selection.", ephemeral=True)
            return

        bot = interaction.client
        guild = bot.get_guild(guild_id)

        if not guild:
            await interaction.response.send_message("❌ Server not found.", ephemeral=True)
            return

        # Authorize the guild
        bot.cog_manager.config.add_guild_cog_authorization(guild_id, self.cog_name, allow=True)

        self.status_message = f"✅ Server `{guild.name}` is now authorized to use cog `{self.cog_name}`."

        # Refresh display
        await self.update_display(interaction)

    async def revoke_guild(self, interaction: discord.Interaction):
        """Revoke authorization for the selected guild."""
        if not self.selected_guild:
            await interaction.response.send_message("❌ No server selected.", ephemeral=True)
            return

        try:
            guild_id = int(self.selected_guild)
        except ValueError:
            await interaction.response.send_message("❌ Invalid server selection.", ephemeral=True)
            return

        bot = interaction.client
        guild = bot.get_guild(guild_id)

        if not guild:
            await interaction.response.send_message("❌ Server not found.", ephemeral=True)
            return

        # Check if it was in allowed list, if not try disallowed list
        success = bot.cog_manager.config.remove_guild_cog_authorization(guild_id, self.cog_name, from_allowed=True)
        if not success:
            success = bot.cog_manager.config.remove_guild_cog_authorization(guild_id, self.cog_name, from_allowed=False)

        if success:
            action = "authorization revoked" if success else "removed from disallowed list"
            self.status_message = f"❌ Server `{guild.name}` {action} for cog `{self.cog_name}`."
        else:
            self.status_message = f"ℹ️ Server `{guild.name}` had no special authorization for cog `{self.cog_name}`."

        # Refresh display
        await self.update_display(interaction)

    async def back_to_cog_management(self, interaction: discord.Interaction):
        """Go back to cog management view."""
        # Recreate cog management view
        view = CogManagementView()

        # Set the selected cog so it stays selected
        view.selected_cog = self.cog_name

        # Populate and update display
        await view.update_display(interaction)


class PrefixModal(ui.Modal, title="Set Server Prefix"):
    """Modal for setting a custom prefix."""

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

        self.prefix_input = ui.TextInput(label="New Prefix", placeholder="Enter new command prefix (e.g., ! or >)", required=True, max_length=5)
        self.add_item(self.prefix_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle prefix update."""
        new_prefix = self.prefix_input.value.strip()

        if not new_prefix:
            await interaction.response.send_message("❌ Prefix cannot be empty", ephemeral=True)
            return

        bot = interaction.client

        # Set guild-specific prefix
        guild_config = bot.config.config.setdefault("guilds", {}).setdefault(str(self.guild_id), {})
        guild_config["prefix"] = new_prefix
        bot.config.save_config()

        await interaction.response.send_message(f"✅ Server prefix set to: `{new_prefix}`", ephemeral=True)


class BotPrefixManagementView(View):
    """View for managing the default bot prefixes."""

    def __init__(self):
        super().__init__(timeout=900)
        self.selected_prefix_index = None
        self.status_message = None

        # Add prefix button
        add_prefix_btn = Button(label="Add Prefix", style=discord.ButtonStyle.primary, emoji="➕", custom_id="add_prefix")
        add_prefix_btn.callback = self.add_prefix
        self.add_item(add_prefix_btn)

        # Edit prefix button
        edit_prefix_btn = Button(label="Edit Prefix", style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="edit_prefix", disabled=True)
        edit_prefix_btn.callback = self.edit_prefix
        self.add_item(edit_prefix_btn)

        # Delete prefix button
        delete_prefix_btn = Button(label="Delete Prefix", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="delete_prefix", disabled=True)
        delete_prefix_btn.callback = self.delete_prefix
        self.add_item(delete_prefix_btn)

        # Refresh button
        refresh_btn = Button(label="Refresh", style=discord.ButtonStyle.gray, emoji="🔄", custom_id="refresh_prefixes")
        refresh_btn.callback = self.refresh_display
        self.add_item(refresh_btn)

        # Back button
        back_btn = Button(label="Back", style=discord.ButtonStyle.gray, emoji="⬅️", custom_id="back_to_bot_settings")
        back_btn.callback = self.back_to_bot_settings
        self.add_item(back_btn)

        # Prefix selector dropdown
        self.prefix_select = ui.Select(
            placeholder="Select a prefix to edit/delete...",
            options=[
                discord.SelectOption(label="Loading...", value="loading", description="Please wait while prefixes are loaded")
            ],  # Will be populated dynamically
            custom_id="prefix_selector",
        )
        self.prefix_select.callback = self.select_prefix
        self.add_item(self.prefix_select)

    async def update_display(self, interaction: discord.Interaction):
        """Update the embed with current prefix information."""
        bot = interaction.client

        prefixes = bot.config.get("prefixes", [])

        embed = discord.Embed(
            title="🔤 Default Bot Prefixes", description="Manage the default command prefixes for the bot", color=discord.Color.blue()
        )

        # Show status message if any
        if self.status_message:
            embed.add_field(name="Status", value=self.status_message, inline=False)
            self.status_message = None  # Clear after displaying

        if prefixes:
            prefix_list = "\n".join([f"• `{prefix}`" for prefix in prefixes])
            embed.add_field(name=f"Current Default Prefixes ({len(prefixes)})", value=prefix_list, inline=False)
        else:
            embed.add_field(name="Current Default Prefixes", value="No prefixes configured", inline=False)

        embed.add_field(name="Note", value="These prefixes will be used when servers don't have their own custom prefix set.", inline=False)

        # Update prefix selector
        self.prefix_select.options = []
        if prefixes:
            for i, prefix in enumerate(prefixes):
                option = discord.SelectOption(label=f"Prefix {i+1}: {prefix}", value=str(i), description="Click to select this prefix")
                self.prefix_select.options.append(option)
        else:
            # Add placeholder option when no prefixes exist
            option = discord.SelectOption(label="No prefixes configured", value="none", description="Add a prefix to get started")
            self.prefix_select.options.append(option)

        # Enable/disable edit/delete buttons and select based on available prefixes
        has_selection = self.selected_prefix_index is not None
        has_prefixes = len(prefixes) > 0
        self.prefix_select.disabled = not has_prefixes
        self.children[1].disabled = not (has_selection and has_prefixes)  # edit_prefix_btn
        self.children[2].disabled = not (has_selection and has_prefixes)  # delete_prefix_btn

        await interaction.response.edit_message(embed=embed, view=self)

    async def select_prefix(self, interaction: discord.Interaction):
        """Handle prefix selection."""
        selected_value = self.prefix_select.values[0] if self.prefix_select.values else None
        if selected_value in ["none", "loading"]:
            self.selected_prefix_index = None
        else:
            self.selected_prefix_index = int(selected_value) if selected_value else None
        await self.update_display(interaction)

    async def add_prefix(self, interaction: discord.Interaction):
        """Add a new prefix."""
        modal = BotPrefixModal(is_edit=False)
        await interaction.response.send_modal(modal)

    async def edit_prefix(self, interaction: discord.Interaction):
        """Edit the selected prefix."""
        if self.selected_prefix_index is None:
            await interaction.response.send_message("❌ No prefix selected.", ephemeral=True)
            return

        bot = interaction.client
        prefixes = bot.config.get("prefixes", [])

        if self.selected_prefix_index >= len(prefixes):
            await interaction.response.send_message("❌ Selected prefix no longer exists.", ephemeral=True)
            return

        current_prefix = prefixes[self.selected_prefix_index]
        modal = BotPrefixModal(is_edit=True, current_prefix=current_prefix, prefix_index=self.selected_prefix_index)
        await interaction.response.send_modal(modal)

    async def delete_prefix(self, interaction: discord.Interaction):
        """Delete the selected prefix."""
        if self.selected_prefix_index is None:
            await interaction.response.send_message("❌ No prefix selected.", ephemeral=True)
            return

        bot = interaction.client
        prefixes = bot.config.get("prefixes", [])

        if self.selected_prefix_index >= len(prefixes):
            await interaction.response.send_message("❌ Selected prefix no longer exists.", ephemeral=True)
            return

        deleted_prefix = prefixes.pop(self.selected_prefix_index)
        bot.config.config["prefixes"] = prefixes
        bot.config.save_config()

        self.status_message = f"✅ Prefix `{deleted_prefix}` deleted successfully."

        # Reset selection and refresh display
        self.selected_prefix_index = None
        await self.update_display(interaction)

    async def refresh_display(self, interaction: discord.Interaction):
        """Refresh the display."""
        await self.update_display(interaction)

    async def back_to_bot_settings(self, interaction: discord.Interaction):
        """Go back to bot settings."""
        # Recreate bot settings view
        view = BotOwnerSettingsView()

        embed = discord.Embed(title="🤖 Bot Settings", description="Global bot configuration", color=discord.Color.blue())

        # Import here to avoid circular imports
        bot = interaction.client

        # Basic bot info
        embed.add_field(
            name="Bot Information", value=f"**Name:** {bot.user.name}\n**ID:** {bot.user.id}\n**Servers:** {len(bot.guilds)}", inline=False
        )

        # Configuration settings
        default_prefixes = bot.config.get("prefixes", [])
        prefix_display = ", ".join([f"`{p}`" for p in default_prefixes])
        error_channel_id = bot.config.get("error_log_channel", None)
        error_channel = bot.get_channel(int(error_channel_id)) if error_channel_id else None

        config_info = [f"**Default Prefixes:** {prefix_display}", f"**Error Log Channel:** {error_channel.mention if error_channel else 'Not set'}"]
        embed.add_field(name="Configuration", value="\n".join(config_info), inline=False)

        await interaction.response.edit_message(embed=embed, view=view)


class BotPrefixModal(ui.Modal, title="Manage Bot Prefix"):
    """Modal for adding or editing bot prefixes."""

    def __init__(self, is_edit: bool = False, current_prefix: str = "", prefix_index: int = None):
        super().__init__()
        self.is_edit = is_edit
        self.prefix_index = prefix_index

        title_text = "Edit Bot Prefix" if is_edit else "Add Bot Prefix"
        self.title = title_text

        self.prefix_input = ui.TextInput(
            label="Prefix", placeholder="Enter command prefix (e.g., ! or >)", required=True, max_length=5, default=current_prefix
        )
        self.add_item(self.prefix_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle prefix add/edit."""
        new_prefix = self.prefix_input.value.strip()

        if not new_prefix:
            await interaction.response.send_message("❌ Prefix cannot be empty", ephemeral=True)
            return

        bot = interaction.client

        prefixes = bot.config.get("prefixes", [])

        if self.is_edit and self.prefix_index is not None:
            # Edit existing prefix
            if self.prefix_index >= len(prefixes):
                await interaction.response.send_message("❌ Prefix no longer exists.", ephemeral=True)
                return
            old_prefix = prefixes[self.prefix_index]
            prefixes[self.prefix_index] = new_prefix
            action = f"updated from `{old_prefix}` to `{new_prefix}`"
        else:
            # Add new prefix
            if new_prefix in prefixes:
                await interaction.response.send_message(f"❌ Prefix `{new_prefix}` already exists.", ephemeral=True)
                return
            prefixes.append(new_prefix)
            action = f"added: `{new_prefix}`"

        bot.config.config["prefixes"] = prefixes
        bot.config.save_config()

        await interaction.response.send_message(
            f"✅ Bot prefix {action}\n\n*Click 'Refresh' in the prefix management view to see the updated list.*", ephemeral=True
        )


class CogManagementView(View):
    """View for managing cogs globally."""

    def __init__(self):
        super().__init__(timeout=900)
        self.selected_cog = None
        self.status_message = None

        # Cog selector dropdown
        self.cog_select = ui.Select(
            placeholder="Select a cog to manage...",
            options=[
                discord.SelectOption(label="Loading...", value="loading", description="Please wait while cogs are loaded")
            ],  # Will be populated dynamically
            custom_id="cog_selector",
        )
        self.cog_select.callback = self.select_cog
        self.add_item(self.cog_select)

        # Action buttons
        self.enable_btn = Button(label="Enable/Disable", style=discord.ButtonStyle.primary, emoji="🔄", custom_id="toggle_cog", disabled=True)
        self.enable_btn.callback = self.toggle_cog
        self.add_item(self.enable_btn)

        self.visibility_btn = Button(
            label="Set Visibility", style=discord.ButtonStyle.secondary, emoji="👁️", custom_id="set_visibility", disabled=True
        )
        self.visibility_btn.callback = self.set_visibility
        self.add_item(self.visibility_btn)

        self.control_btn = Button(label="Load/Unload/Reload", style=discord.ButtonStyle.secondary, emoji="⚡", custom_id="control_cog", disabled=True)
        self.control_btn.callback = self.control_cog
        self.add_item(self.control_btn)

        # Back button
        back_btn = Button(label="Back", style=discord.ButtonStyle.gray, emoji="⬅️", custom_id="back_to_bot_settings")
        back_btn.callback = self.back_to_bot_settings
        self.add_item(back_btn)

    async def update_display(self, interaction: discord.Interaction):
        """Update the embed and populate cog selector."""
        bot = interaction.client

        all_cogs = bot.cog_manager.get_all_cogs_with_config()

        # Populate cog selector
        self.cog_select.options = []
        if all_cogs:
            for cog_name in sorted(all_cogs.keys()):
                config = all_cogs[cog_name]
                enabled = config.get("enabled", False)
                loaded = f"thetower.bot.cogs.{cog_name}" in bot.extensions
                public = config.get("public", False)

                # Create description showing status
                status_parts = []
                if enabled:
                    status_parts.append("✅")
                else:
                    status_parts.append("❌")

                if loaded:
                    status_parts.append("🟢")
                else:
                    status_parts.append("🔴")

                if public:
                    status_parts.append("🌐")
                else:
                    status_parts.append("🔒")

                description = " ".join(status_parts)

                option = discord.SelectOption(label=cog_name, value=cog_name, description=description)
                self.cog_select.options.append(option)
        else:
            # Add placeholder option when no cogs exist
            option = discord.SelectOption(label="No cogs available", value="none", description="No cogs found in the system")
            self.cog_select.options.append(option)

        # Update embed
        embed = discord.Embed(
            title="⚙️ Cog Management",
            description="View all cogs and their status. Select a cog from the dropdown to manage it.",
            color=discord.Color.blue(),
        )

        # Show status message if any
        if self.status_message:
            embed.add_field(name="Status", value=self.status_message, inline=False)
            self.status_message = None  # Clear after displaying

        # Show all cogs status
        if all_cogs:
            cog_status_lines = []
            for cog_name in sorted(all_cogs.keys()):
                config = all_cogs[cog_name]
                enabled = config.get("enabled", False)
                loaded = f"thetower.bot.cogs.{cog_name}" in bot.extensions
                public = config.get("public", False)

                # Create status indicators
                status_parts = []
                if enabled:
                    status_parts.append("✅")
                else:
                    status_parts.append("❌")

                if loaded:
                    status_parts.append("🟢")
                else:
                    status_parts.append("🔴")

                if public:
                    status_parts.append("🌐")
                else:
                    status_parts.append("🔒")

                status = " ".join(status_parts)

                # Highlight selected cog
                if self.selected_cog == cog_name:
                    cog_status_lines.append(f"**`{cog_name}`** {status} ← Selected")
                else:
                    cog_status_lines.append(f"`{cog_name}` {status}")

            embed.add_field(name=f"All Cogs ({len(all_cogs)})", value="\n".join(cog_status_lines), inline=False)

            # Show selected cog details if any
            if self.selected_cog and self.selected_cog in all_cogs:
                config = all_cogs[self.selected_cog]
                enabled = config.get("enabled", False)
                loaded = f"thetower.bot.cogs.{self.selected_cog}" in bot.extensions
                public = config.get("public", False)

                embed.add_field(
                    name=f"Details: {self.selected_cog}",
                    value=f"**Enabled:** {'✅ Yes' if enabled else '❌ No'}\n"
                    f"**Loaded:** {'🟢 Yes' if loaded else '🔴 No'}\n"
                    f"**Visibility:** {'🌐 Public' if public else '🔒 Private'}",
                    inline=False,
                )
        else:
            embed.add_field(name="Cogs", value="No cogs found in the system", inline=False)

        # Enable/disable action buttons based on selection
        has_selection = self.selected_cog is not None
        has_cogs = len(all_cogs) > 0
        self.cog_select.disabled = not has_cogs
        self.enable_btn.disabled = not (has_selection and has_cogs)
        self.visibility_btn.disabled = not (has_selection and has_cogs)
        self.control_btn.disabled = not (has_selection and has_cogs)

        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.NotFound:
            # Interaction has expired, ignore the error
            pass

    async def select_cog(self, interaction: discord.Interaction):
        """Handle cog selection."""
        selected_value = self.cog_select.values[0] if self.cog_select.values else None
        if selected_value in ["none", "loading"]:
            self.selected_cog = None
        else:
            self.selected_cog = selected_value
        await self.update_display(interaction)

    async def toggle_cog(self, interaction: discord.Interaction):
        """Toggle a cog's enabled/disabled status."""
        if not self.selected_cog:
            await interaction.response.send_message("❌ No cog selected.", ephemeral=True)
            return

        bot = interaction.client

        config = bot.cog_manager.config.get_bot_owner_cog_config(self.selected_cog)
        currently_enabled = config.get("enabled", False)
        new_state = not currently_enabled

        bot.cog_manager.config.set_bot_owner_cog_enabled(self.selected_cog, new_state)

        # Defer the response to handle potentially long-running operations
        await interaction.response.defer()

        # If enabling, try to load; if disabling, unload
        if new_state:
            await bot.cog_manager.load_cog(self.selected_cog)
            action = "enabled"
        else:
            await bot.cog_manager.unload_cog(self.selected_cog)
            action = "disabled"

        self.status_message = f"✅ Cog `{self.selected_cog}` has been {action}."

        # Send follow-up message since we deferred
        embed = discord.Embed(
            title="⚙️ Cog Management",
            description="View all cogs and their status. Select a cog from the dropdown to manage it.",
            color=discord.Color.blue(),
        )

        # Add status message
        embed.add_field(name="Status", value=self.status_message, inline=False)
        self.status_message = None  # Clear after displaying

        # Re-populate the view for the follow-up
        all_cogs = bot.cog_manager.get_all_cogs_with_config()

        # Update cog selector options
        self.cog_select.options = []
        if all_cogs:
            for cog_name in sorted(all_cogs.keys()):
                config = all_cogs[cog_name]
                enabled = config.get("enabled", False)
                loaded = f"thetower.bot.cogs.{cog_name}" in bot.extensions
                public = config.get("public", False)

                # Create description showing status
                status_parts = []
                if enabled:
                    status_parts.append("✅")
                else:
                    status_parts.append("❌")

                if loaded:
                    status_parts.append("🟢")
                else:
                    status_parts.append("🔴")

                if public:
                    status_parts.append("🌐")
                else:
                    status_parts.append("🔒")

                description = " ".join(status_parts)

                option = discord.SelectOption(label=cog_name, value=cog_name, description=description)
                self.cog_select.options.append(option)

        # Show all cogs status
        if all_cogs:
            cog_status_lines = []
            for cog_name in sorted(all_cogs.keys()):
                config = all_cogs[cog_name]
                enabled = config.get("enabled", False)
                loaded = f"thetower.bot.cogs.{cog_name}" in bot.extensions
                public = config.get("public", False)

                # Create status indicators
                status_parts = []
                if enabled:
                    status_parts.append("✅")
                else:
                    status_parts.append("❌")

                if loaded:
                    status_parts.append("🟢")
                else:
                    status_parts.append("🔴")

                if public:
                    status_parts.append("🌐")
                else:
                    status_parts.append("🔒")

                status = " ".join(status_parts)

                # Highlight selected cog
                if self.selected_cog == cog_name:
                    cog_status_lines.append(f"**`{cog_name}`** {status} ← Selected")
                else:
                    cog_status_lines.append(f"`{cog_name}` {status}")

            embed.add_field(name=f"All Cogs ({len(all_cogs)})", value="\n".join(cog_status_lines), inline=False)

            # Show selected cog details if any
            if self.selected_cog and self.selected_cog in all_cogs:
                config = all_cogs[self.selected_cog]
                enabled = config.get("enabled", False)
                loaded = f"thetower.bot.cogs.{self.selected_cog}" in bot.extensions
                public = config.get("public", False)

                embed.add_field(
                    name=f"Details: {self.selected_cog}",
                    value=f"**Enabled:** {'✅ Yes' if enabled else '❌ No'}\n"
                    f"**Loaded:** {'🟢 Yes' if loaded else '🔴 No'}\n"
                    f"**Visibility:** {'🌐 Public' if public else '🔒 Private'}",
                    inline=False,
                )

        # Enable/disable action buttons based on selection
        has_selection = self.selected_cog is not None
        has_cogs = len(all_cogs) > 0
        self.cog_select.disabled = not has_cogs
        self.enable_btn.disabled = not (has_selection and has_cogs)
        self.visibility_btn.disabled = not (has_selection and has_cogs)
        self.control_btn.disabled = not (has_selection and has_cogs)

        await interaction.followup.send(embed=embed, view=self)

    async def set_visibility(self, interaction: discord.Interaction):
        """Set a cog's visibility with granular server control."""
        if not self.selected_cog:
            await interaction.response.send_message("❌ No cog selected.", ephemeral=True)
            return

        # Create visibility management view
        view = CogVisibilityView(self.selected_cog)
        await view.update_display(interaction)

    async def control_cog(self, interaction: discord.Interaction):
        """Load/unload/reload a cog."""
        if not self.selected_cog:
            await interaction.response.send_message("❌ No cog selected.", ephemeral=True)
            return

        bot = interaction.client

        # Check actual extension loading state instead of relying on loaded_cogs list
        extension_name = f"thetower.bot.cogs.{self.selected_cog}"
        loaded = extension_name in bot.extensions

        if loaded:
            # Offer reload or unload
            view = View(timeout=900)

            reload_btn = Button(label="Reload", style=discord.ButtonStyle.primary, emoji="🔄", custom_id="reload_cog")
            reload_btn.callback = self.do_reload
            view.add_item(reload_btn)

            unload_btn = Button(label="Unload", style=discord.ButtonStyle.danger, emoji="🛑", custom_id="unload_cog")
            unload_btn.callback = self.do_unload
            view.add_item(unload_btn)

            await interaction.response.send_message(f"What would you like to do with `{self.selected_cog}`?", view=view, ephemeral=True)
        else:
            # Defer the response for potentially long-running load operation
            await interaction.response.defer()

            # Try to load
            success = await bot.cog_manager.load_cog(self.selected_cog)
            if success:
                self.status_message = f"✅ Cog `{self.selected_cog}` loaded successfully."
            else:
                self.status_message = f"❌ Failed to load cog `{self.selected_cog}`. Check logs for details."

            # Send follow-up with updated display
            embed = discord.Embed(
                title="⚙️ Cog Management",
                description="View all cogs and their status. Select a cog from the dropdown to manage it.",
                color=discord.Color.blue(),
            )

            # Add status message
            embed.add_field(name="Status", value=self.status_message, inline=False)
            self.status_message = None  # Clear after displaying

            # Re-populate the view for the follow-up
            all_cogs = bot.cog_manager.get_all_cogs_with_config()

            # Update cog selector options
            self.cog_select.options = []
            if all_cogs:
                for cog_name in sorted(all_cogs.keys()):
                    config = all_cogs[cog_name]
                    enabled = config.get("enabled", False)
                    loaded = f"thetower.bot.cogs.{cog_name}" in bot.extensions
                    public = config.get("public", False)

                    # Create description showing status
                    status_parts = []
                    if enabled:
                        status_parts.append("✅")
                    else:
                        status_parts.append("❌")

                    if loaded:
                        status_parts.append("🟢")
                    else:
                        status_parts.append("🔴")

                    if public:
                        status_parts.append("🌐")
                    else:
                        status_parts.append("🔒")

                    description = " ".join(status_parts)

                    option = discord.SelectOption(label=cog_name, value=cog_name, description=description)
                    self.cog_select.options.append(option)

            # Show all cogs status
            if all_cogs:
                cog_status_lines = []
                for cog_name in sorted(all_cogs.keys()):
                    config = all_cogs[cog_name]
                    enabled = config.get("enabled", False)
                    loaded = f"thetower.bot.cogs.{cog_name}" in bot.extensions
                    public = config.get("public", False)

                    # Create status indicators
                    status_parts = []
                    if enabled:
                        status_parts.append("✅")
                    else:
                        status_parts.append("❌")

                    if loaded:
                        status_parts.append("🟢")
                    else:
                        status_parts.append("🔴")

                    if public:
                        status_parts.append("🌐")
                    else:
                        status_parts.append("🔒")

                    status = " ".join(status_parts)

                    # Highlight selected cog
                    if self.selected_cog == cog_name:
                        cog_status_lines.append(f"**`{cog_name}`** {status} ← Selected")
                    else:
                        cog_status_lines.append(f"`{cog_name}` {status}")

                embed.add_field(name=f"All Cogs ({len(all_cogs)})", value="\n".join(cog_status_lines), inline=False)

                # Show selected cog details if any
                if self.selected_cog and self.selected_cog in all_cogs:
                    config = all_cogs[self.selected_cog]
                    enabled = config.get("enabled", False)
                    loaded = f"thetower.bot.cogs.{self.selected_cog}" in bot.extensions
                    public = config.get("public", False)

                    embed.add_field(
                        name=f"Details: {self.selected_cog}",
                        value=f"**Enabled:** {'✅ Yes' if enabled else '❌ No'}\n"
                        f"**Loaded:** {'🟢 Yes' if loaded else '🔴 No'}\n"
                        f"**Visibility:** {'🌐 Public' if public else '🔒 Private'}",
                        inline=False,
                    )

            # Enable/disable action buttons based on selection
            has_selection = self.selected_cog is not None
            has_cogs = len(all_cogs) > 0
            self.cog_select.disabled = not has_cogs
            self.enable_btn.disabled = not (has_selection and has_cogs)
            self.visibility_btn.disabled = not (has_selection and has_cogs)
            self.control_btn.disabled = not (has_selection and has_cogs)

            await interaction.followup.send(embed=embed, view=self)

    async def do_reload(self, interaction: discord.Interaction):
        """Reload the selected cog."""
        await interaction.response.defer()
        success = await interaction.client.cog_manager.reload_cog(self.selected_cog)
        if success:
            self.status_message = f"✅ Cog `{self.selected_cog}` reloaded successfully."
        else:
            self.status_message = f"❌ Failed to reload cog `{self.selected_cog}`. Check logs for details."

        # Send follow-up with updated display
        embed = discord.Embed(
            title="⚙️ Cog Management",
            description="View all cogs and their status. Select a cog from the dropdown to manage it.",
            color=discord.Color.blue(),
        )

        # Add status message
        embed.add_field(name="Status", value=self.status_message, inline=False)
        self.status_message = None  # Clear after displaying

        # Re-populate the view for the follow-up
        bot = interaction.client
        all_cogs = bot.cog_manager.get_all_cogs_with_config()

        # Update cog selector options
        self.cog_select.options = []
        if all_cogs:
            for cog_name in sorted(all_cogs.keys()):
                config = all_cogs[cog_name]
                enabled = config.get("enabled", False)
                loaded = f"thetower.bot.cogs.{cog_name}" in bot.extensions
                public = config.get("public", False)

                # Create description showing status
                status_parts = []
                if enabled:
                    status_parts.append("✅")
                else:
                    status_parts.append("❌")

                if loaded:
                    status_parts.append("🟢")
                else:
                    status_parts.append("🔴")

                if public:
                    status_parts.append("🌐")
                else:
                    status_parts.append("🔒")

                description = " ".join(status_parts)

                option = discord.SelectOption(label=cog_name, value=cog_name, description=description)
                self.cog_select.options.append(option)

        # Show all cogs status
        if all_cogs:
            cog_status_lines = []
            for cog_name in sorted(all_cogs.keys()):
                config = all_cogs[cog_name]
                enabled = config.get("enabled", False)
                loaded = f"thetower.bot.cogs.{cog_name}" in bot.extensions
                public = config.get("public", False)

                # Create status indicators
                status_parts = []
                if enabled:
                    status_parts.append("✅")
                else:
                    status_parts.append("❌")

                if loaded:
                    status_parts.append("🟢")
                else:
                    status_parts.append("🔴")

                if public:
                    status_parts.append("🌐")
                else:
                    status_parts.append("🔒")

                status = " ".join(status_parts)

                # Highlight selected cog
                if self.selected_cog == cog_name:
                    cog_status_lines.append(f"**`{cog_name}`** {status} ← Selected")
                else:
                    cog_status_lines.append(f"`{cog_name}` {status}")

            embed.add_field(name=f"All Cogs ({len(all_cogs)})", value="\n".join(cog_status_lines), inline=False)

            # Show selected cog details if any
            if self.selected_cog and self.selected_cog in all_cogs:
                config = all_cogs[self.selected_cog]
                enabled = config.get("enabled", False)
                loaded = f"thetower.bot.cogs.{self.selected_cog}" in bot.extensions
                public = config.get("public", False)

                embed.add_field(
                    name=f"Details: {self.selected_cog}",
                    value=f"**Enabled:** {'✅ Yes' if enabled else '❌ No'}\n"
                    f"**Loaded:** {'🟢 Yes' if loaded else '🔴 No'}\n"
                    f"**Visibility:** {'🌐 Public' if public else '🔒 Private'}",
                    inline=False,
                )

        # Enable/disable action buttons based on selection
        has_selection = self.selected_cog is not None
        has_cogs = len(all_cogs) > 0
        self.cog_select.disabled = not has_cogs
        self.enable_btn.disabled = not (has_selection and has_cogs)
        self.visibility_btn.disabled = not (has_selection and has_cogs)
        self.control_btn.disabled = not (has_selection and has_cogs)

        await interaction.followup.send(embed=embed, view=self)

    async def do_unload(self, interaction: discord.Interaction):
        """Unload the selected cog."""
        await interaction.response.defer()
        success = await interaction.client.cog_manager.unload_cog(self.selected_cog)
        if success:
            self.status_message = f"✅ Cog `{self.selected_cog}` unloaded successfully."
        else:
            self.status_message = f"❌ Failed to unload cog `{self.selected_cog}`. Check logs for details."

        # Send follow-up with updated display
        embed = discord.Embed(
            title="⚙️ Cog Management",
            description="View all cogs and their status. Select a cog from the dropdown to manage it.",
            color=discord.Color.blue(),
        )

        # Add status message
        embed.add_field(name="Status", value=self.status_message, inline=False)
        self.status_message = None  # Clear after displaying

        # Re-populate the view for the follow-up
        bot = interaction.client
        all_cogs = bot.cog_manager.get_all_cogs_with_config()

        # Update cog selector options
        self.cog_select.options = []
        if all_cogs:
            for cog_name in sorted(all_cogs.keys()):
                config = all_cogs[cog_name]
                enabled = config.get("enabled", False)
                loaded = f"thetower.bot.cogs.{cog_name}" in bot.extensions
                public = config.get("public", False)

                # Create description showing status
                status_parts = []
                if enabled:
                    status_parts.append("✅")
                else:
                    status_parts.append("❌")

                if loaded:
                    status_parts.append("🟢")
                else:
                    status_parts.append("🔴")

                if public:
                    status_parts.append("🌐")
                else:
                    status_parts.append("🔒")

                description = " ".join(status_parts)

                option = discord.SelectOption(label=cog_name, value=cog_name, description=description)
                self.cog_select.options.append(option)

        # Show all cogs status
        if all_cogs:
            cog_status_lines = []
            for cog_name in sorted(all_cogs.keys()):
                config = all_cogs[cog_name]
                enabled = config.get("enabled", False)
                loaded = f"thetower.bot.cogs.{cog_name}" in bot.extensions
                public = config.get("public", False)

                # Create status indicators
                status_parts = []
                if enabled:
                    status_parts.append("✅")
                else:
                    status_parts.append("❌")

                if loaded:
                    status_parts.append("🟢")
                else:
                    status_parts.append("🔴")

                if public:
                    status_parts.append("🌐")
                else:
                    status_parts.append("🔒")

                status = " ".join(status_parts)

                # Highlight selected cog
                if self.selected_cog == cog_name:
                    cog_status_lines.append(f"**`{cog_name}`** {status} ← Selected")
                else:
                    cog_status_lines.append(f"`{cog_name}` {status}")

            embed.add_field(name=f"All Cogs ({len(all_cogs)})", value="\n".join(cog_status_lines), inline=False)

            # Show selected cog details if any
            if self.selected_cog and self.selected_cog in all_cogs:
                config = all_cogs[self.selected_cog]
                enabled = config.get("enabled", False)
                loaded = f"thetower.bot.cogs.{self.selected_cog}" in bot.extensions
                public = config.get("public", False)

                embed.add_field(
                    name=f"Details: {self.selected_cog}",
                    value=f"**Enabled:** {'✅ Yes' if enabled else '❌ No'}\n"
                    f"**Loaded:** {'🟢 Yes' if loaded else '🔴 No'}\n"
                    f"**Visibility:** {'🌐 Public' if public else '🔒 Private'}",
                    inline=False,
                )

        # Enable/disable action buttons based on selection
        has_selection = self.selected_cog is not None
        has_cogs = len(all_cogs) > 0
        self.cog_select.disabled = not has_cogs
        self.enable_btn.disabled = not (has_selection and has_cogs)
        self.visibility_btn.disabled = not (has_selection and has_cogs)
        self.control_btn.disabled = not (has_selection and has_cogs)

        await interaction.followup.send(embed=embed, view=self)

    async def back_to_bot_settings(self, interaction: discord.Interaction):
        """Go back to bot settings."""
        # Recreate bot settings view
        view = BotOwnerSettingsView()

        embed = discord.Embed(title="🤖 Bot Settings", description="Global bot configuration", color=discord.Color.blue())

        # Import here to avoid circular imports
        bot = interaction.client

        # Basic bot info
        embed.add_field(
            name="Bot Information", value=f"**Name:** {bot.user.name}\n**ID:** {bot.user.id}\n**Servers:** {len(bot.guilds)}", inline=False
        )

        # Configuration settings
        default_prefixes = bot.config.get("prefixes", [])
        prefix_display = ", ".join([f"`{p}`" for p in default_prefixes])
        error_channel_id = bot.config.get("error_log_channel", None)
        error_channel = bot.get_channel(int(error_channel_id)) if error_channel_id else None

        config_info = [f"**Default Prefixes:** {prefix_display}", f"**Error Log Channel:** {error_channel.mention if error_channel else 'Not set'}"]
        embed.add_field(name="Configuration", value="\n".join(config_info), inline=False)

        await interaction.response.edit_message(embed=embed, view=view)
