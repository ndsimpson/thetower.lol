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
    process_display_names,
    require_tournament_data,
)
from thetower.web.live.ui_components import get_league_for_player, setup_common_ui


@require_tournament_data
def live_score():
    st.markdown("# Live Placement Analysis")
    logging.info("Starting live placement analysis")
    t2_start = perf_counter()

    # Use common UI setup, but hide league selector (auto-detect via inputs)
    options, league, is_mobile = setup_common_ui(show_league_selector=False)

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

    # Process display names to handle duplicates
    df = process_display_names(df)

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

    # Check for query parameters
    query_player_id = st.query_params.get("player_id")
    query_player_name = st.query_params.get("player")

    # Initialize selected_player from query params or session state
    initial_player = None
    if query_player_id:
        # Find player by player_id
        matching_players = df[df["player_id"] == query_player_id]
        if not matching_players.empty:
            initial_player = matching_players.iloc[0]["display_name"]
    elif query_player_name:
        # Find player by name (check both real_name and display_name)
        matching_players = df[
            (df["real_name"].str.lower() == query_player_name.lower()) | (df["display_name"].str.lower() == query_player_name.lower())
        ]
        if not matching_players.empty:
            initial_player = matching_players.iloc[0]["display_name"]

    # Player selection via text inputs (no dropdown required)
    st.markdown("### Enter Player")
    if is_mobile:
        # In mobile view, stack inputs vertically
        name_col = st.container()
        id_col = st.container()
    else:
        # In desktop view, use side-by-side columns
        name_col, id_col = st.columns([2, 1])

    with name_col:
        selected_player = st.text_input(
            "Enter player name",
            value=(initial_player or query_player_name or ""),
            key="player_name_input",
        )

    with id_col:
        player_id_input = st.text_input("Or enter Player ID", value=(query_player_id or ""), key=f"player_id_input_{league}")

    # Handle player_id input
    if player_id_input and not selected_player:
        # Auto-detect league based on provided player ID (case as entered)
        pid_input = player_id_input.strip()
        auto_league = get_league_for_player(pid_input)
        if auto_league and auto_league != league:
            # Refresh data for detected league
            df, latest_time, bracket_creation_times, tourney_start_date = get_placement_analysis_data(auto_league)
            df = process_display_names(df)
            league = auto_league
        matching_players = df[df["player_id"] == pid_input]
        if not matching_players.empty:
            selected_player = matching_players.iloc[0]["display_name"]
        else:
            # If not found in current df, try other leagues
            from thetower.backend.tourney_results.constants import leagues as _leagues

            found = False
            for lg in _leagues:
                if lg == league:
                    continue
                try:
                    df_tmp, latest_time, bracket_creation_times, tourney_start_date = get_placement_analysis_data(lg)
                    df_tmp = process_display_names(df_tmp)
                    match_df = df_tmp[df_tmp["player_id"] == pid_input]
                    if not match_df.empty:
                        df = df_tmp
                        league = lg
                        selected_player = match_df.iloc[0]["display_name"]
                        found = True
                        break
                except Exception:
                    continue
            if not found:
                st.error(f"Player ID '{player_id_input}' not found in current tournament data.")
                return

    if not selected_player:
        # Try matching by entered name across leagues
        if selected_player := (selected_player or "").strip():
            name_lower = selected_player.lower()
            # First try current league
            match_df = df[(df["real_name"].str.lower() == name_lower) | (df["display_name"].str.lower() == name_lower)]
            if match_df.empty:
                from thetower.backend.tourney_results.constants import leagues as _leagues

                for lg in _leagues:
                    if lg == league:
                        continue
                    try:
                        df_tmp, latest_time, bracket_creation_times, tourney_start_date = get_placement_analysis_data(lg)
                        df_tmp = process_display_names(df_tmp)
                        match_df = df_tmp[(df_tmp["real_name"].str.lower() == name_lower) | (df_tmp["display_name"].str.lower() == name_lower)]
                        if not match_df.empty:
                            df = df_tmp
                            league = lg
                            selected_player = match_df.iloc[0]["display_name"]
                            break
                    except Exception:
                        continue
            if not selected_player:
                st.error("Player not found by name in any active league.")
                return
        else:
            st.info("Enter a player name or Player ID to analyze placement")
            return

    # Get the player's highest wave
    wave_to_analyze = df[df.display_name == selected_player].wave.max()
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

    # Group by checkpoints (30-minute intervals) and calculate averages, min, and max
    results_df["Checkpoint"] = results_df["Creation Time"].dt.floor("30min")
    checkpoint_df = (
        results_df.groupby("Checkpoint")
        .agg(
            {
                "Position": ["mean", "min", "max"],
                "Top Wave": "mean",
                "Median Wave": "mean",
                "Players Above": "mean",
                "Bracket": "count",  # Count of brackets per checkpoint
            }
        )
        .round(1)
        .reset_index()
    )

    # Flatten multi-level column names
    checkpoint_df.columns = ["_".join(col).strip("_") if col[1] else col[0] for col in checkpoint_df.columns.values]

    # Rename columns for display
    checkpoint_df = checkpoint_df.rename(
        columns={
            "Position_mean": "Avg Placement",
            "Position_min": "Best Case",
            "Position_max": "Worst Case",
            "Top Wave_mean": "Avg Top Wave",
            "Median Wave_mean": "Avg Median Wave",
            "Players Above_mean": "Avg Players Above",
            "Bracket_count": "Brackets",
        }
    )

    # Keep original datetime format for checkpoint display
    checkpoint_df["Checkpoint"] = checkpoint_df["Checkpoint"].dt.strftime("%Y-%m-%d %H:%M:%S")

    st.write(f"Analysis for wave {wave_to_analyze} (averaged by 30-minute checkpoints):")
    # Display condensed dataframe
    st.dataframe(
        checkpoint_df,
        hide_index=True,
        column_config={
            "Avg Placement": st.column_config.NumberColumn("Avg Placement", help="Average placement position across brackets in this checkpoint"),
            "Best Case": st.column_config.NumberColumn("Best Case", help="Best (lowest) placement position in this checkpoint"),
            "Worst Case": st.column_config.NumberColumn("Worst Case", help="Worst (highest) placement position in this checkpoint"),
            "Brackets": st.column_config.NumberColumn("Brackets", help="Number of brackets in this checkpoint"),
        },
    )

    # Calculate player's actual position
    player_bracket = df[df["display_name"] == selected_player]["bracket"].iloc[0]
    player_creation_time = bracket_creation_times[player_bracket]
    player_position = (
        df[(df["bracket"] == player_bracket) & (df["datetime"] == latest_time)]
        .sort_values("wave", ascending=False)
        .index.get_loc(df[(df["bracket"] == player_bracket) & (df["datetime"] == latest_time) & (df["display_name"] == selected_player)].index[0])
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

    # Update the legend names for the scatter plot and trendline
    fig.data[0].name = "Average Placement"
    fig.data[0].showlegend = True
    if len(fig.data) > 1:  # Trendline trace exists
        fig.data[1].name = "Lowess Trendline"
        fig.data[1].showlegend = True

    # Add best case scenario line
    fig.add_scatter(
        x=plot_df["Creation Time"],
        y=plot_df["Best Case"],
        mode="lines",
        line=dict(color="green", width=2, dash="dash"),
        name="Best Case",
        showlegend=True,
    )

    # Add worst case scenario line
    fig.add_scatter(
        x=plot_df["Creation Time"],
        y=plot_df["Worst Case"],
        mode="lines",
        line=dict(color="red", width=2, dash="dash"),
        name="Worst Case",
        showlegend=True,
    )

    # Add player's actual position marker
    fig.add_scatter(
        x=[player_creation_time],
        y=[player_position],
        mode="markers",
        marker=dict(symbol="x", size=15, color="purple"),
        name="Actual Position",
        showlegend=True,
    )

    # Update plot layout
    fig.update_layout(yaxis_title="Position", height=400, margin=dict(l=20, r=20, t=40, b=20), legend=dict(orientation="h" if is_mobile else "v"))
    fig.update_yaxes(autorange="reversed")

    st.plotly_chart(fig, use_container_width=True)

    # Log execution time
    t2_stop = perf_counter()
    logging.info(f"Full live_placement_analysis for {league} took {t2_stop - t2_start}")


live_score()
