#!/tourney/tourney_venv/bin/python
from ..tourney_utils import create_tourney_rows, get_summary
from ..models import TourneyResult, BattleCondition
from ..get_results import get_file_name, get_last_date
from ..constants import leagues
from django.core.files.uploadedfile import SimpleUploadedFile
from glob import glob
import time
import logging
import os
import datetime
import threading

import schedule

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.backend.towerdb.settings")
django.setup()


# Graceful towerbcs import handling
try:
    from towerbcs import predict_future_tournament, TournamentPredictor
    TOWERBCS_AVAILABLE = True
    logging.info("towerbcs package loaded successfully")
except ImportError as e:
    logging.warning(f"towerbcs package not available: {e}")
    logging.warning("Battle condition predictions will be skipped")
    # Create dummy functions to prevent errors
    TOWERBCS_AVAILABLE = False

    def predict_future_tournament(tourney_id, league):
        return []

    class TournamentPredictor:
        @staticmethod
        def get_tournament_info(date):
            return None, date, 0


logging.basicConfig(level=logging.INFO)


def update_summary(result):
    summary = get_summary(result.date)
    result.overview = summary
    result.save()


def execute():
    for league in leagues:
        last_date = get_last_date()

        logging.info(f"Trying to upload results for {league=} and {last_date=}")

        last_results = TourneyResult.objects.filter(date=last_date, league=league)

        if last_results:
            logging.info(f"Nothing new, results are already uploaded for {last_date=}")
            continue

        logging.info("Something new")
        last_files = sorted([file_name for file_name in glob(
            f"{os.getenv('HOME')}/tourney/results_cache/{league}/{last_date}*") if "csv_raw" not in file_name])

        if not last_files:
            logging.info("Apparently we're checking the files before the download script could get them, try later.")
            continue

        last_file = last_files[-1]

        # Get tournament info and conditions (skip if towerbcs not available)
        conditions = []
        if TOWERBCS_AVAILABLE:
            try:
                tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info(last_date)
                conditions = predict_future_tournament(tourney_id, league)
                logging.info(f"Predicted {len(conditions)} battle conditions for {league}")
            except Exception as e:
                logging.error(f"Error predicting battle conditions: {e}")
                conditions = []
        else:
            logging.info("Skipping battle condition prediction (towerbcs not available)")

        try:
            with open(last_file, "rb") as infile:
                contents = infile.read()
        except FileNotFoundError:
            logging.info(f"{last_file=} not found, maybe later")
            continue

        logging.info("Creating file object")
        csv_file = SimpleUploadedFile(
            name=get_file_name(),
            content=contents,
            content_type="text/csv",
        )
        logging.info("Creating tourney_result")
        result, _ = TourneyResult.objects.update_or_create(
            date=last_date,
            league=league,
            defaults=dict(
                result_file=csv_file,
                public=True,  # Make results public by default
            ),
        )

        # Apply battle conditions if any were predicted
        if conditions:
            condition_ids = BattleCondition.objects.filter(name__in=conditions).values_list('id', flat=True)
            result.conditions.set(condition_ids)
            logging.info(f"Applied {len(condition_ids)} battle conditions to tournament result")
        else:
            logging.info("No battle conditions to apply")

        create_tourney_rows(result)

        # Generate summary for Legends league results
        if league == "Legends":
            logging.info("Generating summary for Legends league results")
            thread = threading.Thread(target=update_summary, args=(result,))
            thread.start()


if __name__ == "__main__":
    now = datetime.datetime.now()
    logging.info(f"Started import_results at {now}.")

    schedule.every().hour.at(":05").do(execute)
    logging.info(schedule.get_jobs())

    while True:

        n = schedule.idle_seconds()
        logging.info(f"Sleeping {n} seconds.")
        time.sleep(n)
        schedule.run_pending()
