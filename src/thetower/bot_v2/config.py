import json
import logging
from pathlib import Path
from typing import Any, Dict

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
        with open(self.path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
        logger.info("Config loaded")

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
        logger.info("Config saved")

    def get(self, key: str, default=None):
        return self.config.get(key, default)

    def set(self, key: str, value):
        self.config[key] = value
        self.save()

