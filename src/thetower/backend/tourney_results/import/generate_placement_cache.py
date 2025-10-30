#!/usr/bin/env python
"""
Generate per-tourney placement cache files for live placement analysis.

This script groups live snapshots into tourneys (using a 42-hour gap), then
incrementally updates a single flat cache file per tourney (per league). It is
safe to run periodically (every 30 minutes) or once via --once.

Writes are atomic; the cache file contains a `last_processed_iso` marker so the
generator only processes new snapshots since the last run.
"""
import argparse
import datetime
import json
import logging
import os
import tempfile
import time
from pathlib import Path

import django
import pandas as pd
import schedule

# Django setup
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.backend.towerdb.settings")
django.setup()

from thetower.backend.tourney_results.constants import leagues

# used to map player_id -> real display name for caches
from thetower.backend.tourney_results.data import get_player_id_lookup
from thetower.backend.tourney_results.shun_config import include_shun_enabled_for
from thetower.backend.tourney_results.tourney_utils import get_time

logging.basicConfig(level=logging.INFO)

# Configuration
# Resolve HOME defensively: prefer explicit env var, fall back to Path.home()
_home_env = os.getenv("HOME")
HOME = Path(_home_env) if _home_env else Path.home()
# Allow an explicit override for the live results base (useful for dev/debug)
LIVE_BASE = Path(os.getenv("LIVE_RESULTS_BASE") or (HOME / "tourney" / "results_cache"))
# Log resolved paths early to aid debugging when run under different envs
logging.info(f"Resolved HOME env: {_home_env!r}, HOME Path: {HOME}, LIVE_BASE: {LIVE_BASE}")
# place caches in the existing results_cache directory (requested):
# cache files will be written under LIVE_BASE to keep them alongside snapshots
CACHE_BASE = LIVE_BASE
GAP_HOURS = 42


