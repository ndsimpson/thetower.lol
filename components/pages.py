import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dtower.thetower.settings")
django.setup()

import streamlit as st

from dtower.tourney_results.constants import Graph, Options

st.set_page_config(
    page_title="The Tower tourney results",
    layout="centered",
    initial_sidebar_state="auto",
    menu_items={
        "Get Help": "https://discord.com/channels/850137217828388904/1299774861908115559",
    },
)

options = Options(links_toggle=True, default_graph=Graph.last_16.value, average_foreground=True)

if st.session_state.get("options") is None:
    st.session_state.options = options

overview_pages = [
    st.Page("overview.py", title="Overview", icon="🏠", url_path="overview"),
    st.Page("about.py", title="About", icon="👴", url_path="about"),
]

live_pages = [
    st.Page("live_score.py", title="Live Scores", icon="⏱️", url_path="live"),
    st.Page("live_progress.py", title="Live Progress (testing)", icon="🧪", url_path="progress"),
    st.Page("live_results.py", title="Live Results (testing)", icon="🧪", url_path="liveresults"),
    st.Page("bracket_analysis.py", title="Live Bracket Analysis (testing)", icon="🧪", url_path="livebracket"),
    st.Page("placement_analysis.py", title="Live Placement Analysis (testing)", icon="🧪", url_path="placement"),
    st.Page("live_bracket.py", title="Bracket view", icon="🔠", url_path="bracket"),
]

individual_pages = [
    st.Page("player.py", title="Individual Player Stats", icon="⛹️", url_path="player"),
    st.Page("comparison.py", title="Player Comparison", icon="🔃", url_path="comparison"),
    st.Page("namechangers.py", title="Namechangers", icon="💩", url_path="namechangers"),
]

league_pages = [
    st.Page("results.py", title="League Standings", icon="🐳", url_path="results"),
    # st.Page(partial(compute_results, league=champ, options=options), title="Results Champions", icon="🏆", url_path="champ"),
    # st.Page(partial(compute_results, league=plat, options=options), title="Results Platinum", icon="📉", url_path="platinum"),
    # st.Page(partial(compute_results, league=gold, options=options), title="Results Gold", icon="🥇", url_path="gold"),
    # st.Page(partial(compute_results, league=silver, options=options), title="Results Silver", icon="🥈", url_path="silver"),
    # st.Page(partial(compute_results, league=copper, options=options), title="Results Copper", icon="🥉", url_path="copper"),
    st.Page("counts.py", title="Wave cutoff (counts)", icon="🐈", url_path="counts"),
    st.Page("winners.py", title="Winners", icon="🔥", url_path="winners"),
]

deprecated_pages = [
    st.Page("top_scores.py", title="Top Scores", icon="🤑", url_path="top"),
    st.Page("breakdown.py", title="Breakdown", icon="🪁", url_path="breakdown"),
    st.Page("various.py", title="Relics and Avatars", icon="👽", url_path="relics"),
    st.Page("fallen_defenders.py", title="Fallen defenders", icon="🪦", url_path="fallen"),
]

page_dict = {}
page_dict["Overview"] = overview_pages
page_dict["Live Standings"] = live_pages
page_dict["Individual Data"] = individual_pages
page_dict["League Data"] = league_pages
page_dict["Deprecated"] = deprecated_pages

pg = st.navigation(page_dict)
pg.run()
