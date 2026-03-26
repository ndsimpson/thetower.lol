"""
Access log statistics for the Tower admin site.

Aggregates parsed log data into counts by page, IP, hour, and day.
Supports filtering by date range, IP, and path before aggregation.
"""

import logging
from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from thetower.web.admin._access_log_common import all_paths_for_dates, catalog_files, get_log_dir, parse_files

logger = logging.getLogger(__name__)

st.title("📊 Web Access Log Statistics")

# ---------------------------------------------------------------------------
# Load catalog
# ---------------------------------------------------------------------------
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
min_date, max_date = min(available_dates), max(available_dates)

# ---------------------------------------------------------------------------
# Date range selector
# ---------------------------------------------------------------------------
with st.expander("Date Range (UTC)", expanded=True):
    col1, col2 = st.columns(2)
    start_date = col1.date_input("From", value=max(min_date, max_date - timedelta(days=6)), min_value=min_date, max_value=max_date)
    end_date = col2.date_input("To", value=max_date, min_value=min_date, max_value=max_date)

    if end_date < start_date:
        st.warning("End date is before start date.")
        st.stop()

selected_dates = [d for d in available_dates if start_date <= d <= end_date]

if not selected_dates:
    st.info("No log files in the selected date range.")
    st.stop()

# ---------------------------------------------------------------------------
# Load + parse all files in range
# ---------------------------------------------------------------------------
paths = all_paths_for_dates(catalog, selected_dates)

with st.spinner("Loading log data…"):
    rows = parse_files(paths)

if not rows:
    st.info("No log entries in the selected date range.")
    st.stop()

df = pd.DataFrame(rows)
for col in ["dt", "site", "ip", "path", "qs", "ctx"]:
    if col not in df.columns:
        df[col] = "-"
df["ip"] = df["ip"].str.strip()
df["path"] = df["path"].str.strip()

# Parse timestamps
df["timestamp"] = pd.to_datetime(df["dt"], format="%Y-%m-%d %H:%M:%S UTC", utc=True, errors="coerce")
df = df.dropna(subset=["timestamp"])
df["date"] = df["timestamp"].dt.date
df["hour"] = df["timestamp"].dt.floor("h")

# ---------------------------------------------------------------------------
# Pre-filter controls
# ---------------------------------------------------------------------------
with st.expander("Filters", expanded=True):
    col_site, col_ip, col_path = st.columns(3)
    site_options = sorted(df["site"].unique().tolist())
    site_filter = col_site.multiselect("Site", site_options, default=site_options)
    ip_filter = col_ip.text_input("IP contains")
    path_filter = col_path.text_input("Path contains")

if site_filter:
    df = df[df["site"].isin(site_filter)]

if ip_filter:
    df = df[df["ip"].str.contains(ip_filter, case=False, na=False)]
if path_filter:
    df = df[df["path"].str.contains(path_filter, case=False, na=False)]

if df.empty:
    st.info("No entries match the current filters.")
    st.stop()

total = len(df)
st.caption(f"**{total:,} requests** across {len(selected_dates)} day(s) " f"({start_date.isoformat()} → {end_date.isoformat()})")

st.divider()

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_time, tab_pages, tab_ips = st.tabs(["📅 Over Time", "📄 By Page", "🌐 By IP"])

# ── Over Time ───────────────────────────────────────────────────────────────
with tab_time:
    granularity = st.radio("Granularity", ["Hourly", "Daily"], horizontal=True)

    if granularity == "Hourly":
        counts = df.groupby("hour").size().reset_index(name="Requests")
        counts.rename(columns={"hour": "Time (UTC)"}, inplace=True)
        fig = px.bar(counts, x="Time (UTC)", y="Requests", title="Requests per Hour")
    else:
        counts = df.groupby("date").size().reset_index(name="Requests")
        counts.rename(columns={"date": "Date"}, inplace=True)
        fig = px.bar(counts, x="Date", y="Requests", title="Requests per Day")

    st.plotly_chart(fig, width="stretch")

# ── By Page ─────────────────────────────────────────────────────────────────
with tab_pages:
    col_n, col_sort = st.columns([1, 1])
    top_n = col_n.slider("Show top N pages", min_value=5, max_value=50, value=20, step=5)
    sort_by = col_sort.radio("Sort by", ["Count", "Path"], horizontal=True)

    page_counts = df.groupby("path").size().reset_index(name="Requests")

    if sort_by == "Count":
        page_counts = page_counts.sort_values("Requests", ascending=False)
    else:
        page_counts = page_counts.sort_values("path")

    top_pages = page_counts.head(top_n)
    fig_pages = px.bar(
        top_pages.sort_values("Requests"),
        x="Requests",
        y="path",
        orientation="h",
        title=f"Top {top_n} Pages by Request Count",
        labels={"path": "Page"},
    )
    fig_pages.update_layout(height=max(300, top_n * 22))
    st.plotly_chart(fig_pages, width="stretch")

    st.dataframe(page_counts, width="stretch", hide_index=True)

# ── By IP ────────────────────────────────────────────────────────────────────
with tab_ips:
    col_n2, col_sort2 = st.columns([1, 1])
    top_n_ip = col_n2.slider("Show top N IPs", min_value=5, max_value=100, value=25, step=5)
    sort_by_ip = col_sort2.radio("Sort by", ["Count", "IP"], horizontal=True, key="ip_sort")

    ip_counts = df.groupby("ip").size().reset_index(name="Requests")

    if sort_by_ip == "Count":
        ip_counts = ip_counts.sort_values("Requests", ascending=False)
    else:
        ip_counts = ip_counts.sort_values("ip")

    top_ips = ip_counts.head(top_n_ip)
    fig_ips = px.bar(
        top_ips.sort_values("Requests"),
        x="Requests",
        y="ip",
        orientation="h",
        title=f"Top {top_n_ip} IPs by Request Count",
        labels={"ip": "IP"},
    )
    fig_ips.update_layout(height=max(300, top_n_ip * 22))
    st.plotly_chart(fig_ips, width="stretch")

    # Per-IP breakdown: click an IP to see which pages they hit
    st.subheader("Per-IP page breakdown")
    selected_ip = st.selectbox(
        "Select IP",
        options=ip_counts["ip"].tolist(),
        format_func=lambda x: f"{x}  ({ip_counts.loc[ip_counts['ip'] == x, 'Requests'].iloc[0]:,} reqs)",
    )
    if selected_ip:
        ip_df = df[df["ip"] == selected_ip].groupby("path").size().reset_index(name="Requests")
        ip_df = ip_df.sort_values("Requests", ascending=False)
        st.dataframe(ip_df, width="stretch", hide_index=True)
