from typing import Literal
import logging

CommandTypeOption = Literal["prefix", "slash", "both", "none"]


class CommandTypeManager:
    """Manages the type (prefix/slash/both) for each command."""

    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)

        # Load settings
        self.default_mode = self.bot.config.get("command_type_mode", "both")
        self.command_types = self.bot.config.get("command_types", {})

    def get_command_type(self, command_name: str) -> CommandTypeOption:
        """Get the command type for a specific command."""
        return self.command_types.get(command_name, self.default_mode)

    def set_command_type(self, command_name: str, command_type: CommandTypeOption) -> bool:
        """Set the command type for a specific command."""
        # Validate command type
        valid_types = ["prefix", "slash", "both", "none"]
        if command_type not in valid_types:
            return False

        # Update the setting
        self.command_types[command_name] = command_type
        self.bot.config.config["command_types"] = self.command_types
        self.bot.config.save_config()

        return True

    def set_default_mode(self, command_type: CommandTypeOption) -> bool:
        """Set the default command type mode."""
        # Validate command type
        valid_types = ["prefix", "slash", "both", "none"]
        if command_type not in valid_types:
            return False

        # Update the setting
        self.default_mode = command_type
        self.bot.config.config["command_type_mode"] = command_type
        self.bot.config.save_config()

        return True

    async def sync_commands(self):
        """Sync slash commands with Discord."""
        try:
            # This syncs globally - can take up to an hour to propagate
            synced = await self.bot.tree.sync()
            self.logger.info(f"Synced {len(synced)} command(s) with Discord")
            return len(synced)
        except Exception as e:
            self.logger.error(f"Error syncing commands: {e}")
            return None