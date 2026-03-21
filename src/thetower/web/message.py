"""
Maintenance mode page for the Tower web interface.

Displayed in place of all normal pages when maintenance mode is active on the public site.
"""

import streamlit as st

from thetower.web.maintenance import DEFAULT_HEADER, DEFAULT_MESSAGE, get_maintenance_state

state = get_maintenance_state()
header = state.get("header") or DEFAULT_HEADER
message = state.get("message") or DEFAULT_MESSAGE

st.markdown(f"## 🔧 {header}")
st.markdown(message)
