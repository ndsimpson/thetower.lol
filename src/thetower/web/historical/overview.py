import functools


@functools.lru_cache(maxsize=2)
def _legend_avg_wave_leaderboard_cached(patch_id, legend_str, hidden_features):
    from collections import defaultdict

    from thetower.backend.tourney_results.data import get_player_id_lookup

    # Re-import models inside cache for safety
    from thetower.backend.tourney_results.models import PatchNew, TourneyResult, TourneyRow

    latest_patch = PatchNew.objects.get(id=patch_id)
    public = {"public": True} if not hidden_features else {}
    tourney_results = TourneyResult.objects.filter(date__gte=latest_patch.start_date, date__lte=latest_patch.end_date, league=legend_str, **public)
    if not tourney_results.exists():
        return []
    rows = TourneyRow.objects.filter(result__in=tourney_results)
    if not rows.exists():
        return []
    player_waves = defaultdict(list)
    for row in rows:
        player_waves[row.player_id].append(row.wave)
    # Count number of unique tournaments in this patch (Legend)
    tourney_ids = set(rows.values_list("result_id", flat=True))
    max_tourneys = len(tourney_ids)
    # Only include players who played in all tournaments
    player_avg = [(pid, sum(waves) / len(waves), len(waves)) for pid, waves in player_waves.items() if len(waves) == max_tourneys]
    if not player_avg:
        return []
    player_avg.sort(key=lambda x: (x[1], x[2]), reverse=True)
    lookup = get_player_id_lookup()
    return player_avg[:5], lookup


import time


def render_legend_avg_wave_leaderboard():
    """Render leaderboard for highest average waves in Legend league for the latest patch (min 2 tourneys)."""
    try:
        latest_patch = PatchNew.objects.order_by("-start_date").first()
        if not latest_patch:
            return
        hidden_features = bool(os.environ.get("HIDDEN_FEATURES"))
        # Use patch id and legend string for cache key
        cache_key = (latest_patch.id, legend, hidden_features)
        # 1 hour cache: forcibly clear if older than 1 hour
        now = int(time.time())
        if not hasattr(render_legend_avg_wave_leaderboard, "_last_cache_time"):
            render_legend_avg_wave_leaderboard._last_cache_time = 0
        if now - render_legend_avg_wave_leaderboard._last_cache_time > 3600:
            _legend_avg_wave_leaderboard_cached.cache_clear()
            render_legend_avg_wave_leaderboard._last_cache_time = now
        result = _legend_avg_wave_leaderboard_cached(*cache_key)
        if not result or not result[0]:
            return
        top_5, lookup = result
        medals = ["🥇", "🥈", "🥉"]
        colors = [
            "linear-gradient(135deg, #FFD700 0%, #FFA500 100%)",
            "linear-gradient(135deg, #C0C0C0 0%, #A8A8A8 100%)",
            "linear-gradient(135deg, #CD7F32 0%, #B87333 100%)",
            "#2a2a3e",
        ]
        pills = []
        for idx in range(min(3, len(top_5))):
            pid, avg_wave, tournaments = top_5[idx]
            real_name = lookup.get(pid, f"Player {pid}")
            real_name = real_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            medal = medals[idx]
            bg_color = colors[idx]
            pill = f"""<div style="flex: 1; min-width: 110px; text-align: center; padding: 0.75rem; background: {bg_color}; border-radius: 7px; box-shadow: 0 1.5px 3px rgba(0,0,0,0.2);">
    <div style="font-size: 1.5rem;">{medal}</div>
    <div style="font-size: 0.85rem; font-weight: bold; color: #1a1a1a; margin: 0.375rem 0;">{real_name}</div>
    <div style="font-size: 0.8rem; font-weight: bold; color: #333333;">{avg_wave:.1f} avg wave<br><span style=\"font-size:0.8em; color:{bg_color}\">({tournaments} tournaments)</span></div>
</div>"""
            pills.append(pill)
        if len(top_5) >= 4:
            remaining_html = ""
            for idx in range(3, min(5, len(top_5))):
                pid, avg_wave, tournaments = top_5[idx]
                real_name = lookup.get(pid, f"Player {pid}")
                real_name = real_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                position_num = idx + 1
                remaining_html += f"""<div style="margin-bottom: 0.5rem; padding: 0.5rem; background: rgba(255,255,255,0.05); border-radius: 5px;">
    <div style="font-size: 0.85rem; color: #e0e0e0;"><strong>#{position_num}</strong> {real_name}</div>
    <div style="font-size: 0.75rem; color: #a0a0a0;">{avg_wave:.1f} avg wave <span style=\"font-size:0.8em; color:#888\">({tournaments} tournaments)</span></div>
</div>"""
            fourth_pill = f"""<div style="flex: 1; min-width: 110px; padding: 0.75rem; background: {colors[3]}; border-radius: 7px; box-shadow: 0 1.5px 3px rgba(0,0,0,0.2);">
    {remaining_html}
</div>"""
            pills.append(fourth_pill)
        pills_html = "".join(pills)
        leaderboard_html = f"""
<div style="margin: 1.5rem 0; padding: 1.125rem; background: #1e1e2e; border-radius: 8px; box-shadow: 0 3px 4.5px rgba(0,0,0,0.3);">
    <h3 style="margin: 0 0 0.75rem 0; color: #667eea; text-align: center; font-size: 1.1rem;">📈 Legend - Highest Average Wave (Latest Patch, min 2 tournaments)</h3>
    <div style="display: flex; justify-content: space-around; flex-wrap: wrap; gap: 0.75rem;">
        {pills_html}
    </div>
</div>
"""
        st.html(leaderboard_html)
    except Exception:
        pass


