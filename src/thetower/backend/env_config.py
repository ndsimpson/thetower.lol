"""
Environment configuration utilities for thetower project.

This module provides centralized validation and access to required environment variables,
avoiding redundant validation code throughout the codebase.
"""

import os
from pathlib import Path


def get_csv_data() -> str:
    """
    Get and validate the CSV_DATA environment variable.

    Returns:
        str: Path to the CSV results cache directory (e.g., /data/results_cache)

    Raises:
        RuntimeError: If CSV_DATA is not set
    """
    csv_data = os.getenv("CSV_DATA")
    if not csv_data:
        raise RuntimeError(
            "CSV_DATA environment variable is not set. "
            "Please set it to the path where tournament CSV files should be stored (e.g., /data/results_cache)."
        )
    return csv_data


def get_django_data() -> Path:
    """
    Get and validate the DJANGO_DATA environment variable.

    Returns:
        Path: Path object to the Django data directory (e.g., /data/django)

    Raises:
        RuntimeError: If DJANGO_DATA is not set
    """
    django_data = os.getenv("DJANGO_DATA")
    if not django_data:
        raise RuntimeError(
            "DJANGO_DATA environment variable is not set. "
            "Please set it to the path where Django database and static files should be stored (e.g., /data/django)."
        )
    return Path(django_data)
