#!/usr/bin/env python
"""
Setup script to extract Streamlit pages from installed thetower package.

This script copies the src/thetower/web/ directory from the installed package
to /opt/thetower/, ensuring Streamlit services have access to pages.py and
related files. Idempotent: skips extraction if version hasn't changed.
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
VERSION_MARKER = STREAMLIT_TARGET_DIR / ".thetower_version"


def setup_streamlit():
    """Extract Streamlit pages from package to /opt/thetower/ if version changed."""
    try:
        import thetower

        # Get the installed thetower version
        try:
            # Try to get version from package
            installed_version = thetower.__version__
        except AttributeError:
            # Fallback: use pkg_resources or importlib.metadata
            try:
                from importlib.metadata import version
                installed_version = version("thetower")
            except Exception:
                # If all else fails, use a timestamp-based marker
                installed_version = "unknown"

        # Check if we already extracted this version
        if VERSION_MARKER.exists():
            existing_version = VERSION_MARKER.read_text().strip()
            if existing_version == installed_version:
                logger.info(
                    f"Streamlit pages already up-to-date "
                    f"(version {installed_version})"
                )
                return 0

        # Get the thetower package location
        thetower_path = Path(thetower.__file__).parent
        logger.info(f"Found thetower package at {thetower_path}")

        # Source: web subdirectory of thetower package
        web_src = thetower_path / "web"

        if not web_src.exists():
            raise FileNotFoundError(f"Web directory not found at {web_src}")

        # Target: /opt/thetower/src/thetower/web
        web_dst = STREAMLIT_TARGET_DIR / "src" / "thetower" / "web"

        logger.info(f"Extracting Streamlit pages (version {installed_version})")
        logger.info(f"  Source: {web_src}")
        logger.info(f"  Target: {web_dst}")

        # Create parent directories
        web_dst.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing web dir if present
        if web_dst.exists():
            logger.info(f"Removing existing {web_dst}")
            shutil.rmtree(web_dst)

        # Copy web directory
        shutil.copytree(web_src, web_dst)

        # Write version marker
        VERSION_MARKER.write_text(installed_version)

        logger.info("✓ Streamlit pages extracted successfully")
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
