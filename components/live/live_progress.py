# Third-party imports
import pandas as pd
import plotly.express as px
import streamlit as st

# Local/application imports
from components.live.common import get_live_data
from components.util import get_league_filter, get_options
from dtower.tourney_results.constants import champ, leagues
from dtower.tourney_results.data import get_tourneys
from dtower.tourney_results.models import TourneyResult


@st.cache_data(ttl=300, max_entries=100)
def process_top_players(df: pd.DataFrame, n: int = 25):
    """Process and cache top players data"""
    top_n = (df.groupby("player_id")['wave']
             .max()
             .nlargest(n)
             .index)

    tdf = df[df.player_id.isin(top_n)].copy()
    tdf["datetime"] = pd.to_datetime(tdf["datetime"])

    return tdf, tdf.datetime.iloc[-1], tdf.datetime.iloc[0]


@st.cache_data(ttl=300)
def calculate_fill_ups(df: pd.DataFrame, pdf: pd.DataFrame, first_moment):
    """Calculate and cache fill-up progress"""
    fill_ups = []
    pdf_ids = set(pdf.id)  # Convert to set for faster lookups

    for dt, sdf in df.groupby("datetime"):
        joined_ids = set(sdf.player_id.unique())
        time_delta = dt - first_moment
        time = time_delta.total_seconds() / 3600
        fillup = len(joined_ids.intersection(pdf_ids))  # Faster set intersection
        fill_ups.append((time, fillup))

    return pd.DataFrame(sorted(fill_ups), columns=["time", "fillup"])


@st.cache_data(ttl=300)
def create_progress_plot(tdf: pd.DataFrame, is_mobile: bool):
    """Create and cache progress plot"""
    fig = px.line(
        tdf,
        x="datetime",
        y="wave", color="real_name",
        title="Top 25 Players: live score",
        markers=True,
        line_shape="linear"
    )

    fig.update_traces(mode="lines+markers")
    fig.update_layout(
        xaxis_title="Time",
        yaxis_title="Wave",
        legend_title="real_name",
        hovermode="closest",
        height=500,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h" if is_mobile else "v"),
        uirevision=True  # Preserve UI state
    )
    return fig


@st.cache_data(ttl=300)
def create_fillup_plot(fill_ups: pd.DataFrame):
    """Create and cache fill-up plot"""
    fig = px.line(
        fill_ups,
        x="time",
        y="fillup",
        title="Fill up progress",
        markers=True,
        line_shape="linear"
    )

    fig.update_traces(mode="lines+markers", fill="tozeroy")
    fig.update_layout(
        xaxis_title="Time [h]",
        yaxis_title="Fill up [players]",
        hovermode="closest",
        height=400,
        margin=dict(l=20, r=20, t=40, b=20),
        uirevision=True
    )
    fig.add_hline(y=2500, line_dash="dot", line_color="green")
    return fig


def live_progress():
    st.markdown("# Live Progress")
    options = get_options(links=False)

    # Sidebar configuration
    with st.sidebar:
        league_index = get_league_filter(options.current_league)
        league = st.radio("League", leagues, league_index)
        is_mobile = st.checkbox("Mobile view", value=st.session_state.get("mobile_view", False), key="mobile_view")

    try:
        df = get_live_data(league)
        tdf, first_moment, last_moment = process_top_players(df)
    except (IndexError, ValueError):
        st.info("No current data, wait until the tourney day")
        return

    # Display progress plot
    progress_fig = create_progress_plot(tdf, is_mobile)
    st.plotly_chart(progress_fig, use_container_width=True)

    # Get reference data efficiently
    qs = (TourneyResult.objects
          .filter(league=league, public=True)
          .order_by("-date")
          .first() or
          TourneyResult.objects
          .filter(league=champ, public=True)
          .order_by("-date")
          .first())

    if not qs:
        st.warning("No reference data available")
        return

    pdf = get_tourneys([qs])

    # Calculate and display fill-up progress
    fill_ups_df = calculate_fill_ups(df, pdf, first_moment)
    fillup_fig = create_fillup_plot(fill_ups_df)
    st.plotly_chart(fillup_fig, use_container_width=True)


live_progress()
