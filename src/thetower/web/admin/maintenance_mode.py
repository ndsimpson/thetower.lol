"""
Maintenance Mode admin page for the Tower hidden site.

Allows enabling/disabling maintenance mode and editing the message shown to public visitors.
State is persisted to the Django data directory so it survives site updates.
"""

import streamlit as st

from thetower.web.maintenance import DEFAULT_HEADER, DEFAULT_MESSAGE, get_maintenance_state, set_maintenance_state


def main() -> None:
    st.title("🛠️ Maintenance Mode")
    st.markdown(
        "Controls the maintenance mode displayed to public site visitors. "
        "When enabled, **all public pages show the maintenance message** instead of their normal content. "
        "The hidden admin site is unaffected."
    )

    state = get_maintenance_state()

    st.divider()

    status_label = "🔴 ENABLED" if state["enabled"] else "🟢 Disabled"
    st.metric("Current Status", status_label)

    st.divider()

    new_enabled = st.toggle("Enable Maintenance Mode", value=state["enabled"])

    new_header = st.text_input(
        "Maintenance Page Header",
        value=state.get("header") or DEFAULT_HEADER,
        help="Heading displayed at the top of the maintenance page.",
    )

    new_message = st.text_area(
        "Maintenance Message",
        value=state.get("message") or DEFAULT_MESSAGE,
        height=120,
        help="Displayed to visitors on all public pages while maintenance mode is active.",
    )

    if st.button("💾 Save Changes", type="primary", use_container_width=True):
        try:
            set_maintenance_state(
                enabled=new_enabled,
                header=new_header.strip() or DEFAULT_HEADER,
                message=new_message.strip() or DEFAULT_MESSAGE,
            )
            st.success("Maintenance mode settings saved successfully.")
            st.rerun()
        except Exception as exc:
            st.error(f"Failed to save maintenance mode settings: {exc}")


main()
