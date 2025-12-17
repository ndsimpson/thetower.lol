import json
import logging
import sys
from os import getenv
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ConfigManager:
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
                logger.warning(f"Config file not found at: {self.config_path}. Creating blank config file.")
                self._create_blank_config()
            else:
                self.load_config()

            self.initialized = True

    def _create_blank_config(self) -> None:
        """Create a blank configuration file with empty JSON object."""
        # Ensure the directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Create blank config (empty JSON object)
        self.config = {}

        # Write the blank config
        with open(self.config_path, "w") as f:
            json.dump(self.config, f, indent=4)

        logger.info(f"Created blank config file at: {self.config_path}")

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
        """Save configuration to JSON file with alphabetically sorted guilds and cogs."""
        try:
            # Sort guilds section alphabetically
            if "guilds" in self.config:
                for guild_id, guild_data in self.config["guilds"].items():
                    # Sort enabled_cogs list if it exists
                    if "enabled_cogs" in guild_data and isinstance(guild_data["enabled_cogs"], list):
                        guild_data["enabled_cogs"] = sorted(guild_data["enabled_cogs"])
                    # Sort all cog settings within this guild
                    self.config["guilds"][guild_id] = self._sort_dict_keys(guild_data)

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
            guild_id: The guild ID (required for multi-guild support)

        Returns:
            The setting value or default
        """
        if guild_id is None:
            raise ValueError("guild_id is required for multi-guild support. Pass ctx.guild.id or interaction.guild_id")

        # Don't create empty structures when reading - only get what exists
        cog_settings = self.config.get("guilds", {}).get(str(guild_id), {}).get(cog_name, {})
        return cog_settings.get(setting_name, default)

    def set_cog_setting(self, cog_name: str, setting_name: str, value: Any, guild_id: int = None) -> None:
        """Set a cog-specific setting.

        Args:
            cog_name: The name of the cog
            setting_name: The name of the setting
            value: The value to set
            guild_id: The guild ID (required for multi-guild support)
        """
        if guild_id is None:
            raise ValueError("guild_id is required for multi-guild support. Pass ctx.guild.id or interaction.guild_id")

        cog_settings = self.config.setdefault("guilds", {}).setdefault(str(guild_id), {}).setdefault(cog_name, {})
        cog_settings[setting_name] = value

        # Sort the settings for this guild
        self.config["guilds"][str(guild_id)] = self._sort_dict_keys(self.config["guilds"][str(guild_id)])

        self.save_config()
        logger.info(f"Set {cog_name} setting '{setting_name}' for guild {guild_id}")

    def update_cog_settings(self, cog_name: str, settings: Dict[str, Any], guild_id: int = None) -> None:
        """Update multiple cog settings at once.

        Args:
            cog_name: The name of the cog
            settings: Dictionary of setting names and values
            guild_id: The guild ID (required for multi-guild support)
        """
        if guild_id is None:
            raise ValueError("guild_id is required for multi-guild support. Pass ctx.guild.id or interaction.guild_id")

        cog_settings = self.config.setdefault("guilds", {}).setdefault(str(guild_id), {}).setdefault(cog_name, {})
        cog_settings.update(settings)

        # Sort the settings for this guild
        self.config["guilds"][str(guild_id)] = self._sort_dict_keys(self.config["guilds"][str(guild_id)])

        self.save_config()
        logger.info(f"Updated multiple settings for {cog_name} in guild {guild_id}")

    def remove_cog_setting(self, cog_name: str, setting_name: str, guild_id: int = None) -> bool:
        """Remove a cog-specific setting.

        Args:
            cog_name: The name of the cog
            setting_name: The name of the setting
            guild_id: The guild ID (required for multi-guild support)

        Returns:
            True if setting was removed, False if it didn't exist
        """
        if guild_id is None:
            raise ValueError("guild_id is required for multi-guild support. Pass ctx.guild.id or interaction.guild_id")

        try:
            cog_settings = self.config["guilds"][str(guild_id)][cog_name]
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
            guild_id: The guild ID (required for multi-guild support)

        Returns:
            True if the setting exists, False otherwise
        """
        if guild_id is None:
            raise ValueError("guild_id is required for multi-guild support. Pass ctx.guild.id or interaction.guild_id")

        try:
            return setting_name in self.config["guilds"][str(guild_id)][cog_name]
        except KeyError:
            return False

    def get_all_cog_settings(self, cog_name: str, guild_id: int = None) -> Dict[str, Any]:
        """Get all settings for a specific cog.

        Args:
            cog_name: The name of the cog
            guild_id: The guild ID (required for multi-guild support)

        Returns:
            Dictionary of all cog settings
        """
        if guild_id is None:
            raise ValueError("guild_id is required for multi-guild support. Pass ctx.guild.id or interaction.guild_id")

        # Don't create empty structures when reading - only get what exists
        return self.config.get("guilds", {}).get(str(guild_id), {}).get(cog_name, {}).copy()

    # Guild Metadata Methods

    def get_guild_enabled_cogs(self, guild_id: int) -> list:
        """Get the list of enabled cogs for a guild.

        Args:
            guild_id: The guild ID

        Returns:
            List of enabled cog names
        """
        if guild_id is None:
            raise ValueError("guild_id is required")

        # Don't create empty structures when reading - only get what exists
        return self.config.get("guilds", {}).get(str(guild_id), {}).get("enabled_cogs", [])

    def set_guild_enabled_cogs(self, guild_id: int, enabled_cogs: list) -> None:
        """Set the list of enabled cogs for a guild.

        Args:
            guild_id: The guild ID
            enabled_cogs: List of cog names to enable
        """
        if guild_id is None:
            raise ValueError("guild_id is required")

        guild_config = self.config.setdefault("guilds", {}).setdefault(str(guild_id), {})
        guild_config["enabled_cogs"] = sorted(enabled_cogs)

        self.save_config()
        logger.info(f"Set enabled_cogs for guild {guild_id}: {enabled_cogs}")

    def add_guild_enabled_cog(self, guild_id: int, cog_name: str) -> bool:
        """Add a cog to the guild's enabled list.

        Args:
            guild_id: The guild ID
            cog_name: The cog name to enable

        Returns:
            True if added, False if already enabled
        """
        enabled_cogs = self.get_guild_enabled_cogs(guild_id)

        if cog_name not in enabled_cogs:
            enabled_cogs.append(cog_name)
            self.set_guild_enabled_cogs(guild_id, enabled_cogs)
            return True
        return False

    def remove_guild_enabled_cog(self, guild_id: int, cog_name: str) -> bool:
        """Remove a cog from the guild's enabled list.

        Args:
            guild_id: The guild ID
            cog_name: The cog name to disable

        Returns:
            True if removed, False if was not enabled
        """
        enabled_cogs = self.get_guild_enabled_cogs(guild_id)

        if cog_name in enabled_cogs:
            enabled_cogs.remove(cog_name)
            self.set_guild_enabled_cogs(guild_id, enabled_cogs)
            return True
        return False

    # Bot Owner Settings Methods

    def get_bot_owner_cog_config(self, cog_name: str) -> Dict[str, Any]:
        """Get bot owner configuration for a specific cog.

        Args:
            cog_name: The name of the cog

        Returns:
            Dictionary with 'enabled' and 'public' keys, or empty dict if not found
        """
        return self.config.setdefault("bot_owner_settings", {}).setdefault("cogs", {}).get(cog_name, {}).copy()

    def set_bot_owner_cog_enabled(self, cog_name: str, enabled: bool) -> None:
        """Set whether a cog is enabled globally by the bot owner.

        Args:
            cog_name: The name of the cog
            enabled: True to enable, False to disable
        """
        cog_config = self.config.setdefault("bot_owner_settings", {}).setdefault("cogs", {}).setdefault(cog_name, {})
        cog_config["enabled"] = enabled
        self.save_config()
        logger.info(f"Bot owner set cog '{cog_name}' enabled={enabled}")

    def set_bot_owner_cog_public(self, cog_name: str, public: bool) -> None:
        """Set whether a cog is public (available to all guilds).

        Args:
            cog_name: The name of the cog
            public: True for public, False for restricted
        """
        cog_config = self.config.setdefault("bot_owner_settings", {}).setdefault("cogs", {}).setdefault(cog_name, {})
        cog_config["public"] = public
        self.save_config()
        logger.info(f"Bot owner set cog '{cog_name}' public={public}")

    def get_all_bot_owner_cogs(self) -> Dict[str, Dict[str, Any]]:
        """Get all bot owner cog configurations.

        Returns:
            Dictionary mapping cog names to their configurations
        """
        return self.config.setdefault("bot_owner_settings", {}).setdefault("cogs", {}).copy()

    def add_guild_cog_authorization(self, guild_id: int, cog_name: str, allow: bool = True) -> None:
        """Add or remove a cog authorization for a specific guild.

        Args:
            guild_id: The guild ID
            cog_name: The name of the cog
            allow: True to add to allowed list, False to add to disallowed list
        """
        guild_auth = self.config.setdefault("bot_owner_settings", {}).setdefault("guild_cog_authorizations", {}).setdefault(str(guild_id), {})

        if allow:
            # Add to allowed list
            allowed = guild_auth.setdefault("allowed", [])
            if cog_name not in allowed:
                allowed.append(cog_name)
                allowed.sort()
        else:
            # Add to disallowed list
            disallowed = guild_auth.setdefault("disallowed", [])
            if cog_name not in disallowed:
                disallowed.append(cog_name)
                disallowed.sort()

        self.save_config()
        list_type = "allowed" if allow else "disallowed"
        logger.info(f"Bot owner added cog '{cog_name}' to {list_type} list for guild {guild_id}")

    def remove_guild_cog_authorization(self, guild_id: int, cog_name: str, from_allowed: bool = True) -> bool:
        """Remove a cog authorization from a guild's allowed or disallowed list.

        Args:
            guild_id: The guild ID
            cog_name: The name of the cog
            from_allowed: True to remove from allowed list, False to remove from disallowed list

        Returns:
            True if removed, False if not found
        """
        try:
            guild_auth = self.config["bot_owner_settings"]["guild_cog_authorizations"][str(guild_id)]
            list_name = "allowed" if from_allowed else "disallowed"

            if cog_name in guild_auth.get(list_name, []):
                guild_auth[list_name].remove(cog_name)
                self.save_config()
                logger.info(f"Bot owner removed cog '{cog_name}' from {list_name} list for guild {guild_id}")
                return True
            return False
        except KeyError:
            return False

    def get_guild_cog_authorizations(self, guild_id: int) -> Dict[str, list]:
        """Get the allowed and disallowed cog lists for a guild.

        Args:
            guild_id: The guild ID

        Returns:
            Dictionary with 'allowed' and 'disallowed' lists
        """
        guild_auth = self.config.setdefault("bot_owner_settings", {}).setdefault("guild_cog_authorizations", {}).get(str(guild_id), {})
        return {"allowed": guild_auth.get("allowed", []).copy(), "disallowed": guild_auth.get("disallowed", []).copy()}

    def get_cog_guild_authorizations(self, cog_name: str) -> Dict[str, list]:
        """Get the authorization status for a specific cog across all guilds.

        Args:
            cog_name: The name of the cog

        Returns:
            Dictionary with 'allowed' and 'disallowed' lists containing guild IDs
        """
        guild_auths = self.config.setdefault("bot_owner_settings", {}).setdefault("guild_cog_authorizations", {})
        allowed_guilds = []
        disallowed_guilds = []

        for guild_id, auth in guild_auths.items():
            if cog_name in auth.get("allowed", []):
                allowed_guilds.append(int(guild_id))
            elif cog_name in auth.get("disallowed", []):
                disallowed_guilds.append(int(guild_id))

        return {"allowed": allowed_guilds, "disallowed": disallowed_guilds}

    def is_cog_allowed_for_guild(self, cog_name: str, guild_id: int) -> bool:
        """Check if a cog is allowed for a specific guild (bot owner level check).

        This checks:
        1. Cog is enabled by bot owner
        2. Cog is not in guild's disallowed list
        3. Cog is public OR in guild's allowed list

        Args:
            cog_name: The name of the cog
            guild_id: The guild ID

        Returns:
            True if the cog is allowed for the guild, False otherwise
        """
        # Get cog config
        cog_config = self.get_bot_owner_cog_config(cog_name)

        # Must be enabled by bot owner
        if not cog_config.get("enabled", False):
            return False

        # Get guild authorizations
        guild_auth = self.get_guild_cog_authorizations(guild_id)

        # Must not be disallowed
        if cog_name in guild_auth["disallowed"]:
            return False

        # Must be public OR explicitly allowed
        is_public = cog_config.get("public", False)
        is_allowed = cog_name in guild_auth["allowed"]

        return is_public or is_allowed

    def authorize_guild_cog(self, guild_id: int, cog_name: str) -> None:
        """Authorize a cog for a guild (add to allowed list and remove from disallowed).

        Args:
            guild_id: The guild ID
            cog_name: The name of the cog
        """
        # Remove from disallowed list if present
        self.remove_guild_cog_authorization(guild_id, cog_name, from_allowed=False)
        # Add to allowed list
        self.add_guild_cog_authorization(guild_id, cog_name, allow=True)

    def unauthorize_guild_cog(self, guild_id: int, cog_name: str) -> None:
        """Deny a cog for a guild (add to disallowed list and remove from allowed).

        Args:
            guild_id: The guild ID
            cog_name: The name of the cog
        """
        # Remove from allowed list if present
        self.remove_guild_cog_authorization(guild_id, cog_name, from_allowed=True)
        # Add to disallowed list
        self.add_guild_cog_authorization(guild_id, cog_name, allow=False)

    def get_global_cog_setting(self, cog_name: str, setting_name: str, default: Any = None) -> Any:
        """Get a global cog-specific setting (bot owner level).

        Args:
            cog_name: The name of the cog
            setting_name: The name of the setting
            default: Default value if setting doesn't exist

        Returns:
            The setting value or default
        """
        # Global cog settings are stored under bot_owner_settings.cogs.{cog_name}.settings
        cog_config = self.config.setdefault("bot_owner_settings", {}).setdefault("cogs", {}).setdefault(cog_name, {})
        settings = cog_config.setdefault("settings", {})
        return settings.get(setting_name, default)

    def set_global_cog_setting(self, cog_name: str, setting_name: str, value: Any) -> None:
        """Set a global cog-specific setting (bot owner level).

        Args:
            cog_name: The name of the cog
            setting_name: The name of the setting
            value: The value to set
        """
        cog_config = self.config.setdefault("bot_owner_settings", {}).setdefault("cogs", {}).setdefault(cog_name, {})
        settings = cog_config.setdefault("settings", {})
        settings[setting_name] = value
        self.save_config()
        logger.info(f"Set global {cog_name} setting '{setting_name}' = {value}")

    def update_global_cog_settings(self, cog_name: str, settings: Dict[str, Any]) -> None:
        """Update multiple global cog settings at once.

        Args:
            cog_name: The name of the cog
            settings: Dictionary of setting names and values
        """
        cog_config = self.config.setdefault("bot_owner_settings", {}).setdefault("cogs", {}).setdefault(cog_name, {})
        existing_settings = cog_config.setdefault("settings", {})
        existing_settings.update(settings)
        self.save_config()
        logger.info(f"Updated global settings for {cog_name}: {settings}")

    def remove_global_cog_setting(self, cog_name: str, setting_name: str) -> bool:
        """Remove a global cog-specific setting.

        Args:
            cog_name: The name of the cog
            setting_name: The name of the setting

        Returns:
            True if setting was removed, False if it didn't exist
        """
        try:
            settings = self.config["bot_owner_settings"]["cogs"][cog_name]["settings"]
            if setting_name in settings:
                del settings[setting_name]
                self.save_config()
                logger.info(f"Removed global {cog_name} setting '{setting_name}'")
                return True
            return False
        except KeyError:
            return False

    def has_global_cog_setting(self, cog_name: str, setting_name: str) -> bool:
        """Check if a global cog-specific setting exists.

        Args:
            cog_name: The name of the cog
            setting_name: The name of the setting

        Returns:
            True if the setting exists, False otherwise
        """
        try:
            return setting_name in self.config["bot_owner_settings"]["cogs"][cog_name]["settings"]
        except KeyError:
            return False

    def get_all_global_cog_settings(self, cog_name: str) -> Dict[str, Any]:
        """Get all global settings for a specific cog.

        Args:
            cog_name: The name of the cog

        Returns:
            Dictionary of all global cog settings
        """
        try:
            return self.config["bot_owner_settings"]["cogs"][cog_name]["settings"].copy()
        except KeyError:
            return {}
