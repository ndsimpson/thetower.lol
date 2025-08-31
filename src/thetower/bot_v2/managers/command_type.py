import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CommandTypeManager:
    """Resolve per-command invocation mode and trigger (prefix/slash/both/none).

    Small, testable manager that reads/writes overrides through an injected
    ConfigManager-like object (duck-typed: get/set).
    """

    VALID_MODES = {"prefix", "slash", "both", "none"}

    def __init__(self, config):
        self.config = config

    def get_command_type(self, command_name: str, guild_id: Optional[int] = None) -> str:
        """Return the effective mode for a command (string in VALID_MODES).

        Resolution order:
          1. per-guild override in config['command_triggers'][guild_id][command_name]
          2. global per-command override in config['command_triggers']['_global'][command_name]
          3. config['command_types'][command_name]
          4. config['command_type_mode'] (default)
        """
        # 1: check command_triggers
        triggers = self.config.get("command_triggers", {})
        if guild_id is not None:
            g = triggers.get(str(guild_id), {})
            if command_name in g:
                mode = g[command_name].get("type")
                if mode:
                    return mode

        # 2: global in command_triggers
        g_global = triggers.get("_global", {})
        if command_name in g_global:
            mode = g_global[command_name].get("type")
            if mode:
                return mode

        # 3: explicit command_types mapping
        cmd_types = self.config.get("command_types", {})
        if command_name in cmd_types:
            return cmd_types[command_name]

        # 4: fallback
        return self.config.get("command_type_mode", "prefix")

    def get_effective_trigger(self, command_name: str, guild_id: Optional[int] = None) -> Tuple[str, Optional[str]]:
        """Return (mode, trigger) resolved for the command and guild.

        trigger is a string for prefix or slash name when provided; None otherwise.
        """
        mode = self.get_command_type(command_name, guild_id)
        triggers = self.config.get("command_triggers", {})

        # guild-level trigger
        if guild_id is not None:
            g = triggers.get(str(guild_id), {})
            if command_name in g:
                return mode, g[command_name].get("trigger")

        # global override
        g_global = triggers.get("_global", {})
        if command_name in g_global:
            return mode, g_global[command_name].get("trigger")

        # fallback: no custom trigger
        return mode, None

    def set_override(self, command_name: str, mode: str, trigger: Optional[str] = None, guild_id: Optional[int] = None) -> None:
        """Set or remove an override for a command.

        Use guild_id=None to set global override under _global.
        """
        if mode not in self.VALID_MODES:
            raise ValueError(f"Invalid mode: {mode}")

        triggers = self.config.get("command_triggers", {})
        key = "_global" if guild_id is None else str(guild_id)
        if key not in triggers:
            triggers[key] = {}

        triggers[key][command_name] = {"type": mode}
        if trigger is not None:
            triggers[key][command_name]["trigger"] = trigger

        self.config.set("command_triggers", triggers)

    def remove_override(self, command_name: str, guild_id: Optional[int] = None) -> None:
        triggers = self.config.get("command_triggers", {})
        key = "_global" if guild_id is None else str(guild_id)
        if key in triggers and command_name in triggers[key]:
            del triggers[key][command_name]
            self.config.set("command_triggers", triggers)

    def build_guild_sync_payload(self, guild_id: Optional[int] = None) -> List[Dict]:
        """Build a list of app-command specs to register for a guild.

        This returns a list of dicts with at least 'name' and 'description'.
        Actual parameter mapping is out of scope for this minimal scaffold.
        """
        payload = []

        # Walk commands from a curated list in config (or return empty)
        commands = self.config.get("registered_commands", [])
        for cmd in commands:
            mode = self.get_command_type(cmd, guild_id)
            if mode in ("slash", "both"):
                _, trigger = self.get_effective_trigger(cmd, guild_id)
                name = trigger if trigger else cmd.split()[-1]
                payload.append({"name": name, "description": f"{cmd} (auto)"})

        return payload
