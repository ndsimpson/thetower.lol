import logging
from pathlib import Path
from discord.ext.commands import Context, Paginator

from .configmanager import ConfigManager

logger = logging.getLogger(__name__)


class CogManager:
    """
    Utility class to manage cog loading, unloading, and configuration.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = ConfigManager()
        self.loaded_cogs = []
        self.unloaded_cogs = []

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