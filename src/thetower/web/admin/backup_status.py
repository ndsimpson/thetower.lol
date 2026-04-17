"""Backup Status admin page.

Shows Cloudflare R2 backup health by querying the bucket live using the
read-only R2 credentials. Data is cached for 5 minutes.
"""

import logging
import os
from datetime import datetime, timezone

import streamlit as st

logger = logging.getLogger(__name__)

_PREFIXES = {
    "tar": {"label": "Raw Tars", "icon": "📦", "description": "Snapshot tar archives (indefinite lock)"},
    "db/daily": {"label": "DB Daily", "icon": "📅", "description": "Daily database backups (9-day expiry)"},
    "db/weekly": {"label": "DB Weekly", "icon": "🗓️", "description": "Weekly database backups (36-day expiry)"},
    "db/monthly": {"label": "DB Monthly", "icon": "📆", "description": "Monthly database backups (13-month expiry)"},
}


def _fmt_bytes(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f} GB"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    if n >= 1_000:
        return f"{n / 1_000:.1f} KB"
    return f"{n} B"


def _time_ago(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = datetime.now(timezone.utc) - dt
    days = diff.days
    seconds = diff.seconds
    if days > 1:
        return f"{days} days ago"
    if days == 1:
        return "1 day ago"
    if seconds >= 3600:
        hours = seconds // 3600
        return f"{hours}h ago"
    if seconds >= 60:
        return f"{seconds // 60}m ago"
    return "just now"


def _credentials_available() -> bool:
    return bool(
        os.getenv("R2_ACCOUNT_ID") and os.getenv("R2_READ_ACCESS_KEY_ID") and os.getenv("R2_READ_SECRET_ACCESS_KEY") and os.getenv("R2_BUCKET_NAME")
    )


@st.cache_data(ttl=300)
def _fetch_prefix_stats(prefix: str) -> dict:
    """Fetch and aggregate object stats for a given R2 prefix. Cached 5 minutes."""
    try:
        from thetower.backend.backup.r2_client import get_r2_bucket, get_r2_read_client

        client = get_r2_read_client()
        bucket = get_r2_bucket()
        paginator = client.get_paginator("list_objects_v2")

        objects = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix + "/"):
            for obj in page.get("Contents", []):
                objects.append(obj)

        objects.sort(key=lambda o: o["LastModified"], reverse=True)
        total_size = sum(o["Size"] for o in objects)
        return {"count": len(objects), "total_size": total_size, "objects": objects, "error": None}

    except Exception as exc:
        logger.exception(f"Failed to fetch R2 stats for prefix {prefix!r}")
        return {"count": 0, "total_size": 0, "objects": [], "error": str(exc)}


def backup_status_page() -> None:
    st.title("☁️ Backup Status")

    col_refresh, col_updated = st.columns([1, 3])
    with col_refresh:
        if st.button("🔄 Refresh"):
            _fetch_prefix_stats.clear()
            st.rerun()
    with col_updated:
        st.caption(f"Data cached for 5 minutes · Last render: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

    if not _credentials_available():
        st.warning("R2 read credentials not configured. " "Set R2_ACCOUNT_ID, R2_BUCKET_NAME, R2_READ_ACCESS_KEY_ID, and R2_READ_SECRET_ACCESS_KEY.")
        return

    # Summary metric row
    st.markdown("---")
    cols = st.columns(len(_PREFIXES))
    all_stats: dict[str, dict] = {}

    for i, (prefix, meta) in enumerate(_PREFIXES.items()):
        stats = _fetch_prefix_stats(prefix)
        all_stats[prefix] = stats
        with cols[i]:
            if stats["error"]:
                st.metric(f"{meta['icon']} {meta['label']}", "Error")
                st.caption(stats["error"][:80])
            else:
                last_obj = stats["objects"][0] if stats["objects"] else None
                last_str = _time_ago(last_obj["LastModified"]) if last_obj else "never"
                st.metric(
                    f"{meta['icon']} {meta['label']}",
                    f"{stats['count']} files",
                    _fmt_bytes(stats["total_size"]),
                )
                st.caption(f"Last: {last_str}")

    # Detailed per-prefix tables
    st.markdown("---")
    for prefix, meta in _PREFIXES.items():
        stats = all_stats[prefix]
        default_expanded = prefix in ("db/daily", "db/weekly")

        with st.expander(f"{meta['icon']} {meta['label']} — {meta['description']}", expanded=default_expanded):
            if stats["error"]:
                st.error(f"Error: {stats['error']}")
                continue

            if not stats["objects"]:
                st.info("No backups found in this prefix.")
                continue

            rows = []
            for obj in stats["objects"][:25]:
                last_mod: datetime = obj["LastModified"]
                rows.append(
                    {
                        "Filename": obj["Key"].split("/")[-1],
                        "Size": _fmt_bytes(obj["Size"]),
                        "Uploaded": last_mod.strftime("%Y-%m-%d %H:%M UTC"),
                        "Age": _time_ago(last_mod),
                    }
                )

            st.dataframe(rows, use_container_width=True, hide_index=True)

            if stats["count"] > 25:
                st.caption(f"Showing 25 of {stats['count']} objects · Total: {_fmt_bytes(stats['total_size'])}")
            else:
                st.caption(f"Total: {_fmt_bytes(stats['total_size'])}")


backup_status_page()
