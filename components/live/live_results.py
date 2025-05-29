import streamlit as st
import logging
from time import perf_counter

from components.live.ui_components import setup_common_ui
from components.live.data_ops import (
    get_processed_data,
    require_tournament_data
)
from dtower.tourney_results.constants import champ, how_many_results_public_site
from dtower.tourney_results.data import get_tourneys
from dtower.tourney_results.models import TourneyResult


@require_tournament_data
def live_results():
    st.markdown("# Live Results")
    logging.info("Starting live results")
    t2_start = perf_counter()

    # Use common UI setup
    options, league, is_mobile = setup_common_ui()

    # Get processed data
    df, tdf, ldf, _, _ = get_processed_data(league)

    # Get reference data for joined calculation
    qs = TourneyResult.objects.filter(league=league, public=True).order_by("-date")
    if not qs:
        qs = TourneyResult.objects.filter(league=champ, public=True).order_by("-date")
    tourney = qs[0]
    pdf = get_tourneys([tourney])

    cols = st.columns([3, 2] if not is_mobile else [1])

    with cols[0]:
        st.write("Current result (ordered)")
        st.dataframe(
            ldf[["name", "real_name", "wave"]][:how_many_results_public_site],
            height=700,
            width=400
        )

    canvas = cols[0] if is_mobile else cols[1]

    joined_ids = set(ldf.player_id.unique())
    pdf["joined"] = [player_id in joined_ids for player_id in pdf.id]
    pdf = pdf.rename(columns={"wave": "wave_last"})
    pdf.index = pdf.index + 1

    topx = canvas.selectbox("top x", [1000, 500, 200, 100, 50, 25], key=f"topx_{league}")
    joined_sum = sum(pdf["joined"][:topx])
    joined_tot = len(pdf["joined"][:topx])

    color = ("green" if joined_sum / joined_tot >= 0.7
             else "orange" if joined_sum / joined_tot >= 0.5
             else "red")
    canvas.write(
        f"Has top {topx} joined already? <font color='{color}'>{joined_sum}</font>/{topx}",
        unsafe_allow_html=True
    )
    canvas.dataframe(
        pdf[["real_name", "wave_last", "joined"]][:topx],
        height=600,
        width=400
    )

    # Log execution time
    t2_stop = perf_counter()
    logging.info(f"Full live_results for {league} took {t2_stop - t2_start}")


live_results()
