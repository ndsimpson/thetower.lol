# Standard library imports
import logging
import os

# Django setup
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dtower.thetower.settings")
django.setup()

# Third-party imports
from tqdm import tqdm

# Local imports
from dtower.tourney_results.models import TourneyResult, TourneyRow
from dtower.tourney_results.data import get_shun_ids, get_sus_ids
from dtower.tourney_results.tourney_utils import reposition

# Initialize logging
logging.basicConfig(level=logging.INFO)


def fix_tourney_results():
    results = TourneyResult.objects.all()

    changes_count = 0
    total_changes = 0

    for result in tqdm(results, desc="Processing tournaments"):
        changes = reposition(result, testrun=True, verbose=True)
        if changes:
            changes_count += 1
            total_changes += changes

    logging.info(f"Number of tourneys changed: {changes_count}")
    logging.info(f"Total changes made: {total_changes}")


def view_broken_results():

    # Get the excluded player IDs
    excluded_ids = get_sus_ids() | get_shun_ids()

    # Query for TourneyRows
    suspicious_rows = TourneyRow.objects.filter(
        position__gt=0,
        player_id__in=excluded_ids
    ).order_by('result__date', 'position')

    # Print results
    for row in suspicious_rows:
        logging.info(f"Tournament {row.result.date}: Player {row.player_id} ({row.nickname}) "
                     f"placed {row.position} with wave {row.wave}")

    logging.info(f"Total suspicious entries found: {suspicious_rows.count()}")


if __name__ == "__main__":
    view_broken_results()
    fix_tourney_results()

