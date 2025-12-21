import logging
import os
from pathlib import Path
from time import perf_counter

import pandas as pd
import plotly.express as px
import streamlit as st

from thetower.backend.tourney_results.constants import leagues as ALL_LEAGUES
from thetower.backend.tourney_results.data import get_player_id_lookup
from thetower.backend.tourney_results.formatting import BASE_URL, make_player_url
from thetower.backend.tourney_results.shun_config import include_shun_enabled_for
from thetower.web.live.data_ops import (
    format_time_ago,
    get_bracket_data,
    get_data_refresh_timestamp,
    get_live_data,
    initialize_bracket_state,
    process_bracket_selection,
    process_display_names,
    require_tournament_data,
)
from thetower.web.live.ui_components import get_league_for_player, setup_common_ui


@require_tournament_data
def live_bracket():
    st.markdown("# Live Bracket")
    logging.info("Starting live bracket")
    t2_start = perf_counter()

    # Use common UI setup, but hide league selector
    options, league, is_mobile = setup_common_ui(show_league_selector=False)

    # Get data refresh timestamp
    refresh_timestamp = get_data_refresh_timestamp(league)
    if refresh_timestamp:
        time_ago = format_time_ago(refresh_timestamp)
        st.caption(f"📊 Data last refreshed: {time_ago} ({refresh_timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC)")
        # Indicate whether shunned players are included for this page (only on hidden site)
        hidden_features = os.environ.get("HIDDEN_FEATURES")
        if hidden_features:
            try:
                include_shun = include_shun_enabled_for("live_bracket")
                st.caption(f"🔍 Including shunned players: {'Yes' if include_shun else 'No'}")
            except Exception:
                # Don't break the page if the shun config can't be read
                pass
    else:
        st.caption("📊 Data refresh time: Unknown")

    # Get live data and process brackets
    try:
        include_shun = include_shun_enabled_for("live_bracket")
        df = get_live_data(league, include_shun)
        bracket_order, fullish_brackets = get_bracket_data(df)
        df = df[df.bracket.isin(fullish_brackets)].copy()  # no sniping

    except (IndexError, ValueError):
        if options.current_player_id:
            # Get player's known name
            lookup = get_player_id_lookup()
            known_name = lookup.get(options.current_player_id, options.current_player_id)
            st.error(f"{known_name} ({options.current_player_id}) hasn't participated in this tournament.")
        else:
            st.error("No tournament data available.")
        return

    bracket_order, fullish_brackets = get_bracket_data(df)
    df = df[df.bracket.isin(fullish_brackets)].copy()  # no sniping

    name_col, id_col = st.columns(2)

    # Initialize bracket navigation
    bracket_idx = initialize_bracket_state(bracket_order, league)
    selected_real_name = None
    selected_player_id = None
    selected_bracket = None

    # Handle selection methods via text inputs with auto league detection
    if options.current_player:
        selected_real_name = options.current_player
    elif options.current_player_id:
        selected_player_id = options.current_player_id
    else:
        selected_real_name_input = name_col.text_input("Search by Player Name", value="", key=f"player_name_input_{league}")
        selected_player_id_input = id_col.text_input("Or by Player ID", value="", key=f"player_id_input_{league}")

        # Optional bracket ID search
        selected_bracket_input = st.text_input("Or search by Bracket ID", value="", key=f"bracket_id_input_{league}")

        # Determine league and selection based on inputs
        if selected_player_id_input.strip():
            pid_upper = selected_player_id_input.strip().upper()
            auto_league = get_league_for_player(pid_upper)
            if auto_league:
                league = auto_league
                include_shun = include_shun_enabled_for("live_bracket")
                df = get_live_data(league, include_shun)
                bracket_order, fullish_brackets = get_bracket_data(df)
                df = df[df.bracket.isin(fullish_brackets)].copy()
                selected_player_id = pid_upper
            else:
                st.error("Could not determine league for the given Player ID.")
                return
        elif selected_real_name_input.strip():
            name_lower = selected_real_name_input.strip().lower()
            found = False
            for lg in ALL_LEAGUES:
                try:
                    include_shun = include_shun_enabled_for("live_bracket")
                    df_tmp = get_live_data(lg, include_shun)
                    order_tmp, full_tmp = get_bracket_data(df_tmp)
                    df_tmp = df_tmp[df_tmp.bracket.isin(full_tmp)].copy()
                    if not df_tmp.empty:
                        # Case-insensitive match on real/display name
                        match_df = df_tmp[(df_tmp["real_name"].str.lower() == name_lower) | (df_tmp["display_name"].str.lower() == name_lower)]
                        if not match_df.empty:
                            df = df_tmp
                            bracket_order = order_tmp
                            league = lg
                            selected_real_name = match_df.iloc[0]["real_name"]
                            found = True
                            break
                except Exception:
                    continue
            if not found:
                st.error("Player name not found in any active league.")
                return
        elif selected_bracket_input.strip():
            # Try to locate bracket across leagues
            br_id = selected_bracket_input.strip()
            found = False
            for lg in ALL_LEAGUES:
                try:
                    include_shun = include_shun_enabled_for("live_bracket")
                    df_tmp = get_live_data(lg, include_shun)
                    order_tmp, full_tmp = get_bracket_data(df_tmp)
                    df_tmp = df_tmp[df_tmp.bracket.isin(full_tmp)].copy()
                    if br_id in order_tmp:
                        df = df_tmp
                        bracket_order = order_tmp
                        league = lg
                        selected_bracket = br_id
                        found = True
                        break
                except Exception:
                    continue
            if not found:
                st.error("Bracket ID not found in any active league.")
                return

    if not any([selected_real_name, selected_player_id, selected_bracket]):
        return

    try:
        # Process bracket selection using data_ops utility
        bracket_id, tdf, selected_real_name, bracket_idx = process_bracket_selection(
            df, selected_real_name, selected_player_id, selected_bracket, bracket_order
        )
        # Update session state for selected bracket index but do not render nav controls
        st.session_state[f"current_bracket_idx_{league}"] = bracket_idx
    except ValueError as e:
        if selected_player_id:
            # Get player's known name
            lookup = get_player_id_lookup()
            known_name = lookup.get(selected_player_id, selected_player_id)
            st.error(f"{known_name} (#{selected_player_id}) hasn't participated in this tournament.")
        else:
            st.error(str(e))
        return

    # Create a copy of the DataFrame to avoid SettingWithCopyWarning
    tdf = tdf.copy()

    # Display bracket information
    player_ids = sorted(tdf.player_id.unique())
    # Use loc for datetime conversion
    tdf.loc[:, "datetime"] = pd.to_datetime(tdf["datetime"])
    bracket_start_time = tdf["datetime"].min()
    st.info(f"Bracket started at approx.: {bracket_start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    # Process display names and create visualization
    tdf = process_display_names(tdf)
    fig = px.line(tdf, x="datetime", y="wave", color="display_name", title="Live bracket score", markers=True, line_shape="linear")
    fig.update_traces(mode="lines+markers")
    fig.update_layout(xaxis_title="Time", yaxis_title="Wave", legend_title="real_name", hovermode="x unified")
    fig.update_traces(hovertemplate="%{y}")
    st.plotly_chart(fig, use_container_width=True)

    # Process and display latest data
    last_moment = tdf.datetime.max()
    # Create a copy and use loc for setting index
    ldf = tdf[tdf.datetime == last_moment].copy()
    ldf.loc[:, "datetime"] = pd.to_datetime(ldf["datetime"])
    ldf = ldf.reset_index(drop=True)
    ldf.index = pd.RangeIndex(start=1, stop=len(ldf) + 1)
    ldf = process_display_names(ldf)

    # Use loc for safer column selection
    display_df = ldf.loc[:, ["player_id", "name", "real_name", "wave", "datetime"]]

    # Create table HTML
    st.write(display_df.style.format(make_player_url, subset=["player_id"]).to_html(escape=False), unsafe_allow_html=True)

    css_path = Path(__file__).parent.parent / "static" / "styles" / "style.css"
    with open(css_path, "r") as infile:
        table_styling = f"<style>{infile.read()}</style>"
    st.write(table_styling, unsafe_allow_html=True)

    # Display comparison links
    comparison_container = st.container()
    with comparison_container:
        if player_ids:
            # Use selected player ID if available, otherwise find ID for selected name, otherwise first player
            if selected_player_id:
                comparison_player_id = selected_player_id
            elif selected_real_name:
                # Find player ID for the selected name
                selected_player_data = tdf[tdf.real_name == selected_real_name]
                comparison_player_id = selected_player_data.player_id.iloc[0] if not selected_player_data.empty else player_ids[0]
            else:
                # Bracket navigation - use first player
                comparison_player_id = player_ids[0]
            bracket_url = f"https://{BASE_URL}/comparison?bracket_player={comparison_player_id}"
            st.write(f'<a href="{bracket_url}">See comparison</a>', unsafe_allow_html=True)

    # Log execution time
    t2_stop = perf_counter()
    logging.info(f"Full live_bracket for {league} took {t2_stop - t2_start}")


live_bracket()
