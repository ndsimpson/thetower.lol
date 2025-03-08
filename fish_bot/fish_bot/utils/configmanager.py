import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict
from watchdog.events import FileSystemEventHandler, FileModifiedEvent
from fish_bot.utils.filemonitor import BaseFileMonitor

logger = logging.getLogger(__name__)


class ConfigManager(BaseFileMonitor):
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            config_path = os.getenv('FISHBOT_CONFIG')
            if not config_path:
                logger.error("FISHBOT_CONFIG environment variable is not set")
                sys.exit(1)

            self.config_path = Path(config_path)
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
            with open(self.config_path, 'r') as f:
                self.config = json.load(f)
            logger.info("Configuration loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            raise

    def save_config(self) -> None:
        """Save configuration to JSON file."""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
            logger.info("Configuration saved successfully")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            raise

    def add_command_channel(self, command: str, channel_id: str, public: bool = True) -> bool:
        """Add a channel to command permissions."""

        cmd_perms = self.config.setdefault("command_permissions", {}).setdefault("commands", {})
        cmd_config = cmd_perms.setdefault(command, {}).setdefault("channels", {})
        cmd_config[channel_id] = {"public": public}

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

        super().start_monitoring(
            self.config_path.parent,
            ConfigFileHandler(self),
            recursive=False
        )

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
