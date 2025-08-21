import os

import streamlit as st
from pathlib import Path

from thetower.web.historical.results import Results
from thetower.backend.tourney_results.constants import Graph, Options, leagues, legend
# from thetower.backend.tourney_results.formatting import get_url
from thetower.backend.tourney_results.models import TourneyResult


def compute_overview(options: Options):
    print("overview")
    public = {"public": True} if not os.environ.get("HIDDEN_FEATURES") else {}
    last_tourney = TourneyResult.objects.filter(**public).latest("date")
    last_tourney_date = last_tourney.date

    css_path = Path(__file__).parent.parent / "static" / "styles" / "style.css"
    with open(css_path, "r") as infile:
        st.write(f"<style>{infile.read()}</style>", unsafe_allow_html=True)

    if overview := TourneyResult.objects.filter(league=legend, **public).latest("date").overview:
        st.markdown(overview, unsafe_allow_html=True)

    for league in leagues:
        # url = get_url(path=league.lower())
        # st.page_link("results.py", label=league)
        url = "results"
        st.write(f"<h2><a href='{url}' target='_self'>{league}</a></h2>", unsafe_allow_html=True)

        results = Results(options, league=league)
        to_be_displayed = results.prepare_data(current_page=1, step=11, date=last_tourney_date)

        if to_be_displayed is None:
            st.warning("Failed to display results, likely loss of data.")
            return None

        to_be_displayed_styler = results.regular_preparation(to_be_displayed)
        st.write(
            to_be_displayed_styler.hide(axis="index").to_html(escape=False),
            unsafe_allow_html=True,
        )


options = Options(links_toggle=False, default_graph=Graph.last_16.value, average_foreground=True)
compute_overview(options)
