import asyncio
import logging
import time
from pathlib import Path
from typing import Dict, Tuple
from discord.ext.commands import Context, Paginator
from discord import Embed, Color
from watchdog.events import FileSystemEventHandler, FileModifiedEvent
from watchdog.observers import Observer

from .configmanager import ConfigManager

logger = logging.getLogger(__name__)


class CogManager(FileSystemEventHandler):
    """
    Utility class to manage cog loading, unloading, configuration, and auto-reloading.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = ConfigManager()
        self.loaded_cogs = []
        self.unloaded_cogs = []

        # Auto-reload related attributes
        self.last_reload: Dict[str, float] = {}  # Track last reload time per cog
        self.reload_cooldown = 1.0  # 1 second cooldown between reloads
        self.observer = None
        self.watching_path = None

        # Initialize auto-reload settings if they don't exist
        if not self.config.has_cog_setting("cogmanager", "auto_reload_enabled"):
            self.config.set_cog_setting("cogmanager", "auto_reload_enabled", False)

        if not self.config.has_cog_setting("cogmanager", "auto_reload_cogs"):
            self.config.set_cog_setting("cogmanager", "auto_reload_cogs", [])

        # Start observer if auto-reload is enabled
        if self.config.get_cog_setting("cogmanager", "auto_reload_enabled", False):
            self.start_observer()

    def start_observer(self):
        """Start the file system observer for auto-reloading."""
        if self.observer is not None:
            # Observer is already running
            return

        try:
            cogs_path = Path(__file__).parent.parent.resolve() / "cogs"
            self.watching_path = cogs_path

            self.observer = Observer()
            self.observer.schedule(self, str(cogs_path), recursive=False)
            self.observer.start()
            logger.info(f"Started auto-reload file watcher on {cogs_path}")
        except Exception as e:
            logger.error(f"Failed to start auto-reload observer: {e}", exc_info=True)
            self.observer = None

    def stop_observer(self):
        """Stop the file system observer."""
        if self.observer is not None:
            try:
                self.observer.stop()
                self.observer.join()
                logger.info("Stopped auto-reload file watcher")
            except Exception as e:
                logger.error(f"Error stopping auto-reload observer: {e}")
            finally:
                self.observer = None

    def on_modified(self, event: FileModifiedEvent) -> None:
        """
        Handle file modification events by reloading the corresponding cog.

        This method is called automatically by the watchdog observer when a file
        is modified in the watched directory.

        Args:
            event: The file system event containing information about the modified file
        """
        # Skip if auto-reload is disabled globally
        if not self.config.get_cog_setting("cogmanager", "auto_reload_enabled", False):
            return

        # Skip directory events and non-Python files
        if event.is_directory:
            return

        path = Path(event.src_path)
        if path.suffix != '.py':
            return

        cog_name = path.stem

        # Check if this specific cog has auto-reload enabled
        auto_reload_cogs = self.config.get_cog_setting("cogmanager", "auto_reload_cogs", [])
        if cog_name not in auto_reload_cogs:
            logger.debug(f"Modified file {cog_name}.py has auto-reload disabled, ignoring")
            return

        # Check if this is a loaded cog before attempting to reload
        if cog_name in self.loaded_cogs:
            asyncio.run_coroutine_threadsafe(
                self.auto_reload_cog(cog_name),
                self.bot.loop
            )
        else:
            logger.debug(f"Modified file {cog_name}.py is not a loaded cog, ignoring")

    async def auto_reload_cog(self, cog_name: str) -> None:
        """
        Reload a cog if it's not on cooldown.

        Args:
            cog_name: The name of the cog to reload
        """
        try:
            # Check if enough time has passed since last reload
            current_time = time.time()
            if cog_name in self.last_reload:
                time_since_reload = current_time - self.last_reload[cog_name]
                if time_since_reload < self.reload_cooldown:
                    logger.debug(f"Skipped reload of {cog_name}: cooldown active ({time_since_reload:.2f}s < {self.reload_cooldown}s)")
                    return

            # Update the last reload time before attempting reload
            self.last_reload[cog_name] = current_time

            # Attempt to reload the cog
            success = await self.reload_cog(cog_name)

            if success:
                logger.info(f"🔄 Auto-reloaded cog: {cog_name}")
            else:
                logger.warning(f"⚠️ Auto-reload reported failure for cog: {cog_name}")

        except Exception as e:
            logger.error(f"❌ Failed to auto-reload {cog_name}: {e}", exc_info=True)

    async def toggle_auto_reload(self) -> bool:
        """Toggle the global auto_reload_enabled setting."""
        current_setting = self.config.get_cog_setting("cogmanager", "auto_reload_enabled", False)
        new_setting = not current_setting
        self.config.set_cog_setting("cogmanager", "auto_reload_enabled", new_setting)

        # Start or stop the observer based on the new setting
        if new_setting:
            self.start_observer()
        else:
            self.stop_observer()

        return new_setting

    async def toggle_cog_auto_reload(self, cog_name: str) -> Tuple[bool, bool]:
        """
        Toggle auto-reload for a specific cog.

        Args:
            cog_name: The name of the cog to toggle auto-reload for

        Returns:
            A tuple of (is_global_enabled, is_cog_enabled)
        """
        auto_reload_cogs = self.config.get_cog_setting("cogmanager", "auto_reload_cogs", [])
        global_enabled = self.config.get_cog_setting("cogmanager", "auto_reload_enabled", False)

        # Toggle the cog's auto-reload status
        if cog_name in auto_reload_cogs:
            auto_reload_cogs.remove(cog_name)
            cog_enabled = False
        else:
            auto_reload_cogs.append(cog_name)
            cog_enabled = True

        # Save the updated configuration
        self.config.set_cog_setting("cogmanager", "auto_reload_cogs", auto_reload_cogs)

        # Make sure the observer is started if needed
        if global_enabled and cog_enabled and self.observer is None:
            self.start_observer()

        return global_enabled, cog_enabled

    async def toggle_auto_reload_with_ctx(self, ctx: Context) -> None:
        """Toggle the global auto-reload setting with Discord context feedback."""
        new_setting = await self.toggle_auto_reload()
        status = "✅ enabled" if new_setting else "❌ disabled"
        await ctx.send(f"🔄 Auto-reload is now {status}.")

        # Additional message if auto-reload is enabled but no cogs are set to use it
        if new_setting and not self.config.get_cog_setting("cogmanager", "auto_reload_cogs", []):
            await ctx.send("⚠️ Note: Auto-reload is enabled globally, but no cogs are set to use it. "
                           "Use `toggle_cog_auto_reload <cog_name>` to enable for specific cogs.")

    async def toggle_cog_auto_reload_with_ctx(self, ctx: Context, cog_name: str) -> None:
        """Toggle auto-reload for a specific cog with Discord context feedback."""
        # Check if the cog exists first
        cogs_path = Path(__file__).parent.parent.resolve() / "cogs"
        cog_file = cogs_path / f"{cog_name}.py"

        if not cog_file.exists():
            return await ctx.send(f"❌ Error: Cog '{cog_name}' does not exist.")

        global_enabled, cog_enabled = await self.toggle_cog_auto_reload(cog_name)
        status = "✅ enabled" if cog_enabled else "❌ disabled"
        await ctx.send(f"🔄 Auto-reload for cog `{cog_name}` is now {status}.")

        # Additional message if the cog has auto-reload enabled but global auto-reload is disabled
        if cog_enabled and not global_enabled:
            await ctx.send("⚠️ Note: This cog is set to use auto-reload, but global auto-reload is disabled. "
                           "Use `toggle_auto_reload` to enable globally.")

    async def auto_reload_settings(self, ctx: Context) -> None:
        """Display auto-reload settings following the project's settings command pattern."""
        global_enabled = self.config.get_cog_setting("cogmanager", "auto_reload_enabled", False)
        enabled_cogs = self.config.get_cog_setting("cogmanager", "auto_reload_cogs", [])

        # Create standardized settings embed
        embed = Embed(
            title="Auto-Reload Settings",
            description="Current configuration for automatic cog reloading",
            color=Color.blue()
        )

        # Flag settings section
        global_status = "✅ Enabled" if global_enabled else "❌ Disabled"
        embed.add_field(
            name="Flag Settings",
            value=f"**Global Auto-Reload**: {global_status}",
            inline=False
        )

        # Cog settings section
        if enabled_cogs:
            cogs_text = ""
            for cog in sorted(enabled_cogs):
                # Check if the cog is currently loaded
                loaded_status = "✅ loaded" if cog in self.loaded_cogs else "⚠️ not loaded"
                cogs_text += f"• `{cog}` ({loaded_status})\n"
        else:
            cogs_text = "*No cogs are set to use auto-reload*"

        embed.add_field(
            name="Auto-Reload Enabled Cogs",
            value=cogs_text,
            inline=False
        )

        # Status information
        if self.observer is not None and self.observer.is_alive():
            status_emoji = "✅ Active"
            status_path = f"Watching: `{self.watching_path}`"
        else:
            status_emoji = "⏸️ Inactive"
            status_path = "No directory being monitored"

        embed.add_field(
            name="Observer Status",
            value=f"{status_emoji}\n{status_path}",
            inline=False
        )

        # Add footer with usage instructions
        embed.set_footer(text="Use toggle_auto_reload or toggle_cog_auto_reload <name> to change settings")

        await ctx.send(embed=embed)

    async def get_auto_reload_status(self, ctx: Context) -> None:
        """Display the status of auto-reload settings."""
        global_enabled = self.config.get("auto_reload_enabled", False)
        enabled_cogs = self.config.get("auto_reload_cogs", [])

        status = "✅ enabled" if global_enabled else "❌ disabled"
        message = f"**Auto-Reload Status**\n\nGlobal setting: {status}\n"

        if enabled_cogs:
            message += "\nCogs with auto-reload enabled:\n"
            for cog in enabled_cogs:
                # Check if the cog is currently loaded
                loaded_status = "✅ loaded" if cog in self.loaded_cogs else "⚠️ not loaded"
                message += f"- `{cog}` ({loaded_status})\n"
        else:
            message += "\nNo cogs are set to use auto-reload."

        await ctx.send(message)

    async def load_cogs(self) -> None:
        """
        Load cogs based on configuration settings.
        """
        cogs_path = Path(__file__).parent.parent.resolve() / "cogs"
        print(cogs_path)

        # Access global configuration for cogs
        enabled_cogs = self.config.get("enabled_cogs", [])
        disabled_cogs = self.config.get("disabled_cogs", [])
        load_all = self.config.get("load_all_cogs", False)

        logger.info(f"Cog loading configuration: load_all={load_all}, enabled={enabled_cogs}, disabled={disabled_cogs}")

        for file in cogs_path.iterdir():
            if file.suffix == ".py":
                extension = file.stem

                # Skip disabled cogs
                if extension in disabled_cogs:
                    logger.info(f"Skipping disabled extension '{extension}'")
                    self.unloaded_cogs.append(extension)
                    continue

                # Only load enabled cogs if not loading all
                if not load_all and extension not in enabled_cogs:
                    logger.info(f"Skipping non-enabled extension '{extension}'")
                    self.unloaded_cogs.append(extension)
                    continue

                try:
                    await self.bot.load_extension(f"cogs.{extension}")
                    self.loaded_cogs.append(extension)
                    logger.info(f"Loaded extension '{extension}'")
                except Exception as e:
                    exception = f"{type(e).__name__}: {e}"
                    logger.error(f"Failed to load extension {extension}\n{exception}")
                    self.unloaded_cogs.append(extension)

    async def reload_cog(self, cog_name: str) -> bool:
        """Reload a specific cog"""
        try:
            await self.bot.reload_extension(f"cogs.{cog_name}")
            logger.info(f"Reloaded cog '{cog_name}'")
            return True
        except Exception as e:
            logger.error(f"Failed to reload cog '{cog_name}': {str(e)}")
            return False

    async def unload_cog(self, cog_name: str) -> bool:
        """Unload a specific cog"""
        try:
            await self.bot.unload_extension(f"cogs.{cog_name}")
            if cog_name in self.loaded_cogs:
                self.loaded_cogs.remove(cog_name)
                self.unloaded_cogs.append(cog_name)
            logger.info(f"Unloaded cog '{cog_name}'")
            return True
        except Exception as e:
            logger.error(f"Failed to unload cog '{cog_name}': {str(e)}")
            return False

    async def load_cog(self, cog_name: str) -> bool:
        """Load a specific cog"""
        # First check if this cog is enabled or if load_all_cogs is enabled
        load_all = self.config.get("load_all_cogs", False)
        enabled_cogs = self.config.get("enabled_cogs", [])
        disabled_cogs = self.config.get("disabled_cogs", [])

        # Never load disabled cogs
        if cog_name in disabled_cogs:
            logger.warning(f"Cannot load disabled cog: {cog_name}")
            return False

        # Check if cog is enabled or load_all is true
        if not (load_all or cog_name in enabled_cogs):
            logger.warning(f"Cannot load cog that is not enabled: {cog_name}")
            return False

        # Now proceed with loading if allowed
        try:
            await self.bot.load_extension(f"cogs.{cog_name}")
            if cog_name in self.unloaded_cogs:
                self.unloaded_cogs.remove(cog_name)
                self.loaded_cogs.append(cog_name)
            logger.info(f"Loaded cog '{cog_name}'")
            return True
        except Exception as e:
            logger.error(f"Failed to load cog '{cog_name}': {str(e)}")
            return False

    async def enable_cog(self, cog_name: str) -> tuple:
        """Enable a cog in configuration and optionally load it"""
        # Get current configs
        enabled_cogs = self.config.get("enabled_cogs", [])
        disabled_cogs = self.config.get("disabled_cogs", [])
        success_msg = ""
        error_msg = ""

        # Update configs
        config_changed = False
        if cog_name in disabled_cogs:
            disabled_cogs.remove(cog_name)
            self.config.config["disabled_cogs"] = disabled_cogs
            config_changed = True

        if cog_name not in enabled_cogs:
            enabled_cogs.append(cog_name)
            self.config.config["enabled_cogs"] = enabled_cogs
            config_changed = True

        if config_changed:
            self.config.save_config()
            success_msg = f"✅ Cog `{cog_name}` has been enabled in configuration."

        # Try to load the cog if it's not already loaded
        if cog_name not in self.loaded_cogs:
            try:
                await self.load_cog(cog_name)
                success_msg += " Cog has been loaded."
            except Exception as e:
                error_msg = f"⚠️ Couldn't load cog: {str(e)}"

        return success_msg, error_msg

    async def disable_cog(self, cog_name: str) -> tuple:
        """Disable a cog in configuration and optionally unload it"""
        # Get current configs
        enabled_cogs = self.config.get("enabled_cogs", [])
        disabled_cogs = self.config.get("disabled_cogs", [])
        success_msg = ""
        error_msg = ""

        # Update configs
        config_changed = False
        if cog_name in enabled_cogs:
            enabled_cogs.remove(cog_name)
            self.config.config["enabled_cogs"] = enabled_cogs
            config_changed = True

        if cog_name not in disabled_cogs:
            disabled_cogs.append(cog_name)
            self.config.config["disabled_cogs"] = disabled_cogs
            config_changed = True

        if config_changed:
            self.config.save_config()
            success_msg = f"❌ Cog `{cog_name}` has been disabled in configuration."

        # Unload the cog if it's currently loaded
        if cog_name in self.loaded_cogs:
            try:
                await self.unload_cog(cog_name)
                success_msg += " Cog has been unloaded."
            except Exception as e:
                error_msg = f"⚠️ Couldn't unload cog: {str(e)}"

        return success_msg, error_msg

    async def toggle_load_all(self) -> bool:
        """Toggle the load_all_cogs setting"""
        current_setting = self.config.get("load_all_cogs", False)
        new_setting = not current_setting
        self.config.config["load_all_cogs"] = new_setting
        self.config.save_config()
        return new_setting

    def should_load_cog(self, cog_name: str) -> bool:
        """Check if a cog should be loaded based on configuration"""
        load_all = self.config.get("load_all_cogs", False)
        enabled_cogs = self.config.get("enabled_cogs", [])
        disabled_cogs = self.config.get("disabled_cogs", [])

        # Never load disabled cogs
        if cog_name in disabled_cogs:
            return False

        # Either load all cogs or check if it's in the enabled list
        return load_all or cog_name in enabled_cogs

    def get_cog_status_list(self):
        """Get comprehensive status information about all cogs"""
        # Get current configs
        enabled_cogs = self.config.get("enabled_cogs", [])
        disabled_cogs = self.config.get("disabled_cogs", [])
        load_all = self.config.get("load_all_cogs", False)

        # Get cog files
        cogs_path = Path(__file__).parent.parent.resolve() / "cogs"
        available_cogs = [file.stem for file in cogs_path.iterdir() if file.suffix == ".py"]

        cog_status = []
        for cog in available_cogs:
            status = {
                'name': cog,
                'loaded': cog in self.loaded_cogs,
                'explicitly_enabled': cog in enabled_cogs,
                'explicitly_disabled': cog in disabled_cogs,
                'effectively_enabled': load_all or cog in enabled_cogs,
                'effectively_disabled': cog in disabled_cogs or (not load_all and cog not in enabled_cogs)
            }
            cog_status.append(status)

        return cog_status, load_all

    async def list_modules(self, ctx: Context) -> None:
        """Lists all cogs and their status of loading."""
        cog_list = Paginator(prefix='', suffix='')
        cog_list.add_line('**✅ Successfully loaded:**')
        for cog in self.loaded_cogs:
            cog_list.add_line('- ' + cog)
        cog_list.add_line('**❌ Not loaded:**')
        for cog in self.unloaded_cogs:
            cog_list.add_line('- ' + cog)
        for page in cog_list.pages:
            await ctx.send(page)

    async def load_cog_with_ctx(self, ctx: Context, cog: str) -> None:
        """Try and load the selected cog with Discord context feedback."""
        # First check if this cog is enabled
        load_all = self.config.get("load_all_cogs", False)
        enabled_cogs = self.config.get("enabled_cogs", [])
        disabled_cogs = self.config.get("disabled_cogs", [])

        # Never load disabled cogs
        if cog in disabled_cogs:
            return await ctx.send('❌ Cannot load disabled cog. Enable it first with `enable_cog` command.')

        # Check if cog is enabled or load_all is true
        if not (load_all or cog in enabled_cogs):
            return await ctx.send('❌ Cannot load cog that is not enabled. Enable it first with `enable_cog` command.')

        if cog in self.loaded_cogs:
            return await ctx.send('Cog already loaded.')

        try:
            success = await self.load_cog(cog)
            if success:
                await ctx.send('✅ Module successfully loaded.')
            else:
                await ctx.send('**💢 Could not load module. Check logs for details.**')
        except Exception as e:
            await ctx.send('**💢 Could not load module: An exception was raised. For your convenience, the exception will be printed below:**')
            await ctx.send('```{}\n{}```'.format(type(e).__name__, e))

    async def unload_cog_with_ctx(self, ctx: Context, cog: str) -> None:
        """Unload the selected cog with Discord context feedback."""
        if cog not in self.loaded_cogs:
            return await ctx.send('💢 Module not loaded.')

        success = await self.unload_cog(cog)
        if success:
            await ctx.send('✅ Module successfully unloaded.')
        else:
            await ctx.send('**💢 Could not unload module. Check logs for details.**')

    async def reload_cog_with_ctx(self, ctx: Context, cog: str) -> None:
        """Reload the selected cog with Discord context feedback."""
        # Check if the cog is enabled before reloading
        load_all = self.config.get("load_all_cogs", False)
        enabled_cogs = self.config.get("enabled_cogs", [])
        disabled_cogs = self.config.get("disabled_cogs", [])

        if cog in disabled_cogs:
            return await ctx.send('❌ Cannot reload disabled cog. Enable it first with `enable_cog` command.')

        if not (load_all or cog in enabled_cogs):
            return await ctx.send('❌ Cannot reload cog that is not enabled. Enable it first with `enable_cog` command.')

        if cog not in self.loaded_cogs:
            return await ctx.send('💢 Module not loaded, cannot reload.')

        try:
            success = await self.reload_cog(cog)
            if success:
                await ctx.send('✅ Module successfully reloaded.')
            else:
                await ctx.send('**💢 Could not reload module. Check logs for details.**')
        except Exception as e:
            await ctx.send('**💢 Could not reload module: An exception was raised. For your convenience, the exception will be printed below:**')
            await ctx.send('```{}\n{}```'.format(type(e).__name__, e))

    async def enable_cog_with_ctx(self, ctx: Context, cog: str) -> None:
        """Enable a cog with Discord context feedback."""
        success_msg, error_msg = await self.enable_cog(cog)

        if success_msg:
            await ctx.send(success_msg)
        if error_msg:
            await ctx.send(error_msg)

    async def disable_cog_with_ctx(self, ctx: Context, cog: str) -> None:
        """Disable a cog with Discord context feedback."""
        success_msg, error_msg = await self.disable_cog(cog)

        if success_msg:
            await ctx.send(success_msg)
        if error_msg:
            await ctx.send(error_msg)