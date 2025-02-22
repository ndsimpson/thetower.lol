import subprocess
from discord.ext import commands
from discord.ext.commands import Context
from fish_bot.basecog import BaseCog
from fish_bot import const


class ServiceControl(BaseCog, name="Service Control"):
    """Commands for managing system services.

    Provides functionality to restart specific services and stop the bot.
    Only authorized users can access these commands.
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot

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
    async def restart(self, ctx, servicename):
        """Restart a system service."""
        if servicename in self.config["restartable_services"]:
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

    @commands.command()
    async def stop(self, ctx: Context):
        """Stop the bot service."""
        await ctx.send(f"{ctx.author} requested a stop. Stopping service...")
        user = self.bot.get_user(const.id_fishy)
        await user.send(f"Emergency stop command received by {ctx.author}. Stopping service...")
        try:
            result = subprocess.run(
                ["systemctl", "stop", "fish_bot"],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                await ctx.send(f"Error stopping service: {result.stderr}")
        except Exception as e:
            await ctx.send(f"Failed to stop service: {str(e)}")


async def setup(bot) -> None:
    await bot.add_cog(ServiceControl(bot))
