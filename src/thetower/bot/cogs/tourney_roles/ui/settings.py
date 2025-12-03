"""
Settings management views for the Tournament Roles cog.

This module contains:
- Settings view that integrates with the global settings system
- Configuration interfaces for all tournament role settings
"""

from __future__ import annotations

import discord
from discord import ui

from thetower.bot.ui.context import SettingsViewContext

from .core import TournamentRolesCore


class VerifiedRoleModal(ui.Modal, title="Set Verified Role"):
    """Modal for setting the verified role requirement."""

    role_input = ui.TextInput(
        label="Role Name or ID",
        placeholder="Enter role name or ID (leave blank to disable)",
        required=False,
        max_length=100,
    )

    def __init__(self, cog, guild_id: int, parent_view, original_interaction):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.parent_view = parent_view
        self.original_interaction = original_interaction

    async def on_submit(self, interaction: discord.Interaction):
        """Handle the modal submission."""
        guild = interaction.guild
        input_value = self.role_input.value.strip()

        # Handle blank input to disable verification
        if not input_value:
            self.cog.set_setting("verified_role_id", None, guild_id=self.guild_id)
            await interaction.response.send_message("✅ Verification role requirement removed", ephemeral=True)

            # Update the embed
            embed = await self.parent_view.get_embed()
            await self.original_interaction.edit_original_response(embed=embed, view=self.parent_view)
            return  # Try to find the role
        role = None

        # First, try as role ID
        if input_value.isdigit():
            role = guild.get_role(int(input_value))

        # If not found, try by name (case-insensitive)
        if not role:
            role = discord.utils.get(guild.roles, name=input_value)

        # If still not found, try partial match
        if not role:
            matching_roles = [r for r in guild.roles if input_value.lower() in r.name.lower()]
            if len(matching_roles) == 1:
                role = matching_roles[0]
            elif len(matching_roles) > 1:
                role_names = ", ".join([f"`{r.name}`" for r in matching_roles[:5]])
                more = f" and {len(matching_roles) - 5} more" if len(matching_roles) > 5 else ""
                await interaction.response.send_message(
                    f"❌ Multiple roles match '{input_value}': {role_names}{more}\n" f"Please be more specific or use the role ID.",
                    ephemeral=True,
                )
                return

        # Validate the role
        if not role:
            await interaction.response.send_message(
                f"❌ Could not find role '{input_value}'\n" f"Please enter a valid role name or ID.",
                ephemeral=True,
            )
            return

        if role.is_default():
            await interaction.response.send_message("❌ Cannot use @everyone as verification role", ephemeral=True)
            return

        if role.managed:
            await interaction.response.send_message(f"❌ Cannot use managed role {role.mention} (managed by bot/integration)", ephemeral=True)
            return

        # Set the role
        self.cog.set_setting("verified_role_id", str(role.id), guild_id=self.guild_id)
        await interaction.response.send_message(f"✅ Users must have {role.mention} role to be eligible", ephemeral=True)

        # Update the embed
        embed = await self.parent_view.get_embed()
        await self.original_interaction.edit_original_response(embed=embed, view=self.parent_view)


class LogChannelModal(ui.Modal, title="Set Log Channel"):
    """Modal for setting the log channel."""

    channel_input = ui.TextInput(
        label="Channel Name or ID",
        placeholder="Enter channel name or ID (leave blank to disable)",
        required=False,
        max_length=100,
    )

    def __init__(self, cog, guild_id: int, parent_view, original_interaction):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.parent_view = parent_view
        self.original_interaction = original_interaction

    async def on_submit(self, interaction: discord.Interaction):
        """Handle the modal submission."""
        guild = interaction.guild
        input_value = self.channel_input.value.strip()

        # Handle blank input to disable logging
        if not input_value:
            self.cog.set_setting("log_channel_id", None, guild_id=self.guild_id)
            await interaction.response.send_message("✅ Role update logging disabled", ephemeral=True)

            # Update the embed
            embed = await self.parent_view.get_embed()
            await self.original_interaction.edit_original_response(embed=embed, view=self.parent_view)
            return  # Try to find the channel
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

        # Check bot permissions
        permissions = channel.permissions_for(guild.me)
        if not permissions.send_messages:
            await interaction.response.send_message(f"❌ Bot doesn't have permission to send messages in {channel.mention}", ephemeral=True)
            return

        # Set the channel
        self.cog.set_setting("log_channel_id", str(channel.id), guild_id=self.guild_id)
        await interaction.response.send_message(f"✅ Role update logs will be sent to {channel.mention}", ephemeral=True)

        # Update the embed
        embed = await self.parent_view.get_embed()
        await self.original_interaction.edit_original_response(embed=embed, view=self.parent_view)


