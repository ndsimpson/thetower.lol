import pandas as pd
import logging
import plotly.express as px
import streamlit as st
from time import perf_counter

from components.util import get_league_filter, get_options

from dtower.tourney_results.constants import leagues
from dtower.tourney_results.tourney_utils import get_live_df

logging.basicConfig(level=logging.INFO)


def live_score():
    t2_start = perf_counter()
    options = get_options(links=False)
    with st.sidebar:
        league_index = get_league_filter(options.current_league)
        league = st.radio("League", leagues, league_index)

    with st.sidebar:
        # Check if mobile view
        is_mobile = st.session_state.get("mobile_view", False)
        st.checkbox("Mobile view", value=is_mobile, key="mobile_view")

    tab = st
    try:
        df = get_live_df(league)
        t1_start = perf_counter()
        df["real_name"] = df["real_name"].astype("str")  # Make sure that users with all digit tourney_name's don't trick the column into being a float
        t1_stop = perf_counter()
        logging.info(f"Casting real_name in live_placement_analysis took {t1_stop - t1_start}")
    except (IndexError, ValueError):
        tab.info("No current data, wait until the tourney day")
        return

    # Get data
    group_by_id = df.groupby("player_id")
    top_25 = group_by_id.wave.max().sort_values(ascending=False).index[:25]
    tdf = df[df.player_id.isin(top_25)]

    last_moment = tdf.datetime.iloc[0]
    ldf = df[df.datetime == last_moment]
    ldf.index = ldf.index + 1

    # Get all unique real names for the selector
    all_players = sorted(df["real_name"].unique())
    selected_player = st.selectbox("Select player", all_players)

    if not selected_player:
        return

    # Get the player's highest wave
    wave_to_analyze = df[df.real_name == selected_player].wave.max()

    # Get latest time point
    latest_time = df["datetime"].max()

    st.write(f"Analyzing placement for {selected_player}'s highest wave: {wave_to_analyze}")

    # Analyze each bracket
    results = []
    for bracket in sorted(df["bracket"].unique()):
        # Get data for this bracket at the latest time
        bracket_df = df[df["bracket"] == bracket]
        start_time = bracket_df["datetime"].min()
        last_bracket_df = bracket_df[bracket_df["datetime"] == latest_time].sort_values("wave", ascending=False)

        # Calculate where this wave would rank
        better_or_equal = last_bracket_df[last_bracket_df["wave"] > wave_to_analyze].shape[0]
        total = last_bracket_df.shape[0]
        rank = better_or_equal + 1  # +1 because the input wave would come after equal scores

        results.append(
            {
                "Bracket": bracket,
                "Would Place": f"{rank}/{total}",
                "Top Wave": last_bracket_df["wave"].max(),
                "Median Wave": int(last_bracket_df["wave"].median()),
                "Players Above": better_or_equal,
                "Start Time": start_time,
            }
        )

    # Get bracket creation times
    bracket_creation_times = {}
    for bracket in df["bracket"].unique():
        bracket_creation_times[bracket] = df[df["bracket"] == bracket]["datetime"].min()

    # Convert results to DataFrame and display
    results_df = pd.DataFrame(results)
    # Add creation time and sort by it
    results_df["Creation Time"] = results_df["Bracket"].map(bracket_creation_times)
    results_df = results_df.sort_values("Creation Time")
    # Drop the Creation Time column before display
    results_df = results_df.drop("Creation Time", axis=1)

    st.write(f"Analysis for wave {wave_to_analyze} (ordered by bracket creation time):")
    st.dataframe(results_df, hide_index=True)

    # Create placement vs time plot
    # Get player's actual bracket
    player_bracket = df[df["real_name"] == selected_player]["bracket"].iloc[0]
    player_creation_time = bracket_creation_times[player_bracket]
    player_position = (
        df[(df["bracket"] == player_bracket) & (df["datetime"] == latest_time)]
        .sort_values("wave", ascending=False)
        .index.get_loc(df[(df["bracket"] == player_bracket) & (df["datetime"] == latest_time) & (df["real_name"] == selected_player)].index[0])
        + 1
    )

    plot_df = pd.DataFrame(
        {
            "Creation Time": [bracket_creation_times[b] for b in results_df["Bracket"]],
            "Placement": [int(p.split("/")[0]) for p in results_df["Would Place"]],
        }
    )

    fig = px.scatter(
        plot_df,
        x="Creation Time",
        y="Placement",
        title=f"Placement Timeline for {wave_to_analyze} waves",
        labels={"Creation Time": "Bracket Creation Time", "Placement": "Would Place Position"},
        trendline="lowess",
        trendline_options=dict(frac=0.2),
    )

    # Add player's actual position as a red X
    fig.add_scatter(
        x=[player_creation_time],
        y=[player_position],
        mode="markers",
        marker=dict(symbol="x", size=15, color="red"),
        name="Actual Position",
        showlegend=False,
    )

    fig.update_layout(yaxis_title="Position", height=400, margin=dict(l=20, r=20, t=40, b=20))
    # Reverse y-axis so better placements (lower numbers) are at the top
    fig.update_yaxes(autorange="reversed")

    st.plotly_chart(fig, use_container_width=True)
    t2_stop = perf_counter()
    logging.info(f"full live_placement_analysis took {t2_stop - t2_start}")


live_score()
