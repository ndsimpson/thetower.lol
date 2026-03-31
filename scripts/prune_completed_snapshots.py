"""prune_completed_snapshots.py — Free storage by removing redundant snapshot files.

For each completed (non-current) tourney group that already has an archive,
deletes ALL snapshots in that group.  This is safe because:

  - ``data_ops.py`` only reads snapshots from the current (most recent) tourney group.
  - ``generate_placement_cache.py`` has already processed all old snapshots; its
    caches are complete and independent of the snapshot files.
  - ``regression_analysis.py`` reads from ``{league}/`` (historical CSVs), not
    from ``{league}_live/`` snapshots.
  - The delta archive can reconstruct any earlier state if needed.

The CURRENT tourney group (most recent) is always skipped.
Groups without an archive are always skipped — run build_archives.py first.

Usage (from repo root, venv activated):

    python scripts/prune_completed_snapshots.py             # dry-run, all leagues
    python scripts/prune_completed_snapshots.py --league Champion
    python scripts/prune_completed_snapshots.py --execute   # actually delete files
"""

import argparse
from pathlib import Path


def _fmt_bytes(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    if n >= 1_000:
        return f"{n / 1_000:.1f} KB"
    return f"{n} B"


def main() -> None:
    parser = argparse.ArgumentParser(description="Prune redundant snapshot files from completed tourneys")
    parser.add_argument("--league", default=None, help="Single league to process (default: all)")
    parser.add_argument("--execute", action="store_true", help="Actually delete files (default: dry-run)")
    parser.add_argument("--results-cache", default=None, help="Override CSV_DATA env var")
    args = parser.parse_args()

    from thetower.backend.env_config import get_csv_data
    from thetower.backend.tourney_results.archive_utils import (
        _archive_name_for_group,
        group_snapshots_by_tourney,
        list_snapshots,
    )
    from thetower.backend.tourney_results.constants import leagues

    results_cache = Path(args.results_cache) if args.results_cache else Path(get_csv_data())
    target_leagues = [args.league] if args.league else leagues

    mode_label = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"\n{'='*60}")
    print(f"prune_completed_snapshots  [{mode_label}]")
    if not args.execute:
        print("  (pass --execute to actually delete files)")
    print(f"{'='*60}")

    grand_deleted = 0
    grand_skipped = 0
    grand_bytes = 0

    for league in target_leagues:
        live_path = results_cache / f"{league}_live"
        if not live_path.exists():
            print(f"\n[{league}] Directory not found: {live_path} — skipping")
            continue

        snaps = list_snapshots(live_path)
        if not snaps:
            print(f"\n[{league}] No snapshots found — skipping")
            continue

        groups = group_snapshots_by_tourney(snaps)
        total_groups = len(groups)
        # Always skip the most recent group — may be in progress.
        completed_groups = groups[:-1]

        league_deleted = 0
        league_skipped = 0
        league_bytes = 0

        print(f"\n[{league}]  {len(snaps)} snapshots  |  {total_groups} groups  |  {len(completed_groups)} completed")

        for group in completed_groups:
            archive_path = live_path / _archive_name_for_group(group)
            group_date = archive_path.stem.replace("_archive", "")

            if not archive_path.exists():
                print(f"  {group_date}: no archive — SKIP (run build_archives.py first)")
                league_skipped += len(group)
                continue

            group_bytes = sum(p.stat().st_size for p in group)
            action = "DELETE" if args.execute else "would delete"
            print(f"  {group_date}: {action} {len(group)} snapshots ({_fmt_bytes(group_bytes)})")

            for p in group:
                if args.execute:
                    p.unlink()
            league_deleted += len(group)
            league_bytes += group_bytes

        grand_deleted += league_deleted
        grand_skipped += league_skipped
        grand_bytes += league_bytes

        print(f"  → {league}: {league_deleted} files  ({_fmt_bytes(league_bytes)} freed{'' if args.execute else ' potential'})")

    print(f"\n{'='*60}")
    action_label = "freed" if args.execute else "potential savings"
    print(f"Total files {'deleted' if args.execute else 'to delete'}: {grand_deleted}")
    if grand_skipped:
        print(f"Skipped (no archive): {grand_skipped} files — run build_archives.py first")
    print(f"Storage {action_label}: {_fmt_bytes(grand_bytes)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
