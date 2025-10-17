"""Battle Conditions Mismatch Analysis - Admin Page

Compare stored battle conditions against predicted values for all tournaments.
Shows mismatches between database values and calculated predictions.
"""

# Django setup
import os

import django
import pandas as pd
import streamlit as st

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.backend.towerdb.settings")
django.setup()

from thetower.backend.tourney_results.models import TourneyResult

# Try to import towerbcs with graceful fallback
try:
    from towerbcs import TournamentPredictor, predict_future_tournament
    TOWERBCS_AVAILABLE = True
except ImportError:
    TOWERBCS_AVAILABLE = False
    predict_future_tournament = None
    TournamentPredictor = None


st.markdown("# Battle Conditions Mismatch Analysis")


if not TOWERBCS_AVAILABLE:
    st.error("⚠️ TowerBCS package not available")
    st.markdown(
        """
    The `towerbcs` package is not installed. To use battle conditions prediction, run the update script: `python src/thetower/scripts/install_towerbcs.py`
    """
    )
    st.stop()


# Function to get tourney_id for a given date
# This is a placeholder - need to implement proper tourney_id calculation
def get_tourney_id_for_date(date):
    # Placeholder: assume tourney_id starts from some base
    # Need to implement proper logic based on how tourney_ids are assigned
    base_date = pd.Timestamp('2022-01-01')  # Example base date
    days_diff = (date - base_date).days
    # Assume tournaments every 3 days or whatever the schedule is
    # This needs to be adjusted based on actual tournament scheduling
    tourney_id = days_diff // 3 + 1  # Placeholder calculation
    return tourney_id


# Get all tournaments
tournaments = TourneyResult.objects.filter(public=True).order_by('date', 'league')

mismatches = []
total_checked = 0

with st.spinner("Analyzing battle conditions..."):
    for tournament in tournaments:
        total_checked += 1

        # Get stored conditions
        stored_bcs = set(tournament.conditions.values_list('shortcut', flat=True))

        # Predict conditions
        try:
            tourney_id = get_tourney_id_for_date(tournament.date)
            predicted_bcs = set(predict_future_tournament(tourney_id, tournament.league))
        except Exception as e:
            st.warning(f"Failed to predict BCs for {tournament}: {e}")
            continue

        # Check for mismatch
        if stored_bcs != predicted_bcs:
            mismatch_info = {
                'tournament_id': tournament.id,
                'date': tournament.date,
                'league': tournament.league,
                'stored_bcs': ', '.join(sorted(stored_bcs)),
                'predicted_bcs': ', '.join(sorted(predicted_bcs)),
                'missing_in_db': ', '.join(sorted(predicted_bcs - stored_bcs)),
                'extra_in_db': ', '.join(sorted(stored_bcs - predicted_bcs))
            }
            mismatches.append(mismatch_info)

st.markdown("## Analysis Complete")
st.markdown(f"Checked {total_checked} tournaments")
st.markdown(f"Found {len(mismatches)} mismatches")

if mismatches:
    st.markdown("## Mismatches Found")

    # Convert to DataFrame for better display
    df = pd.DataFrame(mismatches)

    # Display summary stats
    st.markdown("### Summary Statistics")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Mismatches", len(mismatches))
    with col2:
        st.metric("Tournaments Affected", df['tournament_id'].nunique())
    with col3:
        leagues_affected = df['league'].nunique()
        st.metric("Leagues Affected", leagues_affected)

    # Display detailed table
    st.markdown("### Detailed Mismatch Table")
    st.dataframe(
        df[['tournament_id', 'date', 'league', 'stored_bcs', 'predicted_bcs', 'missing_in_db', 'extra_in_db']],
        use_container_width=True,
        column_config={
            'tournament_id': st.column_config.NumberColumn("Tournament ID", width="small"),
            'date': st.column_config.DateColumn("Date", width="medium"),
            'league': st.column_config.TextColumn("League", width="medium"),
            'stored_bcs': st.column_config.TextColumn("Stored BCs", width="large"),
            'predicted_bcs': st.column_config.TextColumn("Predicted BCs", width="large"),
            'missing_in_db': st.column_config.TextColumn("Missing in DB", width="large"),
            'extra_in_db': st.column_config.TextColumn("Extra in DB", width="large"),
        }
    )

    # Group by league for additional insights
    st.markdown("### Mismatches by League")
    league_summary = df.groupby('league').size().reset_index(name='mismatch_count')
    st.bar_chart(league_summary.set_index('league'))

else:
    st.success("✅ No battle condition mismatches found!")

st.markdown("---")
st.markdown("*Note: Tourney ID calculation is currently a placeholder and may need adjustment based on actual tournament scheduling.*")
st.markdown("*Note: Tourney ID calculation is currently a placeholder and may need adjustment based on actual tournament scheduling.*")
