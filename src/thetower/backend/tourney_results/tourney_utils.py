# Standard library imports
import datetime
import logging
import os
import re
from pathlib import Path
from time import perf_counter
from types import MappingProxyType

# Third-party imports
import anthropic
import pandas as pd
from django.apps import apps
from django.db.models import Q

# Local imports
from .constants import champ, leagues, legend
from .data import get_player_id_lookup, get_shun_ids, get_sus_ids, get_tourneys
from .models import Injection, PromptTemplate, TourneyResult, TourneyRow

# Initialize logging
logging.basicConfig(level=logging.INFO)


def create_tourney_rows(tourney_result: TourneyResult) -> None:
    """Idempotent function to process tourney result during the csv import process.

    The idea is that:
     - if there are not rows created, create them,
     - if there are already rows created, update all positions at least (positions should never
    be set manually, that doesn't make sense?),
     - if there are things like wave changed, assume people changed this manually from admin.
    """

    csv_path = tourney_result.result_file.path

    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        # try other path
        csv_path = csv_path.replace("uploads", "src/thetower/backend/uploads")

        df = pd.read_csv(csv_path)

    if df.empty:
        logging.error(f"Empty csv file: {csv_path}")
        return

    if 0 in df.columns:
        df = df.rename(columns={0: "id", 1: "tourney_name", 2: "wave"})
        # df["tourney_name"] = df["tourney_name"].map(lambda x: x.strip())  # We're stripping white space on csv save so we shouldn't need this anymore.
        df["avatar"] = df.tourney_name.map(lambda name: int(avatar[0]) if (avatar := re.findall(r"\#avatar=([-\d]+)\${5}", name)) else -1)
        df["relic"] = df.tourney_name.map(lambda name: int(relic[0]) if (relic := re.findall(r"\#avatar=\d+\${5}relic=([-\d]+)", name)) else -1)
        df["tourney_name"] = df.tourney_name.map(lambda name: name.split("#")[0])
    if "player_id" in df.columns:
        df = df.rename(columns={"player_id": "id", "name": "tourney_name", "wave": "wave"})
        # Make sure that users with all digit tourney_name's don't trick the column into being a float
        df["tourney_name"] = df["tourney_name"].astype("str")
        # df["tourney_name"] = df["tourney_name"].map(lambda x: x.strip())  # We're stripping white space on csv save so we shouldn't need this anymore.
        logging.info(f"There are {len(df.query('tourney_name.str.len() == 0'))} blank tourney names.")
        df.loc[df["tourney_name"].str.len() == 0, "tourney_name"] = df["id"]

    excluded_ids = get_sus_ids()
    positions = calculate_positions(df.id, df.index, df.wave, excluded_ids)

    df["position"] = positions

    create_data = []

    for _, row in df.iterrows():
        create_data.append(
            dict(
                player_id=row.id,
                result=tourney_result,
                nickname=row.tourney_name,
                wave=row.wave,
                position=row.position,
                avatar_id=row.avatar,
                relic_id=row.relic,
            )
        )

    TourneyRow.objects.bulk_create([TourneyRow(**data) for data in create_data])


def calculate_positions(ids: list[int], indices: list[int], waves: list[int], exclude_ids: set[int]) -> list[int]:
    """Calculate positions for tournament participants.

    Args:
        ids: List of player IDs
        indices: List of indices corresponding to player positions
        waves: List of wave numbers reached by players
        exclude_ids: Set of player IDs to exclude from position calculation

    Returns:
        List of calculated positions where excluded players get -1
    """
    positions = []
    current = 0
    borrow = 1

    # Flatten list of exclude_ids if it's nested
    if any(isinstance(item, (list, set)) for item in exclude_ids):
        exclude_ids = set().union(*exclude_ids)
    else:
        exclude_ids = set(exclude_ids)

    for id_, idx, wave in zip(ids, indices, waves):
        if id_ in exclude_ids:
            positions.append(-1)
            continue

        if idx - 1 in indices and wave == waves[idx - 1]:
            borrow += 1
        else:
            current += borrow
            borrow = 1

        positions.append(current)

    return positions


