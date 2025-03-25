import pandas as pd
import streamlit as st

from components.util import get_league_selection, get_options

from dtower.tourney_results.models import TourneyResult, TourneyRow


def compute_counts():
    options = get_options(links=False)
    league = get_league_selection(options)

    st.header(f"Wave cutoff required for top X in {league}")

    # Define cutoff ranges
    cutoff_ranges = {
        # "Top 200": {
        #     "counts": [1, 10, 25, 50, 100, 200],
        #     "limit": 300
        # },
        "Top 1000": {
            "counts": [1, 10, 25, 50, 100, 200, 400, 600, 800, 1000],
            "limit": 1100
        },
        "Top 2500": {
            "counts": [1, 100, 250, 500, 750, 1000, 1500, 2000, 2500],
            "limit": 2600
        },
        "Top 5000": {
            "counts": [1, 100, 500, 1000, 2000, 2500, 3000, 4000, 5000],
            "limit": 5100
        }
    }

    # Create columns for controls
    range_col, bc_col, slid_col, _ = st.columns([1, 1, 2, 2])

    selected_range = range_col.selectbox(
        "Range",
        options=list(cutoff_ranges.keys()),
        help="Select the range of positions to display"
    )

    counts_for = cutoff_ranges[selected_range]["counts"]
    limit = cutoff_ranges[selected_range]["limit"]

    bc_display = bc_col.selectbox(
        "Battle Conditions",
        ["Hide", "Short", "Full"],
        help="How to display battle conditions"
    )

    champ_results = TourneyResult.objects.filter(league=league, public=True).order_by("-date")

    per_page = 22
    pages = len(champ_results) // per_page

    if pages == 1:
        per_page = 10
        pages = 2

    which_page = slid_col.slider("Select page", 1, pages, 1)

    champ_results = champ_results[(which_page - 1) * per_page : which_page * per_page]

    rows = TourneyRow.objects.filter(result__in=champ_results, position__lt=limit, position__gt=0).order_by("-wave").values("result_id", "wave")

    row_height = (per_page + 1) * 35 + 2

    results = []

    for tourney in champ_results:
        waves = [row["wave"] for row in rows if row["result_id"] == tourney.id]
        result = {"date": tourney.date}

        # Handle BC display based on selection
        if bc_display != "Hide":
            bcs = tourney.conditions.all()
            if bc_display == "Short":
                result["bcs"] = "/".join([bc.shortcut for bc in bcs])
            else:  # "Full"
                result["bcs"] = "/".join([bc.name for bc in bcs])

        result |= {f"Top {count_for}": waves[count_for - 1] if count_for <= len(waves) else 0
                   for count_for in counts_for}
        results.append(result)

    to_be_displayed = pd.DataFrame(results).sort_values("date", ascending=False).reset_index(drop=True)
    st.dataframe(to_be_displayed, use_container_width=True, height=row_height, hide_index=True)


compute_counts()
