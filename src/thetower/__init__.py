"""
Tower - The Tower tournament results and Discord bot system.

A unified package for managing The Tower tournament data, providing web interfaces,
Discord bot functionality, and data analysis tools.
"""

try:
    from importlib.metadata import version

    __version__ = version("thetower")
except Exception:
    __version__ = "unknown"

__all__ = [
    "__version__",
]
