import logging
from time import perf_counter

import pandas as pd
import plotly.express as px
import streamlit as st

from thetower.backend.tourney_results.constants import champ
from thetower.backend.tourney_results.data import get_tourneys
from thetower.backend.tourney_results.models import TourneyResult
from thetower.backend.tourney_results.shun_config import include_shun_enabled_for
from thetower.web.live.data_ops import (
    format_time_ago,
    get_data_refresh_timestamp,
    get_processed_data,
    process_display_names,
    require_tournament_data,
)
from thetower.web.live.ui_components import setup_common_ui


@require_tournament_data
def live_progress():
    st.markdown("# Live Progress")
    logging.info("Starting live progress")
    t2_start = perf_counter()

    # Use common UI setup
    options, league, is_mobile = setup_common_ui()

    # Get data refresh timestamp
    refresh_timestamp = get_data_refresh_timestamp(league)
    if refresh_timestamp:
        time_ago = format_time_ago(refresh_timestamp)
        st.caption(f"📊 Data last refreshed: {time_ago} ({refresh_timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC)")
        # Indicate whether shunned players are included for this page
        try:
            include_shun = include_shun_enabled_for("live_progress")
            st.caption(f"🔍 Including shunned players: {'Yes' if include_shun else 'No'}")
        except Exception:
            pass
    else:
        st.caption("📊 Data refresh time: Unknown")

    # Get processed data
    include_shun = include_shun_enabled_for("live_progress")
    df, tdf, ldf, first_moment, last_moment = get_processed_data(league, include_shun)

    # Process display names for better visualization
    tdf = process_display_names(tdf)

    # Create top 25 progress plot
    fig = px.line(tdf, x="datetime", y="wave", color="display_name", title="Top 25 Players: live score", markers=True, line_shape="linear")

    fig.update_traces(mode="lines+markers")
    fig.update_layout(
        xaxis_title="Time",
        yaxis_title="Wave",
        legend_title="Player Name",
        hovermode="closest",
        height=500,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h" if is_mobile else "v"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Get reference data for fill-up calculation
    qs = TourneyResult.objects.filter(league=league, public=True).order_by("-date")
    if not qs:
        qs = TourneyResult.objects.filter(league=champ, public=True).order_by("-date")
    tourney = qs[0]
    pdf = get_tourneys([tourney])

    # Fill up progress calculation
    fill_ups = []
    for dt, sdf in df.groupby("datetime"):
        joined_ids = set(sdf.player_id.unique())
        time_delta = dt - first_moment
        time = time_delta.total_seconds() / 3600
        fillup = sum([player_id in joined_ids for player_id in pdf.id])
        fill_ups.append((time, fillup))

    # Create fill up progress plot
    fill_ups = pd.DataFrame(sorted(fill_ups), columns=["time", "fillup"])
    fig = px.line(fill_ups, x="time", y="fillup", title="Fill up progress", markers=True, line_shape="linear")
    fig.update_traces(mode="lines+markers", fill="tozeroy")
    fig.update_layout(
        xaxis_title="Time [h]",
        yaxis_title="Fill up [players]",
        hovermode="closest",
        height=400,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Log execution time
    t2_stop = perf_counter()
    logging.info(f"Full live_progress for {league} took {t2_stop - t2_start}")


live_progress()
