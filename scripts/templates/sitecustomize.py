"""Custom site configuration for Python interpreter.

NOTE: This file must be copied to the virtual environment's site-packages directory
to take effect. Run: Copy-Item sitecustomize.py .venv\\Lib\\site-packages\\sitecustomize.py

This will redirect all Python bytecode (.pyc files) to a centralized cache directory
instead of creating __pycache__ folders throughout the project.
"""

import os
import sys

# Get the project root directory
# When sitecustomize.py is in site-packages, we need to find the actual project root
# Look for common project indicators like pyproject.toml, setup.py, .git, etc.


def find_project_root():
    """Find the project root directory by looking for project markers."""
    import os

    # Start from current working directory
    current_dir = os.getcwd()

    # Look for project markers
    markers = ["pyproject.toml", "setup.py", ".git", "requirements.txt", "README.md"]

    # Walk up the directory tree
    check_dir = current_dir
    while check_dir != os.path.dirname(check_dir):  # Stop at filesystem root
        for marker in markers:
            if os.path.exists(os.path.join(check_dir, marker)):
                return check_dir
        check_dir = os.path.dirname(check_dir)

    # Fallback to current working directory
    return current_dir


project_root = find_project_root()

# Set custom location for bytecode files
# Best practice: Use project-level cache directory that survives venv recreation
# and can be shared across different environments
cache_dir = os.path.join(project_root, ".cache", "python")

# Create cache directory if it doesn't exist
os.makedirs(cache_dir, exist_ok=True)
sys.pycache_prefix = cache_dir