import os
from collections import Counter
from pathlib import Path

import streamlit as st

from thetower.backend.tourney_results.constants import Graph, Options, leagues, legend
from thetower.backend.tourney_results.data import get_player_id_lookup, get_tourneys
from thetower.backend.tourney_results.models import PatchNew, TourneyResult, TourneyRow
from thetower.web.util import escape_df_html

# Try to import towerbcs for tournament countdown
try:
    from towerbcs import TournamentPredictor, predict_future_tournament

    TOWERBCS_AVAILABLE = True
except ImportError:
    TOWERBCS_AVAILABLE = False
    TournamentPredictor = None
    predict_future_tournament = None


def format_time_until(days_until, tourney_date):
    """Format the countdown to the next tournament."""
    if days_until < 0:
        return "Tournament has passed"
    elif days_until == 0:
        return "Today!"
    elif days_until == 1:
        return "Tomorrow!"
    else:
        return f"{days_until} days"


def render_tournament_countdown():
    """Render the tournament countdown header."""
    if not TOWERBCS_AVAILABLE:
        st.info("ℹ️ Tournament countdown unavailable - towerbcs package not installed")
        return

    try:
        tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info()
        time_str = format_time_until(days_until, tourney_date)

        # Get battle conditions for Legend league if available
        bcs_html = ""
        if days_until <= 1:  # Only show BCs within 24 hours
            try:
                legend_bcs = predict_future_tournament(tourney_id, legend)
                if legend_bcs:
                    bc_names = " • ".join(legend_bcs)
                    bcs_html = f"""
<div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid rgba(255,255,255,0.2);">
    <div style="font-size: 0.85rem; color: #f0f0f0; margin-bottom: 0.3rem;">Legend Battle Conditions:</div>
    <div style="font-size: 0.95rem; color: white; font-weight: 500;">{bc_names}</div>
    <a href="bcs" target="_self" style="font-size: 0.8rem; color: #ffd700; text-decoration: underline; margin-top: 0.3rem; display: inline-block;">View all league BCs →</a>
</div>"""
            except Exception:
                pass  # Silently fail BC prediction

        countdown_html = f"""
<div style="text-align: center; padding: 1.5rem; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 10px; margin-bottom: 2rem; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
    <h2 style="margin: 0; color: white; font-size: 1.8rem;">⏰ Next Tournament</h2>
    <p style="margin: 0.5rem 0 0 0; color: white; font-size: 1.3rem; font-weight: bold;">{tourney_date.strftime('%A, %B %d, %Y')}</p>
    <p style="margin: 0.3rem 0 0 0; color: #f0f0f0; font-size: 1.1rem;">{time_str}</p>
    {bcs_html}
</div>
"""
        st.html(countdown_html)

    except Exception as e:
        st.warning(f"⚠️ Could not load tournament countdown: {str(e)}")


