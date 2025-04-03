#!/tourney/tourney_venv/bin/python
import os
import datetime
import threading

import schedule

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dtower.thetower.settings")
django.setup()


import logging
import time
from glob import glob

from django.core.files.uploadedfile import SimpleUploadedFile

from dtower.tourney_results.constants import leagues
from dtower.tourney_results.get_results import get_file_name, get_last_date
from dtower.tourney_results.models import TourneyResult, BattleCondition
from dtower.tourney_results.tourney_utils import create_tourney_rows, get_summary
from towerbcs.towerbcs import predict_future_tournament, TournamentPredictor


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
        last_files = sorted([file_name for file_name in glob(f"{os.getenv('HOME')}/tourney/results_cache/{league}/{last_date}*") if "csv_raw" not in file_name])

        if not last_files:
            logging.info("Apparently we're checking the files before the download script could get them, try later.")
            continue

        last_file = last_files[-1]

        tourney_id, tourney_date, days_until = TournamentPredictor.get_tournament_info(last_date)
        conditions = predict_future_tournament(tourney_id, league)

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
            ),
        )
        condition_ids = BattleCondition.objects.filter(name__in=conditions).values_list('id', flat=True)
        result.conditions.set(condition_ids)
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
