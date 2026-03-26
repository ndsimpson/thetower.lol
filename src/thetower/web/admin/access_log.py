"""
Access log viewer for the Tower admin site.

Reads from DJANGO_DATA/web_access.log and its rotated hourly backups.
"""

import logging

import pandas as pd
import streamlit as st

from thetower.web.admin._access_log_common import catalog_files, get_log_dir, parse_files

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
st.title("🌐 Web Access Log Viewer")

try:
    log_dir = get_log_dir()
except Exception as e:
    st.error(f"Cannot locate log directory: {e}")
    st.stop()

catalog = catalog_files(log_dir)

if not catalog:
    st.info("No access log files found yet.")
    st.stop()

available_dates = list(catalog.keys())  # newest first

# --- Time range controls ---
with st.expander("Time Range", expanded=True):
    col_date, col_mode = st.columns([2, 1])

    selected_date = col_date.selectbox(
        "Date (UTC)",
        available_dates,
        format_func=lambda d: d.isoformat(),
        index=0,
    )

    view_mode = col_mode.radio("Show", ["Full day", "Hour range"], horizontal=True)

    hours_for_date = [h for h, _ in catalog[selected_date]]
    min_h, max_h = min(hours_for_date), max(hours_for_date)

    if view_mode == "Hour range":
        col_h1, col_h2 = st.columns(2)
        start_hour = col_h1.selectbox("From hour (UTC)", list(range(24)), index=min_h, format_func=lambda h: f"{h:02d}:00")
        end_hour = col_h2.selectbox("To hour (UTC)", list(range(24)), index=max_h, format_func=lambda h: f"{h:02d}:59")
        if end_hour < start_hour:
            st.warning("End hour is before start hour — showing full day instead.")
            start_hour, end_hour = 0, 23
    else:
        start_hour, end_hour = 0, 23

# --- Text filters ---
with st.expander("Filters", expanded=True):
    col1, col2, col3, col4 = st.columns(4)
    ip_filter = col1.text_input("IP contains")
    path_filter = col2.text_input("Path contains")
    qs_filter = col3.text_input("Query string contains")
    ctx_filter = col4.text_input("Context contains")

# --- Load files for selected date + hour range ---
selected_paths = [path for h, path in catalog[selected_date] if start_hour <= h <= end_hour]
rows = parse_files(selected_paths)

# --- Apply text filters ---
filtered = rows
if ip_filter:
    filtered = [r for r in filtered if ip_filter.lower() in r["ip"].lower()]
if path_filter:
    filtered = [r for r in filtered if path_filter.lower() in r["path"].lower()]
if qs_filter:
    filtered = [r for r in filtered if qs_filter.lower() in r["qs"].lower()]
if ctx_filter:
    filtered = [r for r in filtered if ctx_filter.lower() in r["ctx"].lower()]

# --- Summary ---
hour_label = f"{start_hour:02d}:00\u2013{end_hour:02d}:59" if view_mode == "Hour range" else "all day"
st.caption(f"Showing {len(filtered):,} of {len(rows):,} entries \u2014 " f"{selected_date.isoformat()} {hour_label} ({len(selected_paths)} file(s))")

# --- Display ---
if filtered:
    df = pd.DataFrame(filtered, columns=["dt", "site", "ip", "path", "qs", "ctx"])
    df.columns = ["Datetime (UTC)", "Site", "IP", "Path", "Query String", "Context"]
    st.dataframe(df, width="stretch", hide_index=True)
else:
    st.info("No entries match the current filters.")