def reposition(tourney_result: TourneyResult, testrun: bool = False, verbose: bool = False) -> int:
    """Recalculates positions for tournament results and updates the database.

    Args:
        tourney_result: Tournament result to reposition
        testrun: If True, only calculate changes without updating database
        verbose: If True, log detailed position changes

    Returns:
        Number of position changes made
    """
    qs = tourney_result.rows.all().order_by("-wave")
    bulk_data = qs.values_list("player_id", "wave", "nickname")
    indexes = [idx for idx, _ in enumerate(bulk_data)]
    ids = [datum[0] for datum in bulk_data]
    waves = [datum[1] for datum in bulk_data]
    nicknames = [datum[2] for datum in bulk_data]

    excluded_ids = get_sus_ids()
    positions = calculate_positions(ids, indexes, waves, excluded_ids)

    bulk_update_data = []
    changes = 0

    for index, obj in enumerate(qs):
        if obj.position != positions[index]:
            changes += 1
            if verbose:
                logging.info(
                    f"Player {obj.player_id} ({nicknames[index]}) at wave {waves[index]}: "
                    f"Position changing from {obj.position} to {positions[index]}"
                )
            obj.position = positions[index]
            bulk_update_data.append(obj)

    if not testrun and bulk_update_data:
        TourneyRow.objects.bulk_update(bulk_update_data, ["position"])

    if changes:
        logging.info(f"Repositioned {changes} rows in tournament {tourney_result}")
    return changes


def get_summary(last_date: datetime.datetime) -> str:
    """Generate AI summary of tournament results.

    Args:
        last_date: Latest date to include in summary

    Returns:
        Generated summary text from AI model
    """
    logging.info("Collecting ai summary data...")

    qs = TourneyResult.objects.filter(league=legend, date__lte=last_date).order_by("-date")[:10]

    qs_dates = qs.values_list("date", flat=True)

    champ_qs = TourneyResult.objects.filter(~Q(date__in=qs_dates), league=champ, date__lte=last_date).order_by("-date")[:10]

    df1 = get_tourneys(qs, offset=0, limit=50)
    df2 = get_tourneys(champ_qs, offset=0, limit=50)

    df = pd.concat([df1, df2])

    ranking = ""

    for date, sdf in df.groupby(["date"]):
        bcs = [(bc.name, bc.shortcut) for bc in sdf.iloc[0]["bcs"]]
        ranking += f"Tourney of {date[0].isoformat()}, battle conditions: {bcs}:\n"
        ranking += "\n".join(
            [
                f"{row.position}. {row.real_name} (tourney_name: {row.tourney_name}) - {row.wave}"
                for _, row in sdf[["position", "real_name", "tourney_name", "wave"]].iterrows()
            ]
        )
        ranking += "\n\n"

        top1_message = Injection.objects.last().text

    prompt_template = PromptTemplate.objects.get(id=1).text
    text = prompt_template.format(
        ranking=ranking,
        last_date=last_date,
        top1_message=top1_message,
    )

    logging.info("Starting to generate ai summary...")
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=4096,
        temperature=1.0,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": text,
                    }
                ],
            }
        ],
    )

    response = message.content[0].text
    logging.info(f"Ai summary done: {response}")

    return response


def get_time(file_path: Path) -> datetime.datetime:
    """Parse datetime from filename.

    Args:
        file_path: Path object containing timestamp in filename

    Returns:
        Parsed datetime object
    """
    return datetime.datetime.strptime(str(file_path.stem), "%Y-%m-%d__%H_%M")


