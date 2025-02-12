import pandas as pd
import streamlit as st

from components.util import get_league_filter, get_options

from dtower.tourney_results.constants import champ, how_many_results_public_site, leagues
from dtower.tourney_results.data import get_tourneys
from dtower.tourney_results.models import TourneyResult
from dtower.tourney_results.tourney_utils import get_live_df


@st.cache_data(ttl=300)
def get_data(league):
    return get_live_df(league)


def live_results():
    st.markdown("# Live Results")
    print("liveresults")
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

    last_moment = tdf.datetime.iloc[0]
    ldf = df[df.datetime == last_moment]
    ldf.index = ldf.index + 1

    tdf["datetime"] = pd.to_datetime(tdf["datetime"])

    # Get reference data for joined calculation
    qs = TourneyResult.objects.filter(league=league, public=True).order_by("-date")
    if not qs:
        qs = TourneyResult.objects.filter(league=champ, public=True).order_by("-date")
    tourney = qs[0]
    pdf = get_tourneys([tourney])

    cols = st.columns([3, 2] if not is_mobile else [1])

    with cols[0]:
        st.write("Current result (ordered)")
        st.dataframe(ldf[["name", "real_name", "wave"]][:how_many_results_public_site], height=700, width=400)

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
    canvas.dataframe(pdf[["real_name", "wave_last", "joined"]][:topx], height=600, width=400)


live_results()
