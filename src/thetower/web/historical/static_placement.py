import statistics

import pandas as pd
import streamlit as st

from thetower.backend.tourney_results.constants import leagues
from thetower.backend.tourney_results.models import TourneyResult, TourneyRow


_DEFAULT_LEAGUES = ["Legend", "Champion", "Platinum", "Gold"]
_PLACES = list(range(1, 31))


def _compute_global_thresholds(result: TourneyResult) -> tuple[list[int | None], int, float, float]:
    """
    Return (thresholds, num_brackets, median, mean) for a given TourneyResult.

    threshold[k] is the lowest wave that earns global place k+1 (0-indexed list),
    i.e. sorted_waves[k * num_brackets - 1].
    """
    waves = list(TourneyRow.objects.filter(result=result, position__gt=0).values_list("wave", flat=True).order_by("-wave"))
    if not waves:
        return [None] * 30, 0, 0.0, 0.0

    # Number of brackets = count of position=1 rows
    num_brackets = TourneyRow.objects.filter(result=result, position=1).count()
    if num_brackets == 0:
        # Fall back to estimating from total count
        num_brackets = max(1, len(waves) // 30)

    thresholds: list[int | None] = []
    for place in _PLACES:
        idx = place * num_brackets - 1
        thresholds.append(waves[idx] if idx < len(waves) else waves[-1])

    med = statistics.median(waves)
    mean = statistics.mean(waves)
    return thresholds, num_brackets, med, mean


def compute_static_placement():
    st.header("Static Global Placement")
    st.caption(
        "What-if analysis: if all players in the league competed in a single pool (no brackets), "
        "what wave would you need to reach each place? "
        "Players are sorted globally and divided into groups of one-per-bracket to find each cutoff."
    )

    # Tournament selector
    col1, col2 = st.columns([2, 1])

    # Build list of available tournaments (use the latest shared date across leagues)
    all_results = TourneyResult.objects.filter(public=True).order_by("-date").values("date").distinct()
    available_dates = sorted({r["date"] for r in all_results}, reverse=True)

    if not available_dates:
        st.error("No historical tournament data available.")
        return

    date_options = [str(d) for d in available_dates]
    selected_date_str = col1.selectbox("Tournament date", date_options, index=0)
    selected_date = available_dates[date_options.index(selected_date_str)]

    selected_leagues = col2.multiselect(
        "Leagues",
        leagues,
        default=_DEFAULT_LEAGUES,
        help="Select leagues to display",
    )

    if not selected_leagues:
        st.warning("Please select at least one league.")
        return

    # Fetch results for selected date
    results_by_league: dict[str, TourneyResult | None] = {}
    for league in selected_leagues:
        qs = TourneyResult.objects.filter(league=league, date=selected_date, public=True)
        results_by_league[league] = qs.first()

    # Show summary stats (medal, mean) per league
    summary_cols = st.columns(len(selected_leagues))
    data: dict[str, list[int | None]] = {}
    league_stats: dict[str, tuple[int, float, float]] = {}

    for i, league in enumerate(selected_leagues):
        result = results_by_league[league]
        if result is None:
            with summary_cols[i]:
                st.metric(league, "No data")
            data[league] = [None] * 30
            continue

        thresholds, num_brackets, med, mean = _compute_global_thresholds(result)
        data[league] = thresholds
        league_stats[league] = (num_brackets, med, mean)

        bcs = result.conditions.all()
        bc_str = " / ".join(bc.shortcut for bc in bcs) if bcs else "–"
        with summary_cols[i]:
            st.metric(league, f"Median: {med:.0f}", help=f"BCs: {bc_str} · {num_brackets} brackets · Mean: {mean:.0f}")

    # Build the placement table
    table: dict[str, list] = {"Place": _PLACES}
    for league in selected_leagues:
        table[league] = data[league]

    df = pd.DataFrame(table)

    # Highlight the median row (place 15 in a 30-place bracket)
    def _highlight_median(row: pd.Series) -> list[str]:
        return ["font-weight: bold; background-color: rgba(100,100,200,0.15)" if row["Place"] == 15 else "" for _ in row]

    styled = df.style.apply(_highlight_median, axis=1)

    row_height = (len(_PLACES) + 1) * 35 + 10
    st.dataframe(styled, hide_index=True, width="stretch", height=row_height)

    # Explanation
    with st.expander("How to read this table"):
        st.markdown(
            """
**Place** — the global rank you would achieve if all players in the league were sorted by wave
and divided evenly into bracket-sized groups.

**Wave shown** — the lowest wave still earning that place (the cutoff). For example, the wave
at "Place 1" is the minimum wave in the top-B players, where B = number of brackets.

**Place 15 (bold)** — approximately the median bracket result: half the brackets would finish
above this wave, half below.

**Why it matters** — bracket luck is removed. If your wave is above the cutoff for your target
place, you would have reached it in a perfectly-fair draw; if it is below, you were relying on
a relatively weak bracket.
"""
        )


compute_static_placement()
