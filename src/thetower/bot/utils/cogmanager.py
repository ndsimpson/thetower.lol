import logging
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

    async def load_cogs(self) -> None:
        """
        Load cogs based on bot owner settings.
        Loads all cogs that are enabled by the bot owner.
        """
        cogs_path = Path(__file__).parent.parent.resolve() / "cogs"
        logger.debug(f"Starting cog loading from {cogs_path}")

        # Get all bot owner cog configurations
        bot_owner_cogs = self.config.get_all_bot_owner_cogs()

        # Track cogs we've attempted to load to prevent duplicates
        attempted_loads = set()

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
                # Skip if we've already attempted this cog
                if extension in attempted_loads:
                    logger.debug(f"Skipping duplicate load attempt for '{extension}'")
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
                    await self.bot.load_extension(f"thetower.bot.cogs.{extension}")
                    if extension not in self.loaded_cogs:
                        self.loaded_cogs.append(extension)
                        logger.info(f"Loaded extension '{extension}'")
                except Exception as e:
                    exception = f"{type(e).__name__}: {e}"
                    logger.error(f"Failed to load extension {extension}\n{exception}")
                    if extension not in self.unloaded_cogs:
                        self.unloaded_cogs.append(extension)

    def get_available_cogs(self) -> list[str]:
        """Get list of all available cogs from the filesystem.

        Returns:
            List of cog names found in the cogs directory
        """
        cogs_path = Path(__file__).parent.parent.resolve() / "cogs"
        available_cogs = []

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
            is_bot_owner: Whether the user is the bot owner (bypasses all checks)

        Returns:
            True if the guild can use the cog, False otherwise
        """
        # Bot owner bypasses all checks
        if is_bot_owner:
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
        parts = filename.split('_')
        return ''.join(word.capitalize() for word in parts)

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
        snake = re.sub('([a-z0-9])([A-Z])', r'\1_\2', class_name)
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
        class_name_with_spaces = ' '.join(word.capitalize() for word in filename.split('_'))
        cog = self.bot.get_cog(class_name_with_spaces)
        if cog:
            return cog

        # Try strategy 3: Search through all loaded cogs
        # This handles custom names set in the cog definition
        for cog in self.bot.cogs.values():
            # Check if the cog's module matches the filename
            if hasattr(cog, '__module__'):
                module_parts = cog.__module__.split('.')
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

            await self.bot.reload_extension(f"thetower.bot.cogs.{cog_name}")
            logger.info(f"Reloaded cog '{cog_name}'")
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
            await self.bot.unload_extension(f"thetower.bot.cogs.{cog_name}")
            if cog_name in self.loaded_cogs:
                self.loaded_cogs.remove(cog_name)
                self.unloaded_cogs.append(cog_name)
            logger.info(f"Unloaded cog '{cog_name}'")
            return True
        except Exception as e:
            logger.error(f"Failed to unload cog '{cog_name}': {str(e)}")
            return False

    async def load_cog(self, cog_name: str) -> bool:
        """Load a specific cog if enabled by bot owner"""
        # Check if bot owner has enabled this cog
        cog_config = self.config.get_bot_owner_cog_config(cog_name)
        if not cog_config.get("enabled", False):
            logger.warning(f"Cannot load cog '{cog_name}' - not enabled by bot owner")
            return False

        # Now proceed with loading if allowed
        try:
            await self.bot.load_extension(f"thetower.bot.cogs.{cog_name}")
            if cog_name in self.unloaded_cogs:
                self.unloaded_cogs.remove(cog_name)
            if cog_name not in self.loaded_cogs:
                self.loaded_cogs.append(cog_name)
            logger.info(f"Loaded cog '{cog_name}'")
            return True
        except Exception as e:
            logger.error(f"Failed to load cog '{cog_name}': {str(e)}")
            return False

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
                    self.bot.tree.copy_global_to(guild=guild)
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
                    self.bot.tree.copy_global_to(guild=guild)
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

        # Get cog files
        cogs_path = Path(__file__).parent.parent.resolve() / "cogs"
        available_cogs = [file.stem for file in cogs_path.iterdir() if file.suffix == ".py" and not file.stem.startswith("_")]

        cog_status = []
        for cog in sorted(available_cogs):
            cog_config = bot_owner_cogs.get(cog, {})
            is_allowed = self.config.is_cog_allowed_for_guild(cog, guild_id)

            status = {
                "name": cog,
                "loaded": cog in self.loaded_cogs,
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
