#!/tourney/tourney_venv/bin/python
import datetime
import os
import time

import requests

weekdays_sat = [5, 6, 0, 1]
weekdays_wed = [2, 3, 4]

wednesday = 2
saturday = 5


import io
import logging

import pandas as pd

logging.basicConfig(level=logging.INFO)


def get_current_time__game_server():
    """Game server runs on utc time, but we don't want to try accessing results until 1 hour after the tourney is done."""
    return datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)


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
    offset = get_date_offset()

    last_tourney_day = (utcnow - datetime.timedelta(days=offset)).day
    last_tourney_month = (utcnow - datetime.timedelta(days=offset)).month
    last_tourney_year = (utcnow - datetime.timedelta(days=offset)).year

    return f"{last_tourney_year}-{str(last_tourney_month).zfill(2)}-{str(last_tourney_day).zfill(2)}"


def get_file_name():
    return f"{get_last_date()}.csv"


def get_file_path(file_name, league):
    return f"{os.getenv('HOME')}/tourney/results_cache/{league}/{file_name}"


def make_request(league):
    base_url = os.getenv("NEW_LEADERBOARD_URL")
    params = {"tier": league, "pass": os.getenv("LEADERBOARD_PASS")}

    csv_response = requests.get(base_url, params=params)
    csv_contents = csv_response.text

    header = "player_id,name,avatar,relic,wave,bracket,tourney_number\n"

    csv_contents = header + csv_contents

    try:
        df = pd.read_csv(io.StringIO(csv_contents.strip()), on_bad_lines='warn')
    except Exception as e:
        path = f"/tmp/{league}__failed_result.csv"

        with open(path, "w") as outfile:
            outfile.write(csv_contents)

        logging.info(f"{league} csv failed processing. Check {path} for the faulty file and adjust.")
        logging.info(e)

    df["wave"] = df["wave"].astype(int)
    df = df.sort_values("wave", ascending=False)
    return df


def execute(league):
    date_offset = get_date_offset()
    current_time = get_current_time__game_server()
    current_hour = current_time.hour

    if date_offset == 0 or date_offset == 1 and current_hour < 4:
        logging.info("Skipping cause tourney day!!")
        return

    file_path = get_file_path(get_file_name(), league)

    if os.path.isfile(file_path):
        logging.info(f"Using cached file {file_path}")
        return

    try:
        df = make_request(league)
    except Exception as e:
        logging.error(f"Error in make_request: {e}")
        return

    df.to_csv(file_path, index=False)
    logging.info(f"Successfully stored file {file_path}")

    return True


def check():
    print(make_request("Champion")[:4000])


if __name__ == "__main__":
    while True:
        for league in ["Legend", "Champion", "Platinum", "Gold", "Silver", "Copper"]:
            out = execute(league)

            if out:
                time.sleep(10)

        time.sleep(1800)  # this can run in a loop cause we will request the tourney data only once per tourney and cache
