import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dtower.thetower.settings")
django.setup()

import csv
import datetime
from collections import Counter, defaultdict
from functools import lru_cache
from glob import glob
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import extra_streamlit_components as stx
import numpy as np
import pandas as pd
import streamlit as st

from dtower.sus.models import PlayerId, SusPerson
from dtower.tourney_results.constants import data_folder_name_mapping
from dtower.tourney_results.formatting import color_position_barebones
from dtower.tourney_results.models import Patch, Role, TourneyResult


@lru_cache
def get_patches():
    return Patch.objects.all().order_by("start_date")


def date_to_patch(date: datetime.datetime) -> Optional[Patch]:
    for patch in get_patches():
        if date >= patch.start_date and date <= patch.end_date:
            return patch


def wave_to_role_in_patch(roles: List[Role], wave: int) -> Optional[Role]:
    for role in roles:
        if wave >= role.wave_bottom and wave < role.wave_top:
            return role


@lru_cache
def patch_to_roles():
    patch_to_roles = defaultdict(list)

    for role in Role.objects.all():
        patch_to_roles[role.patch].append(role)

    return patch_to_roles


def wave_to_role(wave: int, patch: Optional[Patch]) -> Optional[Role]:
    if not patch:
        return None

    roles = patch_to_roles()[patch]

    if not roles:
        return None

    return wave_to_role_in_patch(roles, wave)


def load_data(folder):
    result_files = sorted(glob(f"{folder}/*"))
    total_results = {}

    for result_file in result_files:
        tourney_results = []

        with open(result_file, "r") as infile:
            file = csv.reader(infile)
            contents = [line for line in file]

        for id_, raw_name, raw_wave in contents:
            name = raw_name.strip()
            wave = int(raw_wave.strip())
            tourney_results.append((id_, name, wave))

        result_date = datetime.datetime.fromisoformat(result_file.split("/")[1].split(".")[0]).date()
        total_results[result_date] = tourney_results

    results_by_id = defaultdict(list)

    for tourney_name, results in total_results.items():
        for id_, name, wave in results:
            results_by_id[id_].append((tourney_name, name, wave))

    position_by_id = defaultdict(list)

    for tourney_name, results in total_results.items():
        for positition, (id_, name, wave) in enumerate(results, 1):
            position_by_id[id_].append((tourney_name, name, positition))

    return total_results, results_by_id, position_by_id


def get_player_id_lookup():
    return dict(PlayerId.objects.all().values_list("id", "player__name"))


def get_id_lookup():
    player_primary_id = {name: id_ for id_, name, primary in PlayerId.objects.all().values_list("id", "player__name", "primary") if primary}
    return {id_: player_primary_id[name] for id_, name in PlayerId.objects.all().values_list("id", "player__name")}


def get_id_real_name_mapping(df: pd.DataFrame, lookup: Dict[str, str]) -> Dict[str, str]:
    def get_most_common(df):
        return Counter(df["tourney_name"]).most_common()[0][0]

    return {id_: lookup.get(id_, get_most_common(group)) for id_, group in df.groupby("id")}


def get_row_to_role(df: pd.DataFrame):
    name_roles: Dict[int, Optional[Role]] = {}

    for patch, roles in patch_to_roles().items():
        patch_start = np.datetime64(patch.start_date)
        patch_end = np.datetime64(patch.end_date)
        id_df = df[(df["date"] >= patch_start) & (df["date"] <= patch_end)]

        for _, filtered_df in id_df.groupby("id"):
            if not filtered_df.empty:
                wave_role = sorted(filtered_df["wave_role"], reverse=True)[0]
                name_roles.update({index: wave_role for index in filtered_df.index})

    df["name_role"] = df.index.map(name_roles.get)
    df["name_role_color"] = df.name_role.map(lambda role: getattr(role, "color", None))
    return df


@st.cache(allow_output_mutation=True)
def load_tourney_results__prev(folder: str) -> pd.DataFrame:
    result_files = sorted(glob(f"{folder}/*"))
    return _load_tourney_results([(file_name, file_name.split("/")[-1].split(".")[0]) for file_name in result_files])


