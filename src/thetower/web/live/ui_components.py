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


def setup_common_ui(show_league_selector: bool = True):
    """Setup common UI elements across live views

    Args:
        show_league_selector: Whether to render the league selector. Defaults to True.
    """
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
        # Either show the selector or use existing/default league without rendering
        if show_league_selector:
            league = get_league_selection(options)
        else:
            league = st.session_state.get("selected_league", "Legend")

    with st.sidebar:
        is_mobile = st.session_state.get("mobile_view", False)
        st.checkbox("Mobile view", value=is_mobile, key="mobile_view")

    return options, league, is_mobile
