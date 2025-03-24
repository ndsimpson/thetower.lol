# Third-party imports
import pandas as pd
import streamlit as st

# Local/application imports
from components.live.common import get_live_data
from components.util import get_league_filter, get_options
from dtower.tourney_results.constants import champ, how_many_results_public_site, leagues
from dtower.tourney_results.data import get_tourneys
from dtower.tourney_results.models import TourneyResult


@st.cache_data(ttl=300, max_entries=100)
def process_live_data(df: pd.DataFrame):
    """Process and cache live tournament data"""
    # Get top 25 players efficiently
    top_25 = (df.groupby("player_id")['wave']
              .max()
              .nlargest(25)
              .index)

    tdf = df[df.player_id.isin(top_25)].copy()

    # Get latest data efficiently
    last_moment = df.datetime.max()
    ldf = df[df.datetime == last_moment].copy()
    ldf.index = ldf.index + 1

    # Convert datetime once
    tdf["datetime"] = pd.to_datetime(tdf["datetime"])

    return tdf, ldf, last_moment


@st.cache_data(ttl=300)
def get_reference_data(league: str):
    """Get and cache reference tournament data"""
    qs = (TourneyResult.objects
          .filter(league=league, public=True)
          .order_by("-date")
          .first() or
          TourneyResult.objects
          .filter(league=champ, public=True)
          .order_by("-date")
          .first())

    return get_tourneys([qs]) if qs else None


@st.cache_data(ttl=300)
def process_joined_data(pdf: pd.DataFrame, ldf: pd.DataFrame, topx: int):
    """Process and cache joined players data"""
    joined_ids = set(ldf.player_id.unique())

    # Efficient DataFrame operations
    pdf = pdf.copy()
    pdf["joined"] = pdf.id.isin(joined_ids)
    pdf = pdf.rename(columns={"wave": "wave_last"})
    pdf.index = pdf.index + 1

    # Calculate join statistics
    joined_sum = pdf["joined"][:topx].sum()
    joined_tot = min(len(pdf), topx)

    return pdf, joined_sum, joined_tot


def live_results():
    st.markdown("# Live Results")
    options = get_options(links=False)

    # Sidebar configuration
    with st.sidebar:
        league_index = get_league_filter(options.current_league)
        league = st.radio("League", leagues, league_index)
        is_mobile = st.checkbox("Mobile view", value=st.session_state.get("mobile_view", False), key="mobile_view")

    try:
        # Get and process initial data
        df = get_live_data(league)
        tdf, ldf, last_moment = process_live_data(df)
    except (IndexError, ValueError):
        st.info("No current data, wait until the tourney day")
        return

    # Layout setup
    cols = st.columns([3, 2] if not is_mobile else [1])

    # Display current results
    with cols[0]:
        st.write("Current result (ordered)")
        st.dataframe(
            ldf[["name", "real_name", "wave"]][:how_many_results_public_site],
            height=700,
            width=400
        )

    # Handle reference data
    pdf = get_reference_data(league)
    if not pdf:
        st.error("No reference data available")
        return

    # Process joined data
    canvas = cols[0] if is_mobile else cols[1]
    topx = canvas.selectbox("top x", [1000, 500, 200, 100, 50, 25], key=f"topx_{league}")

    pdf, joined_sum, joined_tot = process_joined_data(pdf, ldf, topx)

    # Display join statistics
    ratio = joined_sum / joined_tot
    color = "green" if ratio >= 0.7 else "orange" if ratio >= 0.5 else "red"
    canvas.write(
        f"Has top {topx} joined already? <font color='{color}'>{joined_sum}</font>/{topx}",
        unsafe_allow_html=True
    )

    canvas.dataframe(
        pdf[["real_name", "wave_last", "joined"]][:topx],
        height=600,
        width=400
    )


live_results()
