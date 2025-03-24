# Standard library imports
from urllib.parse import urlencode

# Third-party imports
import pandas as pd
import plotly.express as px
import streamlit as st

# Local/application imports
from components.live.common import get_live_data
from components.util import get_league_filter, get_options
from dtower.tourney_results.constants import leagues
from dtower.tourney_results.formatting import BASE_URL, make_player_url


@st.cache_data(ttl=300)
def get_data(league: str, shun: bool = False):
    return get_live_data(league, shun)


@st.cache_data(ttl=300)
def process_bracket_data(df):
    """Process and cache initial bracket data"""
    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"])

    # More efficient bracket counting
    bracket_counts = df.groupby("bracket").player_id.nunique()
    fullish_brackets = bracket_counts[bracket_counts >= 28].index

    # Filter and sort brackets
    df = df[df.bracket.isin(fullish_brackets)]
    bracket_order = df.groupby("bracket")["datetime"].min().sort_values().index.tolist()

    return df, bracket_order


@st.cache_data(ttl=300)
def prepare_bracket_view(df, bracket_id):
    """Process and cache single bracket view data"""
    tdf = df[df.bracket == bracket_id].copy()

    # Efficient name handling
    name_counts = tdf.groupby("real_name")["player_id"].nunique()
    duplicate_names = name_counts[name_counts > 1].index

    tdf["display_name"] = tdf["real_name"]
    if len(duplicate_names) > 0:
        mask = tdf["real_name"].isin(duplicate_names)
        tdf.loc[mask, "display_name"] = tdf[mask].apply(
            lambda x: f"{x['real_name']} ({x['player_id']})", axis=1
        )

    return tdf


@st.cache_data(ttl=300)
def load_css():
    """Cache CSS loading"""
    with open("style.css", "r") as infile:
        return f"<style>{infile.read()}</style>"


@st.cache_data(ttl=300)
def create_bracket_plot(tdf):
    """Create and cache plot"""
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
        hovermode="closest",
        uirevision=True,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
    )
    return fig


def get_bracket_by_name(df: pd.DataFrame, player_name: str) -> int:
    """Get bracket ID by player name"""
    player_brackets = df[df.real_name == player_name].bracket.unique()
    if len(player_brackets) == 0:
        return None
    return player_brackets[-1]  # Return most recent bracket


def get_bracket_by_id(df: pd.DataFrame, player_id: int) -> int:
    """Get bracket ID by player ID"""
    player_brackets = df[df.player_id == player_id].bracket.unique()
    if len(player_brackets) == 0:
        return None
    return player_brackets[-1]  # Return most recent bracket


def handle_manual_selection(df: pd.DataFrame, bracket_order: list) -> int:
    """Handle manual bracket selection"""
    if not bracket_order:
        return None

    bracket_options = {f"Bracket {i + 1}": b for i, b in enumerate(bracket_order)}
    selected = st.selectbox(
        "Select bracket",
        options=list(bracket_options.keys()),
        index=len(bracket_options) - 1
    )
    return bracket_options[selected]


def handle_bracket_selection(df, bracket_order, options):
    """Handle bracket selection logic"""
    if options.current_player:
        return get_bracket_by_name(df, options.current_player)
    elif options.current_player_id:
        return get_bracket_by_id(df, options.current_player_id)

    return handle_manual_selection(df, bracket_order)


def display_final_standings(tdf):
    """Display final standings table"""
    last_moment = tdf.datetime.max()
    ldf = tdf[tdf.datetime == last_moment].copy()
    ldf.index = ldf.index + 1

    st.write(
        ldf[["player_id", "name", "display_name", "wave", "datetime"]]
        .style.format(make_player_url, subset=["player_id"])
        .to_html(escape=False),
        unsafe_allow_html=True
    )


def display_comparison_links(player_ids):
    """Display comparison links"""
    if not player_ids:
        return

    url = f"https://{BASE_URL}/comparison?" + urlencode({"compare": player_ids}, doseq=True)
    bracket_url = f"https://{BASE_URL}/comparison?bracket_player={player_ids[0]}"

    with st.container():
        st.write(f'<a href="{url}">See comparison (old way)</a>', unsafe_allow_html=True)
        st.write(f'<a href="{bracket_url}">See comparison (new way)</a>', unsafe_allow_html=True)

    with st.expander("Copy URL"):
        st.code(url)
        st.code(bracket_url)


def live_bracket():
    st.markdown("# Live Bracket View")
    options = get_options(links=False)

    with st.sidebar:
        league_index = get_league_filter(options.current_league)
        league = st.radio("League", leagues, league_index)

    try:
        # Get and process initial data
        raw_df = get_data(league, True)
        df, bracket_order = process_bracket_data(raw_df)
    except (IndexError, ValueError):
        st.info("No current data, wait until the tourney day")
        return

    if not bracket_order:
        st.info("No full brackets available")
        return

    # Selection logic
    selected_bracket = handle_bracket_selection(df, bracket_order, options)
    if not selected_bracket:
        return

    # Process bracket data
    try:
        tdf = prepare_bracket_view(df, selected_bracket)
        player_ids = sorted(tdf.player_id.unique())
    except Exception as e:
        st.error(f"Selection not found: {str(e)}")
        return

    # Display bracket info
    bracket_start_time = tdf["datetime"].min()
    st.info(f"Bracket started at approx.: {bracket_start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    # Create and display plot
    fig = create_bracket_plot(tdf)
    st.plotly_chart(fig, use_container_width=True)

    # Display final standings
    display_final_standings(tdf)

    # Display comparison links
    display_comparison_links(player_ids)


live_bracket()
