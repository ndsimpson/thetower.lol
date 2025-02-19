"""Display tournament battle conditions in Streamlit interface."""

from datetime import timedelta
import pandas as pd
import streamlit as st
from dtower.tourney_results.constants import leagues
from towerbcs.towerbcs import predict_future_tournament, TournamentPredictor

tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info()

if days_until > 1:
    st.markdown(f"# Next Tournament is on {tourney_date}")
    st.markdown(f"Too soon to display upcoming battle conditions. Try back on {tourney_date - timedelta(days=1)}.")
    st.stop()

st.markdown(f"# Tournament {'is today!' if days_until == 0 else f'is on {tourney_date}'}")

st.dataframe(
    pd.DataFrame.from_dict(
        {league: predict_future_tournament(tourney_id, league) for league in leagues},
        orient='index'
    ).transpose().fillna(''),
    use_container_width=True
)
