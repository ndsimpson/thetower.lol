from urllib.parse import urlencode

import pandas as pd
import plotly.express as px
import streamlit as st

from components.util import get_league_filter, get_options

from dtower.tourney_results.constants import leagues
from dtower.tourney_results.formatting import BASE_URL, make_player_url
from dtower.tourney_results.tourney_utils import get_live_df


@st.cache_data(ttl=300)
def get_data(league: str, shun: bool = False):
    return get_live_df(league, shun)


def live_bracket():
    st.markdown("# Live Bracket View")
    print("livebracketview")
    tab = st
    options = get_options(links=False)

    with st.sidebar:
        league_index = get_league_filter(options.current_league)
        league = st.radio("League", leagues, league_index)

    try:
        df = get_data(league, True)
    except (IndexError, ValueError):
        tab.info("No current data, wait until the tourney day")
        return

    name_col, id_col = tab.columns(2)

    # Sort brackets by their first appearance time
    df["datetime"] = pd.to_datetime(df["datetime"])
    bracket_order = df.groupby("bracket")["datetime"].min().sort_values().index.tolist()

    bracket_counts = dict(df.groupby("bracket").player_id.unique().map(lambda player_ids: len(player_ids)))
    fullish_brackets = [bracket for bracket, count in bracket_counts.items() if count >= 28]

    df = df[df.bracket.isin(fullish_brackets)]  # no sniping

    # Initialize session state for bracket navigation
    if "current_bracket_idx" not in st.session_state:
        st.session_state.current_bracket_idx = 0

    selected_real_name = None
    selected_player_id = None
    selected_bracket = None

    if options.current_player:
        selected_real_name = options.current_player
    elif options.current_player_id:
        selected_player_id = options.current_player_id
    else:
        selected_real_name = name_col.selectbox("Bracket of...", [""] + sorted(df.real_name.unique()))
        selected_player_id = id_col.selectbox("...or by player id", [""] + sorted(df.player_id.unique()))

        if not selected_real_name and not selected_player_id:
            # Add navigation buttons in columns
            prev_col, curr_col, next_col = st.columns([1, 2, 1])

            with prev_col:
                if st.button("← Previous Bracket", key=f"prev_{league}"):
                    st.session_state.current_bracket_idx = (st.session_state.current_bracket_idx - 1) % len(bracket_order)

            with curr_col:
                selected_bracket_direct = st.selectbox("Select Bracket", bracket_order, index=st.session_state.current_bracket_idx)
                if selected_bracket_direct != bracket_order[st.session_state.current_bracket_idx]:
                    st.session_state.current_bracket_idx = bracket_order.index(selected_bracket_direct)

            with next_col:
                if st.button("Next Bracket →", key=f"next_{league}"):
                    st.session_state.current_bracket_idx = (st.session_state.current_bracket_idx + 1) % len(bracket_order)

            selected_bracket = bracket_order[st.session_state.current_bracket_idx]

    if not any([selected_real_name, selected_player_id, selected_bracket]):
        return

    try:
        if selected_bracket:
            bracket_id = selected_bracket
            tdf = df[df.bracket == bracket_id]
            selected_real_name = tdf.real_name.iloc[0]  # Get any player from the bracket for comparison
        elif selected_player_id:
            selected_real_name = df[df.player_id == selected_player_id].real_name.iloc[0]
            sdf = df[df.real_name == selected_real_name]
            bracket_id = sdf.bracket.iloc[0]
            tdf = df[df.bracket == bracket_id]
            st.session_state.current_bracket_idx = bracket_order.index(bracket_id)
        elif selected_real_name:
            sdf = df[df.real_name == selected_real_name]
            bracket_id = sdf.bracket.iloc[0]
            tdf = df[df.bracket == bracket_id]
            st.session_state.current_bracket_idx = bracket_order.index(bracket_id)
    except Exception as e:
        tab.error(f"Selection not found: {str(e)}")
        return

    player_ids = sorted(tdf.player_id.unique())

    tdf["datetime"] = pd.to_datetime(tdf["datetime"])
    bracket_start_time = tdf["datetime"].min()
    tab.info(f"Bracket started at approx.: {bracket_start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    # Add player_id only to duplicated names within this bracket
    tdf = tdf.copy()
    # Get unique real_name/player_id combinations
    name_counts = tdf.groupby("real_name")["player_id"].nunique()
    duplicate_names = name_counts[name_counts > 1].index

    tdf["display_name"] = tdf["real_name"]
    # Only modify display names for players that share the same name in this bracket
    if len(duplicate_names) > 0:
        tdf.loc[tdf["real_name"].isin(duplicate_names), "display_name"] = tdf[tdf["real_name"].isin(duplicate_names)].apply(
            lambda x: f"{x['real_name']} ({x['player_id']})", axis=1
        )

    fig = px.line(tdf, x="datetime", y="wave", color="display_name", title="Live bracket score", markers=True, line_shape="linear")
    fig.update_traces(mode="lines+markers")
    fig.update_layout(xaxis_title="Time", yaxis_title="Wave", legend_title="real_name", hovermode="closest")
    tab.plotly_chart(fig, use_container_width=True)

    last_moment = tdf.datetime.max()
    ldf = tdf[tdf.datetime == last_moment].reset_index(drop=True)
    ldf.index = ldf.index + 1
    # Add player_id only to duplicated names within this bracket
    ldf = ldf.copy()

    # Get unique real_name/player_id combinations
    name_counts = ldf.groupby("real_name")["player_id"].nunique()
    duplicate_names = name_counts[name_counts > 1].index

    # Only modify names for players that share the same name in this bracket
    if len(duplicate_names) > 0:
        ldf.loc[ldf["real_name"].isin(duplicate_names), "real_name"] = ldf[ldf["real_name"].isin(duplicate_names)].apply(
            lambda x: f"{x['real_name']} ({x['player_id']})", axis=1
        )
    tab.write(
        ldf[["player_id", "name", "real_name", "wave", "datetime"]].style.format(make_player_url, subset=["player_id"]).to_html(escape=False), unsafe_allow_html=True
    )
    url = f"https://{BASE_URL}/comparison?" + urlencode({"compare": player_ids}, doseq=True)

    with open("style.css", "r") as infile:
        table_styling = f"<style>{infile.read()}</style>"

    st.write(table_styling, unsafe_allow_html=True)

    # Create a container for comparison links
    comparison_container = st.container()

    with comparison_container:
        st.write(f'<a href="{url}">See comparison (old way)</a>', unsafe_allow_html=True)

        # Add the new bracket comparison link using any player ID from the bracket
        if player_ids:
            bracket_url = f"https://{BASE_URL}/comparison?bracket_player={player_ids[0]}"
            st.write(f'<a href="{bracket_url}">See comparison (new way)</a>', unsafe_allow_html=True)

    # Show the raw URL for copying
    with st.expander("Copy URL"):
        st.code(url)
        if player_ids:
            st.code(f"https://{BASE_URL}/comparison?bracket_player={player_ids[0]}")


live_bracket()
