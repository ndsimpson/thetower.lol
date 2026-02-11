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
from thetower.web.live.ui_components import setup_common_ui
from thetower.web.util import add_player_id


@require_tournament_data
def live_score():
    st.markdown("# Live Placement Analysis")
    logging.info("Starting live placement analysis")
    t2_start = perf_counter()

    # Use common UI setup, hide league selector for auto-detect
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

    # Function to clear selection and search again
    def search_for_new():
        st.query_params.clear()
        if "player_id" in st.session_state:
            st.session_state.pop("player_id")
        if "player_search_term" in st.session_state:
            st.session_state.pop("player_search_term")

    # Check if a player was selected from multiple matches
    selected_id_from_session = st.session_state.get("player_id")
    search_term = st.session_state.get("player_search_term")

    # Initialize selected_player from query params or session state
    initial_player = None
    if query_player_id:
        # Find player by player_id (case-insensitive by normalizing to uppercase)
        qp_upper = query_player_id.strip().upper()
        matching_players = df[df["player_id"] == qp_upper]
        if not matching_players.empty:
            initial_player = matching_players.iloc[0]["display_name"]
    elif query_player_name:
        # Find player by name (check both real_name and display_name)
        matching_players = df[
            (df["real_name"].str.lower() == query_player_name.lower()) | (df["display_name"].str.lower() == query_player_name.lower())
        ]
        if not matching_players.empty:
            initial_player = matching_players.iloc[0]["display_name"]

    # Show "Search for another player" button if we have a player selected or from query params
    if selected_id_from_session or initial_player:
        st.button("Search for another player?", on_click=search_for_new, key=f"search_new_{league}")

    # Player selection via text inputs (no dropdown required)
    st.markdown("### Enter Player")

    # Only show search inputs if no player is selected
    if not (selected_id_from_session or initial_player):
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
                value=search_term or "",
                key="player_name_input",
            )

        with id_col:
            player_id_input = st.text_input("Or enter Player ID", value="", key=f"player_id_input_{league}")
    else:
        selected_player = ""
        player_id_input = ""

    # Handle player_id input with partial match and cross-league search
    if player_id_input and not selected_player:
        # Normalize to uppercase to align with stored player IDs
        pid_search = player_id_input.strip().upper()

        # Search across all leagues for partial player ID matches
        from thetower.backend.tourney_results.constants import leagues as ALL_LEAGUES

        all_matches = []  # Store (player_name, player_id, league) tuples

        for lg in ALL_LEAGUES:
            try:
                df_tmp, _, _, _ = get_placement_analysis_data(lg)
                df_tmp = process_display_names(df_tmp)
                # Partial match on player_id
                match_df = df_tmp[df_tmp["player_id"].str.contains(pid_search, na=False, regex=False)]
                # Add unique players from this league
                for _, row in match_df.drop_duplicates(subset=["player_id"]).iterrows():
                    all_matches.append((row["real_name"], row["player_id"], lg))
            except Exception:
                continue

        if not all_matches:
            st.error(f"No player IDs found matching '{pid_search}' in any active tournament.")
            return
        elif len(all_matches) > 1:
            # Show multiple matches sorted by player ID
            all_matches.sort(key=lambda x: x[1])
            st.warning("Multiple player IDs match. Please select one:")
            for player_name, player_id, player_league in all_matches:
                name_col, id_col, league_col, button_col = st.columns([3, 1, 1, 1])
                name_col.write(player_name)
                id_col.write(player_id)
                league_col.write(player_league)
                if button_col.button("Select", key=f"select_id_{player_id}_{player_league}", on_click=add_player_id, args=(player_id,)):
                    pass
            return
        else:
            # Single match found
            selected_player_name = all_matches[0][0]
            target_league = all_matches[0][2]
            if target_league != league:
                # Reload data for the correct league
                df, latest_time, bracket_creation_times, tourney_start_date = get_placement_analysis_data(target_league)
                df = process_display_names(df)
                league = target_league
            # Set selected_player to continue with analysis
            match_df = df[df["real_name"] == selected_player_name]
            if not match_df.empty:
                selected_player = match_df.iloc[0]["display_name"]
            else:
                st.error("Error loading player data.")
                return

    # Check if a player ID was selected from multiple matches
    if selected_id_from_session:
        # Search across all leagues to find which league this player is in
        from thetower.backend.tourney_results.constants import leagues as ALL_LEAGUES

        found_player = None
        found_league = None

        for lg in ALL_LEAGUES:
            try:
                df_tmp, _, _, _ = get_placement_analysis_data(lg)
                df_tmp = process_display_names(df_tmp)
                match_df = df_tmp[df_tmp["player_id"] == selected_id_from_session]
                if not match_df.empty:
                    found_player = match_df.iloc[0]["display_name"]
                    found_league = lg
                    break
            except Exception:
                continue

        if found_player and found_league:
            if found_league != league:
                # Reload data for the correct league
                df, latest_time, bracket_creation_times, tourney_start_date = get_placement_analysis_data(found_league)
                df = process_display_names(df)
                league = found_league
            selected_player = found_player
            # Skip name-based search since we already have the exact player
        else:
            st.error(f"Player ID {selected_id_from_session} not found in any active tournament.")
            return
    elif initial_player:
        # Use query param player - skip name-based search since we already have the exact player
        selected_player = initial_player
    elif not selected_player or not selected_player.strip():
        st.info("Enter a player name or Player ID to analyze placement")
        return

    # Only do name-based search if player wasn't found via session state or query params
    if not (selected_id_from_session or initial_player):
        # Store search term for later
        st.session_state.player_search_term = selected_player

        # Try matching by entered name across all leagues (supports partial matches)
        name_lower = selected_player.strip().lower()

        # Search across all leagues
        from thetower.backend.tourney_results.constants import leagues as ALL_LEAGUES

        all_matches = []  # Store (player_name, player_id, league) tuples

        for lg in ALL_LEAGUES:
            try:
                df_tmp, _, _, _ = get_placement_analysis_data(lg)
                df_tmp = process_display_names(df_tmp)
                match_df = df_tmp[
                    (df_tmp["real_name"].str.lower().str.contains(name_lower, na=False, regex=False))
                    | (df_tmp["display_name"].str.lower().str.contains(name_lower, na=False, regex=False))
                ]
                # Add unique players from this league
                for _, row in match_df.drop_duplicates(subset=["real_name"]).iterrows():
                    all_matches.append((row["real_name"], row["player_id"], lg))
            except Exception:
                continue

        if not all_matches:
            st.error("Player not found by name in any active league's tournament data.")
            return
        elif len(all_matches) > 1:
            st.warning("Multiple players match. Please select one:")

            # Display each match with name, ID, league, and button
            for player_name, player_id, player_league in all_matches:
                name_col, id_col, league_col, button_col = st.columns([3, 1, 1, 1])
                name_col.write(player_name)
                id_col.write(player_id)
                league_col.write(player_league)
                if button_col.button("Select", key=f"select_{player_name}_{player_league}", on_click=add_player_id, args=(player_id,)):
                    pass
            return
        else:
            # Single match found
            selected_player_name = all_matches[0][0]
            target_league = all_matches[0][2]
            if target_league != league:
                # Reload data for the correct league
                df, latest_time, bracket_creation_times, tourney_start_date = get_placement_analysis_data(target_league)
                df = process_display_names(df)
                league = target_league
            # Get display name
            match_df = df[df["real_name"] == selected_player_name]
            if not match_df.empty:
                selected_player = match_df.iloc[0]["display_name"]
            else:
                st.error("Error loading player data.")
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
