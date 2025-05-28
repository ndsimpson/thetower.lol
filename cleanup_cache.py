import shutil
from pathlib import Path
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


def cleanup_pycache(start_path: Path):
    """Remove all __pycache__ directories recursively starting from start_path."""
    try:
        for item in start_path.rglob('__pycache__'):
            if item.is_dir():
                shutil.rmtree(item)
                logging.info(f"Removed: {item}")
    except Exception as e:
        logging.error(f"Error while cleaning up {item}: {e}")


if __name__ == '__main__':
    # Use the current directory as the starting point
    root_dir = Path.cwd()
    cleanup_pycache(root_dir)