def render_patch_leaderboard():
    """Render the patch leaderboard showing top 5 players with most first place finishes in current patch."""
    try:
        # Get latest patch
        latest_patch = PatchNew.objects.order_by("-start_date").first()
        if not latest_patch:
            return

        public = {"public": True} if not os.environ.get("HIDDEN_FEATURES") else {}

        # Get all tournament results for this patch
        tourney_results = TourneyResult.objects.filter(date__gte=latest_patch.start_date, date__lte=latest_patch.end_date, **public)

        if not tourney_results.exists():
            return

        # Get first and second place finishes for tiebreaking
        first_place_rows = TourneyRow.objects.filter(result__in=tourney_results, position=1).values_list("player_id", flat=True)
        second_place_rows = TourneyRow.objects.filter(result__in=tourney_results, position=2).values_list("player_id", flat=True)

        if not first_place_rows:
            return

        # Count wins and second places per player
        player_first = Counter(first_place_rows)
        player_second = Counter(second_place_rows)

        # Create list of (player_id, first_place_count, second_place_count)
        player_stats = [(player_id, first_count, player_second.get(player_id, 0)) for player_id, first_count in player_first.items()]

        # Sort by first place wins descending, then by second place wins descending
        player_stats.sort(key=lambda x: (x[1], x[2]), reverse=True)

        if not player_stats:
            return

        # Get top 5
        top_5 = player_stats[:5]

        # Get real names
        lookup = get_player_id_lookup()

        # Build HTML for the leaderboard
        medals = ["🥇", "🥈", "🥉"]
        colors = [
            "linear-gradient(135deg, #FFD700 0%, #FFA500 100%)",
            "linear-gradient(135deg, #C0C0C0 0%, #A8A8A8 100%)",
            "linear-gradient(135deg, #CD7F32 0%, #B87333 100%)",
            "#2a2a3e",  # 4th+ place color
        ]

        # Build pills for top 3
        pills = []
        for idx in range(min(3, len(top_5))):
            player_id, first_wins, second_wins = top_5[idx]
            real_name = lookup.get(player_id, f"Player {player_id}")
            real_name = real_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            medal = medals[idx]
            bg_color = colors[idx]

            wins_text = f"{first_wins} Win{'s' if first_wins > 1 else ''}"
            if second_wins > 0:
                wins_text += f" (+{second_wins} 2nd)"

            pill = f"""<div style="flex: 1; min-width: 110px; text-align: center; padding: 0.75rem; background: {bg_color}; border-radius: 7px; box-shadow: 0 1.5px 3px rgba(0,0,0,0.2);">
    <div style="font-size: 1.5rem;">{medal}</div>
    <div style="font-size: 0.85rem; font-weight: bold; color: #1a1a1a; margin: 0.375rem 0;">{real_name}</div>
    <div style="font-size: 0.8rem; font-weight: bold; color: #333333;">{wins_text}</div>
</div>"""
            pills.append(pill)

        # Build 4th pill for 4th and 5th place (if they exist)
        if len(top_5) >= 4:
            remaining_html = ""
            for idx in range(3, min(5, len(top_5))):
                player_id, first_wins, second_wins = top_5[idx]
                real_name = lookup.get(player_id, f"Player {player_id}")
                real_name = real_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

                wins_text = f"{first_wins} Win{'s' if first_wins > 1 else ''}"
                if second_wins > 0:
                    wins_text += f" (+{second_wins} 2nd)"

                position_num = idx + 1
                remaining_html += f"""<div style="margin-bottom: 0.5rem; padding: 0.5rem; background: rgba(255,255,255,0.05); border-radius: 5px;">
    <div style="font-size: 0.85rem; color: #e0e0e0;"><strong>#{position_num}</strong> {real_name}</div>
    <div style="font-size: 0.75rem; color: #a0a0a0;">{wins_text}</div>
</div>"""

            fourth_pill = f"""<div style="flex: 1; min-width: 110px; padding: 0.75rem; background: {colors[3]}; border-radius: 7px; box-shadow: 0 1.5px 3px rgba(0,0,0,0.2);">
    {remaining_html}
</div>"""
            pills.append(fourth_pill)

        # Join all pills together
        pills_html = "".join(pills)

        # Build complete leaderboard HTML
        leaderboard_html = f"""
<div style="margin: 1.5rem 0; padding: 1.125rem; background: #1e1e2e; border-radius: 8px; box-shadow: 0 3px 4.5px rgba(0,0,0,0.3);">
    <h3 style="margin: 0 0 0.75rem 0; color: #667eea; text-align: center; font-size: 1.1rem;">🏆 Patch {latest_patch} Leaderboard - Most First Place Finishes</h3>
    <div style="display: flex; justify-content: space-around; flex-wrap: wrap; gap: 0.75rem;">
        {pills_html}
    </div>
</div>
"""

        st.html(leaderboard_html)

    except Exception:
        # Silently fail if leaderboard can't be generated
        pass


