"""
Maintenance mode utilities for the Tower web interface.

Reads and writes maintenance state from DJANGO_DATA/maintenance_mode.json.
The file is stored in the Django data directory so it persists across site updates.
"""

import json
import logging
from pathlib import Path

from thetower.backend.env_config import get_django_data

logger = logging.getLogger(__name__)

MAINTENANCE_FILE_NAME = "maintenance_mode.json"
DEFAULT_HEADER = "Site Maintenance"
DEFAULT_MESSAGE = "The Tower tournament site is currently undergoing maintenance. Please check back soon."


def _get_maintenance_file() -> Path:
    return get_django_data() / MAINTENANCE_FILE_NAME


def get_maintenance_state() -> dict:
    """
    Read maintenance mode state from disk.

    Returns:
        dict with keys 'enabled' (bool) and 'message' (str).
        Returns defaults if the file does not exist or cannot be read.
    """
    path = _get_maintenance_file()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return {
                "enabled": bool(data.get("enabled", False)),
                "header": str(data.get("header", DEFAULT_HEADER)),
                "message": str(data.get("message", DEFAULT_MESSAGE)),
            }
    except Exception:
        logger.exception("Failed to read maintenance mode state from %s", path)
    return {"enabled": False, "header": DEFAULT_HEADER, "message": DEFAULT_MESSAGE}


def set_maintenance_state(enabled: bool, header: str, message: str) -> None:
    """
    Write maintenance mode state to disk.

    Args:
        enabled: Whether maintenance mode should be active.
        header: The heading to display on the maintenance page.
        message: The message to display to visitors.

    Raises:
        Exception: If the file cannot be written.
    """
    path = _get_maintenance_file()
    path.write_text(json.dumps({"enabled": enabled, "header": header, "message": message}, indent=2), encoding="utf-8")
