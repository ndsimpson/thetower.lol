"""
Site Settings admin page for the Tower hidden site.

Covers site-wide operational settings:
  - Maintenance mode (enable/disable, header, message)
  - Overview cache (status and manual regeneration)
"""

import streamlit as st

from thetower.backend.tourney_results.overview_cache import read_overview_cache, regenerate_overview_cache
from thetower.web.maintenance import DEFAULT_HEADER, DEFAULT_MESSAGE, get_maintenance_state, set_maintenance_state


def _render_maintenance_section() -> None:
    st.subheader("🛠️ Maintenance Mode")
    st.markdown(
        "Controls the maintenance mode displayed to public site visitors. "
        "When enabled, **all public pages show the maintenance message** instead of their normal content. "
        "The hidden admin site is unaffected."
    )

    state = get_maintenance_state()

    status_label = "🔴 ENABLED" if state["enabled"] else "🟢 Disabled"
    st.metric("Current Status", status_label)

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

    if st.button("💾 Save Maintenance Settings", type="primary", width="stretch"):
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


def _render_overview_cache_section() -> None:
    st.subheader("📊 Overview Page Cache")
    st.markdown(
        "The public Overview page is served from a pre-computed cache to avoid slow DB queries on every render. "
        "The cache is regenerated automatically after each tournament import. "
        "Use the button below to force a refresh — e.g. after marking a player as sus/banned."
    )

    cache = read_overview_cache()

    col1, col2 = st.columns(2)
    with col1:
        if cache:
            generated_at = cache.get("generated_at", "unknown")
            last_tourney = cache.get("last_tourney_date", "unknown")
            st.metric("Cache Status", "✅ Present")
            st.caption(f"Generated at: **{generated_at}**")
            st.caption(f"Covers tourney: **{last_tourney}**")
        else:
            st.metric("Cache Status", "⚠️ Missing")
            st.caption("No cache file found — the overview page will show an unavailable message to visitors.")

    with col2:
        if st.button("🔄 Regenerate Overview Cache", type="primary", width="stretch"):
            with st.spinner("Regenerating overview cache…"):
                try:
                    result = regenerate_overview_cache()
                    if result:
                        st.success(f"Cache regenerated. Covers tourney: **{result.get('last_tourney_date', '?')}**")
                    else:
                        st.error("Regeneration returned no data — check logs.")
                except Exception as exc:
                    st.error(f"Failed to regenerate cache: {exc}")
            st.rerun()


def main() -> None:
    st.title("⚙️ Site Settings")

    st.divider()
    _render_maintenance_section()

    st.divider()
    _render_overview_cache_section()


main()