def render_league_standings(league, last_tourney_date, is_legend=False):
    """Render standings for a single league in 4-pill layout."""
    public = {"public": True} if not os.environ.get("HIDDEN_FEATURES") else {}
    limit = 6 if is_legend else 4

    qs = TourneyResult.objects.filter(league=league, date=last_tourney_date, **public)
    if not qs:
        return None

    df = get_tourneys(qs, offset=0, limit=limit)
    if df.empty:
        return None

    # Escape HTML in name columns
    df = escape_df_html(df, ["real_name", "tourney_name"])

    # Create league header (no date)
    league_query = league.replace(" ", "%20")
    league_header = f"""
<div style="margin-top: 2rem; margin-bottom: 0.75rem;">
    <h2 style="color: #667eea; border-bottom: 2px solid #667eea; padding-bottom: 0.5rem; font-size: 1.3rem;">
        <a href="results?league={league_query}" target="_self" style="text-decoration: none; color: #667eea;">{league} 🔗</a>
    </h2>
</div>
"""
    st.markdown(league_header, unsafe_allow_html=True)

    # Build HTML for pills
    medals = ["🥇", "🥈", "🥉"]
    colors = [
        "linear-gradient(135deg, #FFD700 0%, #FFA500 100%)",
        "linear-gradient(135deg, #C0C0C0 0%, #A8A8A8 100%)",
        "linear-gradient(135deg, #CD7F32 0%, #B87333 100%)",
        "#2a2a3e",
    ]

    max_display = 5 if is_legend else 3

    # Build pills for top 3
    pills = []
    for idx in range(min(3, len(df))):
        row = df.iloc[idx]
        name = row["real_name"]
        wave = row["wave"]
        position = idx + 1

        medal = medals[idx]
        bg_color = colors[idx]

        pill = f"""<div style="flex: 1; min-width: 110px; text-align: center; padding: 0.75rem; background: {bg_color}; border-radius: 7px; box-shadow: 0 1.5px 3px rgba(0,0,0,0.2);">
    <div style="font-size: 1.5rem;">{medal}</div>
    <div style="font-size: 0.85rem; font-weight: bold; color: #1a1a1a; margin: 0.375rem 0;">{name}</div>
    <div style="font-size: 0.8rem; font-weight: bold; color: #333333;">Wave {wave}</div>
</div>"""
        pills.append(pill)

    # Build 4th pill for remaining players (if they exist)
    if len(df) >= 4:
        remaining_html = ""
        for idx in range(3, min(max_display, len(df))):
            row = df.iloc[idx]
            name = row["real_name"]
            wave = row["wave"]
            position = idx + 1

            remaining_html += f"""<div style="margin-bottom: 0.5rem; padding: 0.5rem; background: rgba(255,255,255,0.05); border-radius: 5px;">
    <div style="font-size: 0.85rem; color: #e0e0e0;"><strong>#{position}</strong> {name}</div>
    <div style="font-size: 0.75rem; color: #a0a0a0;">Wave {wave}</div>
</div>"""

        fourth_pill = f"""<div style="flex: 1; min-width: 110px; padding: 0.75rem; background: {colors[3]}; border-radius: 7px; box-shadow: 0 1.5px 3px rgba(0,0,0,0.2);">
    {remaining_html}
</div>"""
        pills.append(fourth_pill)

    # Join all pills
    pills_html = "".join(pills)

    # Build complete HTML
    standings_html = f"""
<div style="display: flex; justify-content: space-around; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 1rem;">
    {pills_html}
</div>
"""

    st.html(standings_html)


