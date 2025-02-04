import pandas as pd
import plotly.express as px
import streamlit as st

from components.util import get_league_filter, get_options

from dtower.tourney_results.constants import champ, leagues
from dtower.tourney_results.data import get_tourneys
from dtower.tourney_results.models import TourneyResult
from dtower.tourney_results.tourney_utils import get_live_df


@st.cache_data(ttl=300)
def get_data(league):
    return get_live_df(league)


def live_progress():
    print("liveprogress")
    options = get_options(links=False)
    with st.sidebar:
        league_index = get_league_filter(options.current_league)
        league = st.radio("League", leagues, league_index)

    with st.sidebar:
        # Check if mobile view
        is_mobile = st.session_state.get("mobile_view", False)
        st.checkbox("Mobile view", value=is_mobile, key="mobile_view")

    try:
        df = get_data(league)
    except (IndexError, ValueError):
        st.info("No current data, wait until the tourney day")
        return

    # Get data
    group_by_id = df.groupby("player_id")
    top_25 = group_by_id.wave.max().sort_values(ascending=False).index[:25]
    tdf = df[df.player_id.isin(top_25)]

    first_moment = tdf.datetime.iloc[-1]
    last_moment = tdf.datetime.iloc[0]
    ldf = df[df.datetime == last_moment]
    ldf.index = ldf.index + 1

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


live_progress()
