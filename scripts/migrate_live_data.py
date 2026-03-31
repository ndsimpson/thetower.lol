#!/usr/bin/env python
"""
One-time migration script: converts existing {league}_live/ raw snapshots into
delta archives and raw tars, then deletes the originals after verification.

What it does for each league
-----------------------------
1. Scans {league}_live/ for raw snapshot .csv.gz files.
2. Groups them into per-tourney groups (8-hour gap threshold).
3. For each group:
   a. Builds (or rebuilds) the delta archive:  {league}_live/{date}_archive.csv.gz
   b. Verifies archive fidelity: each snapshot reconstructed row-for-row from archive.
   c. Bundles snapshots to raw tar:  {league}_raw/{date}_raw.tar
   d. Verifies tar contents byte-for-byte.
   e. Deletes the original snapshot files (only after both verifications pass).
4. Leaves placement cache .json files untouched.

Options
-------
--dry-run     Print what would happen without modifying anything.
--league X    Process only the named league (may be repeated).
--force       Rebuild archives even if they already exist (skip idempotency check).

Usage
-----
    python scripts/migrate_live_data.py --dry-run
    python scripts/migrate_live_data.py
    python scripts/migrate_live_data.py --league legend --dry-run
"""
import argparse
import logging
import os
import sys
from pathlib import Path

# Make sure the src layout is importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.backend.towerdb.settings")
django.setup()

from thetower.backend.env_config import get_csv_data
from thetower.backend.tourney_results.archive_utils import (
    build_tourney_archive,
    bundle_tourney_to_raw,
    get_raw_path,
    group_snapshots_by_tourney,
    list_snapshots,
    verify_archive_fidelity,
    verify_tar_contents,
)
from thetower.backend.tourney_results.constants import leagues as all_leagues

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

LIVE_BASE = Path(get_csv_data())


def _archive_path_for_group(league: str, group: list[Path]) -> Path:
    from thetower.backend.tourney_results.archive_utils import _parse_snapshot_time

    first_date = _parse_snapshot_time(group[0]).strftime("%Y-%m-%d")
    return LIVE_BASE / f"{league}_live" / f"{first_date}_archive.csv.gz"


