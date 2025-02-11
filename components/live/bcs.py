import streamlit as st

from dtower.tourney_results.bc import predict_future_tournament, get_next_tournament_id

result = get_next_tournament_id()


if result['days_until'] > 1:
    st.write(f"<h2>Next Tournament is in {result['days_until']} days on {result['next_tournament_date']}</h2>", unsafe_allow_html=True)
    st.write("Too soon to display upcoming battle conditions.  Try back tomorrow.")
else:
    if result['days_until'] == 1:
        st.write(f"<h2>Next Tournament is in {result['days_until']} day on {result['next_tournament_date']}</h2>", unsafe_allow_html=True)
        st.write("The upcoming BCs are:", unsafe_allow_html=True)
    else:
        st.write(f"<h2>Tournament is today!</h2>", unsafe_allow_html=True)
        st.write("The BCs are:", unsafe_allow_html=True)
    battleconditions = predict_future_tournament(result['next_tournament_id'])
    for battlecondition in battleconditions:
        st.write(battlecondition)
