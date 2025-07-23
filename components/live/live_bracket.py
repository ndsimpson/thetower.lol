from urllib.parse import urlencode
import pandas as pd
import plotly.express as px
import streamlit as st
import logging
from time import perf_counter

from components.live.ui_components import setup_common_ui
from components.live.data_ops import (
    get_live_data,
    get_bracket_data,
    process_display_names,
    process_bracket_selection,
    require_tournament_data,
    initialize_bracket_state,
    update_bracket_index
)
from dtower.tourney_results.formatting import BASE_URL, make_player_url
from dtower.tourney_results.data import get_player_id_lookup


@require_tournament_data
def live_bracket():
    st.markdown("# Live Bracket")
    logging.info("Starting live bracket")
    t2_start = perf_counter()

    # Use common UI setup
    options, league, is_mobile = setup_common_ui()

    # Get live data and process brackets
    try:
        df = get_live_data(league, True)
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

    # Handle selection methods
    if options.current_player:
        selected_real_name = options.current_player
    elif options.current_player_id:
        selected_player_id = options.current_player_id
    else:
        selected_real_name = name_col.selectbox(
            "Bracket of...",
            [""] + sorted(df.real_name.unique()),
            key=f"player_name_selector_{league}"
        )
        selected_player_id = id_col.selectbox(
            "...or by player id",
            [""] + sorted(df.player_id.unique()),
            key=f"player_id_selector_{league}"
        )

        if not selected_real_name and not selected_player_id:
            # Add navigation buttons
            prev_col, curr_col, next_col = st.columns([1, 2, 1])

            with prev_col:
                if st.button("← Previous Bracket", key=f"prev_{league}"):
                    update_bracket_index(bracket_idx - 1, len(bracket_order) - 1, league)

            with curr_col:
                selected_bracket_direct = st.selectbox(
                    "Select Bracket",
                    bracket_order,
                    index=st.session_state[f"current_bracket_idx_{league}"],
                    key=f"bracket_selector_{league}"
                )
                if selected_bracket_direct != bracket_order[st.session_state[f"current_bracket_idx_{league}"]]:
                    update_bracket_index(
                        bracket_order.index(selected_bracket_direct),
                        len(bracket_order) - 1,
                        league
                    )

            with next_col:
                if st.button("Next Bracket →", key=f"next_{league}"):
                    update_bracket_index(bracket_idx + 1, len(bracket_order) - 1, league)

            selected_bracket = bracket_order[st.session_state[f"current_bracket_idx_{league}"]]

    if not any([selected_real_name, selected_player_id, selected_bracket]):
        return

    try:
        # Process bracket selection using data_ops utility
        bracket_id, tdf, selected_real_name, bracket_idx = process_bracket_selection(
            df, selected_real_name, selected_player_id, selected_bracket, bracket_order
        )
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
    fig = px.line(
        tdf,
        x="datetime",
        y="wave",
        color="display_name",
        title="Live bracket score",
        markers=True,
        line_shape="linear"
    )
    fig.update_traces(mode="lines+markers")
    fig.update_layout(
        xaxis_title="Time",
        yaxis_title="Wave",
        legend_title="real_name",
        hovermode="closest"
    )
    st.plotly_chart(fig, use_container_width=True)

    # Process and display latest data
    last_moment = tdf.datetime.max()
    # Create a copy and use loc for setting index
    ldf = tdf[tdf.datetime == last_moment].copy()
    ldf.loc[:, 'datetime'] = pd.to_datetime(ldf['datetime'])
    ldf = ldf.reset_index(drop=True)
    ldf.index = pd.RangeIndex(start=1, stop=len(ldf) + 1)
    ldf = process_display_names(ldf)

    # Use loc for safer column selection
    display_df = ldf.loc[:, ["player_id", "name", "real_name", "wave", "datetime"]]

    # Create table HTML
    st.write(
        display_df.style
        .format(make_player_url, subset=["player_id"])
        .to_html(escape=False),
        unsafe_allow_html=True
    )

    # Generate comparison URLs
    url = f"https://{BASE_URL}/comparison?" + urlencode({"compare": player_ids}, doseq=True)
    with open("style.css", "r") as infile:
        table_styling = f"<style>{infile.read()}</style>"
    st.write(table_styling, unsafe_allow_html=True)

    # Display comparison links
    comparison_container = st.container()
    with comparison_container:
        st.write(f'<a href="{url}">See comparison (old way)</a>', unsafe_allow_html=True)
        if player_ids:
            bracket_url = f"https://{BASE_URL}/comparison?bracket_player={player_ids[0]}"
            st.write(f'<a href="{bracket_url}">See comparison (new way)</a>', unsafe_allow_html=True)

    # Show URLs for copying
    with st.expander("Copy URL"):
        st.code(url)
        if player_ids:
            st.code(f"https://{BASE_URL}/comparison?bracket_player={player_ids[0]}")

    # Log execution time
    t2_stop = perf_counter()
    logging.info(f"Full live_bracket for {league} took {t2_stop - t2_start}")


live_bracket()
