import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict
import re
from typing import List, Optional

logger = logging.getLogger(__name__)


class ConfigManager:
    """Minimal file-backed config manager for the v2 scaffold.

    - Uses BOT_DATA_DIR env variable (or DISCORD_BOT_CONFIG fallback)
    - Ensures directory exists and creates a default config.json when missing
    - Provides get/set/save helpers
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "config.json"
        # in-process listeners for config change notifications
        self._listeners = []
        self.config: Dict[str, Any] = {}
        if not self.path.exists():
            logger.info(f"Creating default config at {self.path}")
            self.config = {
                "prefix": "$",
                "enabled_cogs": [],
                "disabled_cogs": [],
                "command_permissions": {"commands": {}},
                "cogs": {"_global": {}},
            }
            self.save()
        else:
            self.load()

    def load(self):
        """Load the primary config file; if it is missing or invalid,
        attempt to load the backup. If both fail, raise the exception.
        """
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
            logger.info("Config loaded from %s", self.path)
            return
        except Exception as e_primary:
            logger.warning("Failed to load primary config (%s): %s", self.path, e_primary)
            # Attempt to load backup
            bak_path = self.path.with_name(self.path.name + ".bak")
            try:
                with open(bak_path, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
                logger.warning("Loaded config from backup %s", bak_path)
                # Restore backup to primary file to recover
                try:
                    shutil.copy2(bak_path, self.path)
                    logger.info("Restored backup to primary config %s", self.path)
                except Exception:
                    logger.debug("Failed to restore backup to primary location", exc_info=True)
                return
            except Exception as e_bak:
                logger.error("Failed to load backup config (%s): %s", bak_path, e_bak)
                # Raise original primary error for visibility
                raise e_primary

    def save(self):
        """Stronger atomic write with atomic backup.

        Steps:
        1. Write new config to a temp file in the same directory and fsync it.
        2. If primary exists, write an atomic backup by copying primary to a temp
           file and os.replace that into <primary>.bak.
        3. Atomically replace primary with the new temp file (os.replace).
        4. Best-effort fsync of the directory and cleanup any temps.
        """
        # ensure directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)

        bak_path = self.path.with_name(self.path.name + ".bak")
        tmp_path = None
        bak_tmp_path = None
        try:
            # 1) write new content to a temp file in same directory
            tmp_fd, tmp_path = tempfile.mkstemp(dir=str(self.data_dir), prefix=self.path.name, text=False)
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(self.config, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                # close happened via context manager; tmp_fd no longer valid
                tmp_fd = None
            except Exception:
                # ensure temp removed on failure
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                raise

            # 2) if primary exists, create an atomic backup by writing to a bak-temp
            if self.path.exists():
                try:
                    bak_tmp_fd, bak_tmp_path = tempfile.mkstemp(dir=str(self.data_dir), prefix=self.path.name + ".bak.", text=False)
                    try:
                        # copy bytes from primary to bak-temp
                        with os.fdopen(bak_tmp_fd, "wb") as bf, open(self.path, "rb") as pf:
                            shutil.copyfileobj(pf, bf)
                        # try to copy metadata; ignore failures
                        try:
                            shutil.copystat(self.path, bak_tmp_path)
                        except Exception:
                            pass
                        # atomically move bak-temp into bak_path
                        os.replace(bak_tmp_path, bak_path)
                        bak_tmp_path = None
                    finally:
                        # if bak_tmp_path still exists, remove in outer finally
                        pass
                except Exception:
                    logger.debug("Failed to create atomic backup (will continue without .bak)", exc_info=True)

            # 3) atomically replace primary with tmp
            os.replace(tmp_path, self.path)
            tmp_path = None

            # 4) best-effort fsync of directory entries
            try:
                dir_fd = os.open(str(self.data_dir), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except Exception:
                # not critical; continue
                pass

            logger.info("Config saved (atomic) to %s", self.path)
        except Exception:
            logger.exception("Failed to save config")
        finally:
            # cleanup any remaining temp files
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            if bak_tmp_path and os.path.exists(bak_tmp_path):
                try:
                    os.remove(bak_tmp_path)
                except Exception:
                    pass
            # notify listeners that a save occurred (non-blocking)
            try:
                self._notify_listeners({"type": "save", "keys": ["permissions"]})
            except Exception:
                logger.debug("Failed to notify listeners after save", exc_info=True)

    def get(self, key: str, default=None):
        return self.config.get(key, default)

    def set(self, key: str, value):
        self.config[key] = value
        self.save()

    def register_listener(self, callback):
        """Register a callback to be notified on config changes.

        The callback may be a regular function or an async coroutine function.
        Returns an unregister callable.
        """
        self._listeners.append(callback)

        def _unregister():
            try:
                self._listeners.remove(callback)
            except ValueError:
                pass

        return _unregister

    def unregister_listener(self, callback) -> None:
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def _notify_listeners(self, event: Dict[str, Any]) -> None:
        """Notify all registered listeners of an event.

        This dispatches coroutine functions via the running loop (create_task)
        or runs them synchronously if no loop is available. Listener errors are
        caught and logged so they don't affect the save path.
        """
        try:
            import asyncio
            import inspect
        except Exception:
            asyncio = None
            inspect = None

        for cb in list(self._listeners):
            try:
                if inspect and inspect.iscoroutinefunction(cb):
                    # schedule on running loop if available
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(cb(event))
                    except RuntimeError:
                        # no running loop; run in new loop
                        try:
                            asyncio.run(cb(event))
                        except Exception:
                            logger.exception("Config listener (async) failed to run")
                else:
                    try:
                        cb(event)
                    except Exception:
                        logger.exception("Config listener (sync) raised an exception")
            except Exception:
                logger.exception("Failed to dispatch config listener")

    # --- Permission helpers ---

    def get_permissions(self) -> Dict[str, Any]:
        """Return the permissions root (may be empty dict).

        Use set_permissions(...) to persist changes.
        """
        return self.config.get("permissions", {}) or {}

    def set_permissions(self, perms: Dict[str, Any]) -> None:
        self.set("permissions", perms)

    def ensure_guild_permissions(self, guild_id: int) -> Dict[str, Any]:
        perms = self.get_permissions()
        guilds = perms.setdefault("guilds", {})
        gid = str(guild_id)
        if gid not in guilds:
            guilds[gid] = {"commands": {}, "bot_roles": {}, "bot_role_map": {}}
            self.set_permissions(perms)
        return guilds[gid]

    def _extract_id(self, identifier: Any) -> str:
        """Extract a numeric id from a mention or raw id.

        Accepts forms like '12345', '<@12345>', '<@!12345>', '<@&12345>'.
        Does not resolve username#discrim; callers should pass mentions or ids.
        """
        if identifier is None:
            raise ValueError("identifier is required")
        s = str(identifier).strip()
        # If the string is purely digits, return it
        if s.isdigit():
            return s
        # Extract digits from mention-like formats
        m = re.search(r"(\d{5,20})", s)
        if m:
            return m.group(1)
        raise ValueError("Could not parse a numeric id from identifier; use a mention or raw id")

    def _ensure_command_entry(self, guild_sec: Dict[str, Any], command: str) -> Dict[str, Any]:
        cmds = guild_sec.setdefault("commands", {})
        if command not in cmds:
            cmds[command] = {"users": [], "roles": [], "public": False}
        return cmds[command]

    def add_user_grant(self, guild_id: int, command: str, user_identifier: Any, channels: Optional[List[str]] = None) -> None:
        gid = str(guild_id)
        perms = self.get_permissions()
        guilds = perms.setdefault("guilds", {})
        guild = guilds.setdefault(gid, {"commands": {}, "bot_roles": {}, "bot_role_map": {}})
        entry = self._ensure_command_entry(guild, command)
        uid = self._extract_id(user_identifier)
        users = entry.setdefault("users", [])
        # prevent duplicates
        for u in users:
            if str(u.get("id") if isinstance(u, dict) else u) == uid:
                # update channels if provided
                if isinstance(u, dict):
                    if channels is not None:
                        u["channels"] = list(channels)
                else:
                    if channels is not None:
                        users.remove(u)
                        users.append({"id": uid, "channels": list(channels)})
                self.set_permissions(perms)
                return
        # append new
        users.append({"id": uid, "channels": list(channels) if channels is not None else []})
        self.set_permissions(perms)

    def remove_user_grant(self, guild_id: int, command: str, user_identifier: Any) -> None:
        perms = self.get_permissions()
        guilds = perms.get("guilds", {})
        gid = str(guild_id)
        guild = guilds.get(gid)
        if not guild:
            return
        cmds = guild.get("commands", {})
        entry = cmds.get(command)
        if not entry:
            return
        uid = self._extract_id(user_identifier)
        users = entry.get("users", [])
        new_users = [u for u in users if str(u.get("id") if isinstance(u, dict) else u) != uid]
        entry["users"] = new_users
        self.set_permissions(perms)

    def add_role_grant(self, guild_id: int, command: str, role_identifier: Any, channels: Optional[List[str]] = None) -> None:
        gid = str(guild_id)
        perms = self.get_permissions()
        guilds = perms.setdefault("guilds", {})
        guild = guilds.setdefault(gid, {"commands": {}, "bot_roles": {}, "bot_role_map": {}})
        entry = self._ensure_command_entry(guild, command)
        rid = self._extract_id(role_identifier)
        roles = entry.setdefault("roles", [])
        for r in roles:
            if str(r.get("id") if isinstance(r, dict) else r) == rid:
                if isinstance(r, dict):
                    if channels is not None:
                        r["channels"] = list(channels)
                else:
                    if channels is not None:
                        roles.remove(r)
                        roles.append({"id": rid, "channels": list(channels)})
                self.set_permissions(perms)
                return
        roles.append({"id": rid, "channels": list(channels) if channels is not None else []})
        self.set_permissions(perms)

    def remove_role_grant(self, guild_id: int, command: str, role_identifier: Any) -> None:
        perms = self.get_permissions()
        guilds = perms.get("guilds", {})
        gid = str(guild_id)
        guild = guilds.get(gid)
        if not guild:
            return
        cmds = guild.get("commands", {})
        entry = cmds.get(command)
        if not entry:
            return
        rid = self._extract_id(role_identifier)
        roles = entry.get("roles", [])
        new_roles = [r for r in roles if str(r.get("id") if isinstance(r, dict) else r) != rid]
        entry["roles"] = new_roles
        self.set_permissions(perms)

    def set_command_public(self, guild_id: int, command: str, public: bool, public_in_dms: bool = False, public_channels: Optional[List[str]] = None) -> None:
        perms = self.get_permissions()
        guilds = perms.setdefault("guilds", {})
        gid = str(guild_id)
        guild = guilds.setdefault(gid, {"commands": {}, "bot_roles": {}, "bot_role_map": {}})
        entry = self._ensure_command_entry(guild, command)
        entry["public"] = bool(public)
        entry["public_in_dms"] = bool(public_in_dms)
        if public_channels is not None:
            entry["public_channels"] = list(public_channels)
        self.set_permissions(perms)

    def list_command_grants(self, guild_id: int, command: str) -> Dict[str, Any]:
        perms = self.get_permissions()
        guilds = perms.get("guilds", {})
        guild = guilds.get(str(guild_id), {})
        cmds = guild.get("commands", {})
        return cmds.get(command, {"users": [], "roles": [], "public": False})

    def format_subject_label(self, subject_type: str, id_str: str, bot=None, guild_id: Optional[int] = None) -> str:
        """Return a display label like 'Name (id)'.

        If bot and guild_id are provided, attempts to resolve the name; otherwise falls back to id only.
        subject_type: 'user' or 'role'
        """
        label = str(id_str)
        try:
            if bot and subject_type == "user":
                # Try guild member first if guild provided
                if guild_id and hasattr(bot, "get_guild"):
                    g = bot.get_guild(int(guild_id))
                    if g:
                        m = g.get_member(int(id_str))
                        if m:
                            label = f"{m.display_name} ({id_str})"
                            return label
                # fallback to fetch_user
                if hasattr(bot, "get_user"):
                    u = bot.get_user(int(id_str))
                    if u:
                        label = f"{u.display_name if hasattr(u, 'display_name') else u.name} ({id_str})"
                        return label
            if bot and subject_type == "role" and guild_id and hasattr(bot, "get_guild"):
                g = bot.get_guild(int(guild_id))
                if g:
                    r = g.get_role(int(id_str))
                    if r:
                        label = f"{r.name} ({id_str})"
                        return label
        except Exception:
            # ignore resolution errors; fall back to id only
            pass
        return f"{label}"

