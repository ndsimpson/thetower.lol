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

home_info_pages = [
    st.Page("historical/overview.py", title="Overview", icon="🏠", url_path="overview"),
    st.Page("historical/about.py", title="About", icon="👴", url_path="about"),
]

current_tournament_pages = [
    st.Page("live/bcs.py", title="Battle Conditions", icon="🔮", url_path="bcs"),
    st.Page("live/live_progress.py", title="Live Progress", icon="⏱️", url_path="liveprogress"),
    st.Page("live/live_results.py", title="Live Results", icon="📋", url_path="liveresults"),
    st.Page("live/live_bracket.py", title="Live Bracket View", icon="🔠", url_path="livebracketview"),
]

live_analytics_pages = [
    st.Page("live/live_bracket_analysis.py", title="Live Bracket Analysis", icon="📉", url_path="livebracketanalysis"),
    st.Page("live/live_placement_analysis.py", title="Live Placement Analysis", icon="📈", url_path="liveplacement"),
]

player_statistics_pages = [
    st.Page("historical/player.py", title="Individual Player Stats", icon="⛹️", url_path="player"),
    st.Page("historical/comparison.py", title="Player Comparison", icon="🔃", url_path="comparison"),
    st.Page("historical/namechangers.py", title="Namechangers", icon="💩", url_path="namechangers"),
]

historical_data_pages = [
    st.Page("historical/results.py", title="League Standings", icon="🐳", url_path="results"),
    st.Page("historical/counts.py", title="Wave Cutoffs", icon="🐈", url_path="counts"),
    st.Page("historical/winners.py", title="Winners", icon="🔥", url_path="winners"),
]

archive_pages = [
    st.Page("historical/deprecated/top_scores.py", title="Top Scores", icon="🤑", url_path="top"),
    st.Page("historical/deprecated/breakdown.py", title="Breakdown", icon="🪁", url_path="breakdown"),
    st.Page("historical/deprecated/various.py", title="Relics and Avatars", icon="👽", url_path="relics"),
    st.Page("historical/deprecated/fallen_defenders.py", title="Fallen Defenders", icon="🪦", url_path="fallen"),
]

# Hidden admin pages (only available when HIDDEN_FEATURES env var is set)
admin_system_health_pages = []
admin_moderation_pages = []

if hidden_features:
    admin_system_health_pages = [
        st.Page("admin/service_status.py", title="Service Status", icon="🔧", url_path="services"),
        st.Page("admin/codebase_status.py", title="Codebase Status", icon="📦", url_path="codebase"),
    ]

    admin_moderation_pages = [
        st.Page("admin/shun_admin.py", title="Shun List Management", icon="🛑", url_path="shunadmin"),
        st.Page("admin/sus_moderation.py", title="Sus Moderation", icon="🚫", url_path="susmoderation"),
        st.Page("admin/multiple_moderation.py", title="Multiple Moderation", icon="⚠️", url_path="multiplemoderation"),
        st.Page("admin/league_progression.py", title="League Progression", icon="📈", url_path="leagueprogression"),
        st.Page("admin/duplicate_tournaments.py", title="Duplicate Tournaments", icon="🔍", url_path="duplicates"),
        st.Page("admin/bc_mismatch.py", title="BC Mismatch Analysis", icon="⚖️", url_path="bcmismatch"),
    ]


page_dict = {}
page_dict["Home & Info"] = home_info_pages
page_dict["Current Tournament"] = current_tournament_pages
page_dict["Live Analytics"] = live_analytics_pages
page_dict["Player Statistics"] = player_statistics_pages
page_dict["Historical Data"] = historical_data_pages
page_dict["Archive"] = archive_pages

# Add admin pages only for hidden features
if hidden_features:
    if admin_system_health_pages:
        page_dict["Admin - System Health"] = admin_system_health_pages
    if admin_moderation_pages:
        page_dict["Admin - Moderation"] = admin_moderation_pages

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
