import streamlit as st
from components.util import get_league_selection, get_options


def setup_common_ui():
    """Setup common UI elements across live views"""
    options = get_options(links=False)

    league = get_league_selection(options)

    with st.sidebar:
        is_mobile = st.session_state.get("mobile_view", False)
        st.checkbox("Mobile view", value=is_mobile, key="mobile_view")

    return options, league, is_mobile