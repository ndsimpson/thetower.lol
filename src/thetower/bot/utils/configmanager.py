import json
import logging
import sys
from os import getenv
from pathlib import Path
from typing import Any, Dict

from watchdog.events import FileModifiedEvent, FileSystemEventHandler

from .filemonitor import BaseFileMonitor

logger = logging.getLogger(__name__)


class ConfigManager(BaseFileMonitor):
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "initialized"):
            config_path = getenv("DISCORD_BOT_CONFIG")
            if not config_path:
                logger.error("DISCORD_BOT_CONFIG environment variable is not set")
                sys.exit(1)

            self.config_path = Path(config_path) / "config.json"
            if not self.config_path.exists():
                logger.error(f"Config file not found at: {self.config_path}")
                sys.exit(1)

            self.config: Dict[str, Any] = {}
            self._observer = None
            self.initialized = True
            self.load_config()

    def load_config(self) -> None:
        """Load configuration from JSON file."""
        try:
            with open(self.config_path, "r") as f:
                self.config = json.load(f)
            logger.info("Configuration loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            raise

    def save_config(self) -> None:
        """Save configuration to JSON file with alphabetically sorted cogs."""
        try:
            # Sort enabled_cogs and disabled_cogs lists if they exist
            if "enabled_cogs" in self.config:
                self.config["enabled_cogs"] = sorted(self.config["enabled_cogs"])

            if "disabled_cogs" in self.config:
                self.config["disabled_cogs"] = sorted(self.config["disabled_cogs"])

            # Sort cog settings alphabetically if they exist
            if "cogs" in self.config:
                for guild_id, guild_cogs in self.config["cogs"].items():
                    self.config["cogs"][guild_id] = self._sort_dict_keys(guild_cogs)

            with open(self.config_path, "w") as f:
                json.dump(self.config, f, indent=4)
            logger.info("Configuration saved successfully")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            raise

    def _sort_dict_keys(self, d: Dict) -> Dict:
        """Sort dictionary keys alphabetically and recursively sort nested dictionaries.

        Args:
            d: Dictionary to sort

        Returns:
            New dictionary with sorted keys
        """
        result = {}
        # Sort the keys alphabetically and create a new dictionary
        for key in sorted(d.keys()):
            # If value is a dictionary, sort it recursively
            if isinstance(d[key], dict):
                result[key] = self._sort_dict_keys(d[key])
            else:
                result[key] = d[key]
        return result

    def add_command_channel(self, command: str, channel_id: str, public: bool = True, authorized_users: list = None) -> bool:
        """Add a channel to command permissions.

        Args:
            command: Command name
            channel_id: Discord channel ID (must be string)
            public: Whether command is public in the channel (default: True)
            authorized_users: List of user IDs authorized to use command (default: None)

        Returns:
            bool: True if channel was added successfully
        """
        # Ensure channel_id is a string
        channel_id = str(channel_id)

        cmd_perms = self.config.setdefault("command_permissions", {}).setdefault("commands", {})
        cmd_config = cmd_perms.setdefault(command, {}).setdefault("channels", {})

        channel_data = {"public": public}
        if authorized_users is not None:
            # Ensure all user IDs are strings
            channel_data["authorized_users"] = [str(uid) for uid in authorized_users]

        cmd_config[channel_id] = channel_data

        self.save_config()
        logger.info(f"Added channel {channel_id} to command '{command}' permissions")
        return True

    def remove_command_channel(self, command: str, channel_id: str) -> bool:
        """Remove a channel from command permissions."""
        try:
            cmd_perms = self.config["command_permissions"]["commands"][command]["channels"]
            if channel_id in cmd_perms:
                del cmd_perms[channel_id]
                self.save_config()
                logger.info(f"Removed channel {channel_id} from command '{command}' permissions")
                return True
            return False
        except KeyError:
            logger.error(f"Channel {channel_id} not found in command '{command}' permissions")
            return False

    def add_authorized_user(self, command: str, channel_id: str, user_id: str) -> bool:
        """Add an authorized user to a command channel."""
        try:
            cmd_perms = self.config["command_permissions"]["commands"]
            if command not in cmd_perms:
                cmd_perms[command] = {"channels": {}}

            channel_config = cmd_perms[command]["channels"].setdefault(channel_id, {"public": False, "authorized_users": []})

            if "authorized_users" not in channel_config:
                channel_config["authorized_users"] = []

            if user_id not in channel_config["authorized_users"]:
                channel_config["authorized_users"].append(user_id)
                self.save_config()
                logger.info(f"Added user {user_id} to authorized users for command '{command}' in channel {channel_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to add authorized user: {e}")
            return False

    def remove_authorized_user(self, command: str, channel_id: str, user_id: str) -> bool:
        """Remove an authorized user from a command channel."""
        try:
            channel_config = self.config["command_permissions"]["commands"][command]["channels"][channel_id]
            if "authorized_users" in channel_config and user_id in channel_config["authorized_users"]:
                channel_config["authorized_users"].remove(user_id)
                self.save_config()
                logger.info(f"Removed user {user_id} from authorized users for command '{command}' in channel {channel_id}")
                return True
            return False
        except KeyError:
            logger.error(f"User {user_id} not found in authorized users for command '{command}' in channel {channel_id}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self.config.get(key, default)

    def start_monitoring(self):
        """Start monitoring the config file for changes."""

        class ConfigFileHandler(FileSystemEventHandler):
            def __init__(self, config_manager):
                self.config_manager = config_manager

            def on_modified(self, event):
                if isinstance(event, FileModifiedEvent):
                    event_path = Path(event.src_path).resolve()
                    config_path = self.config_manager.config_path.resolve()
                    if event_path == config_path:
                        logger.info("Config file modified, reloading...")
                        self.config_manager.load_config()

        super().start_monitoring(self.config_path.parent, ConfigFileHandler(self), recursive=False)

    def get_guild_id(self) -> int:
        """Get the guild ID."""
        return self.config["guild"]["id"]

    def get_user_id(self, user: str) -> int:
        """Get a user ID by their name."""
        return self.config["users"].get(user)

    def get_bot_id(self, bot: str) -> int:
        """Get a bot ID by its name."""
        return self.config["bots"].get(bot)

    def get_channel_id(self, channel: str) -> int:
        """Get a channel ID by its name."""
        return self.config["channels"].get(channel)

    def get_thread_id(self, category: str, thread: str) -> int:
        """Get a thread ID by its category and name."""
        return self.config["threads"].get(category, {}).get(thread)

    def get_role_id(self, role: str) -> int:
        """Get a role ID by its name."""
        return self.config["roles"].get(role)

    def get_ranking_id(self, league: str, rank: str) -> int:
        """Get a ranking ID by its league and rank."""
        if league == "legend":
            return self.config["rankings"]["legend"].get(rank)
        else:
            return self.config["rankings"]["other_leagues"].get(f"{league.lower()}{rank}")

    def get_cog_data_directory(self, cog_name: str) -> Path:
        """Get or create a cog-specific data directory.

        Args:
            cog_name: The name of the cog

        Returns:
            Path object to the cog's data directory
        """
        # Create a 'cogs' directory next to the config file
        base_data_dir = self.config_path.parent / "cogs"
        base_data_dir.mkdir(exist_ok=True, parents=True)

        # Sanitize the cog name to ensure it's a valid directory name
        safe_name = "".join(c for c in cog_name.lower() if c.isalnum() or c in "._- ")

        # Create the path
        cog_dir = base_data_dir / safe_name

        # Ensure the directory exists
        cog_dir.mkdir(exist_ok=True, parents=True)

        logger.debug(f"Cog directory for '{cog_name}' created/accessed at {cog_dir}")
        return cog_dir

    def get_cog_setting(self, cog_name: str, setting_name: str, default: Any = None, guild_id: int = None) -> Any:
        """Get a cog-specific setting.

        Args:
            cog_name: The name of the cog
            setting_name: The name of the setting
            default: Default value if setting doesn't exist
            guild_id: The guild ID (uses current guild if None)

        Returns:
            The setting value or default
        """
        if guild_id is None:
            guild_id = self.get_guild_id()

        cog_settings = self.config.setdefault("cogs", {}).setdefault(str(guild_id), {}).setdefault(cog_name, {})
        return cog_settings.get(setting_name, default)

    def set_cog_setting(self, cog_name: str, setting_name: str, value: Any, guild_id: int = None) -> None:
        """Set a cog-specific setting.

        Args:
            cog_name: The name of the cog
            setting_name: The name of the setting
            value: The value to set
            guild_id: The guild ID (uses current guild if None)
        """
        if guild_id is None:
            guild_id = self.get_guild_id()

        cog_settings = self.config.setdefault("cogs", {}).setdefault(str(guild_id), {}).setdefault(cog_name, {})
        cog_settings[setting_name] = value

        # Sort the cog settings for this guild
        self.config["cogs"][str(guild_id)] = self._sort_dict_keys(self.config["cogs"][str(guild_id)])

        self.save_config()
        logger.info(f"Set {cog_name} setting '{setting_name}' for guild {guild_id}")

    def update_cog_settings(self, cog_name: str, settings: Dict[str, Any], guild_id: int = None) -> None:
        """Update multiple cog settings at once.

        Args:
            cog_name: The name of the cog
            settings: Dictionary of setting names and values
            guild_id: The guild ID (uses current guild if None)
        """
        if guild_id is None:
            guild_id = self.get_guild_id()

        cog_settings = self.config.setdefault("cogs", {}).setdefault(str(guild_id), {}).setdefault(cog_name, {})
        cog_settings.update(settings)

        # Sort the cog settings for this guild
        self.config["cogs"][str(guild_id)] = self._sort_dict_keys(self.config["cogs"][str(guild_id)])

        self.save_config()
        logger.info(f"Updated multiple settings for {cog_name} in guild {guild_id}")

    def remove_cog_setting(self, cog_name: str, setting_name: str, guild_id: int = None) -> bool:
        """Remove a cog-specific setting.

        Args:
            cog_name: The name of the cog
            setting_name: The name of the setting
            guild_id: The guild ID (uses current guild if None)

        Returns:
            True if setting was removed, False if it didn't exist
        """
        if guild_id is None:
            guild_id = self.get_guild_id()

        try:
            cog_settings = self.config["cogs"][str(guild_id)][cog_name]
            if setting_name in cog_settings:
                del cog_settings[setting_name]
                self.save_config()
                logger.info(f"Removed {cog_name} setting '{setting_name}' for guild {guild_id}")
                return True
            return False
        except KeyError:
            return False

    def has_cog_setting(self, cog_name: str, setting_name: str, guild_id: int = None) -> bool:
        """Check if a cog-specific setting exists.

        Args:
            cog_name: The name of the cog
            setting_name: The name of the setting
            guild_id: The guild ID (uses current guild if None)

        Returns:
            True if the setting exists, False otherwise
        """
        if guild_id is None:
            guild_id = self.get_guild_id()

        try:
            return setting_name in self.config["cogs"][str(guild_id)][cog_name]
        except KeyError:
            return False

    def get_all_cog_settings(self, cog_name: str, guild_id: int = None) -> Dict[str, Any]:
        """Get all settings for a specific cog.

        Args:
            cog_name: The name of the cog
            guild_id: The guild ID (uses current guild if None)

        Returns:
            Dictionary of all cog settings
        """
        if guild_id is None:
            guild_id = self.get_guild_id()

        return self.config.setdefault("cogs", {}).setdefault(str(guild_id), {}).setdefault(cog_name, {}).copy()
