import subprocess
from discord.ext import commands
from discord.ext.commands import Context
import discord
from discord import app_commands
from fish_bot.basecog import BaseCog


class ServiceControl(BaseCog, name="Service Control"):
    """Commands for managing system services.

    Provides functionality to restart specific services and stop the bot.
    Only authorized users can access these commands.
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.logger.info("Initializing ServiceControl")

        # Define settings with descriptions
        settings_config = {
            "restartable_services": ([], "List of services that can be controlled"),
            "service_timeout": (30, "Timeout in seconds for service operations"),
            "enable_service_control": (True, "Enable/disable all service control commands")
        }

        # Initialize settings
        for name, (value, description) in settings_config.items():
            if not self.has_setting(name):
                self.set_setting(name, value)

        # Load settings into instance variables
        self._load_settings()

    def _load_settings(self) -> None:
        """Load settings into instance variables."""
        self.restartable_services = self.get_setting("restartable_services")
        self.service_timeout = self.get_setting("service_timeout")
        self.enable_service_control = self.get_setting("enable_service_control")

    async def _execute_service_command(self, action: str, service: str) -> tuple[bool, str]:
        """Execute a systemctl command."""
        if not self.enable_service_control or self._is_paused:
            return False, "Service control is currently disabled or paused"

        cmd = ["systemctl", action, service]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.service_timeout)
            self._last_operation = self.get_current_time()
            self._operation_count += 1
            return result.returncode == 0, result.stderr if result.returncode != 0 else ""
        except subprocess.TimeoutExpired:
            return False, f"Operation timed out after {self.service_timeout} seconds"
        except Exception as e:
            return False, str(e)

    @commands.group(name="service", invoke_without_command=True)
    async def service(self, ctx):
        """Service control operations."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @service.command(name="status")
    async def status_command(self, ctx: Context) -> None:
        """Display operational status and information."""
        # Determine status and color
        if not self.is_ready:
            status_emoji = "⏳"
            status_text = "Initializing"
            embed_color = discord.Color.orange()
        elif self._has_errors:
            status_emoji = "❌"
            status_text = "Error"
            embed_color = discord.Color.red()
        else:
            status_emoji = "✅"
            status_text = "Operational"
            embed_color = discord.Color.blue()

        embed = discord.Embed(
            title="Service Control Status",
            description="Current operational state and statistics",
            color=embed_color
        )

        # Add status information
        status_value = [f"{status_emoji} Status: {status_text}"]
        if self._last_operation:
            time_since = self.format_relative_time(self._last_operation)
            status_value.append(f"🕒 Last Operation: {time_since}")

        embed.add_field(
            name="System State",
            value="\n".join(status_value),
            inline=False
        )

        embed.add_field(
            name="Available Services",
            value=", ".join(self.restartable_services) or "No services configured",
            inline=False
        )

        embed.add_field(
            name="Statistics",
            value=f"Operations completed: {self._operation_count}",
            inline=False
        )

        await ctx.send(embed=embed)

    @service.command(name="settings")
    @app_commands.describe(
        setting_name="Setting to change",
        value="New value for the setting"
    )
    async def settings_command(self, ctx: Context, setting_name: str = None, *, value: str = None):
        """Manage service control settings."""
        if setting_name is None:
            settings = self.get_all_settings()
            embed = discord.Embed(title="Service Control Settings")
            for name, val in settings.items():
                embed.add_field(name=name, value=str(val), inline=False)
            return await ctx.send(embed=embed)

        try:
            if not self.has_setting(setting_name):
                valid_settings = list(self.get_all_settings().keys())
                return await ctx.send(f"Invalid setting. Valid options: {', '.join(valid_settings)}")

            if value is None:
                return await ctx.send(f"{setting_name}: {self.get_setting(setting_name)}")

            # Convert value based on setting type
            if setting_name == "restartable_services":
                value = [s.strip() for s in value.split(',')]

            # Save the setting
            self.set_setting(setting_name, value)

            # Update instance variable if it exists
            if hasattr(self, setting_name):
                setattr(self, setting_name, value)

            await ctx.send(f"✅ Set {setting_name} to {value}")
            self.logger.info(f"Setting changed: {setting_name} = {value}")

        except Exception as e:
            self.logger.error(f"Error changing setting: {e}")
            await ctx.send("An error occurred changing the setting")

    @service.command(name="pause")
    async def pause_command(self, ctx: Context):
        """Pause/unpause service control operations."""
        self._is_paused = not self._is_paused
        state = "paused" if self._is_paused else "resumed"
        await ctx.send(f"Service control operations {state}")

    @service.command(name="restart")
    async def restart_service(self, ctx: Context, servicename: str):
        """Restart a system service."""
        if servicename not in self.restartable_services:
            return await ctx.send("Service not found in allowed services list.")

        await ctx.send(f"Restarting {servicename}")
        success, error = await self._execute_service_command("restart", servicename)
        await ctx.send(f"Successfully restarted {servicename}" if success else f"Error restarting {servicename}: {error}")

    @service.command(name="start")
    async def start_service(self, ctx: Context, servicename: str):
        """Start a system service."""
        if servicename not in self.restartable_services:
            return await ctx.send("Service not found in allowed services list.")

        await ctx.send(f"Starting {servicename}")
        success, error = await self._execute_service_command("start", servicename)
        await ctx.send(f"Successfully started {servicename}" if success else f"Error starting {servicename}: {error}")

    @service.command(name="stop")
    async def stop_service(self, ctx: Context, servicename: str):
        """Stop a system service."""
        if servicename not in self.restartable_services:
            return await ctx.send("Service not found in allowed services list.")

        await ctx.send(f"Stopping {servicename}")
        success, error = await self._execute_service_command("stop", servicename)
        await ctx.send(f"Successfully stopped {servicename}" if success else f"Error stopping {servicename}: {error}")

    async def cog_initialize(self) -> None:
        """Initialize the cog."""
        self.logger.info("Initializing service control")
        try:
            async with self.task_tracker.task_context("Initialization"):
                # Initialize parent
                await super().cog_initialize()

                # Load settings
                self.task_tracker.update_task_status("Initialization", "Loading Settings")
                self._load_settings()

                # Mark as ready
                self.set_ready(True)
                self.logger.info("Service control initialization complete")

        except Exception as e:
            self._has_errors = True
            self.logger.error(f"Initialization failed: {e}", exc_info=True)
            raise


async def setup(bot) -> None:
    await bot.add_cog(ServiceControl(bot))
