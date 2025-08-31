import pandas as pd
import plotly.express as px
import streamlit as st

from thetower.backend.tourney_results.constants import champ, how_many_results_public_site
from thetower.backend.tourney_results.data import get_tourneys
from thetower.backend.tourney_results.models import TourneyResult
from thetower.backend.tourney_results.tourney_utils import get_live_df
from thetower.web.util import get_league_selection, get_options


@st.cache_data(ttl=300)
def get_data(league: str, shun: bool = False):
    return get_live_df(league, shun)


def live_score():
    st.markdown("# Live Scoring")
    print("livescore")
    options = get_options(links=False)
    league = get_league_selection(options)

    with st.sidebar:
        # Check if mobile view
        is_mobile = st.session_state.get("mobile_view", False)
        st.checkbox("Mobile view", value=is_mobile, key="mobile_view")

    tab = st
    try:
        df = get_data(league, True)
    except (IndexError, ValueError):
        tab.info("No current data, wait until the tourney day")
        return

    # Create view tabs
    view_tabs = tab.tabs(["Live Progress", "Current Results", "Bracket Analysis", "Time Analysis"])

    # Get data
    group_by_id = df.groupby("player_id")
    top_25 = group_by_id.wave.max().sort_values(ascending=False).index[:25]
    tdf = df[df.player_id.isin(top_25)]

    first_moment = tdf.datetime.iloc[-1]
    last_moment = tdf.datetime.iloc[0]
    ldf = df[df.datetime == last_moment]
    ldf.index = ldf.index + 1

    # Live Progress Tab
    with view_tabs[0]:
        tdf["datetime"] = pd.to_datetime(tdf["datetime"])
        fig = px.line(tdf, x="datetime", y="wave", color="real_name", title="Top 25 Players: live score", markers=True, line_shape="linear")

        fig.update_traces(mode="lines+markers")
        fig.update_layout(
            xaxis_title="Time",
            yaxis_title="Wave",
            legend_title="real_name",
            hovermode="closest",
            height=500,
            margin=dict(l=20, r=20, t=40, b=20),
            legend=dict(orientation="h" if is_mobile else "v"),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Get reference data for fill-up calculation
        qs = TourneyResult.objects.filter(league=league, public=True).order_by("-date")
        if not qs:
            qs = TourneyResult.objects.filter(league=champ, public=True).order_by("-date")
        tourney = qs[0]
        pdf = get_tourneys([tourney])

        # Fill up progress
        fill_ups = []
        for dt, sdf in df.groupby("datetime"):
            joined_ids = set(sdf.player_id.unique())
            time_delta = dt - first_moment
            time = time_delta.total_seconds() / 3600
            fillup = sum([player_id in joined_ids for player_id in pdf.id])
            fill_ups.append((time, fillup))

        fill_ups = pd.DataFrame(sorted(fill_ups), columns=["time", "fillup"])
        fig = px.line(fill_ups, x="time", y="fillup", title="Fill up progress", markers=True, line_shape="linear")
        fig.update_traces(mode="lines+markers", fill="tozeroy")
        fig.update_layout(
            xaxis_title="Time [h]",
            yaxis_title="Fill up [players]",
            hovermode="closest",
            height=400,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        fig.add_hline(y=1001, line_dash="dot", line_color="green")
        st.plotly_chart(fig, use_container_width=True)

    # Current Results Tab
    with view_tabs[1]:
        cols = st.columns([3, 2] if not is_mobile else [1])

        with cols[0]:
            st.write("Current result (ordered)")
            st.dataframe(ldf[["name", "real_name", "wave"]][:how_many_results_public_site], height=700)

        canvas = cols[0] if is_mobile else cols[1]

        joined_ids = set(ldf.player_id.unique())
        pdf["joined"] = [player_id in joined_ids for player_id in pdf.id]
        pdf = pdf.rename(columns={"wave": "wave_last"})
        pdf.index = pdf.index + 1

        topx = canvas.selectbox("top x", [1000, 500, 200, 100, 50, 25], key=f"topx_{league}")
        joined_sum = sum(pdf["joined"][:topx])
        joined_tot = len(pdf["joined"][:topx])

        color = "green" if joined_sum / joined_tot >= 0.7 else "orange" if joined_sum / joined_tot >= 0.5 else "red"
        canvas.write(f"Has top {topx} joined already? <font color='{color}'>{joined_sum}</font>/{topx}", unsafe_allow_html=True)
        canvas.dataframe(pdf[["real_name", "wave_last", "joined"]][:topx], height=600)

    # Bracket Analysis Tab
    with view_tabs[2]:
        group_by_bracket = ldf.groupby("bracket").wave
        bracket_from_hell = group_by_bracket.sum().sort_values(ascending=False).index[0]
        bracket_from_hell_by_median = group_by_bracket.median().sort_values(ascending=False).index[0]
        bracket_from_heaven = group_by_bracket.sum().sort_values(ascending=True).index[0]
        bracket_from_heaven_by_median = group_by_bracket.median().sort_values(ascending=True).index[0]

        st.write(f"Total closed brackets until now: {ldf.groupby('bracket').ngroups}")

        # Create combined histogram for median and mean waves
        # Calculate top positions for each bracket
        def get_top_n(group, n):
            return group.nlargest(n).iloc[-1] if len(group) >= n else None

        stats_df = pd.DataFrame({
            "Top 1": group_by_bracket.apply(lambda x: get_top_n(x, 1)),
            "Top 4": group_by_bracket.apply(lambda x: get_top_n(x, 4)),
            "Top 10": group_by_bracket.apply(lambda x: get_top_n(x, 10)),
            "Top 15": group_by_bracket.apply(lambda x: get_top_n(x, 15)),
        }).melt()

        # Create histogram
        fig1 = px.histogram(
            stats_df,
            x="value",
            color="variable",
            barmode="overlay",
            opacity=0.7,
            title="Distribution of Top Positions per Bracket",
            labels={"value": "Waves", "count": "Number of Brackets", "variable": "Position"},
            height=300,
        )

        fig1.update_layout(
            margin=dict(l=20, r=20, t=40, b=20),
            legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99)
        )
        st.plotly_chart(fig1, use_container_width=True)

        cols = st.columns(2 if not is_mobile else 1)

        with cols[0]:
            st.write(f"Highest total waves: {bracket_from_hell}")
            st.dataframe(ldf[ldf.bracket == bracket_from_hell][["real_name", "wave", "datetime"]])

            st.write(f"Lowest total waves: {bracket_from_heaven}")
            st.dataframe(ldf[ldf.bracket == bracket_from_heaven][["real_name", "wave", "datetime"]])

        with cols[1]:
            st.write(f"Highest median waves: {bracket_from_hell_by_median}")
            st.dataframe(ldf[ldf.bracket == bracket_from_hell_by_median][["real_name", "wave", "datetime"]])

            st.write(f"Lowest median waves: {bracket_from_heaven_by_median}")
            st.dataframe(ldf[ldf.bracket == bracket_from_heaven_by_median][["real_name", "wave", "datetime"]])

    with view_tabs[3]:
        # Get all unique real names for the selector
        all_players = sorted(df["real_name"].unique())
        selected_player = st.selectbox(
            "Select player",
            all_players,
            key=f"player_selector_{league}"
        )

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


live_score()
