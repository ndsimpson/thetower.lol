# Third-party
import discord

# Local
from thetower.bot.ui.context import SettingsViewContext


class RoleCacheSettingsView(discord.ui.View):
    """Settings view for role cache that integrates with global settings system."""

    def __init__(self, context: SettingsViewContext):
        super().__init__(timeout=900)  # 5 minute timeout
        self.cog = context.cog_instance
        self.guild_id = context.guild_id

    @discord.ui.button(label="View Settings", style=discord.ButtonStyle.primary, emoji="📊")
    async def view_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Display current role cache settings."""
        settings = self.cog.get_all_settings(guild_id=self.guild_id)

        embed = discord.Embed(title="Role Cache Settings", description="Current configuration for role caching system", color=discord.Color.blue())

        for name, value in settings.items():
            # Format durations in a more readable way for time-based settings
            if name in ["refresh_interval", "staleness_threshold", "save_interval"]:
                hours = value // 3600
                minutes = (value % 3600) // 60
                seconds = value % 60
                formatted_value = f"{hours}h {minutes}m {seconds}s ({value} seconds)"
                embed.add_field(name=name, value=formatted_value, inline=False)
            else:
                embed.add_field(name=name, value=str(value), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Refresh Interval", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def set_refresh_interval(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Set the refresh interval."""
        modal = SettingModal(self.cog, "refresh_interval", "Set Refresh Interval", "Enter refresh interval in seconds (minimum 60):")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Staleness Threshold", style=discord.ButtonStyle.secondary, emoji="⏰")
    async def set_staleness_threshold(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Set the staleness threshold."""
        modal = SettingModal(self.cog, "staleness_threshold", "Set Staleness Threshold", "Enter staleness threshold in seconds (minimum 60):")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Save Interval", style=discord.ButtonStyle.secondary, emoji="💾")
    async def set_save_interval(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Set the save interval."""
        modal = SettingModal(self.cog, "save_interval", "Set Save Interval", "Enter save interval in seconds (minimum 60):")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="View Status", style=discord.ButtonStyle.success, emoji="📈")
    async def view_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Display current operational status."""
        # Determine overall status
        has_errors = hasattr(self.cog, "_has_errors") and self.cog._has_errors

        embed = discord.Embed(
            title="Role Cache Status",
            description=f"Current status: {'❌ Error' if has_errors else '✅ Operational' if self.cog.is_ready else '⏳ Initializing'}",
            color=discord.Color.red() if has_errors else discord.Color.blue() if self.cog.is_ready else discord.Color.orange(),
        )

        # Add basic cache statistics
        guild_count = len(self.cog.member_roles)
        total_members = sum(len(guild_data) for guild_data in self.cog.member_roles.values())

        embed.add_field(name="Cache Overview", value=f"**Guilds Cached**: {guild_count}\n**Members Cached**: {total_members}", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


class SettingModal(discord.ui.Modal):
    """Modal for setting configuration values."""

    def __init__(self, cog, setting_name: str, title: str, label: str):
        super().__init__(title=title)
        self.cog = cog
        self.setting_name = setting_name

        self.value_input = discord.ui.TextInput(label=label, placeholder="Enter value in seconds...", required=True, min_length=1, max_length=10)
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission."""
        try:
            value = int(self.value_input.value)

            # Validate minimum value
            if value < 60:
                await interaction.response.send_message("❌ Value must be at least 60 seconds", ephemeral=True)
                return

            # Update the setting
            if self.setting_name == "refresh_interval":
                self.cog.refresh_interval = value
            elif self.setting_name == "staleness_threshold":
                self.cog.staleness_threshold = value
            elif self.setting_name == "save_interval":
                self.cog.save_interval = value

            # Save the setting
            self.cog.set_setting(self.setting_name, value, guild_id=interaction.guild_id)

            # Format confirmation message
            hours = value // 3600
            minutes = (value % 3600) // 60
            seconds = value % 60
            time_format = f"{hours}h {minutes}m {seconds}s"

            await interaction.response.send_message(f"✅ Set {self.setting_name} to {value} seconds ({time_format})", ephemeral=True)

            self.cog.logger.info(f"Settings changed via modal: {self.setting_name} set to {value} by {interaction.user}")

        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number", ephemeral=True)
        except Exception as e:
            self.cog.logger.error(f"Error updating setting {self.setting_name}: {e}", exc_info=True)
            await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)
