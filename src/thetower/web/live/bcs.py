"""Display tournament battle conditions in Streamlit interface."""

import datetime
import logging
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
    st.markdown("The `towerbcs` package is not installed. To use battle conditions prediction, install it with: `pip install -e /path/to/towerbcs`")
    st.stop()

tourney_id, tourney_date, days_until, _ = TournamentPredictor.get_tournament_info()

# BCs are revealed this many days before the tournament
BC_DAYS_EARLY = 1

st.markdown("# Battle Conditions")
if days_until > BC_DAYS_EARLY:
    st.markdown(f"## Next Tournament is on {tourney_date}")
    st.markdown("Battle conditions will be available in:")

    @st.fragment(run_every=1)
    def _countdown():
        bc_dt = datetime.datetime.combine(tourney_date, datetime.time.min, tzinfo=datetime.timezone.utc) - datetime.timedelta(days=BC_DAYS_EARLY)
        remaining = bc_dt - datetime.datetime.now(datetime.timezone.utc)
        total_seconds = int(remaining.total_seconds())
        if total_seconds <= 0:
            st.rerun()
            return
        days_left = total_seconds // 86400
        hours_left = (total_seconds % 86400) // 3600
        minutes_left = (total_seconds % 3600) // 60
        seconds_left = total_seconds % 60
        cols = st.columns(4)
        cols[0].metric("Days", days_left)
        cols[1].metric("Hours", hours_left)
        cols[2].metric("Minutes", minutes_left)
        cols[3].metric("Seconds", seconds_left)

    _countdown()
    st.stop()

st.markdown(f"## Tournament {'is today!' if days_until == 0 else f'is on {tourney_date}'}")

st.dataframe(
    pd.DataFrame.from_dict({league: predict_future_tournament(tourney_id, league) for league in leagues}, orient="index").transpose().fillna(""),
    width="stretch",
)

# Log execution time at the end of the file
t2_stop = perf_counter()
logging.info(f"Full battle conditions analysis took {t2_stop - t2_start}")
