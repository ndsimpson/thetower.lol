#!/usr/bin/env python
"""
Setup script to extract Streamlit pages from installed thetower package.

This script copies the src/thetower/web/ directory from the installed package
to /opt/thetower/, ensuring Streamlit services have access to pages.py and
related files. Safe to run multiple times (overwrites existing files).
"""
import logging
import shutil
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

STREAMLIT_TARGET_DIR = Path("/opt/thetower")


def setup_streamlit():
    """Extract Streamlit pages from package to /opt/thetower/."""
    try:
        import thetower

        # Get the thetower package location
        thetower_path = Path(thetower.__file__).parent
        logger.info(f"Found thetower package at {thetower_path}")

        # Source: web subdirectory of thetower package
        web_src = thetower_path / "web"

        if not web_src.exists():
            raise FileNotFoundError(f"Web directory not found at {web_src}")

        # Target: /opt/thetower/src/thetower/web
        web_dst = STREAMLIT_TARGET_DIR / "src" / "thetower" / "web"

        logger.info(f"Setting up Streamlit pages from {web_src} to {web_dst}")

        # Create parent directories
        web_dst.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing web dir if present
        if web_dst.exists():
            logger.info(f"Removing existing {web_dst}")
            shutil.rmtree(web_dst)

        # Copy web directory
        shutil.copytree(web_src, web_dst)

        logger.info(f"✓ Streamlit pages extracted successfully to {web_dst}")
        return 0

    except Exception as e:
        logger.error(f"✗ Failed to setup Streamlit: {e}")
        import traceback

        traceback.print_exc()
        return 1


def main():
    """Entry point for thetower-init-streamlit command."""
    sys.exit(setup_streamlit())


if __name__ == "__main__":
    main()