class TournamentRolesSettingsView(ui.View):
    """Settings view for tournament roles that integrates with global settings."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)
        self.guild_id = context.guild_id
        self.cog = context.cog_instance
        self.core = TournamentRolesCore(self.cog)

    async def get_settings_embed(self) -> discord.Embed:
        """Create the main settings embed."""
        embed = discord.Embed(
            title="Tournament Roles Settings", description="Configure tournament-based role assignment for this server", color=discord.Color.blue()
        )

        # Core Settings
        embed.add_field(name="Core Configuration", value=self._get_core_settings_text(), inline=False)

        # Update Settings
        embed.add_field(name="Update Settings", value=self._get_update_settings_text(), inline=False)

        # Processing Settings
        embed.add_field(name="Processing Settings", value=self._get_processing_settings_text(), inline=False)

        # Mode Settings
        embed.add_field(name="Operation Modes", value=self._get_mode_settings_text(), inline=False)

        # Logging Settings
        embed.add_field(name="Logging Configuration", value=self._get_logging_settings_text(), inline=False)

        return embed

    def _get_core_settings_text(self) -> str:
        """Get core settings text."""
        league_hierarchy = self.core.get_league_hierarchy(self.guild_id)
        verified_role_id = self.core.get_verified_role_id(self.guild_id)

        lines = []
        lines.append(f"**League Hierarchy:** {' → '.join(league_hierarchy)}")

        if verified_role_id:
            # Try to get role name
            guild = self.cog.bot.get_guild(self.guild_id)
            if guild:
                role = guild.get_role(int(verified_role_id))
                role_name = role.name if role else f"ID: {verified_role_id}"
                lines.append(f"**Verified Role Required:** {role_name}")
            else:
                lines.append(f"**Verified Role Required:** ID: {verified_role_id}")
        else:
            lines.append("**Verified Role Required:** None")

        roles_config = self.core.get_roles_config(self.guild_id)
        lines.append(f"**Configured Roles:** {len(roles_config)}")

        return "\n".join(lines)

    def _get_update_settings_text(self) -> str:
        """Get update settings text."""
        update_settings = self.core.get_update_settings(self.guild_id)

        lines = []
        interval = update_settings["update_interval"]

        lines.append(f"**Update Interval:** {self._format_duration(interval)}")
        lines.append(f"**Update on Startup:** {'Enabled' if update_settings['update_on_startup'] else 'Disabled'}")

        return "\n".join(lines)

    def _get_processing_settings_text(self) -> str:
        """Get processing settings text."""
        processing_settings = self.core.get_processing_settings(self.guild_id)

        lines = []
        lines.append(f"**Batch Size:** {processing_settings['process_batch_size']} users")
        lines.append(f"**Delay Between Batches:** {processing_settings['process_delay']}s")
        lines.append(f"**Error Retry Delay:** {self._format_duration(processing_settings['error_retry_delay'])}")

        return "\n".join(lines)

    def _get_mode_settings_text(self) -> str:
        """Get mode settings text."""
        dry_run = self.core.is_dry_run_enabled(self.guild_id)
        pause = self.cog.get_setting("pause", False, guild_id=self.guild_id)
        debug_logging = self.cog.get_setting("debug_logging", False, guild_id=self.guild_id)

        lines = []
        lines.append(f"**Dry Run Mode:** {'Enabled' if dry_run else 'Disabled'}")
        lines.append(f"**Updates Paused:** {'Yes' if pause else 'No'}")
        lines.append(f"**Debug Logging:** {'Enabled' if debug_logging else 'Disabled'}")

        return "\n".join(lines)

    def _get_logging_settings_text(self) -> str:
        """Get logging settings text."""
        logging_settings = self.core.get_logging_settings(self.guild_id)

        lines = []
        log_channel_id = logging_settings["log_channel_id"]
        if log_channel_id:
            guild = self.cog.bot.get_guild(self.guild_id)
            if guild:
                channel = guild.get_channel(int(log_channel_id))
                channel_name = channel.mention if channel else f"ID: {log_channel_id}"
                lines.append(f"**Log Channel:** {channel_name}")
            else:
                lines.append(f"**Log Channel:** ID: {log_channel_id}")
        else:
            lines.append("**Log Channel:** None")

        lines.append(f"**Log Batch Size:** {logging_settings['log_batch_size']} messages")
        lines.append(f"**Immediate Logging:** {'Enabled' if logging_settings['immediate_logging'] else 'Disabled'}")

        return "\n".join(lines)

    def _format_duration(self, seconds: int) -> str:
        """Format seconds into a human-readable duration."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        parts = []
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if secs or not parts:
            parts.append(f"{secs}s")

        return " ".join(parts)

    @ui.button(label="Core Settings", style=discord.ButtonStyle.primary, emoji="⚙️", row=0)
    async def core_settings(self, interaction: discord.Interaction, button: ui.Button):
        """Open core settings menu."""
        await interaction.response.defer()
        context = SettingsViewContext(guild_id=self.guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=False)
        view = CoreSettingsView(context)
        embed = await view.get_embed()
        await interaction.followup.edit_message(interaction.message.id, embed=embed, view=view)

    @ui.button(label="Update Settings", style=discord.ButtonStyle.primary, emoji="🔄", row=0)
    async def update_settings(self, interaction: discord.Interaction, button: ui.Button):
        """Open update settings menu."""
        await interaction.response.defer()
        context = SettingsViewContext(guild_id=self.guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=False)
        view = UpdateSettingsView(context)
        embed = await view.get_embed()
        await interaction.followup.edit_message(interaction.message.id, embed=embed, view=view)

    @ui.button(label="Processing Settings", style=discord.ButtonStyle.primary, emoji="⚡", row=0)
    async def processing_settings(self, interaction: discord.Interaction, button: ui.Button):
        """Open processing settings menu."""
        await interaction.response.defer()
        context = SettingsViewContext(guild_id=self.guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=False)
        view = ProcessingSettingsView(context)
        embed = await view.get_embed()
        await interaction.followup.edit_message(interaction.message.id, embed=embed, view=view)

    @ui.button(label="Mode Settings", style=discord.ButtonStyle.secondary, emoji="🎭", row=1)
    async def mode_settings(self, interaction: discord.Interaction, button: ui.Button):
        """Open mode settings menu."""
        await interaction.response.defer()
        context = SettingsViewContext(guild_id=self.guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=False)
        view = ModeSettingsView(context)
        embed = await view.get_embed()
        await interaction.followup.edit_message(interaction.message.id, embed=embed, view=view)

    @ui.button(label="Logging Settings", style=discord.ButtonStyle.secondary, emoji="📝", row=1)
    async def logging_settings(self, interaction: discord.Interaction, button: ui.Button):
        """Open logging settings menu."""
        await interaction.response.defer()
        context = SettingsViewContext(guild_id=self.guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=False)
        view = LoggingSettingsView(context)
        embed = await view.get_embed()
        await interaction.followup.edit_message(interaction.message.id, embed=embed, view=view)

    @ui.button(label="Back to Main", style=discord.ButtonStyle.gray, emoji="⬅️", row=2)
    async def back_to_main(self, interaction: discord.Interaction, button: ui.Button):
        """Go back to main settings view."""
        await interaction.response.defer()
        embed = await self.get_settings_embed()
        await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self)

    @ui.button(label="Admin Management", style=discord.ButtonStyle.primary, emoji="⚙️", row=3)
    async def admin_management(self, interaction: discord.Interaction, button: ui.Button):
        """Open admin management interface."""
        # Check permissions
        is_bot_owner = await self.cog.bot.is_owner(interaction.user)
        is_guild_owner = interaction.guild.owner_id == interaction.user.id
        has_manage_guild = interaction.user.guild_permissions.manage_guild

        if not (is_bot_owner or is_guild_owner or has_manage_guild):
            await interaction.response.send_message(
                "❌ You need `Manage Server` permission or be the server owner to access admin management.", ephemeral=True
            )
            return

        from .admin import AdminRoleManagementView

        embed = discord.Embed(
            title="Tournament Roles Management",
            description="Administrative tools for configuring tournament-based role assignment.",
            color=discord.Color.gold(),
        )

        embed.add_field(
            name="Available Actions",
            value="• **Add Role**: Configure a new tournament role\n"
            "• **Remove Role**: Remove an existing tournament role\n"
            "• **List Roles**: View all configured roles\n"
            "• **Set League Hierarchy**: Configure league priority order",
            inline=False,
        )

        view = AdminRoleManagementView(self.cog, self.guild_id, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class CoreSettingsView(ui.View):
    """View for core tournament roles settings."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)
        self.guild_id = context.guild_id
        self.cog = context.cog_instance
        self.core = TournamentRolesCore(self.cog)

    async def get_embed(self) -> discord.Embed:
        """Create the core settings embed."""
        embed = discord.Embed(title="Core Settings", description="Configure fundamental tournament role settings", color=discord.Color.blue())

        # League Hierarchy
        league_hierarchy = self.core.get_league_hierarchy(self.guild_id)
        embed.add_field(name="League Hierarchy", value=f"```{', '.join(league_hierarchy)}```", inline=False)

        # Verified Role
        verified_role_id = self.core.get_verified_role_id(self.guild_id)
        if verified_role_id:
            guild = self.cog.bot.get_guild(self.guild_id)
            if guild:
                role = guild.get_role(int(verified_role_id))
                role_text = role.name if role else f"ID: {verified_role_id}"
            else:
                role_text = f"ID: {verified_role_id}"
            embed.add_field(name="Verified Role Required", value=role_text, inline=True)
        else:
            embed.add_field(name="Verified Role Required", value="None", inline=True)

        # Role Count
        roles_config = self.core.get_roles_config(self.guild_id)
        embed.add_field(name="Configured Roles", value=str(len(roles_config)), inline=True)

        return embed

    @ui.button(label="Set League Hierarchy", style=discord.ButtonStyle.primary, emoji="🏆")
    async def set_league_hierarchy(self, interaction: discord.Interaction, button: ui.Button):
        """Set the league hierarchy."""
        current_hierarchy = self.core.get_league_hierarchy(self.guild_id)
        from .core import LeagueHierarchyModal

        modal = LeagueHierarchyModal(current_hierarchy)
        await interaction.response.send_modal(modal)

        # Wait for modal result
        await modal.wait()
        if hasattr(modal, "result"):
            self.cog.set_setting("league_hierarchy", modal.result, guild_id=self.guild_id)
            embed = await self.get_embed()
            await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self)

    @ui.button(label="Set Verified Role", style=discord.ButtonStyle.secondary, emoji="✅")
    async def set_verified_role(self, interaction: discord.Interaction, button: ui.Button):
        """Set the verified role requirement."""
        modal = VerifiedRoleModal(self.cog, self.guild_id, self, interaction)
        await interaction.response.send_modal(modal)

    @ui.button(label="Back", style=discord.ButtonStyle.gray, emoji="⬅️")
    async def back(self, interaction: discord.Interaction, button: ui.Button):
        """Go back to main settings."""
        context = SettingsViewContext(guild_id=self.guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=False)
        main_view = TournamentRolesSettingsView(context)
        embed = await main_view.get_settings_embed()
        await interaction.response.edit_message(embed=embed, view=main_view)


class UpdateSettingsView(ui.View):
    """View for update-related settings."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)
        self.guild_id = context.guild_id
        self.cog = context.cog_instance
        self.core = TournamentRolesCore(self.cog)

    async def get_embed(self) -> discord.Embed:
        """Create the update settings embed."""
        embed = discord.Embed(title="Update Settings", description="Configure automatic role update behavior", color=discord.Color.blue())

        update_settings = self.core.get_update_settings(self.guild_id)

        embed.add_field(name="Update Interval", value=self._format_duration(update_settings["update_interval"]), inline=True)
        embed.add_field(name="Update on Startup", value="Enabled" if update_settings["update_on_startup"] else "Disabled", inline=True)

        return embed

    def _format_duration(self, seconds: int) -> str:
        """Format seconds into a human-readable duration."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        parts = []
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if secs or not parts:
            parts.append(f"{secs}s")

        return " ".join(parts)

    @ui.button(label="Set Update Interval", style=discord.ButtonStyle.primary, emoji="⏰")
    async def set_update_interval(self, interaction: discord.Interaction, button: ui.Button):
        """Set the update interval."""
        modal = DurationModal("Update Interval", "update_interval", "How often to update roles (in hours)")
        await interaction.response.send_modal(modal)

        await modal.wait()
        if hasattr(modal, "result"):
            # Convert hours to seconds
            hours = modal.result
            seconds = hours * 3600
            self.cog.set_setting("update_interval", seconds, guild_id=self.guild_id)

            embed = await self.get_embed()
            await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self)

    @ui.button(label="Toggle Startup Updates", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def toggle_startup_updates(self, interaction: discord.Interaction, button: ui.Button):
        """Toggle update on startup."""
        current = self.cog.get_setting("update_on_startup", True, guild_id=self.guild_id)
        self.cog.set_setting("update_on_startup", not current, guild_id=self.guild_id)

        status = "enabled" if not current else "disabled"
        await interaction.response.send_message(f"✅ Update on startup {status}", ephemeral=True)

        embed = await self.get_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    @ui.button(label="Back", style=discord.ButtonStyle.gray, emoji="⬅️")
    async def back(self, interaction: discord.Interaction, button: ui.Button):
        """Go back to main settings."""
        context = SettingsViewContext(guild_id=self.guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=False)
        main_view = TournamentRolesSettingsView(context)
        embed = await main_view.get_settings_embed()
        await interaction.response.edit_message(embed=embed, view=main_view)


class DurationModal(ui.Modal, title="Set Duration"):
    """Modal for setting duration values."""

    def __init__(self, title_text: str, setting_key: str, description: str):
        super().__init__(title=title_text)
        self.setting_key = setting_key

        self.duration_input = ui.TextInput(label="Duration (hours)", placeholder="Enter number of hours", required=True)
        self.add_item(self.duration_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission."""
        try:
            hours = float(self.duration_input.value)
            if hours <= 0:
                await interaction.response.send_message("❌ Duration must be positive", ephemeral=True)
                return

            self.result = hours
            await interaction.response.send_message(f"✅ {self.title} set to {hours} hours", ephemeral=True)

        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number", ephemeral=True)


class ProcessingSettingsView(ui.View):
    """View for processing-related settings."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)
        self.guild_id = context.guild_id
        self.cog = context.cog_instance
        self.core = TournamentRolesCore(self.cog)

    async def get_embed(self) -> discord.Embed:
        """Create the processing settings embed."""
        embed = discord.Embed(title="Processing Settings", description="Configure role update processing behavior", color=discord.Color.blue())

        processing_settings = self.core.get_processing_settings(self.guild_id)

        embed.add_field(name="Batch Size", value=f"{processing_settings['process_batch_size']} users per batch", inline=True)
        embed.add_field(name="Batch Delay", value=f"{processing_settings['process_delay']} seconds", inline=True)
        embed.add_field(name="Error Retry Delay", value=self._format_duration(processing_settings["error_retry_delay"]), inline=True)

        return embed

    def _format_duration(self, seconds: int) -> str:
        """Format seconds into a human-readable duration."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        parts = []
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if secs or not parts:
            parts.append(f"{secs}s")

        return " ".join(parts)

    @ui.button(label="Set Batch Size", style=discord.ButtonStyle.primary, emoji="👥")
    async def set_batch_size(self, interaction: discord.Interaction, button: ui.Button):
        """Set the processing batch size."""
        modal = NumberModal("Batch Size", "process_batch_size", "Users to process per batch (10-200)", 10, 200)
        await interaction.response.send_modal(modal)

        await modal.wait()
        if hasattr(modal, "result"):
            self.cog.set_setting("process_batch_size", modal.result, guild_id=self.guild_id)
            embed = await self.get_embed()
            await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self)

    @ui.button(label="Set Batch Delay", style=discord.ButtonStyle.primary, emoji="⏱️")
    async def set_batch_delay(self, interaction: discord.Interaction, button: ui.Button):
        """Set the delay between batches."""
        modal = NumberModal("Batch Delay", "process_delay", "Seconds to wait between batches (0-30)", 0, 30)
        await interaction.response.send_modal(modal)

        await modal.wait()
        if hasattr(modal, "result"):
            self.cog.set_setting("process_delay", modal.result, guild_id=self.guild_id)
            embed = await self.get_embed()
            await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self)

    @ui.button(label="Set Retry Delay", style=discord.ButtonStyle.primary, emoji="🔄")
    async def set_retry_delay(self, interaction: discord.Interaction, button: ui.Button):
        """Set the error retry delay."""
        modal = DurationModal("Error Retry Delay", "error_retry_delay", "Delay before retrying after errors (in minutes)")
        await interaction.response.send_modal(modal)

        await modal.wait()
        if hasattr(modal, "result"):
            minutes = modal.result
            seconds = minutes * 60
            self.cog.set_setting("error_retry_delay", seconds, guild_id=self.guild_id)
        embed = await self.get_embed()
        await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self)

    @ui.button(label="Back", style=discord.ButtonStyle.gray, emoji="⬅️")
    async def back(self, interaction: discord.Interaction, button: ui.Button):
        """Go back to main settings."""
        context = SettingsViewContext(guild_id=self.guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=False)
        main_view = TournamentRolesSettingsView(context)
        embed = await main_view.get_settings_embed()
        await interaction.response.edit_message(embed=embed, view=main_view)


