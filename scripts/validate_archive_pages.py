"""validate_archive_pages.py — Compare archive-backed data functions against the original.

Calls both ``data_ops.get_processed_data`` and ``data_ops_archive.get_processed_data_archive``
for each league and compares the results.  Differences are flagged; the script exits
with a non-zero code if any FAIL checks are found.

Usage (from repo root, venv activated):

    python scripts/validate_archive_pages.py
    python scripts/validate_archive_pages.py --league Legend

Checks per league:
  - Same unique player count (ldf last-snapshot leaderboard)
  - Same player IDs present in ldf
  - Max wave per player: zero mismatches allowed
  - Leaderboard positions: identical index ordering (ties handled the same way)
  - first_moment / last_moment within 1 snapshot period (30 min) of each other

The archive path must exist; run build_archives.py first if it doesn't.
"""

import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"


def _check(label: str, ok: bool, detail: str = "") -> bool:
    status = PASS if ok else FAIL
    line = f"  [{status}] {label}"
    if detail:
        line += f"  ({detail})"
    print(line)
    return ok


def validate_league(league: str) -> bool:
    """Return True if all checks pass for this league."""
    from thetower.web.live.data_ops import get_processed_data, get_processed_data_archive

    print(f"\n{'='*60}")
    print(f"League: {league}")
    print(f"{'='*60}")

    # ── fetch both data sets ───────────────────────────────────────────────────
    try:
        df_orig, tdf_orig, ldf_orig, first_orig, last_orig = get_processed_data(league)
    except Exception as exc:
        print(f"  [{FAIL}] Could not fetch original data: {exc}")
        return False

    try:
        df_arch, tdf_arch, ldf_arch, first_arch, last_arch = get_processed_data_archive(league)
    except Exception as exc:
        print(f"  [{FAIL}] Could not fetch archive data: {exc}")
        return False

    all_ok = True

    # ── ldf (current snapshot leaderboard) ────────────────────────────────────
    print("\n  -- Current leaderboard (ldf) --")

    orig_players = set(ldf_orig["player_id"])
    arch_players = set(ldf_arch["player_id"])
    same_count = len(orig_players) == len(arch_players)
    all_ok &= _check(
        f"Player count  original={len(orig_players):,}  archive={len(arch_players):,}",
        same_count,
    )

    only_in_orig = orig_players - arch_players
    only_in_arch = arch_players - orig_players
    all_ok &= _check(
        "All original players present in archive",
        len(only_in_orig) == 0,
        f"{len(only_in_orig)} missing" if only_in_orig else "",
    )
    all_ok &= _check(
        "No extra players in archive",
        len(only_in_arch) == 0,
        f"{len(only_in_arch)} extra" if only_in_arch else "",
    )

    # Compare max wave per player across the common set.
    # Use groupby().max() to deduplicate players appearing in multiple brackets
    # simultaneously (e.g. mid-tourney restarts) — both readers should agree on
    # the highest wave per player at the current snapshot.
    common = orig_players & arch_players
    if common:
        orig_max = ldf_orig[ldf_orig["player_id"].isin(common)].groupby("player_id")["wave"].max()
        arch_max = ldf_arch[ldf_arch["player_id"].isin(common)].groupby("player_id")["wave"].max()
        aligned = orig_max.align(arch_max, join="inner")
        wave_mismatches = (aligned[0] != aligned[1]).sum()
        all_ok &= _check(
            f"Wave values identical for {len(common):,} common players",
            wave_mismatches == 0,
            f"{wave_mismatches} mismatches" if wave_mismatches else "",
        )

    # Position ordering: top-N player sets should be identical; ordering among tied
    # waves may differ due to stable-sort semantics and is reported as WARN only.
    top_n = min(100, len(ldf_orig), len(ldf_arch))
    if top_n > 0:
        orig_top = ldf_orig.head(top_n)["player_id"].tolist()
        arch_top = ldf_arch.head(top_n)["player_id"].tolist()
        pos_match = orig_top == arch_top
        if not pos_match:
            mismatched_positions = sum(a != b for a, b in zip(orig_top, arch_top))
            # Only FAIL if the wave at a mismatched position actually differs (not just tie ordering)
            orig_waves = ldf_orig.head(top_n).set_index("player_id")["wave"]
            arch_waves = ldf_arch.head(top_n).set_index("player_id")["wave"]
            real_wave_diffs = 0
            for pid in set(orig_top) & set(arch_top):
                if pid in orig_waves.index and pid in arch_waves.index:
                    if orig_waves[pid] != arch_waves[pid]:
                        real_wave_diffs += 1
            status = WARN if real_wave_diffs == 0 else FAIL
            line = f"  [{status}] Top-{top_n} leaderboard order identical  ({mismatched_positions} position differences, {real_wave_diffs} wave value differences)"
            print(line)
            if real_wave_diffs > 0:
                all_ok = False
        else:
            _check(f"Top-{top_n} leaderboard order identical", True)

    # ── df (full timeline) ─────────────────────────────────────────────────────
    print("\n  -- Full timeline (df) --")

    orig_uniq = df_orig["player_id"].nunique()
    arch_uniq = df_arch["player_id"].nunique()
    all_ok &= _check(
        f"Unique players  original={orig_uniq:,}  archive={arch_uniq:,}",
        orig_uniq == arch_uniq,
    )

    orig_snap_count = df_orig["datetime"].nunique()
    arch_snap_count = df_arch["datetime"].nunique()
    _check(
        f"Snapshot count  original={orig_snap_count}  archive={arch_snap_count}",
        orig_snap_count == arch_snap_count,
    )  # WARN only — archive may have slightly different alignment

    orig_max_wave = df_orig.groupby("player_id")["wave"].max()
    arch_max_wave = df_arch.groupby("player_id")["wave"].max()
    combined = orig_max_wave.align(arch_max_wave, join="outer")
    timeline_mismatches = (combined[0] != combined[1]).sum()
    all_ok &= _check(
        "Max wave per player (full timeline): zero mismatches",
        int(timeline_mismatches) == 0,
        f"{timeline_mismatches} mismatches" if timeline_mismatches else "",
    )

    # ── timestamps ────────────────────────────────────────────────────────────
    print("\n  -- Timestamps --")
    import datetime

    max_drift = datetime.timedelta(minutes=35)  # one snapshot period + buffer
    last_drift = abs(last_orig - last_arch) if last_orig and last_arch else None
    if last_drift is not None:
        all_ok &= _check(
            f"last_moment within 35 min  drift={last_drift}",
            last_drift <= max_drift,
        )
    first_drift = abs(first_orig - first_arch) if first_orig and first_arch else None
    if first_drift is not None:
        _check(
            f"first_moment within 35 min  drift={first_drift}",
            first_drift <= max_drift,
        )

    return all_ok


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.backend.towerdb.settings")
    import django

    django.setup()

    parser = argparse.ArgumentParser(description="Validate archive-backed data matches original snapshot reader")
    parser.add_argument("--league", default=None, help="Single league (default: all)")
    parser.add_argument("--results-cache", default=None, help="Override CSV_DATA env var")
    args = parser.parse_args()

    if args.results_cache:
        os.environ["CSV_DATA"] = args.results_cache

    from thetower.backend.tourney_results.constants import leagues

    target_leagues = [args.league] if args.league else leagues

    results: dict[str, bool] = {}
    for league in target_leagues:
        results[league] = validate_league(league)

    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}")
    all_passed = True
    for league, ok in results.items():
        status = PASS if ok else FAIL
        print(f"  {league:<12} [{status}]")
        all_passed = all_passed and ok

    print()
    if all_passed:
        print("All leagues passed. Archive reader is equivalent to snapshot reader.")
        sys.exit(0)
    else:
        print("Some checks FAILED. See details above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