def get_live_df(league: str, shun: bool = False) -> pd.DataFrame:
    """Get live tournament data as DataFrame.

    Args:
        league: League identifier
        shun: If True, only exclude suspicious IDs, otherwise exclude both suspicious and shunned

    Returns:
        DataFrame containing live tournament data

    Raises:
        ValueError: If no current tournament data is available
    """
    t1_start = perf_counter()
    home = Path(os.getenv("HOME"))
    live_path = home / "tourney" / "results_cache" / f"{league}_live"

    all_files = sorted(live_path.glob("*.csv"))

    # Filter out empty files
    non_empty_files = [f for f in all_files if f.stat().st_size > 0]

    if not non_empty_files:
        raise ValueError("No current data, wait until the tourney day")

    last_file = non_empty_files[-1]
    last_date = get_time(last_file)

    data = {}
    for file in non_empty_files:
        current_time = get_time(file)
        time_diff = last_date - current_time
        if time_diff < datetime.timedelta(hours=42.5):
            try:
                df = pd.read_csv(file)
                if not df.empty:  # Only include non-empty dataframes
                    data[current_time] = df
            except Exception as e:
                logging.warning(f"Failed to read {file}: {e}")
                continue

    for dt, df in data.items():
        df["datetime"] = dt

    if not data:
        raise ValueError("No current data, wait until the tourney day")

    df = pd.concat(data.values())
    df = df.sort_values(["datetime", "wave"], ascending=False)
    # df["bracket"] = df.bracket.map(lambda x: x.strip())  # We strip in get_live_results so we don't need to do it here.

    # bracket_counts = dict(df.groupby("bracket").player_id.unique().map(lambda player_ids: len(player_ids)))
    # fullish_brackets = [bracket for bracket, count in bracket_counts.items() if count >= 28]

    # df = df[df.bracket.isin(fullish_brackets)]  # no sniping
    lookup = get_player_id_lookup()
    df["real_name"] = [lookup.get(id, name) for id, name in zip(df.player_id, df.name)]
    df["real_name"] = df["real_name"].astype(str)

    if shun:
        excluded_ids = get_sus_ids()
    else:
        excluded_ids = get_sus_ids() | get_shun_ids()
    df = df[~df.player_id.isin(excluded_ids)]
    df = df.reset_index(drop=True)
    t1_stop = perf_counter()
    logging.debug(f"get_live_df({league}) took {t1_stop - t1_start}")
    return df


def get_full_brackets(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Get bracket information from tournament data.

    Args:
        df: DataFrame containing tournament data

    Returns:
        Tuple containing:
        - bracket_order: List of brackets ordered by creation time
        - fullish_brackets: List of brackets with >= 28 players
    """
    df["datetime"] = pd.to_datetime(df["datetime"])
    bracket_order = df.groupby("bracket")["datetime"].min().sort_values().index.tolist()

    bracket_counts = dict(df.groupby("bracket").player_id.unique().map(lambda player_ids: len(player_ids)))
    fullish_brackets = [bracket for bracket, count in bracket_counts.items() if count >= 28]

    return bracket_order, fullish_brackets


def check_live_entry(league: str, player_id: str) -> bool:
    """Check if player has entered live tournament.

    Args:
        league: League identifier
        player_id: Player ID to check

    Returns:
        True if player has entered, False otherwise
    """
    t1_start = perf_counter()
    logging.info(f"Checking live entry for player {player_id} in {league} league")

    try:
        # Get raw data first
        df = get_live_df(league, True)

        # Use our local bracket filtering
        _, fullish_brackets = get_full_brackets(df)

        # Check if player is in any full bracket
        filtered_df = df[df.bracket.isin(fullish_brackets)]
        player_found = player_id in filtered_df.player_id.values

        t1_stop = perf_counter()
        logging.debug(f"check_live_entry({league}, {player_id}) took {t1_stop - t1_start:.3f} seconds")
        return player_found

    except (IndexError, ValueError):
        return False


def check_all_live_entry(player_id: str) -> bool:
    """Check if player has entered any live tournament.

    Args:
        player_id: Player ID to check

    Returns:
        True if player has entered any tournament, False otherwise
    """
    t1_start = perf_counter()
    for league in leagues:
        if check_live_entry(league, player_id):
            t1_stop = perf_counter()
            logging.debug(f"check_all_live_entry({player_id}) took {t1_stop - t1_start}")
            return True
    t1_stop = perf_counter()
    logging.debug(f"check_all_live_entry({player_id}) took {t1_stop - t1_start}")
    return False


def load_battle_conditions() -> MappingProxyType:
    """
    Load battle conditions from the database into an immutable dictionary.
    Returns a read-only dictionary with condition shortcuts as keys and names as values.
    """
    BattleCondition = apps.get_model("tourney_results", "BattleCondition")
    conditions = {condition.shortcut: condition.name for condition in BattleCondition.objects.all()}
    return MappingProxyType(conditions)
