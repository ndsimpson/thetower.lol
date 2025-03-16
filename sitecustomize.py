"""Custom site configuration for Python interpreter."""

import os
import sys

# Get the project root directory
project_root = os.path.dirname(__file__)

# Set custom location for bytecode files
# Store them in the virtual environment directory if running in a venv
if hasattr(sys, "real_prefix") or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix):
    # Running in a virtual environment
    venv_dir = sys.prefix
    cache_dir = os.path.join(venv_dir, ".cache", "bytecode")
else:
    # Not in a virtual environment, use project directory
    cache_dir = os.path.join(project_root, ".cache", "bytecode")

os.makedirs(cache_dir, exist_ok=True)
sys.pycache_prefix = cache_dir
