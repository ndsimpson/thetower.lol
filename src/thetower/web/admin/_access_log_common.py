"""
Shared helpers for access log viewer and stats pages.
"""

import re
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import streamlit as st

# Matches lines produced by request_logger.py:
# 2026-03-21 14:32:01 UTC | 203.0.113.42    | /comparison | player_id=abc123
LOG_RE = re.compile(r"^(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)" r"\s*\|\s*(?P<ip>[^\|]+)" r"\s*\|\s*(?P<path>[^\|]+)" r"\s*\|\s*(?P<qs>.+)$")

# Matches rotated filenames: web_access.log.2026-03-21_14
FILE_RE = re.compile(r"^web_access\.log\.(\d{4}-\d{2}-\d{2})_(\d{2})$")


def get_log_dir() -> Path:
    from thetower.backend.env_config import get_csv_data

    log_dir = Path(get_csv_data()) / "web_logs"
    log_dir.mkdir(exist_ok=True)
    return log_dir


def catalog_files(log_dir: Path) -> dict[date, list[tuple[int, Path]]]:
    """Return {date: [(hour, path), ...]} with hours sorted ascending, dates newest first."""
    catalog: dict[date, list[tuple[int, Path]]] = defaultdict(list)

    for f in log_dir.glob("web_access.log.*"):
        m = FILE_RE.match(f.name)
        if m:
            d = date.fromisoformat(m.group(1))
            h = int(m.group(2))
            catalog[d].append((h, f))

    # Current active file — assign to current UTC hour
    current = log_dir / "web_access.log"
    if current.exists():
        now = datetime.now(timezone.utc)
        catalog[now.date()].append((now.hour, current))

    for d in catalog:
        catalog[d].sort(key=lambda x: x[0])

    return dict(sorted(catalog.items(), reverse=True))


def parse_files(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                m = LOG_RE.match(line.strip())
                if m:
                    rows.append(m.groupdict())
        except Exception as e:
            st.warning(f"Could not read {path.name}: {e}")
    return rows


def all_paths_for_dates(catalog: dict[date, list[tuple[int, Path]]], dates: list[date]) -> list[Path]:
    """Return all file paths across the given dates, in chronological order."""
    paths = []
    for d in sorted(dates):
        paths.extend(path for _, path in catalog.get(d, []))
    return paths