def migrate_league(league: str, dry_run: bool, force: bool, no_delete: bool = False) -> dict:
    """Migrate one league. Returns a summary dict."""
    live_dir = LIVE_BASE / f"{league}_live"
    raw_dir = get_raw_path(league, LIVE_BASE)

    logger.info(f"=== {league}: scanning {live_dir} ===")

    snapshots = list_snapshots(live_dir)
    if not snapshots:
        logger.info(f"{league}: no snapshots found, nothing to do")
        return {"league": league, "groups": 0, "archived": 0, "tarred": 0, "deleted": 0, "errors": 0}

    groups = group_snapshots_by_tourney(snapshots)
    logger.info(f"{league}: found {len(snapshots)} snapshots across {len(groups)} tourney group(s)")

    summary = {"league": league, "groups": len(groups), "archived": 0, "tarred": 0, "deleted": 0, "errors": 0}

    for i, group in enumerate(groups):
        from thetower.backend.tourney_results.archive_utils import _parse_snapshot_time

        tourney_date = _parse_snapshot_time(group[0]).strftime("%Y-%m-%d")
        logger.info(f"{league} group {i + 1}/{len(groups)}: {tourney_date} ({len(group)} snapshots)")

        archive_path = _archive_path_for_group(league, group)
        tar_path = raw_dir / f"{tourney_date}_raw.tar"

        # ── Step 1: build/verify the delta archive ────────────────────────────
        if archive_path.exists() and not force:
            logger.info(f"  Archive already exists: {archive_path.name} — verifying (not rebuilding)")
        else:
            if dry_run:
                logger.info(f"  [DRY RUN] Would build archive: {archive_path.name}")
            else:
                logger.info(f"  Building archive: {archive_path.name}")
                try:
                    build_tourney_archive(group, write_path=archive_path)
                    summary["archived"] += 1
                    logger.info(f"  Built {archive_path.name}")
                except Exception:
                    logger.exception(f"  FAILED to build archive for {league} {tourney_date}")
                    summary["errors"] += 1
                    continue

        if dry_run:
            logger.info(f"  [DRY RUN] Would verify archive fidelity for {len(group)} snapshots")
        else:
            logger.info(f"  Verifying archive fidelity ({len(group)} snapshots)...")
            ok, errors = verify_archive_fidelity(group, archive_path)
            if not ok:
                for err in errors[:20]:
                    logger.error(f"  FIDELITY ERROR: {err}")
                if len(errors) > 20:
                    logger.error(f"  ... and {len(errors) - 20} more errors")
                logger.error(f"  ABORTING group {tourney_date} — archive fidelity check failed")
                summary["errors"] += 1
                continue
            logger.info("  Archive fidelity OK")

        # ── Step 2: bundle to raw tar ─────────────────────────────────────────
        if tar_path.exists() and not force:
            logger.info(f"  Raw tar already exists: {tar_path.name} — verifying (not re-bundling)")
        else:
            if dry_run:
                logger.info(f"  [DRY RUN] Would bundle to raw tar: {tar_path.name}")
            else:
                logger.info(f"  Bundling to raw tar: {tar_path.name}")
                try:
                    bundle_tourney_to_raw(group, raw_dir)
                    summary["tarred"] += 1
                    logger.info(f"  Bundled {tar_path.name}")
                except Exception:
                    logger.exception(f"  FAILED to bundle {league} {tourney_date} to raw tar")
                    summary["errors"] += 1
                    continue

        if dry_run:
            logger.info("  [DRY RUN] Would verify tar contents")
        else:
            logger.info("  Verifying tar contents...")
            ok, errors = verify_tar_contents(tar_path, group)
            if not ok:
                for err in errors[:20]:
                    logger.error(f"  TAR ERROR: {err}")
                if len(errors) > 20:
                    logger.error(f"  ... and {len(errors) - 20} more errors")
                logger.error(f"  ABORTING deletion for {league} {tourney_date} — tar verification failed")
                summary["errors"] += 1
                continue
            logger.info("  Tar contents verified")

        # ── Step 3: delete original snapshots ────────────────────────────────
        if dry_run:
            logger.info(f"  [DRY RUN] Would delete {len(group)} staging snapshots")
        elif no_delete or os.environ.get("NO_DELETE"):
            logger.info(f"  [NO-DELETE] Skipping deletion of {len(group)} snapshots")
        else:
            deleted = 0
            for snap in group:
                try:
                    snap.unlink()
                    deleted += 1
                except Exception as exc:
                    logger.error(f"  Failed to delete {snap.name}: {exc}")
                    summary["errors"] += 1
            summary["deleted"] += deleted
            logger.info(f"  Deleted {deleted}/{len(group)} snapshots for {league} {tourney_date}")

    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Preview without making any changes")
    parser.add_argument("--league", metavar="NAME", action="append", dest="leagues", help="Process only this league (may be repeated)")
    parser.add_argument("--force", action="store_true", help="Rebuild archives and tars even if they already exist")
    parser.add_argument("--no-delete", action="store_true", help="Build and verify archives/tars but skip deletion of originals")
    args = parser.parse_args()

    target_leagues = args.leagues or all_leagues
    unknown = set(target_leagues) - set(all_leagues)
    if unknown:
        logger.error(f"Unknown league(s): {', '.join(sorted(unknown))}. Valid: {', '.join(all_leagues)}")
        sys.exit(1)

    if args.dry_run:
        logger.info("=== DRY RUN — no files will be written or deleted ===")
    elif args.no_delete:
        logger.info("=== NO-DELETE mode — archives and tars will be built/verified, originals kept ===")

    logger.info(f"LIVE_BASE: {LIVE_BASE}")
    logger.info(f"Processing leagues: {', '.join(target_leagues)}")

    all_summaries = []
    for league in target_leagues:
        summary = migrate_league(league, dry_run=args.dry_run, force=args.force, no_delete=args.no_delete)
        all_summaries.append(summary)

    logger.info("=== Migration complete ===")
    logger.info(f"{'League':<12} {'Groups':>6} {'Archived':>9} {'Tarred':>7} {'Deleted':>8} {'Errors':>7}")
    logger.info("-" * 55)
    for s in all_summaries:
        logger.info(f"{s['league']:<12} {s['groups']:>6} {s['archived']:>9} {s['tarred']:>7} {s['deleted']:>8} {s['errors']:>7}")

    total_errors = sum(s["errors"] for s in all_summaries)
    if total_errors:
        logger.error(f"{total_errors} error(s) encountered — review logs above before deploying")
        sys.exit(1)
    else:
        logger.info("All migrations completed successfully")


if __name__ == "__main__":
    main()
