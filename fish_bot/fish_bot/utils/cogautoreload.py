import asyncio
import logging
import time
from pathlib import Path
from watchdog.events import FileSystemEventHandler


class CogAutoReload(FileSystemEventHandler):
    def __init__(self, bot):
        self.bot = bot
        self.last_reload = {}  # Track last reload time per cog
        self.logger = logging.getLogger(__name__)

    async def reload_cog(self, cog_name):
        try:
            # Check if enough time has passed since last reload
            current_time = time.time()
            if cog_name in self.last_reload:
                if current_time - self.last_reload[cog_name] < 1:  # 1 second cooldown
                    return

            self.last_reload[cog_name] = current_time
            await self.bot.cog_manager.reload_cog(cog_name)
            self.logger.info(f"🔄 Auto-reloaded cog: {cog_name}")
        except Exception as e:
            self.logger.error(f"❌ Failed to auto-reload {cog_name}: {e}")

    def on_modified(self, event):
        path = Path(event.src_path)
        if path.suffix == '.py':
            cog_name = path.stem
            if cog_name in self.bot.cog_manager.loaded_cogs:
                asyncio.run_coroutine_threadsafe(
                    self.reload_cog(cog_name),
                    self.bot.loop
                )
