import logging
from typing import Any, Dict, List, Optional, Set, Tuple

import discord

logger = logging.getLogger(__name__)


def _id_str(x: Any) -> str:
    return str(x) if x is not None else ""


def _normalize_channel_token(token: Any) -> str:
    t = str(token)
    # Do not accept '*' — require the explicit token 'public'.
    if t == "*":
        raise ValueError("Invalid channel token '*': please use 'public' in permissions config instead of '*'.")
    return t


class PermissionManager:
    """Config-backed permission resolver.

    Rules (summary):
      - default is deny
      - supports command-level 'public' or 'public_channels' using token 'public'
      - per-guild user/role grants include explicit channels list; empty/missing => deny
      - global grants mirror guild grants but apply across guilds (and DMs)
      - bot owner and guild owner bypass (if available)

    The public token used in config is the string 'public'.
    """

    def __init__(self, config, bot: Optional[discord.Client] = None):
        self.config = config
        self.bot = bot
        self.bot_owner_id: Optional[str] = None
        # in-memory cached permissions (mirror of config.get_permissions())
        self._perms_cache: Dict[str, Any] = {}
        self._config_unreg = None
        # Ensure a permissions root exists so manager operations are safe.
        try:
            self._ensure_permissions_root()
        except Exception:
            # Be resilient: don't let permission manager initialization block bot startup.
            logger.debug("PermissionManager: could not ensure permissions root on init", exc_info=True)
        # register listener if config supports it
        try:
            if hasattr(self.config, "register_listener"):
                self._config_unreg = self.config.register_listener(self._on_config_change)
        except Exception:
            logger.debug("PermissionManager: failed to register config listener", exc_info=True)

    async def initialize(self) -> None:
        """Attempt to resolve the bot owner from the connected application info."""
        if not self.bot:
            return
        try:
            info = await self.bot.application_info()
            if info and info.owner:
                self.bot_owner_id = _id_str(info.owner.id)
                logger.debug("PermissionManager: resolved bot owner %s", self.bot_owner_id)
        except Exception:
            logger.debug("PermissionManager: unable to fetch application_info for owner id", exc_info=True)
        # load initial cache
        try:
            self._reload_perms_cache()
        except Exception:
            logger.debug("PermissionManager: failed to load initial permissions cache", exc_info=True)

    # -- helpers to read config --
    def _get_permissions_root(self) -> Dict:
        # prefer cached copy if available
        if self._perms_cache:
            return self._perms_cache
        return self.config.get("permissions", {}) or {}

    def _reload_perms_cache(self) -> None:
        try:
            self._perms_cache = self.config.get("permissions", {}) or {}
            logger.debug("PermissionManager: reloaded permissions cache")
        except Exception:
            logger.debug("PermissionManager: failed to reload permissions cache", exc_info=True)

    def _on_config_change(self, event: Dict) -> None:
        try:
            if not event or event.get("type") != "save":
                return
            keys = event.get("keys")
            # if keys provided and permissions not changed, skip
            if keys is not None and "permissions" not in keys:
                return
            # reload cached permissions
            self._reload_perms_cache()
        except Exception:
            logger.exception("PermissionManager: error handling config change event")

    def _ensure_permissions_root(self) -> None:
        """Create an empty permissions structure in config if missing.

        This writes back to the config so management commands can safely assume
        the `permissions` key exists. It's safe to call multiple times.
        """
        root = self.config.get("permissions")
        if root is None:
            default = {"global": {"users": [], "roles": []}, "guilds": {}}
            # Use set to persist via ConfigManager.set if available
            try:
                self.config.set("permissions", default)
            except Exception:
                # If config object doesn't support set (unlikely), mutate in-place
                try:
                    cfg = getattr(self.config, "config", None)
                    if isinstance(cfg, dict):
                        cfg["permissions"] = default
                except Exception:
                    logger.debug("PermissionManager: failed to create permissions root in-place", exc_info=True)

    def _get_guild_section(self, guild_id: Optional[int]) -> Dict:
        perms = self._get_permissions_root()
        guilds = perms.get("guilds", {})
        if guild_id is None:
            return {}
        return guilds.get(str(guild_id), {}) or {}

    def _normalize_channel_set(self, channels: Any) -> Set[str]:
        if not channels:
            return set()
        out = set()
        for c in channels:
            out.add(_normalize_channel_token(c))
        return out

    def _channels_allow(self, chan_set: Set[str], channel_id: Optional[int], allow_in_dms: bool = False) -> bool:
        # empty set => deny
        if not chan_set:
            return False
        if "public" in chan_set:
            return True
        if channel_id is None:
            # DM: only allowed if 'public' present or allow_in_dms True (handled by caller)
            return False
        return str(channel_id) in chan_set

    def _match_user_grants(self, grants: List[Dict], user_id: str, channel_id: Optional[int]) -> bool:
        for g in grants:
            gid = _id_str(g.get("id") if isinstance(g, dict) else g)
            if gid != user_id:
                continue
            channels = g.get("channels") if isinstance(g, dict) else None
            chan_set = self._normalize_channel_set(channels)
            if self._channels_allow(chan_set, channel_id):
                return True
        return False

    def _match_role_grants(self, grants: List[Dict], member_role_ids: Set[str], channel_id: Optional[int]) -> bool:
        for g in grants:
            rid = _id_str(g.get("id") if isinstance(g, dict) else g)
            if rid not in member_role_ids:
                continue
            channels = g.get("channels") if isinstance(g, dict) else None
            chan_set = self._normalize_channel_set(channels)
            if self._channels_allow(chan_set, channel_id):
                return True
        return False

    def _is_command_public(self, guild_section: Dict, command_name: str) -> Tuple[bool, Set[str], bool]:
        # returns (is_public, public_channel_set, public_in_dms)
        cmd_map = guild_section.get("commands", {}) or {}
        c = cmd_map.get(command_name, {}) if isinstance(cmd_map, dict) else {}
        if not c:
            return False, set(), False
        if c.get("public"):
            return True, {"public"}, bool(c.get("public_in_dms", False))
        pcs = self._normalize_channel_set(c.get("public_channels", []))
        return (bool(pcs), pcs, bool(c.get("public_in_dms", False)))

    async def check(self, member_or_user: Any, command_name: str, guild_id: Optional[int] = None, channel_id: Optional[int] = None) -> Tuple[bool, Optional[str]]:
        """Return (allowed, reason).

        member_or_user may be a discord.Member, discord.User, or an int/str user id.
        """
        # resolve user id and roles
        user_id = None
        member_role_ids: Set[str] = set()
        is_guild_owner = False
        if isinstance(member_or_user, discord.Member):
            user_id = _id_str(member_or_user.id)
            member_role_ids = {str(r.id) for r in member_or_user.roles}
            try:
                is_guild_owner = (member_or_user.guild is not None and member_or_user.guild.owner_id == member_or_user.id)
            except Exception:
                is_guild_owner = False
        else:
            user_id = _id_str(member_or_user)

        # 1: bot owner bypass
        if self.bot_owner_id and user_id == self.bot_owner_id:
            return True, "bot_owner"

        # 2: guild owner bypass
        if guild_id is not None and is_guild_owner:
            return True, "guild_owner"

        # gather config sections
        guild_section = self._get_guild_section(guild_id)

        # 3: command public
        is_pub, pub_channels, public_in_dms = self._is_command_public(guild_section, command_name)
        if is_pub:
            if channel_id is None:
                if public_in_dms:
                    return True, "public_in_dms"
            else:
                if self._channels_allow(pub_channels, channel_id):
                    return True, "public"

        # 4: per-guild user grants
        cmd_map = guild_section.get("commands", {}) or {}
        cmd_entry = cmd_map.get(command_name, {}) if isinstance(cmd_map, dict) else {}
        if cmd_entry:
            users = cmd_entry.get("users", [])
            if users and self._match_user_grants(users, user_id, channel_id):
                return True, "user_grant"

            roles = cmd_entry.get("roles", [])
            if roles and self._match_role_grants(roles, member_role_ids, channel_id):
                return True, "role_grant"

        # 5: bot-role mappings
        bot_roles = guild_section.get("bot_roles", {}) or {}
        bot_role_map = guild_section.get("bot_role_map", {}) or {}
        # find bot-roles that map to this command pattern (simple exact or prefix match)
        for br_name, patterns in bot_role_map.items():
            for p in patterns:
                if p.endswith(".*"):
                    if command_name.startswith(p[:-2]):
                        matched = True
                    else:
                        matched = False
                else:
                    matched = (p == command_name)
                if not matched:
                    continue
                # check assignments for this bot-role
                assignments = bot_roles.get(br_name, {}) or {}
                users = assignments.get("users", [])
                roles = assignments.get("roles", [])
                if users and self._match_user_grants(users, user_id, channel_id):
                    return True, f"bot_role:{br_name}:user"
                if roles and self._match_role_grants(roles, member_role_ids, channel_id):
                    return True, f"bot_role:{br_name}:role"

        # 6: global grants
        perms_root = self._get_permissions_root()
        global_section = perms_root.get("global", {}) or {}
        g_users = global_section.get("users", [])
        if g_users and self._match_user_grants(g_users, user_id, channel_id):
            return True, "global_user"
        g_roles = global_section.get("roles", [])
        if g_roles and self._match_role_grants(g_roles, member_role_ids, channel_id):
            return True, "global_role"

        # fallback deny
        return False, None
