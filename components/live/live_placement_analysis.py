# Standard library imports
import logging
from time import perf_counter

# Third-party imports
import pandas as pd
import plotly.express as px
import streamlit as st

# Local/application imports
from components.live.common import get_live_data
from components.util import get_league_filter, get_options
from dtower.tourney_results.constants import leagues
from dtower.tourney_results.tourney_utils import get_shun_ids

logging.basicConfig(level=logging.INFO)


@st.cache_data(ttl=300)
def process_initial_data(df: pd.DataFrame):
    """Process and cache initial data transformations"""
    # Efficient bracket filtering
    bracket_counts = df.groupby("bracket").player_id.nunique()
    fullish_brackets = bracket_counts[bracket_counts >= 28].index

    filtered_df = df[df.bracket.isin(fullish_brackets)].copy()
    filtered_df["real_name"] = filtered_df["real_name"].astype(str)

    # Pre-calculate common values
    latest_time = filtered_df["datetime"].max()
    bracket_creation_times = filtered_df.groupby("bracket")["datetime"].min().to_dict()

    return filtered_df, latest_time, bracket_creation_times


@st.cache_data(ttl=300)
def analyze_bracket_placement(bracket_df: pd.DataFrame, wave_to_analyze: int, latest_time):
    """Analyze placement for a single bracket"""
    last_bracket_df = bracket_df[bracket_df["datetime"] == latest_time]
    better_or_equal = (last_bracket_df["wave"] > wave_to_analyze).sum()
    total = len(last_bracket_df)

    return {
        "Would Place": f"{better_or_equal + 1}/{total}",
        "Top Wave": last_bracket_df["wave"].max(),
        "Median Wave": int(last_bracket_df["wave"].median()),
        "Players Above": better_or_equal,
        "Start Time": bracket_df["datetime"].min(),
    }


def create_placement_plot(plot_data, wave_to_analyze, player_info):
    """Create optimized placement plot"""
    fig = px.scatter(
        plot_data,
        x="Creation Time",
        y="Placement",
        title=f"Placement Timeline for {wave_to_analyze} waves",
        labels={"Creation Time": "Bracket Creation Time", "Placement": "Would Place Position"},
        trendline="lowess",
        trendline_options=dict(frac=0.2),
    )

    # Add player marker
    fig.add_scatter(
        x=[player_info["creation_time"]],
        y=[player_info["position"]],
        mode="markers",
        marker=dict(symbol="x", size=15, color="red"),
        name="Actual Position",
        showlegend=False,
    )

    fig.update_layout(
        yaxis_title="Position",
        height=400,
        margin=dict(l=20, r=20, t=40, b=20),
        uirevision=True  # Preserve UI state
    )
    fig.update_yaxes(autorange="reversed")

    return fig


def live_score():
    st.markdown("# Live Placement Analysis")
    t2_start = perf_counter()

    # Sidebar setup
    options = get_options(links=False)
    with st.sidebar:
        league = st.radio("League", leagues, get_league_filter(options.current_league))

    try:
        # Get and process initial data
        df = get_live_data(league, True)
        df, latest_time, bracket_creation_times = process_initial_data(df)
    except (IndexError, ValueError):
        st.info("No current data, wait until the tourney day")
        return

    # Filter suspicious players
    clean_df = df[~df.player_id.isin(get_shun_ids())]
    selected_player = st.selectbox("Select player", [""] + sorted(clean_df["real_name"].unique()))

    if not selected_player:
        return

    # Analyze player data
    wave_to_analyze = df[df.real_name == selected_player].wave.max()
    st.write(f"Analyzing placement for {selected_player}'s highest wave: {wave_to_analyze}")

    # Analyze brackets efficiently
    results = []
    for bracket in sorted(df["bracket"].unique()):
        bracket_df = df[df["bracket"] == bracket]
        result = analyze_bracket_placement(bracket_df, wave_to_analyze, latest_time)
        result["Bracket"] = bracket
        results.append(result)

    # Create and display results DataFrame
    results_df = pd.DataFrame(results)
    results_df["Creation Time"] = results_df["Bracket"].map(bracket_creation_times)
    results_df = results_df.sort_values("Creation Time").drop("Creation Time", axis=1)
    st.dataframe(results_df, hide_index=True)

    # Create placement plot
    player_bracket = df[df["real_name"] == selected_player]["bracket"].iloc[0]
    player_info = {
        "creation_time": bracket_creation_times[player_bracket],
        "position": (df[(df["bracket"] == player_bracket) &
                        (df["datetime"] == latest_time)]
                     .sort_values("wave", ascending=False)
                     .index.get_loc(df[(df["bracket"] == player_bracket) &
                                       (df["datetime"] == latest_time) &
                                    (df["real_name"] == selected_player)].index[0]) + 1)
    }

    plot_df = pd.DataFrame({
        "Creation Time": [bracket_creation_times[b] for b in results_df["Bracket"]],
        "Placement": [int(p.split("/")[0]) for p in results_df["Would Place"]]
    })

    fig = create_placement_plot(plot_df, wave_to_analyze, player_info)
    st.plotly_chart(fig, use_container_width=True)

    t2_stop = perf_counter()
    logging.info(f"full live_placement_analysis for {league} took {t2_stop - t2_start}")


if __name__ == "__main__":
    live_score()
