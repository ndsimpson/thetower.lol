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
        error_channel_id = bot.config.get("error_log_channel", None)
        error_channel = bot.get_channel(int(error_channel_id)) if error_channel_id else None

        config_info = [
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

        # Cog management button
        cog_mgmt_btn = Button(label="Cog Management", style=discord.ButtonStyle.secondary, emoji="⚙️", custom_id="cog_management")
        cog_mgmt_btn.callback = self.show_cog_management
        self.add_item(cog_mgmt_btn)

        # Cog reload button (quick access)
        cog_reload_btn = Button(label="Cog Reload", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="cog_reload")
        cog_reload_btn.callback = self.show_cog_reload
        self.add_item(cog_reload_btn)

        # Error log channel button
        error_channel_btn = Button(label="Set Error Channel", style=discord.ButtonStyle.secondary, emoji="📝", custom_id="set_error_channel")
        error_channel_btn.callback = self.set_error_channel
        self.add_item(error_channel_btn)

        # Back button
        back_btn = Button(label="Back", style=discord.ButtonStyle.gray, emoji="⬅️", custom_id="back_to_main")
        back_btn.callback = self.back_to_main
        self.add_item(back_btn)

    async def show_cog_reload(self, interaction: discord.Interaction):
        """Show the quick cog reload interface."""
        # Create cog reload view
        view = CogReloadView()
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
            bot = select_interaction.client
            if channel_select.values:
                channel = channel_select.values[0]
                bot.config.config["error_log_channel"] = str(channel.id)
                bot.config.save_config()
                await select_interaction.response.send_message(f"✅ Error log channel set to {channel.mention}", ephemeral=True)
            else:
                # Clear the channel
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


class GuildOwnerSettingsView(View):
    """Settings view for guild owners with limited access."""

    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = guild_id

        # Cog settings button
        cog_settings_btn = Button(label="Cog Settings", style=discord.ButtonStyle.secondary, emoji="⚙️", custom_id="cog_settings")
        cog_settings_btn.callback = self.manage_cog_settings
        self.add_item(cog_settings_btn)

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

        # Enabled Features
        bot = interaction.client

        enabled_cogs = bot.cog_manager.config.get_guild_enabled_cogs(self.guild_id)

        if enabled_cogs:
            cogs_list = ", ".join(enabled_cogs)
            embed.add_field(name="Enabled Features", value=f"**Cogs:** {len(enabled_cogs)} enabled\n**List:** {cogs_list}", inline=False)
        else:
            embed.add_field(name="Enabled Features", value="**Cogs:** 0 enabled", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

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

        await interaction.response.edit_message(embed=embed, view=view)

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

        await interaction.followup.send(embed=embed, view=self, ephemeral=True)

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

            # All cogs now use the unified BaseSettingsView pattern
            view = settings_view_class(context)

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

        # Enabled Features
        bot = interaction.client
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


class AddVisibilityView(View):
    """View for selecting a cog to add visibility to a guild."""

    def __init__(self, guild_id: int, available_cogs: list):
        super().__init__(timeout=900)
        self.guild_id = guild_id
        self.available_cogs = available_cogs

        # Cog selector dropdown
        self.cog_select = ui.Select(
            placeholder="Select a cog to authorize...",
            options=[],
            custom_id="add_cog_selector",
        )
        self.cog_select.callback = self.select_cog
        self.add_item(self.cog_select)

        # Back button
        back_btn = Button(label="Back", style=discord.ButtonStyle.gray, emoji="⬅️", custom_id="back_to_guild_visibility")
        back_btn.callback = self.back_to_guild_visibility
        self.add_item(back_btn)

        # Populate options
        for cog_name in sorted(available_cogs):
            option = discord.SelectOption(label=cog_name, value=cog_name, description="Click to authorize this cog")
            self.cog_select.options.append(option)

    async def update_display(self, interaction: discord.Interaction):
        """Update the embed."""
        bot = interaction.client
        guild = bot.get_guild(self.guild_id)

        embed = discord.Embed(
            title="➕ Add Cog Visibility",
            description=f"Select a cog to authorize for server `{guild.name if guild else 'Unknown'}`.",
            color=discord.Color.green(),
        )

        embed.add_field(
            name=f"Available Cogs ({len(self.available_cogs)})",
            value="\n".join([f"• `{cog}`" for cog in sorted(self.available_cogs)]),
            inline=False,
        )

        await interaction.response.edit_message(embed=embed, view=self)

    async def select_cog(self, interaction: discord.Interaction):
        """Handle cog selection and authorization."""
        selected_cog = self.cog_select.values[0] if self.cog_select.values else None
        if not selected_cog:
            return

        bot = interaction.client
        guild = bot.get_guild(self.guild_id)

        try:
            bot.cog_manager.config.add_guild_cog_authorization(self.guild_id, selected_cog, allow=True)
            await interaction.response.send_message(
                f"✅ Successfully authorized cog `{selected_cog}` for server `{guild.name if guild else 'Unknown'}`.", ephemeral=True
            )
        except Exception as e:
            print(f"Error authorizing {selected_cog} for guild {self.guild_id}: {e}")
            await interaction.response.send_message(f"❌ Failed to authorize cog `{selected_cog}`.", ephemeral=True)

    async def back_to_guild_visibility(self, interaction: discord.Interaction):
        """Go back to guild visibility view."""
        view = GuildCogVisibilityView()
        view.selected_guild = str(self.guild_id)
        await view.update_display(interaction)


class RemoveVisibilityView(View):
    """View for selecting a cog to remove visibility from a guild."""

    def __init__(self, guild_id: int, authorized_cogs: list):
        super().__init__(timeout=900)
        self.guild_id = guild_id
        self.authorized_cogs = authorized_cogs

        # Cog selector dropdown
        self.cog_select = ui.Select(
            placeholder="Select a cog to revoke...",
            options=[],
            custom_id="remove_cog_selector",
        )
        self.cog_select.callback = self.select_cog
        self.add_item(self.cog_select)

        # Back button
        back_btn = Button(label="Back", style=discord.ButtonStyle.gray, emoji="⬅️", custom_id="back_to_guild_visibility")
        back_btn.callback = self.back_to_guild_visibility
        self.add_item(back_btn)

        # Populate options
        for cog_name in sorted(authorized_cogs):
            option = discord.SelectOption(label=cog_name, value=cog_name, description="Click to revoke authorization")
            self.cog_select.options.append(option)

    async def update_display(self, interaction: discord.Interaction):
        """Update the embed."""
        bot = interaction.client
        guild = bot.get_guild(self.guild_id)

        embed = discord.Embed(
            title="➖ Remove Cog Visibility",
            description=f"Select a cog to revoke authorization for server `{guild.name if guild else 'Unknown'}`.",
            color=discord.Color.red(),
        )

        embed.add_field(
            name=f"Authorized Cogs ({len(self.authorized_cogs)})",
            value="\n".join([f"• `{cog}`" for cog in sorted(self.authorized_cogs)]),
            inline=False,
        )

        await interaction.response.edit_message(embed=embed, view=self)

    async def select_cog(self, interaction: discord.Interaction):
        """Handle cog selection and revocation."""
        selected_cog = self.cog_select.values[0] if self.cog_select.values else None
        if not selected_cog:
            return

        bot = interaction.client
        guild = bot.get_guild(self.guild_id)

        try:
            # Try to remove from allowed list
            success = bot.cog_manager.config.remove_guild_cog_authorization(self.guild_id, selected_cog, from_allowed=True)
            if success:
                await interaction.response.send_message(
                    f"❌ Successfully revoked authorization for cog `{selected_cog}` in server `{guild.name if guild else 'Unknown'}`.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(f"ℹ️ Cog `{selected_cog}` was not authorized for this server.", ephemeral=True)
        except Exception as e:
            print(f"Error revoking {selected_cog} for guild {self.guild_id}: {e}")
            await interaction.response.send_message(f"❌ Failed to revoke authorization for cog `{selected_cog}`.", ephemeral=True)

    async def back_to_guild_visibility(self, interaction: discord.Interaction):
        """Go back to guild visibility view."""
        view = GuildCogVisibilityView()
        view.selected_guild = str(self.guild_id)
        await view.update_display(interaction)


class GuildCogVisibilityView(View):
    """View for managing cog visibility for a specific guild with individual operations."""

    def __init__(self):
        super().__init__(timeout=900)
        self.selected_guild = None
        self.status_message = None

        # Guild selector dropdown
        self.guild_select = ui.Select(
            placeholder="Select a server to manage...",
            options=[discord.SelectOption(label="Loading...", value="loading", description="Please wait while servers are loaded")],
            custom_id="guild_selector",
        )
        self.guild_select.callback = self.select_guild
        self.add_item(self.guild_select)

        # Action buttons
        self.add_visibility_btn = Button(
            label="Add Visibility", style=discord.ButtonStyle.primary, emoji="➕", custom_id="add_visibility", disabled=True
        )
        self.add_visibility_btn.callback = self.add_visibility
        self.add_item(self.add_visibility_btn)

        self.remove_visibility_btn = Button(
            label="Remove Visibility", style=discord.ButtonStyle.danger, emoji="➖", custom_id="remove_visibility", disabled=True
        )
        self.remove_visibility_btn.callback = self.remove_visibility
        self.add_item(self.remove_visibility_btn)

        # Back button
        back_btn = Button(label="Back to Cog Management", style=discord.ButtonStyle.gray, emoji="⬅️", custom_id="back_to_cog_mgmt")
        back_btn.callback = self.back_to_cog_management
        self.add_item(back_btn)

    async def update_display(self, interaction: discord.Interaction):
        """Update the embed and populate selectors."""
        bot = interaction.client

        embed = discord.Embed(
            title="🏰 Guild Cog Visibility",
            description="Manage which cogs are available for specific servers. Select a server, then use the buttons to add or remove cog visibility.",
            color=discord.Color.blue(),
        )

        # Show status message if any
        if self.status_message:
            embed.add_field(name="Status", value=self.status_message, inline=False)
            self.status_message = None  # Clear after displaying

        # Populate guild selector
        self.guild_select.options = []
        for guild in sorted(bot.guilds, key=lambda g: g.name):
            option = discord.SelectOption(label=f"{guild.name}", value=str(guild.id), description=f"ID: {guild.id} | Members: {guild.member_count}")
            self.guild_select.options.append(option)

        # Update display based on guild selection
        if self.selected_guild:
            try:
                guild_id = int(self.selected_guild)
                guild = bot.get_guild(guild_id)
                if guild:
                    # Get all enabled cogs
                    all_cogs = bot.cog_manager.get_all_cogs_with_config()
                    enabled_cogs = {name: config for name, config in all_cogs.items() if config.get("enabled", False)}

                    # Get current authorizations for this guild
                    guild_auths = {}
                    for cog_name in enabled_cogs.keys():
                        guild_auth = bot.cog_manager.config.get_cog_guild_authorizations(cog_name)
                        authorized = guild_id in guild_auth["allowed"]
                        disallowed = guild_id in guild_auth["disallowed"]
                        if authorized:
                            guild_auths[cog_name] = "authorized"
                        elif disallowed:
                            guild_auths[cog_name] = "disallowed"
                        else:
                            guild_auths[cog_name] = "default"

                    # Show guild info
                    embed.add_field(
                        name=f"Selected Server: {guild.name}",
                        value=f"**ID:** {guild.id}\n**Members:** {guild.member_count}",
                        inline=False,
                    )

                    # Show detailed cog status list for enabled cogs
                    cog_status_lines = []
                    for cog_name in sorted(enabled_cogs.keys()):
                        config = enabled_cogs[cog_name]
                        loaded = f"thetower.bot.cogs.{cog_name}" in bot.extensions
                        public = config.get("public", False)
                        auth_status = guild_auths[cog_name]

                        # Create status indicators
                        auth_indicator = {"authorized": "✅", "disallowed": "🚫", "default": "⏸️"}.get(auth_status, "❓")

                        load_indicator = "🟢" if loaded else "🔴"
                        visibility_indicator = "🌐" if public else "🔒"

                        status = f"{auth_indicator} {load_indicator} {visibility_indicator}"
                        cog_status_lines.append(f"`{cog_name}` {status}")

                    if cog_status_lines:
                        embed.add_field(
                            name=f"Cog Status ({len(enabled_cogs)} enabled cogs)",
                            value="\n".join(cog_status_lines),
                            inline=False,
                        )

                    embed.add_field(
                        name="Actions",
                        value="Use the buttons below to add or remove cog visibility for this server.",
                        inline=False,
                    )

            except ValueError:
                pass
        else:
            embed.add_field(
                name="Instructions",
                value="Select a server from the dropdown above to manage cog visibility for that server.",
                inline=False,
            )

        # Enable/disable buttons based on guild selection
        has_guild = self.selected_guild is not None
        self.add_visibility_btn.disabled = not has_guild
        self.remove_visibility_btn.disabled = not has_guild

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

    async def add_visibility(self, interaction: discord.Interaction):
        """Show available cogs to add visibility for."""
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

        # Get available cogs (not currently authorized)
        all_cogs = bot.cog_manager.get_all_cogs_with_config()
        enabled_cogs = {name: config for name, config in all_cogs.items() if config.get("enabled", False)}

        available_cogs = []
        for cog_name in enabled_cogs.keys():
            guild_auth = bot.cog_manager.config.get_cog_guild_authorizations(cog_name)
            authorized = guild_id in guild_auth["allowed"]
            if not authorized:  # Only show cogs that are not already authorized
                available_cogs.append(cog_name)

        if not available_cogs:
            await interaction.response.send_message(f"ℹ️ All available cogs are already authorized for `{guild.name}`.", ephemeral=True)
            return

        # Create view with available cogs
        view = AddVisibilityView(guild_id, available_cogs)
        await view.update_display(interaction)

    async def remove_visibility(self, interaction: discord.Interaction):
        """Show currently visible cogs to remove visibility for."""
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

        # Get currently authorized cogs
        all_cogs = bot.cog_manager.get_all_cogs_with_config()
        enabled_cogs = {name: config for name, config in all_cogs.items() if config.get("enabled", False)}

        authorized_cogs = []
        for cog_name in enabled_cogs.keys():
            guild_auth = bot.cog_manager.config.get_cog_guild_authorizations(cog_name)
            authorized = guild_id in guild_auth["allowed"]
            if authorized:  # Only show cogs that are currently authorized
                authorized_cogs.append(cog_name)

        if not authorized_cogs:
            await interaction.response.send_message(f"ℹ️ No cogs are currently authorized for `{guild.name}`.", ephemeral=True)
            return

        # Create view with authorized cogs
        view = RemoveVisibilityView(guild_id, authorized_cogs)
        await view.update_display(interaction)

    async def back_to_cog_management(self, interaction: discord.Interaction):
        """Go back to cog management view."""
        # Recreate cog management view
        view = CogManagementView()
        await view.update_display(interaction)


class CogReloadView(View):
    """Quick reload view for loaded cogs."""

    def __init__(self):
        super().__init__(timeout=900)
        self.selected_cog = None

        # Cog selector dropdown (only loaded cogs)
        self.cog_select = ui.Select(
            placeholder="Select a cog to reload...",
            options=[discord.SelectOption(label="Loading...", value="loading", description="Please wait...")],
            custom_id="reload_cog_selector",
        )
        self.cog_select.callback = self.select_cog
        self.add_item(self.cog_select)

        # Reload button
        self.reload_btn = Button(label="Reload Cog", style=discord.ButtonStyle.primary, emoji="🔄", custom_id="reload_selected_cog", disabled=True)
        self.reload_btn.callback = self.reload_selected_cog
        self.add_item(self.reload_btn)

        # Back button
        back_btn = Button(label="Back", style=discord.ButtonStyle.gray, emoji="⬅️", custom_id="back_to_bot_settings")
        back_btn.callback = self.back_to_bot_settings
        self.add_item(back_btn)

    async def update_display(self, interaction: discord.Interaction):
        """Update the display with current loaded cogs."""
        bot = interaction.client

        # Get only loaded cogs
        loaded_cogs = []
        for extension_name in bot.extensions:
            if extension_name.startswith("thetower.bot.cogs."):
                cog_name = extension_name.replace("thetower.bot.cogs.", "")
                loaded_cogs.append(cog_name)

        # Populate dropdown
        self.cog_select.options = []
        if loaded_cogs:
            for cog_name in sorted(loaded_cogs):
                option = discord.SelectOption(label=cog_name, value=cog_name, description="🟢 Loaded", emoji="🔄")
                self.cog_select.options.append(option)
            self.cog_select.disabled = False
        else:
            # No loaded cogs
            option = discord.SelectOption(label="No cogs loaded", value="none", description="No cogs are currently loaded")
            self.cog_select.options.append(option)
            self.cog_select.disabled = True

        # Create embed
        embed = discord.Embed(
            title="🔄 Quick Cog Reload", description="Select a loaded cog from the dropdown and click Reload.", color=discord.Color.green()
        )

        if loaded_cogs:
            cog_list = "\n".join([f"🟢 `{cog}`" for cog in sorted(loaded_cogs)])
            embed.add_field(name=f"Loaded Cogs ({len(loaded_cogs)})", value=cog_list, inline=False)
        else:
            embed.add_field(name="No Loaded Cogs", value="No cogs are currently loaded.", inline=False)

        # Show selected cog if any
        if self.selected_cog:
            embed.add_field(name="Selected", value=f"🔄 `{self.selected_cog}` - Ready to reload", inline=False)

        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.NotFound:
            # Interaction expired
            pass

    async def select_cog(self, interaction: discord.Interaction):
        """Handle cog selection from dropdown."""
        selected_value = self.cog_select.values[0] if self.cog_select.values else None
        if selected_value in ["none", "loading"]:
            self.selected_cog = None
            self.reload_btn.disabled = True
        else:
            self.selected_cog = selected_value
            self.reload_btn.disabled = False
        await self.update_display(interaction)

    async def reload_selected_cog(self, interaction: discord.Interaction):
        """Reload the selected cog."""
        if not self.selected_cog:
            await interaction.response.send_message("❌ No cog selected.", ephemeral=True)
            return

        await interaction.response.defer()

        bot = interaction.client
        success = await bot.cog_manager.reload_cog(self.selected_cog)

        # Create result embed
        if success:
            embed = discord.Embed(title="✅ Cog Reloaded", description=f"Successfully reloaded `{self.selected_cog}`", color=discord.Color.green())
        else:
            embed = discord.Embed(
                title="❌ Reload Failed", description=f"Failed to reload `{self.selected_cog}`. Check logs for details.", color=discord.Color.red()
            )

        # Keep selection and button enabled for quick successive reloads
        # self.selected_cog remains unchanged
        # self.reload_btn.disabled remains False

        # Update the view
        loaded_cogs = []
        for extension_name in bot.extensions:
            if extension_name.startswith("thetower.bot.cogs."):
                cog_name = extension_name.replace("thetower.bot.cogs.", "")
                loaded_cogs.append(cog_name)

        if loaded_cogs:
            cog_list = "\n".join([f"🟢 `{cog}`" for cog in sorted(loaded_cogs)])
            embed.add_field(name=f"Loaded Cogs ({len(loaded_cogs)})", value=cog_list, inline=False)

        # Show currently selected cog
        if self.selected_cog:
            embed.add_field(name="Selected", value=f"🔄 `{self.selected_cog}` - Ready to reload again", inline=False)

        await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=self)

    async def back_to_bot_settings(self, interaction: discord.Interaction):
        """Return to bot settings view."""
        view = BotOwnerSettingsView()

        embed = discord.Embed(title="🤖 Bot Settings", description="Global bot configuration", color=discord.Color.blue())

        bot = interaction.client

        # Basic bot info
        embed.add_field(
            name="Bot Information", value=f"**Name:** {bot.user.name}\n**ID:** {bot.user.id}\n**Servers:** {len(bot.guilds)}", inline=False
        )

        # Configuration settings
        error_channel_id = bot.config.get("error_log_channel", None)
        error_channel = bot.get_channel(int(error_channel_id)) if error_channel_id else None

        config_info = [
            f"**Error Log Channel:** {error_channel.mention if error_channel else 'Not set'}",
            f"**Load All Cogs:** {'Yes' if bot.config.get('load_all_cogs', False) else 'No'}",
        ]
        embed.add_field(name="Configuration", value="\n".join(config_info), inline=False)

        await interaction.response.edit_message(embed=embed, view=view)


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

        self.bulk_visibility_btn = Button(
            label="Bulk Guild Visibility", style=discord.ButtonStyle.secondary, emoji="🏰", custom_id="bulk_guild_visibility"
        )
        self.bulk_visibility_btn.callback = self.bulk_guild_visibility
        self.add_item(self.bulk_visibility_btn)

        # Refresh cog sources button
        self.refresh_sources_btn = Button(
            label="Refresh Cog Sources", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="refresh_cog_sources"
        )
        self.refresh_sources_btn.callback = self.refresh_cog_sources
        self.add_item(self.refresh_sources_btn)

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
        self.bulk_visibility_btn.disabled = not has_cogs

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

        # Update the existing message instead of sending a followup
        embed = discord.Embed(
            title="⚙️ Cog Management",
            description="View all cogs and their status. Select a cog from the dropdown to manage it.",
            color=discord.Color.blue(),
        )

        # Add status message
        embed.add_field(name="Status", value=self.status_message, inline=False)
        self.status_message = None  # Clear after displaying

        # Re-populate the view for the update
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

        await interaction.followup.send(embed=embed, view=self, ephemeral=True)

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

            await interaction.followup.send(embed=embed, view=self, ephemeral=True)

    async def bulk_guild_visibility(self, interaction: discord.Interaction):
        """Open bulk guild visibility management view."""
        # Create bulk visibility management view
        view = GuildCogVisibilityView()
        await view.update_display(interaction)

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

        await interaction.followup.send(embed=embed, view=self, ephemeral=True)

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

        await interaction.followup.send(embed=embed, view=self, ephemeral=True)

    async def refresh_cog_sources(self, interaction: discord.Interaction):
        """Refresh cog sources to discover newly installed packages."""
        await interaction.response.defer()

        bot = interaction.client

        # Refresh the cog sources
        changes = bot.cog_manager.refresh_cog_sources()

        # Build status message
        status_parts = []
        if changes["added"]:
            status_parts.append("**Added sources:**\n" + "\n".join(f"  • {src}" for src in changes["added"]))
        if changes["removed"]:
            status_parts.append("**Removed sources:**\n" + "\n".join(f"  • {src}" for src in changes["removed"]))

        if not changes["added"] and not changes["removed"]:
            self.status_message = "ℹ️ No changes detected. All cog sources are up to date."
        else:
            self.status_message = "✅ Cog sources refreshed!\n\n" + "\n\n".join(status_parts)

        # Update the existing message (not a new one)
        await self.update_display_edit(interaction)

    async def update_display_edit(self, interaction: discord.Interaction):
        """Update display by editing the original message (used after deferred responses)."""
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
        else:
            option = discord.SelectOption(label="No cogs available", value="none", description="No cogs found in the system")
            self.cog_select.options.append(option)

        # Create embed
        embed = discord.Embed(
            title="⚙️ Cog Management",
            description="View all cogs and their status. Select a cog from the dropdown to manage it.",
            color=discord.Color.blue(),
        )

        # Show status message if any
        if self.status_message:
            embed.add_field(name="Status", value=self.status_message, inline=False)
            self.status_message = None

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
        self.bulk_visibility_btn.disabled = not has_cogs

        await interaction.edit_original_response(embed=embed, view=self)

    async def update_display_followup(self, interaction: discord.Interaction):
        """Update display via followup (used after deferred responses)."""
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
        else:
            option = discord.SelectOption(label="No cogs available", value="none", description="No cogs found in the system")
            self.cog_select.options.append(option)

        # Create embed
        embed = discord.Embed(
            title="⚙️ Cog Management",
            description="View all cogs and their status. Select a cog from the dropdown to manage it.",
            color=discord.Color.blue(),
        )

        # Show status message if any
        if self.status_message:
            embed.add_field(name="Status", value=self.status_message, inline=False)
            self.status_message = None

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
        self.bulk_visibility_btn.disabled = not has_cogs

        await interaction.followup.send(embed=embed, view=self, ephemeral=True)

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
        error_channel_id = bot.config.get("error_log_channel", None)
        error_channel = bot.get_channel(int(error_channel_id)) if error_channel_id else None

        config_info = [
            f"**Error Log Channel:** {error_channel.mention if error_channel else 'Not set'}",
            f"**Load All Cogs:** {'Yes' if bot.config.get('load_all_cogs', False) else 'No'}",
        ]
        embed.add_field(name="Configuration", value="\n".join(config_info), inline=False)

        await interaction.response.edit_message(embed=embed, view=view)
