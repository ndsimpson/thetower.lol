import logging
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


class BaseFileMonitor:
    def __init__(self):
        self._observer = None

    def start_monitoring(self, path: Path, handler: FileSystemEventHandler, recursive: bool = False):
        """Start monitoring a path with a specific handler."""
        self._observer = Observer()
        self._observer.schedule(handler, str(path), recursive=recursive)
        self._observer.start()
        logger.info(f"Started monitoring: {path}")

    def stop_monitoring(self):
        """Stop monitoring."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            logger.info("Stopped monitoring")
