import time
from typing import Any, Dict

import streamlit as st

from thetower.backend.tourney_results.shun_config import (
    get_cache_status,
    include_shun_enabled_for,
    include_shun_invalidate,
    read_mapping_from_disk,
)

PAGE_KEYS = {
    "live_bracket",
    "comparison",
    "live_placement",
    "live_score",
    "live_results",
    "live_progress",
    "live_bracket_analysis",
    "reposition",
    "create_tourney_rows",
}


def _resolve_for_page(cache: Dict[str, Any], page: str) -> Any:
    if not cache or not cache.get("cached"):
        return "<not cached>"
    mapping = cache.get("mapping") or {}
    return bool(mapping.get("pages", {}).get(page, mapping.get("default", False)))


def main() -> None:
    st.title("Shun configuration — Admin")

    st.markdown(
        """
        This page shows the on-disk `include_shun.json` mapping and the current
        in-process cache that the application uses to answer `include_shun` queries.

        Notes:
        - The cache is stored at module-level in the running process (app-level).
          That means it's shared by all Streamlit sessions handled by the same
          process. In multi-process deployments each process will have its own cache.
        - You can invalidate the in-process cache (so the next access reloads from disk),
          or force a reload.
        """
    )

    # Read authoritative disk mapping (no cache side-effects)
    file_mapping = read_mapping_from_disk()

    # Show cache status
    cache_status = get_cache_status()
    st.subheader("In-process cache status")
    col1, col2 = st.columns([2, 1])
    with col1:
        st.write("Cached:", cache_status.get("cached"))
        expiry = cache_status.get("expiry")
        ttl = cache_status.get("ttl_remaining")
        if cache_status.get("cached"):
            st.write(f"Expires at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expiry))} (in {ttl:.0f}s)")
        else:
            st.write("No mapping currently cached")

    with col2:
        if st.button("Invalidate cache"):
            include_shun_invalidate()
            # Try the supported rerun API, fall back to toggling query params
            try:
                st.experimental_rerun()
            except Exception:
                # some Streamlit builds don't expose experimental_rerun; update a
                # query param to force a rerun instead
                try:
                    # Use the stable query params API instead of the deprecated
                    # experimental_get_query_params(). `st.query_params` is a
                    # mapping of str->[str], so convert to a plain dict for
                    # manipulation.
                    params = dict(st.query_params) if st.query_params is not None else {}
                    params["_shun_admin_r"] = [str(time.time())]
                    st.experimental_set_query_params(**params)
                except Exception:
                    # Last resort: no-op; the page will reflect new state on next run
                    pass

        if st.button("Reload from disk"):
            # Force reload by invalidating and issuing a fresh include_shun call
            include_shun_invalidate()
            # call include_shun_enabled_for for a common page to populate cache
            include_shun_enabled_for("live_bracket")
            try:
                st.experimental_rerun()
            except Exception:
                try:
                    params = dict(st.query_params) if st.query_params is not None else {}
                    params["_shun_admin_r"] = [str(time.time())]
                    st.experimental_set_query_params(**params)
                except Exception:
                    pass

    # Build page list
    pages = set(file_mapping.get("pages", {}).keys()) | PAGE_KEYS

    rows = []
    for p in sorted(pages):
        file_val = bool(file_mapping.get("pages", {}).get(p, file_mapping.get("default", False)))
        cache_val = _resolve_for_page(cache_status, p)
        # Also compute the effective resolved value (what include_shun_enabled_for returns)
        resolved = include_shun_enabled_for(p)

        rows.append({"page": p, "file_value": file_val, "cache_value": cache_val, "resolved": resolved})

    st.subheader("Per-page values")
    st.table(rows)

    st.markdown(
        """
        Explanation:
        - file_value: value from the on-disk `include_shun.json` (or the legacy `include_shun` marker).
        - cache_value: value taken from the in-process cached mapping ("<not cached>" if no cache present).
        - resolved: the value returned by the public API `include_shun_enabled_for(page)`; this
          reflects the cache if present or loads the mapping on-demand.
        """
    )


if __name__ == "__main__":
    main()
