"""
Basic web request logger for the Streamlit site.

Logs each unique page visit (by URL path) to a rotating access log file.
Only logs once per URL per session to avoid spamming on Streamlit re-runs.
"""

import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
import streamlit.runtime.scriptrunner as _scriptrunner

logger = logging.getLogger("web.access")
_configured = False

# Module-level dedup: {session_id: last_logged_url}
# Keyed by Streamlit session ID so it works across both script runs per navigation,
# unlike session_state which can be cleared between the routing and render runs.
_session_last_url: dict[str, str] = {}


def _get_session_id() -> str:
    try:
        ctx = _scriptrunner.get_script_run_ctx()
        return ctx.session_id if ctx else "unknown"
    except Exception:
        return "unknown"


def _setup_logger() -> None:
    global _configured
    if _configured:
        return

    try:
        from thetower.backend.env_config import get_csv_data

        log_dir = Path(get_csv_data()) / "web_logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / "web_access.log"
    except Exception:
        log_file = Path("web_access.log")

    handler = logging.handlers.TimedRotatingFileHandler(
        log_file,
        when="h",
        backupCount=720,  # keep 30 days × 24 hours
        encoding="utf-8",
        utc=True,
    )
    handler.suffix = "%Y-%m-%d_%H"  # rotated files: web_access.log.2026-03-21_14
    # Override extMatch so backupCount cleanup recognises our custom suffix format
    import re as _re

    handler.extMatch = _re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}$", _re.ASCII)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    _configured = True


def _get_client_ip() -> str:
    """Return the real visitor IP, preferring Cloudflare's header over generic proxy headers."""
    try:
        headers = st.context.headers
        for header in ("cf-connecting-ip", "x-forwarded-for", "x-real-ip"):
            value = headers.get(header)
            if value:
                # x-forwarded-for can be a comma-separated chain; take the first (client) IP
                return value.split(",")[0].strip()
        # No proxy headers — likely a direct/local request; use the Host as a hint
        return headers.get("host", "localhost")
    except Exception:
        pass
    return "unknown"


def log_request() -> None:
    """Log a web request, skipping duplicate logs within the same session.

    Should be called once per page run, just before pg.run() in pages.py.
    Uses a module-level dict keyed by Streamlit session ID to deduplicate across
    both script runs that Streamlit performs per navigation event.
    """
    _setup_logger()

    try:
        current_url = str(st.context.url)
        path = urlparse(current_url).path or "/"
    except Exception:
        try:
            path = f"/?{dict(st.query_params)}"
        except Exception:
            path = "/"
        current_url = path

    session_id = _get_session_id()
    if _session_last_url.get(session_id) == current_url:
        return
    _session_last_url[session_id] = current_url

    try:
        query_params = dict(st.query_params)
    except Exception:
        query_params = {}

    ip = _get_client_ip()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    qs = "&".join(f"{k}={v}" for k, v in query_params.items()) if query_params else "-"

    logger.info("%s | %-15s | %s | %s", now, ip, path, qs)
