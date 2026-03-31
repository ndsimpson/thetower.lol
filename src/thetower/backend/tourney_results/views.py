from django.http import JsonResponse

from ..sus.models import PlayerId
from .data import get_details, get_tourneys, how_many_results_public_site
from .models import TourneyResult, TourneyRow


def results_per_tourney(request, league, tourney_date):  # Unused with api disabled
    qs = TourneyResult.objects.filter(league=league.capitalize(), date=tourney_date, public=True)

    if not qs.exists():
        return JsonResponse({}, status=404)

    df = get_tourneys(qs, offset=0, limit=how_many_results_public_site)
    df["wave_role"] = df.wave_role.map(lambda x: x.wave_bottom)
    df["verified"] = df.verified.map(lambda x: int(bool(x)))

    response = [
        {
            "id": row.id,
            "position": row.position,
            "tourney_name": row.tourney_name,
            "real_name": row.real_name,
            "wave": row.wave,
            "avatar": row.avatar,
            "relic": row.relic,
            "date": row.date,
            "league": row.league,
            "verified": row.verified,
            "wave_role": row.wave_role,
            "patch": str(row.patch),
        }
        for _, row in df.iterrows()
    ]

    return JsonResponse(response, status=200, safe=False)


def results_per_user(request, player_id):  # Unused with api disabled
    player_ids = PlayerId.objects.filter(id=player_id).select_related("game_instance")
    how_many = int(request.GET.get("how_many", 1000))

    if player_ids:
        player_id = player_ids[0]
        # Get all PlayerIds for this specific game instance
        if player_id.game_instance:
            all_player_ids = PlayerId.objects.filter(game_instance=player_id.game_instance).values_list("id", flat=True)
        else:
            all_player_ids = [player_id.id]
        rows = (
            TourneyRow.objects.select_related("result")
            .filter(
                player_id__in=all_player_ids,
                result__public=True,
                position__gt=0,
            )
            .order_by("-result__date")[:how_many]
        )
    else:
        rows = (
            TourneyRow.objects.select_related("result")
            .filter(
                player_id=player_id,
                result__public=True,
                position__gt=0,
            )
            .order_by("-result__date")[:how_many]
        )

    df = get_details(rows)
    df["wave_role"] = df.wave_role.map(lambda x: x.wave_bottom)
    df["verified"] = df.verified.map(lambda x: int(bool(x)))

    response = [
        {
            "id": row.id,
            "position": row.position,
            "tourney_name": row.tourney_name,
            "real_name": row.real_name,
            "wave": row.wave,
            "avatar": row.avatar,
            "relic": row.relic,
            "date": row.date,
            "league": row.league,
            "verified": row.verified,
            "wave_role": row.wave_role,
            "patch": str(row.patch),
        }
        for _, row in df.iterrows()
    ]

    return JsonResponse(response, status=200, safe=False)