def atomic_write(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    finally:
        # if replace failed for some reason, try cleanup
        if Path(tmp).exists():
            try:
                Path(tmp).unlink()
            except Exception:
                pass


def list_live_snapshots(league: str):
    """List non-empty live snapshot CSVs for a league, sorted chronologically."""
    live_dir = LIVE_BASE / f"{league}_live"
    logging.debug(f"Checking live dir for league {league}: {live_dir}")
    if not live_dir.exists():
        logging.debug(f"Live dir missing for league {league}: {live_dir}")
        return []
    files = [p for p in live_dir.glob("*.csv") if p.stat().st_size > 0]
    files_sorted = sorted(files, key=get_time)
    if not files_sorted:
        logging.debug(f"No non-empty CSV snapshots found for league {league} in {live_dir}")
    return files_sorted


def group_snapshots_into_tourneys(files: list[Path]) -> list[list[Path]]:
    """Group snapshot files into tourneys by gap threshold.

    Each new tourney starts when the gap between consecutive snapshots is > GAP_HOURS.
    """
    groups = []
    if not files:
        return groups
    gap = datetime.timedelta(hours=GAP_HOURS)
    current = [files[0]]
    for prev, cur in zip(files, files[1:]):
        prev_t = get_time(prev)
        cur_t = get_time(cur)
        if (cur_t - prev_t) > gap:
            groups.append(current)
            current = [cur]
        else:
            current.append(cur)
    groups.append(current)
    return groups


def snapshot_iso(p: Path) -> str:
    return p.stem


def build_player_index_from_df(df: pd.DataFrame) -> dict:
    """
    Build a safe player index from a dataframe.

    This is defensive: it tolerates missing columns and NaN values and will
    populate sensible defaults rather than raising exceptions which would
    otherwise cause the whole generator to skip writing a good cache.
    """
    res = {}
    if df is None or df.empty:
        return res

    # Ensure expected columns exist
    cols = set(df.columns)
    has_player = "player_id" in cols
    has_real = "real_name" in cols
    has_wave = "wave" in cols
    has_bracket = "bracket" in cols

    if not has_player:
        return res

    for pid, group in df.groupby("player_id"):
        try:
            # real_name: prefer first non-null, else empty string
            real_name = ""
            if has_real:
                rn = group["real_name"].dropna()
                if not rn.empty:
                    real_name = str(rn.iloc[0])

            # highest_wave: take numeric max if present
            highest_wave = None
            if has_wave:
                try:
                    max_wave = group["wave"].dropna().max()
                    if pd.notna(max_wave):
                        highest_wave = int(max_wave)
                except Exception:
                    highest_wave = None

            # bracket: first non-null bracket value
            bracket = None
            if has_bracket:
                b = group["bracket"].dropna()
                if not b.empty:
                    bracket = str(b.iloc[0])

            res[str(pid)] = {"real_name": real_name, "highest_wave": highest_wave, "bracket": bracket}
        except Exception:
            # defensive fallback for an unexpected per-player error
            res[str(pid)] = {"real_name": "", "highest_wave": None, "bracket": None}

    return res


def process_tourney_group(league: str, group: list[Path], include_shun: bool = False):
    """Process a single tourney group (chronological list of snapshot Paths).

    Writes a flat cache file named {tourney_date}_placement_cache.json under
    the live results cache for the league, next to snapshots:
    LIVE_BASE/{league}_live/{tourney_date}_placement_cache.json
    """
    if not group:
        return
    first = group[0]
    tourney_date = get_time(first).date().isoformat()  # YYYY-MM-DD
    # Place cache files alongside snapshots under the league_live folder so
    # operators find them next to the CSVs (matching get_live_results.py layout)
    cache_file = LIVE_BASE / f"{league}_live" / f"{tourney_date}_placement_cache.json"

    # Load existing cache if present
    last_processed_iso = None
    bracket_times = {}
    player_index = {}
    existing_snapshot_iso = None

    if cache_file.exists():
        try:
            payload = json.loads(cache_file.read_text(encoding="utf8"))
            last_processed_iso = payload.get("last_processed_iso")
            bracket_times = payload.get("bracket_creation_times", {}) or {}
            player_index = payload.get("player_index", {}) or {}
            existing_snapshot_iso = payload.get("snapshot_iso")
            if payload.get("include_shun") != include_shun:
                logging.info(f"include_shun changed for {league} {tourney_date}; forcing full regen")
                last_processed_iso = None
                bracket_times = {}
                player_index = {}
        except Exception:
            logging.exception("Failed to load existing cache, regenerating")
            last_processed_iso = None
            bracket_times = {}
            player_index = {}

    # Build list of snapshots to process (those after last_processed_iso)
    to_process = []
    if last_processed_iso:
        try:
            last_dt = get_time(Path(last_processed_iso))
        except Exception:
            last_dt = None
    else:
        last_dt = None

    for p in group:
        p_dt = get_time(p)
        if (last_dt is None) or (p_dt > last_dt):
            to_process.append(p)

    if not to_process:
        logging.info(f"Cache up-to-date for {league} {tourney_date} (snapshot {existing_snapshot_iso})")
        return

    logging.info(f"Processing {len(to_process)} new snapshots for {league} {tourney_date}")

    for snap in to_process:
        try:
            # Read only this snapshot
            df = pd.read_csv(snap)
            # store full snapshot path so resume logic is robust
            snap_iso = str(snap.resolve())
            snap_time = get_time(snap).isoformat()

            # Record bracket first-seen time if new
            for br in df["bracket"].unique():
                if br not in bracket_times:
                    bracket_times[br] = snap_time

            # After processing snapshot, advance last_processed_iso
            last_processed_iso = snap_iso

            # Persist progress after each snapshot to make the generator resumable
            payload = {
                "tourney_date": tourney_date,
                # snapshot_iso and last_processed_iso are full snapshot path strings
                "snapshot_iso": last_processed_iso,
                "last_processed_iso": last_processed_iso,
                "include_shun": include_shun,
                # use timezone-aware UTC timestamp
                "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "bracket_creation_times": bracket_times,
                "player_index": player_index,
                "meta": {"num_brackets": len(bracket_times)},
            }
            atomic_write(cache_file, payload)
            logging.info(f"Wrote progress for {league} {tourney_date} at {last_processed_iso}")

        except Exception as e:
            logging.exception(f"Failed to process snapshot {snap} for {league} {tourney_date}: {e}")
            # stop processing further snapshots to retry later
            return

    # After processing all snapshots, update player_index from the latest snapshot
    # that actually contains player rows. Iterate from the end backwards so if
    # the final file for some reason is empty or malformed we pick the last
    # good snapshot instead of producing an empty player index.
    try:
        df_latest = None
        for snap in reversed(group):
            try:
                cand = pd.read_csv(snap)
                if cand is not None and not cand.empty and "player_id" in cand.columns:
                    df_latest = cand
                    break
            except Exception:
                # skip malformed snapshot and try the previous one
                continue

        if df_latest is None:
            logging.warning(f"No valid latest snapshot found for {league} {tourney_date}; keeping existing player_index")
        else:
            # Normalize and enrich the latest dataframe so build_player_index_from_df
            # has the columns it expects. Incoming live CSVs commonly have a
            # `name` column (tourney display name) rather than `real_name`.
            # Map player_id -> real_name using the same lookup used elsewhere
            # in the codebase to keep caches consistent with live views.
            try:
                lookup = get_player_id_lookup()
            except Exception:
                lookup = {}

            # populate real_name from lookup (fall back to CSV name if present)
            if "name" in df_latest.columns:
                df_latest["real_name"] = [lookup.get(pid, name) for pid, name in zip(df_latest.player_id, df_latest.name)]
            else:
                df_latest["real_name"] = [lookup.get(pid, "") for pid in df_latest.player_id]

            # normalize bracket strings and coerce wave to numeric where possible
            if "bracket" in df_latest.columns:
                df_latest["bracket"] = df_latest["bracket"].astype(str).map(lambda x: x.strip())
            if "wave" in df_latest.columns:
                df_latest["wave"] = pd.to_numeric(df_latest["wave"], errors="coerce")

            player_index = build_player_index_from_df(df_latest)

        payload = {
            "tourney_date": tourney_date,
            "snapshot_iso": last_processed_iso,
            "last_processed_iso": last_processed_iso,
            "include_shun": include_shun,
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "bracket_creation_times": bracket_times,
            "player_index": player_index,
            "meta": {"num_brackets": len(bracket_times), "num_players": len(player_index)},
        }
        atomic_write(cache_file, payload)
        logging.info(f"Finalized cache for {league} {tourney_date} (snap {last_processed_iso})")
    except Exception:
        logging.exception("Failed to update player_index from latest snapshot")


def execute_once():
    logging.info("Starting placement cache generation run")
    # Read current desired include_shun value for placement analysis so we
    # generate caches that match the UI configuration. This ensures that when
    # include_shun is flipped in `include_shun.json` the generator will produce
    # a cache with the matching payload and the consumer will accept it.
    include_shun = include_shun_enabled_for("live_placement")
    logging.info(f"Placement cache generation: include_shun={include_shun}")
    for league in leagues:
        try:
            snaps = list_live_snapshots(league)
            groups = group_snapshots_into_tourneys(snaps)
            logging.info(f"Found {len(groups)} tourney groups for league {league}")
            for group in groups:
                process_tourney_group(league, group, include_shun=include_shun)
        except Exception:
            logging.exception(f"Failed processing league {league}")
    logging.info("Placement cache generation run complete")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    if args.once:
        execute_once()
        return

    # run once immediately so the long-running process kicks off work
    # as soon as it starts, then fall into scheduled runs on :01 and :31
    # (this follows the schedule usage in get_live_results.py)
    execute_once()

    # schedule at :01 and :31 each hour (30-minute cycles anchored to the clock)
    schedule.every().hour.at(":01").do(execute_once)
    schedule.every().hour.at(":31").do(execute_once)
    logging.info("Scheduled placement cache generation on :01 and :31 each hour")

    while True:
        n = schedule.idle_seconds()
        if n is None:
            # no jobs scheduled? sleep a short while and re-evaluate
            n = 60
        logging.debug(f"Sleeping {n} seconds")
        time.sleep(min(n, 60))
        schedule.run_pending()


if __name__ == "__main__":
    main()