class NumberModal(ui.Modal, title="Set Number Value"):
    """Modal for setting numeric values."""

    def __init__(self, title_text: str, setting_key: str, description: str, min_val: int, max_val: int):
        super().__init__(title=title_text)
        self.setting_key = setting_key
        self.min_val = min_val
        self.max_val = max_val

        self.number_input = ui.TextInput(
            label=f"Value ({min_val}-{max_val})", placeholder=f"Enter a number between {min_val} and {max_val}", required=True
        )
        self.add_item(self.number_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission."""
        try:
            value = int(self.number_input.value)
            if not (self.min_val <= value <= self.max_val):
                await interaction.response.send_message(f"❌ Value must be between {self.min_val} and {self.max_val}", ephemeral=True)
                return

            self.result = value
            await interaction.response.send_message(f"✅ {self.title} set to {value}", ephemeral=True)

        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number", ephemeral=True)


class ModeSettingsView(ui.View):
    """View for mode-related settings."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)
        self.guild_id = context.guild_id
        self.cog = context.cog_instance
        self.core = TournamentRolesCore(self.cog)

    async def get_embed(self) -> discord.Embed:
        """Create the mode settings embed."""
        embed = discord.Embed(title="Operation Modes", description="Configure operational modes and debugging", color=discord.Color.blue())

        dry_run = self.core.is_dry_run_enabled(self.guild_id)
        pause = self.cog.get_setting("pause", False, guild_id=self.guild_id)
        debug_logging = self.cog.get_setting("debug_logging", False, guild_id=self.guild_id)

        embed.add_field(
            name="Dry Run Mode", value="Enabled - No actual changes will be made" if dry_run else "Disabled - Changes will be applied", inline=False
        )
        embed.add_field(
            name="Updates Paused", value="Yes - Automatic updates are disabled" if pause else "No - Automatic updates are active", inline=False
        )
        embed.add_field(
            name="Debug Logging", value="Enabled - Detailed logging active" if debug_logging else "Disabled - Normal logging", inline=False
        )

        return embed

    @ui.button(label="Toggle Dry Run", style=discord.ButtonStyle.danger, emoji="🧪")
    async def toggle_dry_run(self, interaction: discord.Interaction, button: ui.Button):
        """Toggle dry run mode."""
        current = self.core.is_dry_run_enabled(self.guild_id)
        self.cog.set_setting("dry_run", not current, guild_id=self.guild_id)

        status = "enabled" if not current else "disabled"
        await interaction.response.send_message(f"✅ Dry run mode {status}", ephemeral=True)

        embed = await self.get_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    @ui.button(label="Toggle Pause", style=discord.ButtonStyle.secondary, emoji="⏸️")
    async def toggle_pause(self, interaction: discord.Interaction, button: ui.Button):
        """Toggle update pause."""
        current = self.cog.get_setting("pause", False, guild_id=self.guild_id)
        self.cog.set_setting("pause", not current, guild_id=self.guild_id)

        status = "paused" if not current else "resumed"
        await interaction.response.send_message(f"✅ Automatic updates {status}", ephemeral=True)

        embed = await self.get_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    @ui.button(label="Toggle Debug Logging", style=discord.ButtonStyle.secondary, emoji="🔍")
    async def toggle_debug_logging(self, interaction: discord.Interaction, button: ui.Button):
        """Toggle debug logging."""
        current = self.cog.get_setting("debug_logging", False, guild_id=self.guild_id)
        self.cog.set_setting("debug_logging", not current, guild_id=self.guild_id)

        status = "enabled" if not current else "disabled"
        await interaction.response.send_message(f"✅ Debug logging {status}", ephemeral=True)

        embed = await self.get_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    @ui.button(label="Back", style=discord.ButtonStyle.gray, emoji="⬅️")
    async def back(self, interaction: discord.Interaction, button: ui.Button):
        """Go back to main settings."""
        context = SettingsViewContext(guild_id=self.guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=False)
        main_view = TournamentRolesSettingsView(context)
        embed = await main_view.get_settings_embed()
        await interaction.response.edit_message(embed=embed, view=main_view)


class LoggingSettingsView(ui.View):
    """View for logging-related settings."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)
        self.guild_id = context.guild_id
        self.cog = context.cog_instance
        self.core = TournamentRolesCore(self.cog)

    async def get_embed(self) -> discord.Embed:
        """Create the logging settings embed."""
        embed = discord.Embed(title="Logging Configuration", description="Configure role update logging behavior", color=discord.Color.blue())

        logging_settings = self.core.get_logging_settings(self.guild_id)

        # Log Channel
        log_channel_id = logging_settings["log_channel_id"]
        if log_channel_id:
            guild = self.cog.bot.get_guild(self.guild_id)
            if guild:
                channel = guild.get_channel(int(log_channel_id))
                channel_text = channel.mention if channel else f"ID: {log_channel_id}"
            else:
                channel_text = f"ID: {log_channel_id}"
            embed.add_field(name="Log Channel", value=channel_text, inline=True)
        else:
            embed.add_field(name="Log Channel", value="None", inline=True)

        embed.add_field(name="Log Batch Size", value=f"{logging_settings['log_batch_size']} messages", inline=True)
        embed.add_field(name="Immediate Logging", value="Enabled" if logging_settings["immediate_logging"] else "Disabled", inline=True)

        return embed

    @ui.button(label="Set Log Channel", style=discord.ButtonStyle.primary, emoji="📝")
    async def set_log_channel(self, interaction: discord.Interaction, button: ui.Button):
        """Set the logging channel."""
        modal = LogChannelModal(self.cog, self.guild_id, self, interaction)
        await interaction.response.send_modal(modal)

    @ui.button(label="Set Batch Size", style=discord.ButtonStyle.primary, emoji="📊")
    async def set_batch_size(self, interaction: discord.Interaction, button: ui.Button):
        """Set the log batch size."""
        modal = NumberModal("Log Batch Size", "log_batch_size", "Messages to batch before sending (1-50)", 1, 50)
        await interaction.response.send_modal(modal)

        await modal.wait()
        if hasattr(modal, "result"):
            self.cog.set_setting("log_batch_size", modal.result, guild_id=self.guild_id)
            embed = await self.get_embed()
            await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self)

    @ui.button(label="Toggle Immediate Logging", style=discord.ButtonStyle.secondary, emoji="⚡")
    async def toggle_immediate_logging(self, interaction: discord.Interaction, button: ui.Button):
        """Toggle immediate logging."""
        current = self.cog.get_setting("immediate_logging", True, guild_id=self.guild_id)
        self.cog.set_setting("immediate_logging", not current, guild_id=self.guild_id)

        status = "enabled" if not current else "disabled"
        await interaction.response.send_message(f"✅ Immediate logging {status}", ephemeral=True)

        embed = await self.get_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    @ui.button(label="Back", style=discord.ButtonStyle.gray, emoji="⬅️")
    async def back(self, interaction: discord.Interaction, button: ui.Button):
        """Go back to main settings."""
        context = SettingsViewContext(guild_id=self.guild_id, cog_instance=self.cog, interaction=interaction, is_bot_owner=False)
        main_view = TournamentRolesSettingsView(context)
        embed = await main_view.get_settings_embed()
        await interaction.response.edit_message(embed=embed, view=main_view)
