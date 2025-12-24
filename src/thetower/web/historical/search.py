import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.backend.towerdb.settings")
django.setup()


from itertools import groupby
from pathlib import Path

import streamlit as st
from django.db.models import Q

from thetower.backend.sus.models import PlayerId
from thetower.backend.tourney_results.constants import how_many_results_public_site
from thetower.backend.tourney_results.data import get_banned_ids, get_soft_banned_ids, get_sus_ids
from thetower.backend.tourney_results.models import TourneyRow
from thetower.web.util import add_player_id, add_to_comparison


def search_players_optimized(search_term, excluded_player_ids, page=20):
    """
    Optimized search function that combines all searches into unified queries.
    Returns results prioritized by relevance.
    """
    search_term = search_term.strip()
    if not search_term:
        return []

    fragments = [part.strip() for part in search_term.split()]

    # Check if this looks like a player ID search (mostly hex characters)
    hex_chars = sum(1 for c in search_term.upper() if c in "ABCDEF0123456789")
    is_player_id_search = (
        len(search_term.replace(" ", "")) >= 12  # Player IDs are long
        and hex_chars / len(search_term.replace(" ", "")) > 0.7  # Mostly hex characters
    )

    if is_player_id_search:
        # Normalize to uppercase to align with stored player IDs
        search_term = search_term.upper()
        fragments = [frag.upper() for frag in fragments]
        # Player ID search - unified query
        match_conditions = Q()
        for i, fragment in enumerate(fragments):
            if i == 0:
                match_conditions &= Q(player_id__istartswith=fragment)
            else:
                match_conditions &= Q(player_id__icontains=fragment)

        # Single query for player ID search with grouping
        results = list(
            TourneyRow.objects.filter(
                match_conditions,
                ~Q(player_id__in=excluded_player_ids),
                position__lte=how_many_results_public_site,
            )
            .values_list("player_id", "nickname", "result__league")
            .order_by("player_id")
            .distinct()[: page * 3]  # Get more to account for grouping
        )

        # Group by player_id and combine nicknames/leagues, then sort by player_id
        grouped_results = []
        for player_id, group in groupby(sorted(results), lambda x: x[0]):
            group_list = list(group)
            nicknames = list(set(nickname for _, nickname, _ in group_list))
            leagues = list(set(league for _, _, league in group_list if league))
            grouped_results.append((player_id, ", ".join(nicknames[:page]), ", ".join(sorted(leagues))))
            if len(grouped_results) >= page:
                break

        # Sort final results by player_id
        grouped_results.sort(key=lambda x: x[0])
        return grouped_results

    else:
        # Name search - unified query with prioritized results
        all_results = []

        # Build match conditions for name fragments
        primary_fragment = fragments[0] if fragments else ""
        additional_fragments = fragments[1:] if len(fragments) > 1 else []

        # Priority 1: Primary names starting with first fragment
        if primary_fragment:
            base_condition = Q(player__name__istartswith=primary_fragment)
            for fragment in additional_fragments:
                base_condition &= Q(player__name__icontains=fragment)

            priority1_results = list(
                PlayerId.objects.filter(base_condition & Q(primary=True) & ~Q(id__in=excluded_player_ids))
                .select_related("player")
                .order_by("player_id")
                .values_list("id", "player__name")[:page]
            )
            # Add league info by querying TourneyRow for each player
            priority1_with_league = []
            for player_id, name in priority1_results:
                leagues = list(
                    TourneyRow.objects.filter(player_id=player_id, position__lte=how_many_results_public_site)
                    .values_list("result__league", flat=True)
                    .distinct()[:5]
                )
                priority1_with_league.append((player_id, name, ", ".join(sorted(set(leagues)))))
            all_results.extend(priority1_with_league)

        # Priority 2: Nicknames starting with first fragment (if we need more results)
        existing_player_ids = {player_id for player_id, _, _ in all_results}
        if len(all_results) < page and primary_fragment:
            base_condition = Q(nickname__istartswith=primary_fragment)
            for fragment in additional_fragments:
                base_condition &= Q(nickname__icontains=fragment)

            priority2_results = list(
                TourneyRow.objects.filter(
                    base_condition
                    & ~Q(player_id__in=existing_player_ids)
                    & ~Q(player_id__in=excluded_player_ids)
                    & Q(position__lte=how_many_results_public_site)
                )
                .distinct()
                .order_by("player_id")
                .values_list("player_id", "nickname", "result__league")[: page - len(all_results)]
            )
            # Group by player_id to combine leagues
            priority2_with_league = []
            for player_id, group in groupby(priority2_results, lambda x: x[0]):
                group_list = list(group)
                nickname = group_list[0][1]
                leagues = list(set(league for _, _, league in group_list if league))
                priority2_with_league.append((player_id, nickname, ", ".join(sorted(leagues))))
            all_results.extend(priority2_with_league)
            existing_player_ids.update(player_id for player_id, _, _ in priority2_with_league)

        # Priority 3: Primary names containing all fragments (if we need more results)
        if len(all_results) < page and fragments:
            base_condition = Q()
            for fragment in fragments:
                base_condition &= Q(player__name__icontains=fragment)

            priority3_results = list(
                PlayerId.objects.filter(base_condition & Q(primary=True) & ~Q(id__in=existing_player_ids) & ~Q(id__in=excluded_player_ids))
                .select_related("player")
                .order_by("player_id")
                .values_list("id", "player__name")[: page - len(all_results)]
            )
            # Add league info
            priority3_with_league = []
            for player_id, name in priority3_results:
                leagues = list(
                    TourneyRow.objects.filter(player_id=player_id, position__lte=how_many_results_public_site)
                    .values_list("result__league", flat=True)
                    .distinct()[:5]
                )
                priority3_with_league.append((player_id, name, ", ".join(sorted(set(leagues)))))
            all_results.extend(priority3_with_league)
            existing_player_ids.update(player_id for player_id, _, _ in priority3_with_league)

        # Priority 4: Nicknames containing all fragments (if we need more results)
        if len(all_results) < page and fragments:
            base_condition = Q()
            for fragment in fragments:
                base_condition &= Q(nickname__icontains=fragment)

            priority4_results = list(
                TourneyRow.objects.filter(
                    base_condition
                    & ~Q(player_id__in=existing_player_ids)
                    & ~Q(player_id__in=excluded_player_ids)
                    & Q(position__lte=how_many_results_public_site)
                )
                .distinct()
                .order_by("player_id")
                .values_list("player_id", "nickname", "result__league")[: page - len(all_results)]
            )
            # Group by player_id to combine leagues
            priority4_with_league = []
            for player_id, group in groupby(priority4_results, lambda x: x[0]):
                group_list = list(group)
                nickname = group_list[0][1]
                leagues = list(set(league for _, _, league in group_list if league))
                priority4_with_league.append((player_id, nickname, ", ".join(sorted(leagues))))
            all_results.extend(priority4_with_league)

        # Sort name search results by nickname (case-insensitive)
        all_results.sort(key=lambda x: x[1].lower() if x[1] else "")
        return all_results[:page]


