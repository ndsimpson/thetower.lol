"""Display tournament battle conditions in Streamlit interface."""

import logging
from datetime import timedelta
from time import perf_counter

import pandas as pd
import streamlit as st

from thetower.backend.tourney_results.constants import leagues

# Try to import towerbcs with graceful fallback
try:
    from towerbcs import TournamentPredictor, predict_future_tournament

    TOWERBCS_AVAILABLE = True
except ImportError:
    TOWERBCS_AVAILABLE = False
    predict_future_tournament = None
    TournamentPredictor = None

logging.info("Starting battle conditions analysis")
t2_start = perf_counter()

# Check if towerbcs is available
if not TOWERBCS_AVAILABLE:
    st.markdown("# Battle Conditions")
    st.error("⚠️ Battle Conditions module not available")
    st.markdown(
        """
    The `towerbcs` package is not installed. To use battle conditions prediction, run the update script: `python src/thetower/scripts/install_towerbcs.py`
    """
    )
    st.stop()

tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info()

st.markdown("# Battle Conditions")
if days_until > 1:
    st.markdown(f"## Next Tournament is on {tourney_date}")
    st.markdown(f"Too soon to display upcoming battle conditions. Try back on {tourney_date - timedelta(days=1)}.")
    st.stop()

st.markdown(f"## Tournament {'is today!' if days_until == 0 else f'is on {tourney_date}'}")

st.dataframe(
    pd.DataFrame.from_dict({league: predict_future_tournament(tourney_id, league) for league in leagues}, orient="index").transpose().fillna(""),
    use_container_width=True,
)

# Log execution time at the end of the file
t2_stop = perf_counter()
logging.info(f"Full battle conditions analysis took {t2_stop - t2_start}")
