import streamlit as st

from dtower.tourney_results.bc import predict_future_tournament, get_next_tournament

result = get_next_tournament()


if result['days_until'] > 1:
    st.markdown(f"# Next Tournament is on {result['next_date']}")
    st.markdown("Too soon to display upcoming battle conditions.  Try back tomorrow.")
    st.stop()
elif result['days_until'] == 1:
    st.markdown(f"# Next Tournament is on {result['next_date']}")
else:
    st.markdown("# Tournament is today!")

for league in ["Legend", "Champion"]:
    st.markdown(f"## The {league} BCs are:")
    battleconditions = predict_future_tournament(result['next_id'], league)
    for battlecondition in battleconditions:
        st.markdown(f"* {battlecondition}")
