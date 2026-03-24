import logging
import os
from time import perf_counter

import streamlit as st

from thetower.backend.tourney_results.constants import champ, how_many_results_public_site
from thetower.backend.tourney_results.data import get_tourneys
from thetower.backend.tourney_results.models import TourneyResult
from thetower.backend.tourney_results.shun_config import include_shun_enabled_for
from thetower.web.live.data_ops import format_time_ago, get_data_refresh_timestamp, get_processed_data, require_tournament_data
from thetower.web.live.ui_components import setup_common_ui


@require_tournament_data
def live_results():
    st.markdown("# Live Results")
    logging.info("Starting live results")
    t2_start = perf_counter()

    # Use common UI setup
    options, league, is_mobile = setup_common_ui()

    # Get data refresh timestamp
    refresh_timestamp = get_data_refresh_timestamp(league)
    if refresh_timestamp:
        time_ago = format_time_ago(refresh_timestamp)
        st.caption(f"📊 Data last refreshed: {time_ago} ({refresh_timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC)")
        # Indicate whether shunned players are included for this page (only on hidden site)
        hidden_features = os.environ.get("HIDDEN_FEATURES")
        if hidden_features:
            try:
                include_shun = include_shun_enabled_for("live_results")
                st.caption(f"🔍 Including shunned players: {'Yes' if include_shun else 'No'}")
            except Exception:
                pass
    else:
        st.caption("📊 Data refresh time: Unknown")

    # Get processed data
    include_shun = include_shun_enabled_for("live_results")
    df, tdf, ldf, _, _ = get_processed_data(league, include_shun)

    # Get reference data for joined calculation
    qs = TourneyResult.objects.filter(league=league, public=True).order_by("-date")
    if not qs:
        qs = TourneyResult.objects.filter(league=champ, public=True).order_by("-date")
    tourney = qs[0]
    pdf = get_tourneys([tourney])

    # Compute position deltas vs. the prior checkpoint snapshot
    sorted_datetimes = sorted(df["datetime"].unique(), reverse=True)
    prior_positions: dict[str, int] = {}
    if len(sorted_datetimes) >= 2:
        prior_moment = sorted_datetimes[1]
        prior_df = df[df["datetime"] == prior_moment].copy()
        prior_df = prior_df.sort_values("wave", ascending=False).reset_index(drop=True)
        p_current, p_borrow, p_last_wave = 0, 1, None
        p_pos_list: list[int] = []
        for wave in prior_df["wave"]:
            if p_last_wave is not None and wave == p_last_wave:
                p_borrow += 1
            else:
                p_current += p_borrow
                p_borrow = 1
            p_pos_list.append(p_current)
            p_last_wave = wave
        prior_df["_pos"] = p_pos_list
        prior_positions = dict(zip(prior_df["player_id"], prior_df["_pos"]))

    def _format_delta(current_pos: int, player_id: str) -> str:
        if player_id not in prior_positions:
            return "🆕"
        delta = prior_positions[player_id] - current_pos  # positive = moved up
        if delta > 0:
            return f"↑{delta}"
        if delta < 0:
            return f"↓{abs(delta)}"
        return "→"

    ldf_display = ldf.copy()
    ldf_display["±"] = [_format_delta(pos, pid) for pos, pid in zip(ldf_display.index, ldf_display["player_id"])]

    cols = st.columns([3, 2] if not is_mobile else [1])

    with cols[0]:
        st.write("Current result (ordered)")
        st.dataframe(ldf_display[["±", "name", "real_name", "wave"]][:how_many_results_public_site], height=700, width=400)

    canvas = cols[0] if is_mobile else cols[1]

    joined_ids = set(ldf.player_id.unique())
    pdf["joined"] = [player_id in joined_ids for player_id in pdf.id]
    pdf = pdf.rename(columns={"wave": "wave_last"})

    # Calculate positions with tie handling (same wave = same rank)
    pdf = pdf.sort_values("wave_last", ascending=False).reset_index(drop=True)
    positions = []
    current = 0
    borrow = 1
    last_wave = None
    for wave in pdf["wave_last"]:
        if last_wave is not None and wave == last_wave:
            borrow += 1
        else:
            current += borrow
            borrow = 1
        positions.append(current)
        last_wave = wave
    pdf.index = positions

    topx = canvas.selectbox("top x", [1000, 500, 200, 100, 50, 25], key=f"topx_{league}")
    need_to_get_in = canvas.checkbox("Filter by needing to get in", key=f"need_to_get_in_{league}")

    joined_sum = sum(pdf["joined"][:topx])
    joined_tot = len(pdf["joined"][:topx])
    not_joined_count = joined_tot - joined_sum

    if need_to_get_in:
        # Show count of players who need to join
        canvas.write(f"{not_joined_count} in the top {topx} need to join", unsafe_allow_html=True)
        # Filter to show only those who haven't joined from the top X
        top_x_df = pdf[:topx]
        display_df = top_x_df[~top_x_df["joined"]]
    else:
        # Show original message
        color = "green" if joined_sum / joined_tot >= 0.7 else "orange" if joined_sum / joined_tot >= 0.5 else "red"
        canvas.write(f"<font color='{color}'>{joined_sum}</font>/{topx} have already joined.", unsafe_allow_html=True)
        # Show all players in top X
        display_df = pdf[:topx]

    canvas.dataframe(display_df[["real_name", "wave_last", "joined"]], height=600, width=400)

    # Log execution time
    t2_stop = perf_counter()
    logging.info(f"Full live_results for {league} took {t2_stop - t2_start}")


live_results()