def _load_tourney_results(result_files: List[Tuple[str, str]]) -> pd.DataFrame:
    hidden_features = os.environ.get("HIDDEN_FEATURES")
    league_switcher = os.environ.get("LEAGUE_SWITCHER")

    dfs = []

    sus_ids = get_sus_ids()

    load_data_bar = st.progress(0)

    for index, (result_file, date) in enumerate(result_files, 1):
        df = pd.read_csv(result_file, header=None)

        if not hidden_features:
            if league_switcher:
                cutoff = 500
            else:
                cutoff = 200

            df = df.iloc[:cutoff]

        df.columns = ["id", "tourney_name", "wave"]

        result_date = datetime.datetime.fromisoformat(date)
        df["tourney_name"] = df["tourney_name"].map(lambda x: x.strip())
        df["date"] = [result_date] * len(df)

        positions = []
        current = 1

        for id_ in df.id:
            if id_ in sus_ids:
                positions.append(-1)
                continue

            positions.append(current)
            current += 1

        df["position"] = positions
        dfs.append(df)

        load_data_bar.progress(index / len(result_files) * 0.5)

    df = pd.concat(dfs)

    lookup = get_player_id_lookup()
    id_to_real_name = get_id_real_name_mapping(df, lookup)

    df["raw_id"] = df.id
    id_mapping = get_id_lookup()
    df["id"] = df.id.map(lambda id_: id_mapping.get(id_, id_))  # id renormalization

    load_data_bar.progress(0.6)

    df["real_name"] = df.id.map(lambda id_: id_to_real_name[id_])
    df["patch"] = df.date.map(date_to_patch)
    df["patch_version"] = df.patch.map(lambda x: x.version_minor)

    load_data_bar.progress(0.75)

    df["wave_role"] = [wave_to_role(wave, date_to_patch(date)) for wave, date in zip(df["wave"], df["date"])]
    df["wave_role_color"] = df.wave_role.map(lambda role: getattr(role, "color", None))

    load_data_bar.progress(0.95)

    df["position_role_color"] = [color_position_barebones(position) for position in df["position"]]
    df = df.reset_index(drop=True)

    load_data_bar.progress(1.0)

    df = get_row_to_role(df)

    load_data_bar.empty()
    return df


@st.cache(allow_output_mutation=True, suppress_st_warning=True)
def load_tourney_results(folder: str) -> pd.DataFrame:
    hidden_features = os.environ.get("HIDDEN_FEATURES")
    additional_filter = {} if hidden_features else dict(public=True)

    result_files = sorted(
        [
            (
                Path("thetower/dtower") / result_file,
                date.isoformat(),
            )
            for result_file, date in TourneyResult.objects.filter(league=data_folder_name_mapping[folder], **additional_filter).values_list(
                "result_file", "date"
            )
        ],
        key=lambda x: x[1],
    )

    additional_files = sorted(glob("/home/tgrining/tourney/test/*"))
    result_files += [(file_name, file_name.split("/")[-1].split(".")[0]) for file_name in additional_files]

    return _load_tourney_results(result_files)


@st.cache(allow_output_mutation=True)
def get_manager():
    return stx.CookieManager()


@st.cache(allow_output_mutation=True)
def get_player_list(df):
    last_date = df.date.unique()[-1]
    sus_ids = get_sus_ids()
    first_choices = list(df[(df.date == last_date) & ~(df.id.isin(sus_ids))].real_name)
    set_of_first_choices = set(first_choices)
    all_real_names = set(df.real_name.unique()) - set_of_first_choices
    all_tourney_names = set(df.tourney_name.unique()) - set_of_first_choices
    all_user_ids = df.raw_id.unique().tolist()
    last_top_scorer = df[(df.date == sorted(df.date.unique())[-1]) & (df.position == 1)].tourney_name.iloc[0]
    return first_choices, all_real_names, all_tourney_names, all_user_ids, last_top_scorer


def get_sus_data():
    return SusPerson.objects.filter(sus=True).values("name", "player_id").order_by("name")


def get_sus_ids():
    return set(SusPerson.objects.filter(sus=True).values_list("player_id", flat=True))


if __name__ == "__main__":
    df = load_tourney_results("data")
    breakpoint()


# import cProfile
# import pstats

# pr = cProfile.Profile()
# pr.run("load_tourney_results('data')")

# stats = pstats.Stats(pr)
# stats.sort_stats("cumtime")
# stats.print_stats(50)