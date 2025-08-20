import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dtower.thetower.settings")
django.setup()


from itertools import groupby

import streamlit as st
from django.db.models import Q

from components.util import add_player_id, add_to_comparison
from dtower.sus.models import PlayerId, SusPerson
from dtower.tourney_results.constants import how_many_results_public_site
from dtower.tourney_results.models import TourneyRow


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
    hex_chars = sum(1 for c in search_term.upper() if c in 'ABCDEF0123456789')
    is_player_id_search = (
        len(search_term.replace(' ', '')) >= 12 and  # Player IDs are long
        hex_chars / len(search_term.replace(' ', '')) > 0.7  # Mostly hex characters
    )

    if is_player_id_search:
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
            .values_list("player_id", "nickname")
            .order_by("player_id")
            .distinct()[:page * 3]  # Get more to account for grouping
        )

        # Group by player_id and combine nicknames
        grouped_results = []
        for player_id, group in groupby(sorted(results), lambda x: x[0]):
            nicknames = list(set(nickname for _, nickname in group))
            grouped_results.append((player_id, ", ".join(nicknames[:page])))
            if len(grouped_results) >= page:
                break

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
                PlayerId.objects.filter(
                    base_condition &
                    Q(primary=True) &
                    ~Q(id__in=excluded_player_ids)
                )
                .order_by("player_id")
                .values_list("id", "player__name")[:page]
            )
            all_results.extend(priority1_results)

        # Priority 2: Nicknames starting with first fragment (if we need more results)
        existing_player_ids = {player_id for player_id, _ in all_results}
        if len(all_results) < page and primary_fragment:
            base_condition = Q(nickname__istartswith=primary_fragment)
            for fragment in additional_fragments:
                base_condition &= Q(nickname__icontains=fragment)

            priority2_results = list(
                TourneyRow.objects.filter(
                    base_condition &
                    ~Q(player_id__in=existing_player_ids) &
                    ~Q(player_id__in=excluded_player_ids) &
                    Q(position__lte=how_many_results_public_site)
                )
                .distinct()
                .order_by("player_id")
                .values_list("player_id", "nickname")[:page - len(all_results)]
            )
            all_results.extend(priority2_results)
            existing_player_ids.update(player_id for player_id, _ in priority2_results)

        # Priority 3: Primary names containing all fragments (if we need more results)
        if len(all_results) < page and fragments:
            base_condition = Q()
            for fragment in fragments:
                base_condition &= Q(player__name__icontains=fragment)

            priority3_results = list(
                PlayerId.objects.filter(
                    base_condition &
                    Q(primary=True) &
                    ~Q(id__in=existing_player_ids) &
                    ~Q(id__in=excluded_player_ids)
                )
                .order_by("player_id")
                .values_list("id", "player__name")[:page - len(all_results)]
            )
            all_results.extend(priority3_results)
            existing_player_ids.update(player_id for player_id, _ in priority3_results)

        # Priority 4: Nicknames containing all fragments (if we need more results)
        if len(all_results) < page and fragments:
            base_condition = Q()
            for fragment in fragments:
                base_condition &= Q(nickname__icontains=fragment)

            priority4_results = list(
                TourneyRow.objects.filter(
                    base_condition &
                    ~Q(player_id__in=existing_player_ids) &
                    ~Q(player_id__in=excluded_player_ids) &
                    Q(position__lte=how_many_results_public_site)
                )
                .distinct()
                .order_by("player_id")
                .values_list("player_id", "nickname")[:page - len(all_results)]
            )
            all_results.extend(priority4_results)

        return all_results[:page]


def compute_search(player=False, comparison=False):
    with open("style.css", "r") as infile:
        table_styling = f"<style>{infile.read()}</style>"

    st.write(table_styling, unsafe_allow_html=True)

    # Get all suspicious or banned player IDs
    hidden_features = os.environ.get("HIDDEN_FEATURES")

    if not hidden_features:
        excluded_player_ids = list(
            SusPerson.objects.filter(
                Q(sus=True) | Q(soft_banned=True) | Q(banned=True)
            ).values_list('player_id', flat=True)
        )
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
        # nickname_ids is a list of (player_id, nickname) tuples
        # Group by player_id in case there are duplicates
        for player_id, group in groupby(nickname_ids, lambda x: x[0]):
            nicknames_list = [nickname for _, nickname in group]
            datum = {
                "player_id": player_id,
                "nicknames": ", ".join(set(nicknames_list)),
                "how_many_results": len(nicknames_list)
            }
            data_to_be_shown.append(datum)

    for datum in data_to_be_shown:
        nickname_col, player_id_col, button_col = st.columns([1, 1, 1])
        nickname_col.write(datum["nicknames"])
        player_id_col.write(datum["player_id"])

        if player:
            button_col.button("See player page", on_click=add_player_id, args=(datum["player_id"],), key=f'{datum["player_id"]}{datum["nicknames"]}but')

        if comparison:
            button_col.button("Add to comparison", on_click=add_to_comparison, args=(datum["player_id"], datum["nicknames"]), key=f'{datum["player_id"]}comp')

    if not data_to_be_shown:
        st.info("No results found")

    return data_to_be_shown


if __name__ == "__main__":
    compute_search()
