import asyncio
import importlib.metadata
import logging
import sys
from pathlib import Path

from discord.ext.commands import Context, Paginator

from .configmanager import ConfigManager

logger = logging.getLogger(__name__)


class CogManager:
    """
    Utility class to manage cog loading, unloading, and configuration.
    Supports multi-guild operation with bot owner and guild owner permission levels.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = ConfigManager()
        self.loaded_cogs = []
        self.unloaded_cogs = []

        # Registry for cog settings views
        self.cog_settings_registry = {}

        # Registry for UI extensions (buttons, etc. that cogs can add to other cogs)
        self.ui_extension_registry = {}  # target_cog_name -> [(source_cog_name, provider_func), ...]

        # Registry for info extensions (additional info that cogs can add to profile views)
        self.info_extension_registry = {}  # target_cog_name -> [(source_cog_name, provider_func), ...]

        # Discover all cog sources (built-in and external packages)
        self._cog_sources = self._discover_cog_sources()  # List of (module_prefix, path) tuples

    def _discover_cog_sources(self) -> list[tuple[str, Path]]:
        """Discover all cog sources from built-in cogs and registered entry points.

        Returns:
            List of (module_prefix, cog_directory_path) tuples
        """
        sources = [
            # Built-in public cogs from this package
            ("thetower.bot.cogs", Path(__file__).parent.parent.resolve() / "cogs")
        ]

        # Discover external cog packages via entry points
        try:
            # Python 3.10+ can pass group directly to avoid scanning all packages
            # This is much faster and avoids hangs on first run in Python 3.13
            try:
                cog_entries = importlib.metadata.entry_points(group="thetower.bot.cogs")
            except TypeError:
                # Fallback for older Python versions
                entry_points = importlib.metadata.entry_points()
                if hasattr(entry_points, "select"):
                    cog_entries = entry_points.select(group="thetower.bot.cogs")
                else:
                    cog_entries = entry_points.get("thetower.bot.cogs", [])

            for entry_point in cog_entries:
                try:
                    module_path = entry_point.value  # e.g., "thetower_private.cogs"
                    module = __import__(module_path, fromlist=[""])
                    cog_path = Path(module.__file__).parent
                    sources.append((module_path, cog_path))
                    logger.info(f"Discovered external cog source: {entry_point.name} -> {module_path}")
                except Exception as e:
                    logger.warning(f"Failed to load cog source {entry_point.name}: {e}")
        except Exception as e:
            logger.warning(f"Failed to discover entry points: {e}")

        return sources

    def refresh_cog_sources(self) -> dict[str, list[str]]:
        """Re-discover cog sources to pick up newly installed packages.

        This allows bot owners to install new external cog packages without restarting the bot.

        Returns:
            Dictionary with 'added' and 'removed' lists of module prefixes
        """
        old_sources = {module_prefix for module_prefix, _ in self._cog_sources}
        self._cog_sources = self._discover_cog_sources()
        new_sources = {module_prefix for module_prefix, _ in self._cog_sources}

        added = list(new_sources - old_sources)
        removed = list(old_sources - new_sources)

        if added:
            logger.info(f"Discovered new cog sources: {', '.join(added)}")
        if removed:
            logger.info(f"Removed cog sources: {', '.join(removed)}")

        return {"added": added, "removed": removed}

    async def load_cogs(self) -> None:
        """
        Load cogs based on bot owner settings.
        Loads all cogs that are enabled by the bot owner from all discovered sources.
        """
        logger.debug(f"Starting cog loading from {len(self._cog_sources)} source(s)")

        # Get all bot owner cog configurations
        bot_owner_cogs = self.config.get_all_bot_owner_cogs()

        # Track cogs we've attempted to load to prevent duplicates
        attempted_loads = set()

        # Iterate over all cog sources
        for module_prefix, cogs_path in self._cog_sources:
            logger.debug(f"Scanning cog source: {module_prefix} ({cogs_path})")

            if not cogs_path.exists():
                logger.warning(f"Cog source path does not exist: {cogs_path}")
                continue

            for item in cogs_path.iterdir():
                extension = None

                # Handle both single files and folders
                if item.is_file() and item.suffix == ".py" and not item.stem.startswith("_"):
                    extension = item.stem
                elif item.is_dir() and not item.stem.startswith("_"):
                    # Check for __init__.py in folder
                    if (item / "__init__.py").exists():
                        extension = item.stem

                if extension:
                    # Skip if we've already attempted this cog (prevents duplicate cog names across sources)
                    if extension in attempted_loads:
                        logger.debug(f"Skipping duplicate cog name '{extension}' from {module_prefix}")
                        continue

                    attempted_loads.add(extension)

                    # Check if bot owner has enabled this cog
                    cog_config = bot_owner_cogs.get(extension, {})
                    if not cog_config.get("enabled", False):
                        logger.debug(f"Skipping cog '{extension}' - not enabled by bot owner")
                        if extension not in self.unloaded_cogs:
                            self.unloaded_cogs.append(extension)
                        continue

                    # Only attempt to load if not already loaded
                    if extension in self.loaded_cogs:
                        logger.debug(f"Skipping already loaded extension '{extension}'")
                        continue

                    try:
                        # Use the module prefix for this source
                        extension_path = f"{module_prefix}.{extension}"
                        await self.bot.load_extension(extension_path)
                        if extension not in self.loaded_cogs:
                            self.loaded_cogs.append(extension)
                            logger.info(f"Loaded extension '{extension}' from {module_prefix}")
                    except Exception as e:
                        exception = f"{type(e).__name__}: {e}"
                        logger.error(f"Failed to load extension {extension} from {module_prefix}\n{exception}")
                        if extension not in self.unloaded_cogs:
                            self.unloaded_cogs.append(extension)

    def get_available_cogs(self) -> list[str]:
        """Get list of all available cogs from all discovered sources.

        Returns:
            List of cog names found across all cog sources
        """
        available_cogs = []

        # Scan all cog sources
        for module_prefix, cogs_path in self._cog_sources:
            if not cogs_path.exists():
                continue

            for item in cogs_path.iterdir():
                extension = None

                # Handle both single files and folders
                if item.is_file() and item.suffix == ".py" and not item.stem.startswith("_"):
                    extension = item.stem
                elif item.is_dir() and not item.stem.startswith("_"):
                    # Check for __init__.py in folder
                    if (item / "__init__.py").exists():
                        extension = item.stem

                if extension and extension not in available_cogs:
                    available_cogs.append(extension)

        return sorted(available_cogs)

    def get_all_cogs_with_config(self) -> dict[str, dict]:
        """Get all available cogs merged with their configuration.

        Discovers cogs from filesystem and merges with bot owner config.
        Cogs not in config default to: enabled=False, public=False

        Returns:
            Dictionary mapping cog names to their configurations
        """
        # Get all available cogs from filesystem
        available_cogs = self.get_available_cogs()

        # Get configured cogs
        configured_cogs = self.config.get_all_bot_owner_cogs()

        # Merge: start with all available cogs
        all_cogs = {}
        for cog_name in available_cogs:
            if cog_name in configured_cogs:
                # Use existing config
                all_cogs[cog_name] = configured_cogs[cog_name].copy()
            else:
                # Default config for unconfigured cogs
                all_cogs[cog_name] = {"enabled": False, "public": False}

        return all_cogs

    def can_guild_use_cog(self, cog_name: str, guild_id: int, is_bot_owner: bool = False) -> bool:
        """Check if a guild can use a specific cog.

        This implements the three-tier permission system:
        1. Bot owner enables cog globally
        2. Bot owner authorizes guild (for restricted cogs) or blocks guild
        3. Guild owner enables cog for their server

        Args:
            cog_name: The name of the cog
            guild_id: The guild ID
            is_bot_owner: Whether the user is the bot owner (bypasses all checks if BOT_OWNER_OVERRIDE=true)

        Returns:
            True if the guild can use the cog, False otherwise
        """
        # Bot owner bypasses all checks if BOT_OWNER_OVERRIDE is enabled
        from os import getenv

        if is_bot_owner and getenv("BOT_OWNER_OVERRIDE", "true").lower() == "true":
            return True

        # Check bot owner level authorization (steps 1 & 2)
        if not self.config.is_cog_allowed_for_guild(cog_name, guild_id):
            return False

        # Check guild owner has enabled the cog (step 3)
        guild_enabled = self.config.get_guild_enabled_cogs(guild_id)
        return cog_name in guild_enabled

    def resolve_cog_name(self, user_input: str) -> str | None:
        """Resolve a cog name from user input (handles aliases/short names).

        Checks:
        1. Exact match in available cogs
        2. Exact match in loaded cogs (case-insensitive)
        3. Loaded cog that starts with the input (case-insensitive)

        Args:
            user_input: The cog name or alias provided by the user

        Returns:
            The full cog name if found, None otherwise
        """
        user_input_lower = user_input.lower()

        # Get available cogs from filesystem
        available_cogs = self.get_available_cogs()

        # Check for exact match (case-insensitive)
        for cog in available_cogs:
            if cog.lower() == user_input_lower:
                return cog

        # Check loaded cogs for exact match
        for cog in self.loaded_cogs:
            if cog.lower() == user_input_lower:
                return cog

        # Check if any loaded cog starts with the input (for aliases like "bc" -> "battle_conditions")
        for cog in self.loaded_cogs:
            if cog.lower().startswith(user_input_lower):
                return cog

        # Check available cogs for prefix match
        matches = [cog for cog in available_cogs if cog.lower().startswith(user_input_lower)]
        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            # Ambiguous - don't guess
            logger.warning(f"Ambiguous cog name '{user_input}': matches {matches}")
            return None

        return None

    def filename_to_class_name(self, filename: str) -> str:
        """Convert a cog filename to its class name.

        Examples:
            battle_conditions -> BattleConditions
            known_players -> KnownPlayers
            tourney_roles -> TourneyRoles

        Args:
            filename: The cog filename (without .py extension)

        Returns:
            The expected class name in PascalCase
        """
        # Split by underscore and capitalize each part
        parts = filename.split("_")
        return "".join(word.capitalize() for word in parts)

    def class_name_to_filename(self, class_name: str) -> str:
        """Convert a cog class name to its filename.

        Examples:
            BattleConditions -> battle_conditions
            KnownPlayers -> known_players
            TourneyRoles -> tourney_roles

        Args:
            class_name: The cog class name in PascalCase

        Returns:
            The expected filename in snake_case
        """
        # Insert underscore before uppercase letters (except first)
        import re

        snake = re.sub("([a-z0-9])([A-Z])", r"\1_\2", class_name)
        return snake.lower()

    def get_cog_by_filename(self, filename: str):
        """Get a loaded cog by its filename.

        This tries multiple strategies to find the cog:
        1. Try the class name (e.g., BattleConditions)
        2. Try the class name with spaces (e.g., Battle Conditions)
        3. Search all loaded cogs for a match

        Args:
            filename: The cog filename (e.g., 'battle_conditions')

        Returns:
            The cog instance if loaded, None otherwise
        """
        # Try strategy 1: Direct class name lookup
        class_name = self.filename_to_class_name(filename)
        cog = self.bot.get_cog(class_name)
        if cog:
            return cog

        # Try strategy 2: Class name with spaces (e.g., "Battle Conditions")
        class_name_with_spaces = " ".join(word.capitalize() for word in filename.split("_"))
        cog = self.bot.get_cog(class_name_with_spaces)
        if cog:
            return cog

        # Try strategy 3: Search through all loaded cogs
        # This handles custom names set in the cog definition
        for cog in self.bot.cogs.values():
            # Check if the cog's module matches the filename
            if hasattr(cog, "__module__"):
                module_parts = cog.__module__.split(".")
                # Check if the last part matches (works for any module prefix)
                if module_parts and module_parts[-1] == filename:
                    return cog

        return None

    async def reload_cog(self, cog_name: str) -> bool:
        """Reload a specific cog"""
        try:
            # Don't reload if not currently loaded
            if cog_name not in self.loaded_cogs:
                logger.warning(f"Cannot reload '{cog_name}' - not currently loaded")
                return False

            # Find which module prefix this cog is from
            extension_path = self._find_cog_extension_path(cog_name)
            if not extension_path:
                logger.error(f"Cannot find cog '{cog_name}' in any cog source")
                return False

            await self.bot.reload_extension(extension_path)
            logger.info(f"Reloaded cog '{cog_name}' from {extension_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to reload cog '{cog_name}': {str(e)}")
            # Update tracking lists on failure
            if cog_name in self.loaded_cogs:
                self.loaded_cogs.remove(cog_name)
            if cog_name not in self.unloaded_cogs:
                self.unloaded_cogs.append(cog_name)
            return False

    async def unload_cog(self, cog_name: str) -> bool:
        """Unload a specific cog"""
        try:
            # Find which module prefix this cog is from
            extension_path = self._find_cog_extension_path(cog_name)
            if not extension_path:
                logger.error(f"Cannot find cog '{cog_name}' in any cog source")
                return False

            await self.bot.unload_extension(extension_path)
            if cog_name in self.loaded_cogs:
                self.loaded_cogs.remove(cog_name)
                self.unloaded_cogs.append(cog_name)

            # Clear the module from Python's import cache to ensure fresh imports
            if extension_path in sys.modules:
                del sys.modules[extension_path]
                logger.debug(f"Cleared module '{extension_path}' from import cache")

            # Also clear any submodules that might be part of this cog
            modules_to_remove = [k for k in sys.modules.keys() if k.startswith(f"{extension_path}.")]
            for mod in modules_to_remove:
                del sys.modules[mod]
                logger.debug(f"Cleared submodule '{mod}' from import cache")

            logger.info(f"Unloaded cog '{cog_name}' and cleared from cache")
            return True
        except Exception as e:
            logger.error(f"Failed to unload cog '{cog_name}': {str(e)}")
            return False

    def _find_cog_extension_path(self, cog_name: str) -> str | None:
        """Find the full extension path for a cog by searching all sources.

        Args:
            cog_name: The cog name to find

        Returns:
            The full extension path (e.g., 'thetower.bot.cogs.validation') or None
        """
        for module_prefix, cogs_path in self._cog_sources:
            if not cogs_path.exists():
                continue

            # Check if this cog exists in this source
            cog_file = cogs_path / f"{cog_name}.py"
            cog_dir = cogs_path / cog_name

            if cog_file.exists() or (cog_dir.exists() and (cog_dir / "__init__.py").exists()):
                return f"{module_prefix}.{cog_name}"

        return None

    async def load_cog(self, cog_name: str) -> bool:
        """Load a specific cog if enabled by bot owner"""
        # Check if bot owner has enabled this cog
        cog_config = self.config.get_bot_owner_cog_config(cog_name)
        if not cog_config.get("enabled", False):
            logger.warning(f"Cannot load cog '{cog_name}' - not enabled by bot owner")
            return False

        # Find the extension path for this cog
        extension_name = self._find_cog_extension_path(cog_name)
        if not extension_name:
            logger.error(f"Cannot find cog '{cog_name}' in any cog source")
            return False

        # Check if already loaded
        if extension_name in self.bot.extensions:
            # Already loaded, just update tracking lists
            if cog_name in self.unloaded_cogs:
                self.unloaded_cogs.remove(cog_name)
            if cog_name not in self.loaded_cogs:
                self.loaded_cogs.append(cog_name)
            logger.info(f"Cog '{cog_name}' already loaded, updated tracking")
            return True

        # Now proceed with loading if allowed
        try:
            await self.bot.load_extension(extension_name)
            if cog_name in self.unloaded_cogs:
                self.unloaded_cogs.remove(cog_name)
            if cog_name not in self.loaded_cogs:
                self.loaded_cogs.append(cog_name)
            logger.info(f"Loaded cog '{cog_name}' from {extension_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to load cog '{cog_name}': {str(e)}")
            return False

    def sync_loaded_cogs_with_extensions(self) -> None:
        """Synchronize the loaded_cogs list with the actual bot extensions.

        This method ensures that the CogManager's tracking lists are accurate
        by checking what extensions are actually loaded in Discord.py and updating
        the internal lists accordingly.
        """
        # Get all cog extensions that are currently loaded from any source
        loaded_extensions = set()
        for extension_name in self.bot.extensions.keys():
            # Check if this extension matches any of our cog source prefixes
            for module_prefix, _ in self._cog_sources:
                if extension_name.startswith(f"{module_prefix}."):
                    cog_name = extension_name.replace(f"{module_prefix}.", "")
                    loaded_extensions.add(cog_name)
                    break

        # Update loaded_cogs list
        self.loaded_cogs = list(loaded_extensions)

        # Update unloaded_cogs list (cogs that are enabled but not loaded)
        enabled_cogs = set()
        for cog_name, config in self.config.get_all_bot_owner_cogs().items():
            if config.get("enabled", False):
                enabled_cogs.add(cog_name)

        self.unloaded_cogs = list(enabled_cogs - loaded_extensions)

        logger.info(f"Synchronized cog tracking: {len(self.loaded_cogs)} loaded, {len(self.unloaded_cogs)} unloaded")

    async def enable_cog(self, cog_name: str, guild_id: int) -> tuple:
        """Enable a cog for a specific guild.

        Args:
            cog_name: Name of the cog
            guild_id: Guild ID

        Returns:
            Tuple of (success_message, error_message)
        """
        success_msg = []
        error_msg = ""

        try:
            # Check if cog is allowed for this guild (bot owner level)
            if not self.config.is_cog_allowed_for_guild(cog_name, guild_id):
                cog_config = self.config.get_bot_owner_cog_config(cog_name)
                if not cog_config.get("enabled", False):
                    return "", "❌ This cog is not enabled by the bot owner."
                else:
                    return "", "❌ This cog is not authorized for your server. Contact the bot owner."

            # Get current enabled cogs for this guild
            enabled_cogs = self.config.get_guild_enabled_cogs(guild_id)

            if cog_name not in enabled_cogs:
                self.config.add_guild_enabled_cog(guild_id, cog_name)
                success_msg.append(f"✅ Cog `{cog_name}` has been enabled for this server.")
            else:
                return "ℹ️ Cog is already enabled for this server.", ""

            # Try to load the cog if it's not already loaded (bot-wide)
            if cog_name not in self.loaded_cogs:
                if await self.load_cog(cog_name):
                    success_msg.append("Cog has been loaded.")
                else:
                    error_msg = "⚠️ Couldn't load cog (see logs for details)"

            # Sync slash commands for this guild
            try:
                guild = self.bot.get_guild(guild_id)
                if guild:
                    # Add a small delay to avoid rate limiting if multiple syncs happen rapidly
                    await asyncio.sleep(0.5)
                    await self.bot.tree.sync(guild=guild)
                    logger.info(f"Synced slash commands for guild {guild_id} after enabling cog {cog_name}")
            except Exception as e:
                logger.warning(f"Failed to sync slash commands for guild {guild_id}: {e}")
                # Don't fail the enable operation just because sync failed

        except Exception as e:
            error_msg = f"⚠️ Error during cog enable: {str(e)}"
            logger.error(f"Failed to enable cog {cog_name} for guild {guild_id}: {e}", exc_info=True)

        return " ".join(success_msg), error_msg

    async def disable_cog(self, cog_name: str, guild_id: int) -> tuple:
        """Disable a cog for a specific guild.

        Args:
            cog_name: Name of the cog
            guild_id: Guild ID

        Returns:
            Tuple of (success_message, error_message)
        """
        success_msg = []
        error_msg = ""

        try:
            enabled_cogs = self.config.get_guild_enabled_cogs(guild_id)

            if cog_name in enabled_cogs:
                self.config.remove_guild_enabled_cog(guild_id, cog_name)
                success_msg.append(f"❌ Cog `{cog_name}` has been disabled for this server.")
            else:
                return "ℹ️ Cog is already disabled for this server.", ""

            # Note: We don't unload the cog because other guilds might be using it

            # Sync slash commands for this guild to remove cog commands
            try:
                guild = self.bot.get_guild(guild_id)
                if guild:
                    await asyncio.sleep(0.5)
                    await self.bot.tree.sync(guild=guild)
                    logger.info(f"Synced slash commands for guild {guild_id} after disabling cog {cog_name}")
            except Exception as e:
                logger.warning(f"Failed to sync slash commands for guild {guild_id}: {e}")
                # Don't fail the disable operation just because sync failed

        except Exception as e:
            error_msg = f"⚠️ Error during cog disable: {str(e)}"
            logger.error(f"Failed to disable cog {cog_name} for guild {guild_id}: {e}", exc_info=True)

        return " ".join(success_msg), error_msg

    def get_cog_status_list(self, guild_id: int):
        """Get comprehensive status information about all cogs for a specific guild.

        Args:
            guild_id: The guild ID

        Returns:
            Tuple of (cog_status_list, bot_owner_cogs_dict)
        """
        # Get bot owner cog configurations
        bot_owner_cogs = self.config.get_all_bot_owner_cogs()

        # Get guild-specific settings
        enabled_cogs = self.config.get_guild_enabled_cogs(guild_id)
        guild_auth = self.config.get_guild_cog_authorizations(guild_id)

        # Get cog files and directories from all sources
        available_cogs = self.get_available_cogs()

        cog_status = []
        for cog in sorted(available_cogs):
            cog_config = bot_owner_cogs.get(cog, {})
            is_allowed = self.config.is_cog_allowed_for_guild(cog, guild_id)

            # Check actual extension loading state instead of tracking list
            extension_name = f"thetower.bot.cogs.{cog}"
            is_loaded = extension_name in self.bot.extensions

            status = {
                "name": cog,
                "loaded": is_loaded,
                "bot_owner_enabled": cog_config.get("enabled", False),
                "public": cog_config.get("public", False),
                "guild_authorized": cog in guild_auth["allowed"],
                "guild_disallowed": cog in guild_auth["disallowed"],
                "guild_can_use": is_allowed,
                "guild_enabled": cog in enabled_cogs,
            }
            cog_status.append(status)

        return cog_status, bot_owner_cogs

    async def list_modules(self, ctx: Context) -> None:
        """Lists all cogs and their status for the current guild."""
        if not ctx.guild:
            await ctx.send("❌ This command can only be used in a server.")
            return

        guild_id = ctx.guild.id
        is_bot_owner = await ctx.bot.is_owner(ctx.author)

        cog_status, bot_owner_cogs = self.get_cog_status_list(guild_id)

        cog_list = Paginator(prefix="", suffix="")
        cog_list.add_line(f"**Cog Status for {ctx.guild.name}**\n")

        # Group cogs by status
        enabled_for_guild = [s for s in cog_status if s["guild_enabled"]]
        available_not_enabled = [s for s in cog_status if s["guild_can_use"] and not s["guild_enabled"]]
        not_available = [s for s in cog_status if not s["guild_can_use"] and s["bot_owner_enabled"]]
        not_loaded = [s for s in cog_status if not s["bot_owner_enabled"]]

        if enabled_for_guild:
            cog_list.add_line("**✅ Enabled for this server:**")
            for s in enabled_for_guild:
                loaded_str = "🟢" if s["loaded"] else "🔴"
                cog_list.add_line(f"  {loaded_str} {s['name']}")
            cog_list.add_line("")

        if available_not_enabled:
            cog_list.add_line("**📋 Available (not enabled):**")
            for s in available_not_enabled:
                public_str = "(public)" if s["public"] else "(authorized)"
                cog_list.add_line(f"  - {s['name']} {public_str}")
            cog_list.add_line("")

        if not_available and is_bot_owner:
            cog_list.add_line("**🔒 Not available for this server:**")
            for s in not_available:
                if s["guild_disallowed"]:
                    cog_list.add_line(f"  - {s['name']} (disallowed by bot owner)")
                else:
                    cog_list.add_line(f"  - {s['name']} (not authorized)")
            cog_list.add_line("")

        if not_loaded and is_bot_owner:
            cog_list.add_line("**❌ Not enabled by bot owner:**")
            for s in not_loaded:
                cog_list.add_line(f"  - {s['name']}")

        for page in cog_list.pages:
            await ctx.send(page)

    async def load_cog_with_ctx(self, ctx: Context, cog: str) -> None:
        """Try and load the selected cog with Discord context feedback.

        Note: This loads the cog bot-wide, not per-guild.
        Only bot owner can use this command.
        """
        is_bot_owner = await ctx.bot.is_owner(ctx.author)
        if not is_bot_owner:
            return await ctx.send("❌ Only the bot owner can load cogs.")

        # Check if bot owner has enabled this cog
        cog_config = self.config.get_bot_owner_cog_config(cog)
        if not cog_config.get("enabled", False):
            return await ctx.send("❌ This cog is not enabled in bot owner settings. Enable it first with `cog owner enable` command.")

        if cog in self.loaded_cogs:
            return await ctx.send("ℹ️ Cog already loaded.")

        try:
            success = await self.load_cog(cog)
            if success:
                await ctx.send("✅ Module successfully loaded.")
            else:
                await ctx.send("**💢 Could not load module. Check logs for details.**")
        except Exception as e:
            await ctx.send("**💢 Could not load module: An exception was raised. For your convenience, the exception will be printed below:**")
            await ctx.send("```{}\n{}```".format(type(e).__name__, e))

    async def unload_cog_with_ctx(self, ctx: Context, cog: str) -> None:
        """Unload the selected cog with Discord context feedback.

        Note: This unloads the cog bot-wide, not per-guild.
        Only bot owner can use this command.
        """
        is_bot_owner = await ctx.bot.is_owner(ctx.author)
        if not is_bot_owner:
            return await ctx.send("❌ Only the bot owner can unload cogs.")

        if cog not in self.loaded_cogs:
            return await ctx.send("💢 Module not loaded.")

        success = await self.unload_cog(cog)
        if success:
            await ctx.send("✅ Module successfully unloaded.")
        else:
            await ctx.send("**💢 Could not unload module. Check logs for details.**")

    async def reload_cog_with_ctx(self, ctx: Context, cog: str) -> None:
        """Reload the selected cog with Discord context feedback.

        Note: This reloads the cog bot-wide, not per-guild.
        Only bot owner can use this command.
        """
        is_bot_owner = await ctx.bot.is_owner(ctx.author)
        if not is_bot_owner:
            return await ctx.send("❌ Only the bot owner can reload cogs.")

        if cog not in self.loaded_cogs:
            return await ctx.send("💢 Module not loaded, cannot reload.")

        try:
            success = await self.reload_cog(cog)
            if success:
                await ctx.send("✅ Module successfully reloaded.")
            else:
                await ctx.send("**💢 Could not reload module. Check logs for details.**")
        except Exception as e:
            await ctx.send("**💢 Could not reload module: An exception was raised. For your convenience, the exception will be printed below:**")
            await ctx.send("```{}\n{}```".format(type(e).__name__, e))

    async def enable_cog_with_ctx(self, ctx: Context, cog: str) -> None:
        """Enable a cog for the current guild with Discord context feedback."""
        if not ctx.guild:
            return await ctx.send("❌ This command can only be used in a server.")

        # Check if user has permission (guild owner or bot owner)
        is_bot_owner = await ctx.bot.is_owner(ctx.author)
        is_guild_owner = ctx.author.id == ctx.guild.owner_id

        if not (is_bot_owner or is_guild_owner):
            return await ctx.send("❌ Only the server owner or bot owner can enable cogs.")

        success_msg, error_msg = await self.enable_cog(cog, ctx.guild.id)

        if success_msg:
            await ctx.send(success_msg)
        if error_msg:
            await ctx.send(error_msg)

    async def disable_cog_with_ctx(self, ctx: Context, cog: str) -> None:
        """Disable a cog for the current guild with Discord context feedback."""
        if not ctx.guild:
            return await ctx.send("❌ This command can only be used in a server.")

        # Check if user has permission (guild owner or bot owner)
        is_bot_owner = await ctx.bot.is_owner(ctx.author)
        is_guild_owner = ctx.author.id == ctx.guild.owner_id

        if not (is_bot_owner or is_guild_owner):
            return await ctx.send("❌ Only the server owner or bot owner can disable cogs.")

        success_msg, error_msg = await self.disable_cog(cog, ctx.guild.id)

        if success_msg:
            await ctx.send(success_msg)
        if error_msg:
            await ctx.send(error_msg)

    # Bot Owner Management Methods

    async def bot_owner_enable_cog_with_ctx(self, ctx: Context, cog: str) -> None:
        """Enable a cog globally (bot owner only)."""
        if not await ctx.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can use this command.")

        # Resolve cog name from user input
        resolved_cog = self.resolve_cog_name(cog)
        if not resolved_cog:
            return await ctx.send(f"❌ Cog `{cog}` not found. Use the full cog name or a recognized alias.")

        self.config.set_bot_owner_cog_enabled(resolved_cog, True)

        # Try to load if not already loaded
        if resolved_cog not in self.loaded_cogs:
            await self.load_cog(resolved_cog)

        if resolved_cog != cog:
            await ctx.send(f"✅ Cog `{resolved_cog}` (resolved from `{cog}`) has been enabled globally by bot owner.")
        else:
            await ctx.send(f"✅ Cog `{resolved_cog}` has been enabled globally by bot owner.")

    async def bot_owner_disable_cog_with_ctx(self, ctx: Context, cog: str) -> None:
        """Disable a cog globally (bot owner only)."""
        if not await ctx.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can use this command.")

        # Resolve cog name from user input
        resolved_cog = self.resolve_cog_name(cog)
        if not resolved_cog:
            return await ctx.send(f"❌ Cog `{cog}` not found. Use the full cog name or a recognized alias.")

        self.config.set_bot_owner_cog_enabled(resolved_cog, False)

        if resolved_cog != cog:
            await ctx.send(f"❌ Cog `{resolved_cog}` (resolved from `{cog}`) has been disabled globally by bot owner.")
        else:
            await ctx.send(f"❌ Cog `{resolved_cog}` has been disabled globally by bot owner.")

    async def bot_owner_set_cog_public_with_ctx(self, ctx: Context, cog: str, public: bool) -> None:
        """Set whether a cog is public or restricted (bot owner only)."""
        if not await ctx.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can use this command.")

        # Resolve cog name from user input
        resolved_cog = self.resolve_cog_name(cog)
        if not resolved_cog:
            return await ctx.send(f"❌ Cog `{cog}` not found. Use the full cog name or a recognized alias.")

        self.config.set_bot_owner_cog_public(resolved_cog, public)
        status = "public (all servers can use)" if public else "restricted (requires authorization)"

        if resolved_cog != cog:
            await ctx.send(f"🔧 Cog `{resolved_cog}` (resolved from `{cog}`) is now {status}.")
        else:
            await ctx.send(f"🔧 Cog `{resolved_cog}` is now {status}.")

    async def bot_owner_authorize_guild_with_ctx(self, ctx: Context, cog: str, guild_id: int) -> None:
        """Authorize a guild to use a restricted cog (bot owner only)."""
        if not await ctx.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can use this command.")

        # Resolve cog name from user input
        resolved_cog = self.resolve_cog_name(cog)
        if not resolved_cog:
            return await ctx.send(f"❌ Cog `{cog}` not found. Use the full cog name or a recognized alias.")

        self.config.add_guild_cog_authorization(guild_id, resolved_cog, allow=True)

        # Show both names if different
        if resolved_cog != cog:
            await ctx.send(f"✅ Guild {guild_id} has been authorized to use cog `{resolved_cog}` (resolved from `{cog}`).")
        else:
            await ctx.send(f"✅ Guild {guild_id} has been authorized to use cog `{resolved_cog}`.")

    async def bot_owner_revoke_guild_with_ctx(self, ctx: Context, cog: str, guild_id: int) -> None:
        """Revoke a guild's authorization for a restricted cog (bot owner only)."""
        if not await ctx.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can use this command.")

        # Resolve cog name from user input
        resolved_cog = self.resolve_cog_name(cog)
        if not resolved_cog:
            return await ctx.send(f"❌ Cog `{cog}` not found. Use the full cog name or a recognized alias.")

        success = self.config.remove_guild_cog_authorization(guild_id, resolved_cog, from_allowed=True)
        if success:
            if resolved_cog != cog:
                await ctx.send(f"❌ Guild {guild_id}'s authorization for cog `{resolved_cog}` (resolved from `{cog}`) has been revoked.")
            else:
                await ctx.send(f"❌ Guild {guild_id}'s authorization for cog `{resolved_cog}` has been revoked.")
        else:
            await ctx.send(f"ℹ️ Guild {guild_id} was not authorized for cog `{resolved_cog}`.")

    async def bot_owner_disallow_guild_with_ctx(self, ctx: Context, cog: str, guild_id: int) -> None:
        """Explicitly disallow a guild from using a cog (bot owner only)."""
        if not await ctx.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can use this command.")

        # Resolve cog name from user input
        resolved_cog = self.resolve_cog_name(cog)
        if not resolved_cog:
            return await ctx.send(f"❌ Cog `{cog}` not found. Use the full cog name or a recognized alias.")

        self.config.add_guild_cog_authorization(guild_id, resolved_cog, allow=False)

        if resolved_cog != cog:
            await ctx.send(f"🚫 Guild {guild_id} has been disallowed from using cog `{resolved_cog}` (resolved from `{cog}`).")
        else:
            await ctx.send(f"🚫 Guild {guild_id} has been disallowed from using cog `{resolved_cog}`.")

    async def bot_owner_allow_guild_with_ctx(self, ctx: Context, cog: str, guild_id: int) -> None:
        """Remove a guild from the disallowed list (bot owner only)."""
        if not await ctx.bot.is_owner(ctx.author):
            return await ctx.send("❌ Only the bot owner can use this command.")

        # Resolve cog name from user input
        resolved_cog = self.resolve_cog_name(cog)
        if not resolved_cog:
            return await ctx.send(f"❌ Cog `{cog}` not found. Use the full cog name or a recognized alias.")

        success = self.config.remove_guild_cog_authorization(guild_id, resolved_cog, from_allowed=False)
        if success:
            if resolved_cog != cog:
                await ctx.send(f"✅ Guild {guild_id} is no longer disallowed from using cog `{resolved_cog}` (resolved from `{cog}`).")
            else:
                await ctx.send(f"✅ Guild {guild_id} is no longer disallowed from using cog `{resolved_cog}`.")
        else:
            await ctx.send(f"ℹ️ Guild {guild_id} was not in the disallow list for cog `{resolved_cog}`.")

    # Cog Settings Registry Methods

    def register_cog_settings_view(self, cog_name: str, settings_view_class: type) -> None:
        """Register a settings view class for a cog.

        Args:
            cog_name: The name of the cog (snake_case)
            settings_view_class: The View class that handles cog settings
        """
        self.cog_settings_registry[cog_name] = settings_view_class
        logger.debug(f"Registered settings view for cog '{cog_name}': {settings_view_class.__name__}")

    def get_cog_settings_view(self, cog_name: str) -> type | None:
        """Get the registered settings view class for a cog.

        Args:
            cog_name: The name of the cog (snake_case)

        Returns:
            The View class for the cog's settings, or None if not registered
        """
        return self.cog_settings_registry.get(cog_name)

    def get_enabled_cogs_with_settings(self, guild_id: int) -> list[str]:
        """Get list of enabled cogs for a guild that have settings views registered.

        Args:
            guild_id: The guild ID

        Returns:
            List of cog names that are enabled for the guild and have settings views
        """
        enabled_cogs = []
        all_cogs = self.get_all_cogs_with_config()

        for cog_name in all_cogs.keys():
            # Check if cog is enabled for this guild
            if self.can_guild_use_cog(cog_name, guild_id, is_bot_owner=False):
                # Check if cog has a settings view registered
                if cog_name in self.cog_settings_registry:
                    enabled_cogs.append(cog_name)

        return sorted(enabled_cogs)

    # UI Extension Registry Methods

    def register_ui_extension(self, target_cog: str, source_cog: str, provider_func: callable) -> None:
        """Register a UI extension provider function for a target cog.

        Args:
            target_cog: The name of the cog that will display the extension (e.g., "player_lookup")
            source_cog: The name of the cog providing the extension (e.g., "manage_sus")
            provider_func: Function that takes (player, requesting_user, guild_id) and returns a discord.ui.Button or None
        """
        if target_cog not in self.ui_extension_registry:
            self.ui_extension_registry[target_cog] = []

        # Remove any existing registration with the same source cog and function name to avoid duplicates
        # This is important for cog reloads where the function object is recreated
        provider_func_name = provider_func.__name__
        self.ui_extension_registry[target_cog] = [
            (src, provider)
            for src, provider in self.ui_extension_registry[target_cog]
            if not (src == source_cog and provider.__name__ == provider_func_name)
        ]

        # Add the new registration
        self.ui_extension_registry[target_cog].append((source_cog, provider_func))
        logger.debug(f"Registered UI extension from '{source_cog}' for target cog '{target_cog}' (function: {provider_func.__name__})")

    def get_ui_extensions(self, target_cog: str) -> list:
        """Get all registered UI extension provider functions for a target cog.

        Args:
            target_cog: The name of the cog to get extensions for

        Returns:
            List of provider functions that can be called with (player, requesting_user, guild_id)
        """
        return [provider for source, provider in self.ui_extension_registry.get(target_cog, [])]

    def unregister_ui_extensions_from_source(self, source_cog: str) -> None:
        """Remove all UI extensions registered by a source cog.

        Args:
            source_cog: The name of the cog whose extensions should be removed
        """
        for target_cog in self.ui_extension_registry:
            original_count = len(self.ui_extension_registry[target_cog])
            self.ui_extension_registry[target_cog] = [
                (src, provider) for src, provider in self.ui_extension_registry[target_cog] if src != source_cog
            ]
            removed_count = original_count - len(self.ui_extension_registry[target_cog])
            if removed_count > 0:
                logger.debug(f"Removed {removed_count} UI extensions from '{source_cog}' for target cog '{target_cog}'")

    def get_ui_extension_sources(self, target_cog: str) -> list[str]:
        """Get list of source cogs that have registered UI extensions for a target cog.

        Args:
            target_cog: The name of the target cog

        Returns:
            List of source cog names
        """
        return [source for source, provider in self.ui_extension_registry.get(target_cog, [])]

    # Info Extension Registry Methods

    def register_info_extension(self, target_cog: str, source_cog: str, provider_func: callable) -> None:
        """Register an info extension provider function for a target cog.

        Args:
            target_cog: The name of the cog that will display the extension (e.g., "player_lookup")
            source_cog: The name of the cog providing the extension (e.g., "tourney_roles")
            provider_func: Function that takes (player, details, requesting_user, permission_context) and returns a list of embed fields
        """
        if target_cog not in self.info_extension_registry:
            self.info_extension_registry[target_cog] = []

        # Remove any existing registration with the same source cog and function name to avoid duplicates
        # This is important for cog reloads where the function object is recreated
        provider_func_name = provider_func.__name__
        self.info_extension_registry[target_cog] = [
            (src, provider)
            for src, provider in self.info_extension_registry[target_cog]
            if not (src == source_cog and provider.__name__ == provider_func_name)
        ]

        # Add the new registration
        self.info_extension_registry[target_cog].append((source_cog, provider_func))
        logger.debug(f"Registered info extension from '{source_cog}' for target cog '{target_cog}' (function: {provider_func.__name__})")

    def get_info_extensions(self, target_cog: str) -> list:
        """Get all registered info extension provider functions for a target cog.

        Args:
            target_cog: The name of the cog to get extensions for

        Returns:
            List of provider functions that can be called with (player, details, requesting_user, permission_context)
        """
        return [provider for source, provider in self.info_extension_registry.get(target_cog, [])]

    def unregister_info_extensions_from_source(self, source_cog: str) -> None:
        """Remove all info extensions registered by a source cog.

        Args:
            source_cog: The name of the cog whose extensions should be removed
        """
        for target_cog in self.info_extension_registry:
            original_count = len(self.info_extension_registry[target_cog])
            self.info_extension_registry[target_cog] = [
                (src, provider) for src, provider in self.info_extension_registry[target_cog] if src != source_cog
            ]
            removed_count = original_count - len(self.info_extension_registry[target_cog])
            if removed_count > 0:
                logger.debug(f"Removed {removed_count} info extensions from '{source_cog}' for target cog '{target_cog}'")

    def get_info_extension_sources(self, target_cog: str) -> list[str]:
        """Get list of source cogs that have registered info extensions for a target cog.

        Args:
            target_cog: The name of the target cog

        Returns:
            List of source cog names
        """
        return [source for source, provider in self.info_extension_registry.get(target_cog, [])]
