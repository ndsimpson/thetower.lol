import datetime

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_extras.let_it_rain import rain

from dtower.tourney_results.constants import Graph, Options, leagues


def links_toggle():
    with st.sidebar:
        st.write("Toggles")
        links = st.checkbox("Links to users? (will make dataframe ugly)", value=False)

    return links


def get_options(links=None):
    if links is not False:
        links = links_toggle()

    options = Options(links_toggle=links, default_graph=Graph.last_16.value, average_foreground=True)

    query = st.query_params

    if query:
        print(datetime.datetime.now(), query)

    player = query.get("player")
    player_id = query.get("player_id")
    compare_players = query.get_all("compare")
    league = query.get("league")
    print(f"{player=}, {compare_players=}, {league=}")

    options.current_player = player
    options.current_player_id = player_id
    options.compare_players = compare_players
    options.current_league = league

    if options.current_league:
        options.current_league = options.current_league.capitalize()

    return options


def get_league_filter(league=None):
    try:
        index = leagues.index(league)
    except ValueError:
        index = 0

    return index


def get_league_selection(options=None):
    """Get or set the league selection from session state"""
    if options is None:
        options = get_options(links=False)

    # Initialize league in session state if not present
    if "selected_league" not in st.session_state:
        league_index = get_league_filter(options.current_league)
        st.session_state.selected_league = leagues[league_index]

    with st.sidebar:
        # Use the session state value as the default
        league_index = leagues.index(st.session_state.selected_league)
        league = st.radio("League", leagues, league_index)
        # Update session state when changed
        st.session_state.selected_league = league

    return league


def gantt(df):
    def get_borders(dates: list[datetime.date]) -> list[tuple[datetime.date, datetime.date]]:
        """Get start and finish of each interval. Assuming dates are sorted and tourneys are max 4 days apart."""

        borders = []

        start = dates[0]

        for date, next_date in zip(dates[1:], dates[2:]):
            if next_date - date > datetime.timedelta(days=4):
                end = date
                borders.append((start, end))
                start = next_date

        borders.append((start, dates[-1]))

        return borders

    gantt_data = []

    for i, row in df.iterrows():
        borders = get_borders(row.tourneys_attended)
        name = row.Player

        for start, end in borders:
            gantt_data.append(
                {
                    "Player": name,
                    "Start": start,
                    "Finish": end,
                    "Champion": name,
                }
            )

    gantt_df = pd.DataFrame(gantt_data)

    fig = px.timeline(gantt_df, x_start="Start", x_end="Finish", y="Player", color="Champion")
    fig.update_yaxes(autorange="reversed")
    return fig


def add_player_id(player_id):
    st.session_state.player_id = player_id


def add_to_comparison(player_id, nicknames):
    if "comparison" in st.session_state:
        st.session_state.comparison.add(player_id)
        st.session_state.addee_map[player_id] = nicknames
    else:
        st.session_state.comparison = {player_id}
        st.session_state.addee_map = {player_id: nicknames}

    print(f"{st.session_state.comparison=} {st.session_state.addee_map=}")
    st.session_state.counter = st.session_state.counter + 1 if st.session_state.get("counter") else 1


def deprecated():
    st.info("This page is now deprecated and won't be updated past the end of Champ era. If you use or like this page, please let the site admins know on discord.")


def makeitrain(icon: str, after: datetime.date, before: datetime.date):
    today = datetime.date.today()
    if today >= after and today <= before:
        rain(
            emoji=icon,
            font_size=27,
            falling_speed=20,
            animation_length="infinite",
        )
