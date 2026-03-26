import statistics
from collections import defaultdict

import pandas as pd
import streamlit as st

from thetower.backend.tourney_results.constants import leagues
from thetower.backend.tourney_results.models import TourneyResult, TourneyRow


def compute_median_history():
    st.header("Median Wave History")
    st.caption(
        "Median (and mean) wave across all brackets in a league for each tournament. "
        "Useful for tracking overall difficulty and wave inflation over time."
    )

    col1, col2, col3 = st.columns([2, 2, 2])

    num_tourneys = col1.slider(
        "Number of recent tournaments",
        min_value=5,
        max_value=30,
        value=12,
    )
    stat_choice = col2.radio("Statistic", ["Median", "Mean", "Both"], horizontal=True)
    selected_leagues = st.multiselect(
        "Leagues",
        leagues,
        default=["Legend", "Champion", "Platinum", "Gold"],
        help="Select leagues to display",
    )

    if not selected_leagues:
        st.warning("Please select at least one league.")
        return

    # Collect the last num_tourneys results per league and build a lookup from result_id to (league, date)
    league_results: dict[str, list] = {}
    result_to_meta: dict[int, tuple[str, object]] = {}  # result_id -> (league, date)
    all_result_ids: list[int] = []

    for league in selected_leagues:
        results = list(TourneyResult.objects.filter(league=league, public=True).order_by("-date")[:num_tourneys])
        league_results[league] = results
        for r in results:
            result_to_meta[r.id] = (league, r.date)
            all_result_ids.append(r.id)

    # Fetch all waves in one query
    rows = TourneyRow.objects.filter(result__in=all_result_ids, position__gt=0).values("result_id", "wave")

    waves_by_result: dict[int, list[int]] = defaultdict(list)
    for row in rows:
        waves_by_result[row["result_id"]].append(row["wave"])

    # Build BC tooltip lookup: result_id -> short BC string
    result_bcs: dict[int, str] = {}
    for league in selected_leagues:
        for r in league_results[league]:
            bcs = r.conditions.all()
            result_bcs[r.id] = " / ".join(bc.shortcut for bc in bcs) if bcs else ""

    # Determine all unique dates (used as columns)
    all_dates = sorted(
        {r.date for results in league_results.values() for r in results},
        reverse=True,
    )
    date_strs = [str(d) for d in all_dates]

    # Build per-date BC tooltip (may differ by league but we use any non-empty one)
    date_to_bc: dict[str, str] = {}
    for league in selected_leagues:
        for r in league_results[league]:
            key = str(r.date)
            if key not in date_to_bc or not date_to_bc[key]:
                date_to_bc[key] = result_bcs[r.id]

    # Build rows: one per league (two if both median + mean)
    table_rows = []
    for league in selected_leagues:
        date_to_result = {str(r.date): r for r in league_results[league]}

        if stat_choice == "Both":
            row_med: dict[str, object] = {"League": f"{league} (median)"}
            row_mean: dict[str, object] = {"League": f"{league} (mean)"}
            for d in date_strs:
                result = date_to_result.get(d)
                if result is None:
                    row_med[d] = None
                    row_mean[d] = None
                else:
                    waves = waves_by_result.get(result.id, [])
                    if not waves:
                        row_med[d] = None
                        row_mean[d] = None
                    else:
                        row_med[d] = round(statistics.median(waves), 1)
                        row_mean[d] = round(statistics.mean(waves), 0)
            table_rows.append(row_med)
            table_rows.append(row_mean)
        else:
            row: dict[str, object] = {"League": league}
            for d in date_strs:
                result = date_to_result.get(d)
                if result is None:
                    row[d] = None
                else:
                    waves = waves_by_result.get(result.id, [])
                    if not waves:
                        row[d] = None
                    elif stat_choice == "Median":
                        row[d] = round(statistics.median(waves), 1)
                    else:
                        row[d] = round(statistics.mean(waves), 0)
            table_rows.append(row)

    # Build flipped table: dates as rows, leagues (or "League (stat)") as columns.
    # BCs vary per league, so only show the BCs column when exactly one league is selected;
    # with multiple leagues the column would be ambiguous.
    show_bcs = len(selected_leagues) == 1

    league_cols = [row["League"] for row in table_rows]
    flipped_rows = []
    for d in date_strs:
        flipped_row: dict[str, object] = {"Date": d}
        if show_bcs:
            bc = date_to_bc.get(d, "")
            flipped_row["BCs"] = bc if bc else "–"
        for row in table_rows:
            flipped_row[row["League"]] = row.get(d)
        flipped_rows.append(flipped_row)

    df = pd.DataFrame(flipped_rows)

    col_config: dict = {
        "Date": st.column_config.TextColumn("Date", width="small"),
    }
    if show_bcs:
        col_config["BCs"] = st.column_config.TextColumn("BCs", width="small")
    else:
        st.caption("ℹ️ Battle conditions differ per league and are hidden when multiple leagues are shown.")
    for col in league_cols:
        col_config[col] = st.column_config.NumberColumn(col, format="%.1f")

    row_height = (len(flipped_rows) + 1) * 35 + 10

    st.dataframe(df, hide_index=True, use_container_width=True, height=row_height, column_config=col_config)


compute_median_history()
