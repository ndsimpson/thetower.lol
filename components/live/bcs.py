"""Display tournament battle conditions in Streamlit interface."""

import streamlit as st
from datetime import timedelta
from dtower.tourney_results.bc import predict_future_tournament, get_tournament_info


tourney_id, tourney_date, days_until = get_tournament_info()

if days_until > 1:
    st.markdown(f"# Next Tournament is on {tourney_date}")
    st.markdown(f"Too soon to display upcoming battle conditions. Try back on {tourney_date - timedelta(days=1)}.")
    st.stop()
elif days_until == 1:
    st.markdown(f"# Next Tournament is on {tourney_date}")
else:
    st.markdown("# Tournament is today!")

for league in ["Legend", "Champion", "Platinum"]:
    st.header(f"The {league} BCs are:", divider=True)
    # st.markdown(f"## The {league} BCs are:")
    battle_conditions = predict_future_tournament(tourney_id, league)
    for condition in battle_conditions:
        st.markdown(f"* {condition}")
