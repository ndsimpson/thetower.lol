import datetime
import logging
import os
from time import perf_counter

import pandas as pd
import plotly.express as px
import streamlit as st

from thetower.backend.tourney_results.shun_config import include_shun_enabled_for
from thetower.web.live.data_ops import (
    analyze_wave_placement,
    format_time_ago,
    get_data_refresh_timestamp,
    get_placement_analysis_data,
    require_tournament_data,
)
from thetower.web.live.ui_components import setup_common_ui


@require_tournament_data
def live_score():
    st.markdown("# Live Placement Analysis")
    logging.info("Starting live placement analysis")
    t2_start = perf_counter()

    # Use common UI setup
    options, league, is_mobile = setup_common_ui()

    # Show data refresh and shun status upfront so users see it even if cache isn't ready
    try:
        refresh_timestamp = get_data_refresh_timestamp(league)
        if refresh_timestamp:
            time_ago = format_time_ago(refresh_timestamp)
            st.caption(f"📊 Data last refreshed: {time_ago} ({refresh_timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC)")
        else:
            st.caption("📊 Data refresh time: Unknown")

        # Indicate whether shunned players are included for this page (only on hidden site)
        hidden_features = os.environ.get("HIDDEN_FEATURES")
        if hidden_features:
            try:
                include_shun = include_shun_enabled_for("live_placement_cache")
                st.caption(f"🔍 Including shunned players: {'Yes' if include_shun else 'No'}")
            except Exception:
                pass
    except Exception:
        # Don't break the page for display issues
        pass

    # Get placement analysis data (plus tourney start date)
    df, latest_time, bracket_creation_times, tourney_start_date = get_placement_analysis_data(league)

    # Show tourney start date so users know which tourney the cache is for
    try:
        st.caption(f"Tourney start date: {tourney_start_date}")
    except Exception:
        st.write(f"Tourney start date: {tourney_start_date}")

    # (Optional) If we didn't have a refresh timestamp earlier, show fallback based on latest_time
    try:
        if not refresh_timestamp:
            ts = latest_time
            if ts is None:
                refresh_text = "Unknown"
                ts_display = "Unknown"
            else:
                # Make timezone explicit: show UTC timestamp
                if ts.tzinfo is None:
                    ts_utc = ts.replace(tzinfo=datetime.timezone.utc)
                else:
                    ts_utc = ts.astimezone(datetime.timezone.utc)

                refresh_text = format_time_ago(ts_utc)
                ts_display = ts_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

            st.caption(f"📊 Data last refreshed: {refresh_text} ({ts_display})")
    except Exception:
        # Don't break the page for display issues
        pass

    # Player selection
    selected_player = st.selectbox("Select player", [""] + sorted(df["real_name"].unique()), key=f"player_selector_{league}")
    if not selected_player:
        return

    # Get the player's highest wave
    wave_to_analyze = df[df.real_name == selected_player].wave.max()
    st.write(f"Analyzing placement for {selected_player}'s highest wave: {wave_to_analyze}")

    # Analyze placements
    results = analyze_wave_placement(df, wave_to_analyze, latest_time)

    # Process results for display
    results_df = pd.DataFrame(results)
    results_df["Creation Time"] = results_df["Bracket"].map(bracket_creation_times)
    # Add numeric position column for sorting
    results_df["Position"] = results_df["Would Place"].str.split("/").str[0].astype(int)
    # Sort by creation time initially
    results_df = results_df.sort_values("Creation Time")

    # Group by checkpoints (30-minute intervals) and calculate averages
    results_df["Checkpoint"] = results_df["Creation Time"].dt.floor("30min")
    checkpoint_df = results_df.groupby("Checkpoint").agg({
        "Position": "mean",
        "Top Wave": "mean",
        "Median Wave": "mean",
        "Players Above": "mean",
        "Bracket": "count"  # Count of brackets per checkpoint
    }).round(1).reset_index()

    # Rename columns for display
    checkpoint_df = checkpoint_df.rename(columns={
        "Position": "Avg Placement",
        "Top Wave": "Avg Top Wave",
        "Median Wave": "Avg Median Wave",
        "Players Above": "Avg Players Above",
        "Bracket": "Brackets"
    })

    # Keep original datetime format for checkpoint display
    checkpoint_df["Checkpoint"] = checkpoint_df["Checkpoint"].dt.strftime("%Y-%m-%d %H:%M:%S")

    st.write(f"Analysis for wave {wave_to_analyze} (averaged by 30-minute checkpoints):")
    # Display condensed dataframe
    st.dataframe(
        checkpoint_df,
        hide_index=True,
        column_config={
            "Avg Placement": st.column_config.NumberColumn("Avg Placement", help="Average placement position across brackets in this checkpoint"),
            "Brackets": st.column_config.NumberColumn("Brackets", help="Number of brackets in this checkpoint")
        },
    )

    # Calculate player's actual position
    player_bracket = df[df["real_name"] == selected_player]["bracket"].iloc[0]
    player_creation_time = bracket_creation_times[player_bracket]
    player_position = (
        df[(df["bracket"] == player_bracket) & (df["datetime"] == latest_time)]
        .sort_values("wave", ascending=False)
        .index.get_loc(df[(df["bracket"] == player_bracket) & (df["datetime"] == latest_time) & (df["real_name"] == selected_player)].index[0])
        + 1
    )

    # Create plot data using checkpoint averages
    plot_df = checkpoint_df.copy()
    plot_df["Creation Time"] = pd.to_datetime(checkpoint_df["Checkpoint"])

    # Create placement timeline plot
    fig = px.scatter(
        plot_df,
        x="Creation Time",
        y="Avg Placement",
        title=f"Average Placement Timeline for {wave_to_analyze} waves",
        labels={"Creation Time": "Checkpoint Time", "Avg Placement": "Average Placement Position"},
        trendline="lowess",
        trendline_options=dict(frac=0.2),
    )

    # Add player's actual position marker
    fig.add_scatter(
        x=[player_creation_time],
        y=[player_position],
        mode="markers",
        marker=dict(symbol="x", size=15, color="red"),
        name="Actual Position",
        showlegend=False,
    )

    # Update plot layout
    fig.update_layout(yaxis_title="Position", height=400, margin=dict(l=20, r=20, t=40, b=20))
    fig.update_yaxes(autorange="reversed")

    st.plotly_chart(fig, use_container_width=True)

    # Log execution time
    t2_stop = perf_counter()
    logging.info(f"Full live_placement_analysis for {league} took {t2_stop - t2_start}")


live_score()
