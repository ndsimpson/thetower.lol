# Standard library imports
import os
from pathlib import Path

# Third-party imports
import django
import streamlit as st

from thetower.backend.tourney_results.constants import Graph, Options
from thetower.web.util import makeitrain

# Django setup
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.backend.towerdb.settings")
django.setup()

# Local imports

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

# Add supporter code message at the very top of sidebar first
with st.sidebar:
    st.markdown(
        """<div style="text-align:center; margin-bottom:1em; font-size:0.9em; padding:0.5em; background-color:rgba(30,144,255,0.1); border-radius:0.5em; border:1px solid rgba(30,144,255,0.3);">
            <b>🐟 Support the fishy!</b><br>
            Use code <span style="color:#cd4b3d; font-weight:bold;">thedisasterfish</span> in the <a href="https://store.techtreegames.com/thetower/">TechTree Store</a>
        </div>""",
        unsafe_allow_html=True,
    )

options = Options(links_toggle=True, default_graph=Graph.last_16.value, average_foreground=True)

if st.session_state.get("options") is None:
    st.session_state.options = options

overview_pages = [
    st.Page("historical/overview.py", title="Overview", icon="🏠", url_path="overview"),
    st.Page("historical/about.py", title="About", icon="👴", url_path="about"),
]

live_pages = [
    # st.Page("live/live_score.py", title="Live Scores", icon="⏱️", url_path="live"),
    st.Page("live/bcs.py", title="Battle Conditions", icon="🔮", url_path="bcs"),
    st.Page("live/live_progress.py", title="Live Progress", icon="⏱️", url_path="liveprogress"),
    st.Page("live/live_results.py", title="Live Results", icon="📋", url_path="liveresults"),
    st.Page("live/live_bracket_analysis.py", title="Live Bracket Analysis", icon="📉", url_path="livebracketanalysis"),
    # st.Page("live/live_placement_analysis.py", title="Live Placement Analysis", icon="📈", url_path="liveplacement"),
    st.Page("live/live_bracket.py", title="Live Bracket view", icon="🔠", url_path="livebracketview"),
]

individual_pages = [
    st.Page("historical/player.py", title="Individual Player Stats", icon="⛹️", url_path="player"),
    st.Page("historical/comparison.py", title="Player Comparison", icon="🔃", url_path="comparison"),
    st.Page("historical/namechangers.py", title="Namechangers", icon="💩", url_path="namechangers"),
]

league_pages = [
    st.Page("historical/results.py", title="League Standings", icon="🐳", url_path="results"),
    # st.Page(partial(compute_results, league=champ, options=options), title="Results Champions", icon="🏆", url_path="champ"),
    # st.Page(partial(compute_results, league=plat, options=options), title="Results Platinum", icon="📉", url_path="platinum"),
    # st.Page(partial(compute_results, league=gold, options=options), title="Results Gold", icon="🥇", url_path="gold"),
    # st.Page(partial(compute_results, league=silver, options=options), title="Results Silver", icon="🥈", url_path="silver"),
    # st.Page(partial(compute_results, league=copper, options=options), title="Results Copper", icon="🥉", url_path="copper"),
    st.Page("historical/counts.py", title="Wave cutoff (counts)", icon="🐈", url_path="counts"),
    st.Page("historical/winners.py", title="Winners", icon="🔥", url_path="winners"),
]

deprecated_pages = [
    st.Page("historical/deprecated/top_scores.py", title="Top Scores", icon="🤑", url_path="top"),
    st.Page("historical/deprecated/breakdown.py", title="Breakdown", icon="🪁", url_path="breakdown"),
    st.Page("historical/deprecated/various.py", title="Relics and Avatars", icon="👽", url_path="relics"),
    st.Page("historical/deprecated/fallen_defenders.py", title="Fallen defenders", icon="🪦", url_path="fallen"),
]

# Hidden admin pages (only available when HIDDEN_FEATURES env var is set)
admin_pages = []
if hidden_features:
    admin_pages = [
        st.Page("admin/duplicate_tournaments.py", title="Duplicate Tournament Entries", icon="🔍", url_path="duplicates"),
        st.Page("admin/service_status.py", title="Service Status", icon="🔧", url_path="services"),
        st.Page("admin/codebase_status.py", title="Codebase Status", icon="📦", url_path="codebase"),
        st.Page("admin/sus_moderation.py", title="Sus Moderation Records", icon="🚫", url_path="susmoderation"),
        st.Page("admin/multiple_moderation.py", title="Multiple Moderation Records", icon="⚠️", url_path="multiplemoderation"),
        st.Page("admin/bc_mismatch.py", title="BC Mismatch Analysis", icon="⚖️", url_path="bcmismatch"),
    ]


page_dict = {}
page_dict["Overview"] = overview_pages
page_dict["Live Standings"] = live_pages
page_dict["Individual Data"] = individual_pages
page_dict["League Data"] = league_pages
page_dict["Deprecated"] = deprecated_pages

# Add admin pages only for hidden features
if hidden_features and admin_pages:
    page_dict["Admin"] = admin_pages

pg = st.navigation(page_dict)

# Get absolute paths for logo images
current_dir = Path(__file__).parent
logo_path = current_dir / "static" / "images" / "TT.png"
icon_path = current_dir / "static" / "images" / "TTIcon.png"

st.logo(str(logo_path), size="large", icon_image=str(icon_path))

# Only show toggle and make it rain if there are active rain periods
from thetower.backend.tourney_results.models import RainPeriod

active_period = RainPeriod.get_active_period()

if active_period:
    with st.sidebar:
        if "rain" not in st.session_state:
            st.session_state.rain = True
        rainenabled = st.toggle("Make it rain?", key="rain")

    if rainenabled:
        makeitrain()

st.html(
    """
<style>
    .stMainBlockContainer {
        max-width:60rem;
    }
</style>
"""
)

pg.run()
