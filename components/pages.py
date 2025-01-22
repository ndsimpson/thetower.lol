import os
from datetime import date
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dtower.thetower.settings")
django.setup()

import streamlit as st
from streamlit_extras.app_logo import add_logo

from dtower.tourney_results.constants import Graph, Options
from components.util import makeitrain

hidden_features = os.environ.get("HIDDEN_FEATURES")

if hidden_features:
    page_title = "Admin: The Tower tourney results"
else:
    page_title = "The Tower tourney results"

st.set_page_config(
    page_title=page_title,
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
    # st.Page("live/live_score.py", title="Live Scores", icon="⏱️", url_path="live"),
    st.Page("live/live_progress.py", title="Live Progress", icon="⏱️", url_path="liveprogress"),
    st.Page("live/live_results.py", title="Live Results", icon="📋", url_path="liveresults"),
    st.Page("live/live_bracket_analysis.py", title="Live Bracket Analysis", icon="📉", url_path="livebracketanalysis"),
    st.Page("live/live_placement_analysis.py", title="Live Placement Analysis", icon="📈", url_path="liveplacement"),
    st.Page("live/live_bracket.py", title="Bracket view", icon="🔠", url_path="livebracketview"),
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

st.logo("components/static/TT.png", size="large", icon_image="components/static/TTIcon.png")
# add_logo("components/static/TT.png")

with st.sidebar:
    rainenabled = st.toggle("Make it rain?", value=True)

if rainenabled:
    makeitrain("❄️", date(2025, 1, 1), date(2025, 2, 1))
    makeitrain("💘", date(2025, 2, 13), date(2025, 2, 15))
    makeitrain("🍀", date(2025, 3, 16), date(2025, 3, 18))
    makeitrain("💧", date(2025, 4, 3), date(2025, 4, 5))


pg.run()