def compute_overview(options: Options):
    print("overview")

    # Load custom CSS
    css_path = Path(__file__).parent.parent / "static" / "styles" / "style.css"
    with open(css_path, "r") as infile:
        st.write(f"<style>{infile.read()}</style>", unsafe_allow_html=True)
    # Display logo header with top anchor
    logo_path = Path(__file__).parent.parent / "static" / "images" / "TT.png"
    if logo_path.exists():
        # Center the logo image and add top anchor
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown("<a id='top'></a>", unsafe_allow_html=True)
            st.image(str(logo_path), width=400, use_container_width=False)

    # Render tournament countdown
    render_tournament_countdown()
    # Add jump link above patch leaderboard
    st.markdown(
        """
<div style='text-align: center; margin: 0.5rem 0 1.2rem 0;'>
    <a href='#league-results' style='font-size: 0.92rem; color: #ffd700; text-decoration: underline;'>↓ Jump to League Results</a>
</div>
""",
        unsafe_allow_html=True,
    )
    # Render patch leaderboard
    render_patch_leaderboard()

    # Get latest tournament date
    public = {"public": True} if not os.environ.get("HIDDEN_FEATURES") else {}
    last_tourney = TourneyResult.objects.filter(**public).latest("date")
    last_tourney_date = last_tourney.date

    # Show overview text if available
    if overview := TourneyResult.objects.filter(league=legend, **public).latest("date").overview:
        st.markdown(overview, unsafe_allow_html=True)

    # Render Legend average wave leaderboard (latest patch)
    render_legend_avg_wave_leaderboard()
    # Add divider for results date
    results_date_str = last_tourney_date.strftime("%A, %B %d, %Y") if hasattr(last_tourney_date, "strftime") else str(last_tourney_date)
    st.markdown(
        f"""
<a id=\"league-results\"></a>
<div style='margin: 2.5rem 0 1.5rem 0; text-align: center;'>
    <span style='font-size: 1.25rem; color: #667eea; font-weight: 600;'>Results for {results_date_str}</span>
</div>
""",
        unsafe_allow_html=True,
    )
    # Render Legend standings first (top 5)
    render_league_standings(legend, last_tourney_date, is_legend=True)

    # Render Champion through Copper leagues in two columns
    other_leagues = leagues[1:]
    # Add a spacer column for more gap
    col1, spacer, col2 = st.columns([1, 0.15, 1])
    # Render leagues in original order, alternating columns
    for idx, league in enumerate(other_leagues):
        with col1 if idx % 2 == 0 else col2:
            render_league_standings(league, last_tourney_date, is_legend=False)


options = Options(links_toggle=False, default_graph=Graph.last_16.value, average_foreground=True)
compute_overview(options)
st.markdown(
    """
<div style='text-align: center; margin: 2.5rem 0 1.5rem 0;'>
    <a href='#top' style='font-size: 0.92rem; color: #667eea; text-decoration: underline;'>↑ Back to Top</a>
</div>
""",
    unsafe_allow_html=True,
)
