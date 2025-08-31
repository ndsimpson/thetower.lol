import streamlit as st

from thetower.backend.tourney_results.constants import leagues
from thetower.backend.tourney_results.tourney_utils import check_live_entry
from thetower.web.util import get_league_selection, get_options


def get_league_for_player(player_id: str) -> str:
    """Find which league a player is participating in."""
    for league in leagues:
        if check_live_entry(league, player_id):
            return league
    return None


def setup_common_ui():
    """Setup common UI elements across live views"""
    options = get_options(links=False)

    # Check if we have a player_id in query params
    if player_id := options.current_player_id:
        # Get league directly without showing selector
        league = get_league_for_player(player_id)
        if league:
            st.session_state.selected_league = league
        else:
            st.session_state.selected_league = "Legend"  # Default if not found
    else:
        # Show league selector as normal
        league = get_league_selection(options)

    with st.sidebar:
        is_mobile = st.session_state.get("mobile_view", False)
        st.checkbox("Mobile view", value=is_mobile, key="mobile_view")

    return options, league, is_mobile
