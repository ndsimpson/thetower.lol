import os
from datetime import timedelta

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.settings")
django.setup()

from django.utils import timezone

from ..sus.models import SusPerson
from .models import TourneyRow


def analyze_shunned_participation():
    # Get current date and time ranges
    now = timezone.now().date()
    two_weeks_ago = now - timedelta(days=14)
    one_month_ago = now - timedelta(days=30)
    three_months_ago = now - timedelta(days=90)
    six_months_ago = now - timedelta(days=180)

    # Get shunned players
    shunned_players = SusPerson.objects.filter(shun=True)

    print("\nShunned Players Tournament Participation:\n")
    print("Player ID                     Name                2 Weeks  1 Month  3 Months  6 Months  Total")
    print("-" * 95)

    for player in shunned_players:
        # Get base queryset for this player
        player_rows = TourneyRow.objects.filter(player_id=player.player_id)

        # Count tournaments in each time period
        two_week_count = player_rows.filter(result__date__gte=two_weeks_ago).count()
        one_month_count = player_rows.filter(result__date__gte=one_month_ago).count()
        three_month_count = player_rows.filter(result__date__gte=three_months_ago).count()
        six_month_count = player_rows.filter(result__date__gte=six_months_ago).count()
        total_count = player_rows.count()

        name = player.name if player.name else "Unknown"
        print(
            f"{player.player_id:<25} {name:<20} {two_week_count:>8} {one_month_count:>8} {three_month_count:>9} {six_month_count:>9} {total_count:>7}"
        )


if __name__ == "__main__":
    analyze_shunned_participation()