def compute_search(player=False, comparison=False):
    css_path = Path(__file__).parent.parent / "static" / "styles" / "style.css"
    with open(css_path, "r") as infile:
        table_styling = f"<style>{infile.read()}</style>"

    st.write(table_styling, unsafe_allow_html=True)

    # Get all suspicious or banned player IDs
    hidden_features = os.environ.get("HIDDEN_FEATURES")

    if not hidden_features:
        sus_ids = get_sus_ids()
        banned_ids = get_banned_ids()
        soft_banned_ids = get_soft_banned_ids()
        excluded_player_ids = list(sus_ids.union(banned_ids).union(soft_banned_ids))
    else:
        excluded_player_ids = []

    name_col, id_col = st.columns([1, 1])

    page = 20

    real_name_part = name_col.text_input("Enter part of the player name")
    player_id_part = id_col.text_input("Enter part of the player_id to be queried")

    # Determine which search to perform
    search_term = ""
    if real_name_part.strip():
        search_term = real_name_part.strip()
    elif player_id_part.strip():
        search_term = player_id_part.strip()

    # Debug output
    if search_term:
        st.write(f"🔍 Searching for: '{search_term}'")

    if search_term:
        # Use the optimized search function
        nickname_ids = search_players_optimized(search_term, excluded_player_ids, page)
        st.write(f"📊 Found {len(nickname_ids)} raw results")
    else:
        nickname_ids = []

    # Process results for display
    data_to_be_shown = []

    # Handle the optimized search results format
    if nickname_ids:
        # nickname_ids is a list of (player_id, nickname, leagues) tuples
        # Group by player_id in case there are duplicates
        for player_id, group in groupby(nickname_ids, lambda x: x[0]):
            group_list = list(group)
            nicknames_list = [nickname for _, nickname, _ in group_list]
            leagues_list = [leagues for _, _, leagues in group_list if leagues]
            datum = {
                "player_id": player_id,
                "nicknames": ", ".join(set(nicknames_list)),
                "leagues": ", ".join(set(leagues_list)) if leagues_list else "",
                "how_many_results": len(nicknames_list),
            }
            data_to_be_shown.append(datum)

    for datum in data_to_be_shown:
        nickname_col, player_id_col, league_col, button_col = st.columns([2, 1, 1, 1])
        nickname_col.write(datum["nicknames"])
        player_id_col.write(datum["player_id"])
        league_col.write(datum.get("leagues", ""))

        if player:
            button_col.button(
                "See player page", on_click=add_player_id, args=(datum["player_id"],), key=f'{datum["player_id"]}{datum["nicknames"]}but'
            )

        if comparison:
            button_col.button(
                "Add to comparison", on_click=add_to_comparison, args=(datum["player_id"], datum["nicknames"]), key=f'{datum["player_id"]}comp'
            )

    if not data_to_be_shown:
        st.info("No results found")

    return data_to_be_shown


if __name__ == "__main__":
    compute_search()
