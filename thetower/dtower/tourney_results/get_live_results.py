#!/tourney/tourney_venv/bin/python
import datetime
import io
import logging
import os
import time

import pandas as pd
import requests
import schedule

from components.live.data_ops import clear_cache
from dtower.tourney_results.constants import leagues

weekdays_sat = [5, 6, 0, 1]
weekdays_wed = [2, 3, 4]

wednesday = 2
saturday = 5

logging.basicConfig(level=logging.INFO)


def get_current_time__game_server():
    """Game server runs on utc time."""
    return datetime.datetime.now(datetime.UTC)


def get_date_offset() -> int:
    """Figure out how far away from last tourney day current time is."""
    utcnow = get_current_time__game_server()

    if utcnow.weekday() in weekdays_wed:
        offset = utcnow.weekday() - wednesday
    elif utcnow.weekday() in weekdays_sat:
        offset = (utcnow.weekday() - saturday) % 7
    else:
        raise ValueError("wtf")

    return offset


def get_last_date():
    utcnow = get_current_time__game_server()
    return f"{utcnow.year}-{str(utcnow.month).zfill(2)}-{str(utcnow.day).zfill(2)}__{utcnow.hour}_{utcnow.minute}"


def get_file_name():
    return f"{get_last_date()}.csv"


def get_file_path(file_name, league):
    return f"{os.getenv('HOME')}/tourney/results_cache/{league}_live/{file_name}"


def make_request(league):
    base_url = os.getenv("NEW_LEADERBOARD_URL")
    params = {"tier": league, "pass": os.getenv("LEADERBOARD_PASS")}

    csv_response = requests.get(base_url, params=params)
    csv_contents = csv_response.text

    header = "player_id,name,avatar,relic,wave,bracket,tourney_number\n"

    csv_contents = header + csv_contents
    df = pd.read_csv(io.StringIO(csv_contents.strip()), on_bad_lines='warn')
    df["wave"] = df["wave"].astype(int)
    df = df.sort_values("wave", ascending=False)
    df["name"] = df["name"].map(lambda x: x.strip())
    df["bracket"] = df["bracket"].map(lambda x: x.strip())
    logging.info(f"There are {len(df.query('name.str.len() == 0'))} blank tourney names.")
    df.loc[df['name'].str.len() == 0, 'name'] = df['player_id']
    return df


def execute(league):
    logging.info(f"Working on {league}.")
    file_path = get_file_path(get_file_name(), league)
    df = make_request(league)

    df.to_csv(file_path, index=False)
    logging.info(f"Successfully stored file {file_path}")

    try:
        clear_cache()
        logging.info("Successfully cleared Streamlit cache")
    except Exception as e:
        logging.warning(f"Failed to clear Streamlit cache: {e}")

    return True


def get_results():
    date_offset = get_date_offset()
    current_time = get_current_time__game_server()
    current_hour = current_time.hour

    if date_offset > 1 or (date_offset == 1 and current_hour > 5):
        logging.info("Skipping because _not_ tourney day anymore!!")
        return

    if date_offset == 0 and current_hour == 0 and current_time.minute == 0:
        logging.info("Skipping because tourney *just* started.")
        return

    for league in leagues:
        try:
            execute(league)
        except Exception as e:
            logging.exception(e)
        time.sleep(2)


if __name__ == "__main__":
    now = datetime.datetime.now()
    logging.info(f"Started get_live_results at {now}.")

    schedule.every().hour.at(":00").do(get_results)
    schedule.every().hour.at(":30").do(get_results)
    logging.info(schedule.get_jobs())

    while True:
        n = schedule.idle_seconds()
        logging.info(f"Sleeping {n} seconds.")
        time.sleep(n)
        schedule.run_pending()