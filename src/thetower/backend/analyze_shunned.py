import os
from datetime import timedelta

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.backend.towerdb.settings")
django.setup()

from django.utils import timezone

from thetower.backend.sus.models import ModerationRecord
from thetower.backend.tourney_results.models import TourneyRow


def analyze_shunned_participation():
    # Get current date and time ranges
    now = timezone.now().date()
    two_weeks_ago = now - timedelta(days=14)
    one_month_ago = now - timedelta(days=30)
    three_months_ago = now - timedelta(days=90)
    six_months_ago = now - timedelta(days=180)

    # Get unique shunned player tower_ids from ModerationRecord
    shunned_tower_ids = set(ModerationRecord.objects.filter(
        moderation_type='shun',
        status='active'
    ).values_list('tower_id', flat=True))

    print("\nShunned Players Tournament Participation:\n")
    print("Player ID                     Name                2 Weeks  1 Month  3 Months  6 Months  Total")
    print("-" * 95)

    for tower_id in sorted(shunned_tower_ids):
        # Get base queryset for this player
        player_rows = TourneyRow.objects.filter(player_id=tower_id)

        # Count tournaments in each time period
        two_week_count = player_rows.filter(result__date__gte=two_weeks_ago).count()
        one_month_count = player_rows.filter(result__date__gte=one_month_ago).count()
        three_month_count = player_rows.filter(result__date__gte=three_months_ago).count()
        six_month_count = player_rows.filter(result__date__gte=six_months_ago).count()
        total_count = player_rows.count()

        # Try to get name from any linked KnownPlayer record for this tower_id
        name = "Unknown"
        try:
            record_with_known_player = ModerationRecord.objects.filter(
                tower_id=tower_id,
                known_player__isnull=False
            ).first()
            if record_with_known_player and record_with_known_player.known_player:
                name = record_with_known_player.known_player.name or "Unknown"
        except Exception:
            pass

        print(
            f"{tower_id:<25} {name:<20} {two_week_count:>8} {one_month_count:>8} {three_month_count:>9} {six_month_count:>9} {total_count:>7}"
        )


if __name__ == "__main__":
    analyze_shunned_participation()
