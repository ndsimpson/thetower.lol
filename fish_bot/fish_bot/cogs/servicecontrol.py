import subprocess
from discord.ext import commands
from discord.ext.commands import Context
from fish_bot.basecog import BaseCog


class ServiceControl(BaseCog, name="Service Control"):
    """Commands for managing system services.

    Provides functionality to restart specific services and stop the bot.
    Only authorized users can access these commands.
    """

    def __init__(self, bot):
        super().__init__(bot)

    @commands.group(name="service", invoke_without_command=True)
    async def service(self, ctx):
        """Service control operations.

        Available subcommands:
        - restart: Restart a specific system service
        - stop: Stop the bot service
        """
        if ctx.invoked_subcommand is None:
            # List all available subcommands
            commands_list = [command.name for command in self.service.commands]
            await ctx.send(f"Available subcommands: {', '.join(commands_list)}")

    @service.command(name="restart")
    async def restart_service(self, ctx: Context, servicename: str):
        """Restart a system service."""
        if servicename in self.config.get("restartable_services", []):
            await ctx.send(f"Restarting {servicename}")
            try:
                result = subprocess.run(
                    ["systemctl", "restart", servicename],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    await ctx.send(f"Successfully restarted {servicename}")
                else:
                    await ctx.send(f"Error restarting {servicename}: {result.stderr}")
            except Exception as e:
                await ctx.send(f"Failed to restart service: {str(e)}")
        else:
            await ctx.send("Service not found.")

    @service.command(name="start")
    async def start_service(self, ctx: Context, servicename: str):
        """Start a system service."""
        if servicename in self.config.get("restartable_services", []):
            await ctx.send(f"Starting {servicename}")
            try:
                result = subprocess.run(
                    ["systemctl", "start", servicename],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    await ctx.send(f"Successfully started {servicename}")
                else:
                    await ctx.send(f"Error starting {servicename}: {result.stderr}")
            except Exception as e:
                await ctx.send(f"Failed to start service: {str(e)}")
        else:
            await ctx.send("Service not found.")

    @service.command(name="stop")
    async def stop_service(self, ctx: Context, servicename: str):
        """Stop a system service."""
        if servicename in self.config.get("restartable_services", []):
            await ctx.send(f"Stopping {servicename}")
            try:
                result = subprocess.run(
                    ["systemctl", "stop", servicename],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    await ctx.send(f"Successfully stopped {servicename}")
                else:
                    await ctx.send(f"Error stopping {servicename}: {result.stderr}")
            except Exception as e:
                await ctx.send(f"Failed to stop service: {str(e)}")
        else:
            await ctx.send("Service not found.")


async def setup(bot) -> None:
    await bot.add_cog(ServiceControl(bot))
