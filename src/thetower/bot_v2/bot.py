import logging
import os
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands

from .managers.command_type import CommandTypeManager
from .managers.config import ConfigManager
from .managers.permission import PermissionManager

logger = logging.getLogger(__name__)


class DiscordBot(commands.Bot):
    def __init__(self, data_dir: Optional[Path] = None):
        # Determine data dir
        env_dir = os.getenv("BOT_DATA_DIR") or os.getenv("DISCORD_BOT_CONFIG")
        data_dir = Path(data_dir or env_dir or Path.cwd())

        # Config manager
        self.config = ConfigManager(data_dir)

        # Command type manager (resolves prefix/slash/both/none per-command)
        self.command_types = CommandTypeManager(self.config)

        # Permission manager
        self.permissions = PermissionManager(self.config, bot=self)

        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(command_prefix=self.config.get("prefix", "$"), intents=intents, case_insensitive=True)

    async def setup_hook(self):
        logger.info("Bot setup_hook running")
        # initialize managers that require bot context
        await self.permissions.initialize()
        # Register a global check for prefix/command-framework commands.
        # This is added here to ensure managers are initialized.
        self.add_check(self._global_command_check)

    async def _global_command_check(self, ctx) -> bool:
        """Global check for discord.ext.commands commands (prefix/hybrid)."""
        try:
            cmd = ctx.command
            if cmd is None:
                return True
            cog_name = getattr(cmd, "cog_name", None)
            if cog_name:
                cmd_name = f"{cog_name}.{cmd.name}"
            else:
                cmd_name = cmd.name

            guild_id = ctx.guild.id if ctx.guild else None
            channel_id = ctx.channel.id if getattr(ctx, "channel", None) else None
            allowed, _ = await self.permissions.check(ctx.author, cmd_name, guild_id=guild_id, channel_id=channel_id)
            if not allowed:
                # Friendly denial
                try:
                    await ctx.reply("Permission denied.")
                except Exception:
                    pass
            return allowed
        except Exception:
            # On unexpected errors, deny by default but do not raise
            logger.exception("Error during global permission check")
            return False

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Intercept application command interactions and enforce permissions."""
        try:
            if interaction.type == discord.InteractionType.application_command:
                # Try to resolve a sensible command name
                cmd_name = None
                if getattr(interaction, "command", None) is not None:
                    cmd = interaction.command
                    cog_name = getattr(cmd, "cog_name", None)
                    name = getattr(cmd, "name", None)
                    if cog_name and name:
                        cmd_name = f"{cog_name}.{name}"
                    elif name:
                        cmd_name = name
                if not cmd_name:
                    # Fallback to raw payload name
                    data = interaction.data or {}
                    cmd_name = data.get("name")

                user = interaction.user
                guild_id = interaction.guild.id if interaction.guild else None
                channel_id = interaction.channel.id if getattr(interaction, "channel", None) else None

                allowed, _ = await self.permissions.check(user, cmd_name, guild_id=guild_id, channel_id=channel_id)
                if not allowed:
                    try:
                        await interaction.response.send_message("Permission denied.", ephemeral=True)
                    except Exception:
                        # If response already done or cannot respond, ignore
                        pass
                    return
        except Exception:
            logger.exception("Error during interaction permission check")
            # Deny on errors
            try:
                await interaction.response.send_message("Permission check failed.", ephemeral=True)
            except Exception:
                pass

        # If allowed or not an application_command, delegate to base
        await super().on_interaction(interaction)


bot = DiscordBot()


@bot.command()
async def ping(ctx):
    """Simple ping command for smoke testing."""
    await ctx.send("Pong!")


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN not set")
    bot.run(token)


if __name__ == "__main__":
    main()
