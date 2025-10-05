#!/usr/bin/env python3
"""
Fix ModerationRecord created_at timestamps using original SusPerson data.

During migration from SusPerson to ModerationRecord, the created_at field was
populated with the current time instead of preserving the original creation
timestamp from the SusPerson.created field. This script fixes that by
matching ModerationRecord entries back to their original SusPerson records
and updating the timestamps.

Usage:
    python fix_moderation_record_timestamps.py --dry-run    # Test run
    python fix_moderation_record_timestamps.py --execute    # Apply fixes
"""

import argparse
import logging
import os
import sys

import django

# Setup Django
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "towerdb.settings")
django.setup()

from django.db import transaction

from thetower.backend.sus.models import ModerationRecord, SusPerson

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('timestamp_fix.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def find_timestamp_mismatches():
    """
    Find ModerationRecord entries that were likely created during migration
    and have incorrect created_at timestamps.
    """
    logger.info("Scanning for ModerationRecord timestamp issues...")

    # Get all SusPerson records with their original timestamps
    sus_records = {
        sus.player_id: sus.created
        for sus in SusPerson.objects.all()
    }

    logger.info(f"Found {len(sus_records)} original SusPerson records")

    # Find ModerationRecord entries that could have timestamp issues
    moderation_records = ModerationRecord.objects.filter(
        source='manual'  # Focus on migrated records (likely marked as manual)
    ).select_related('known_player')

    mismatches = []
    for record in moderation_records:
        original_created = sus_records.get(record.tower_id)
        if original_created:
            # Check if the timestamps are significantly different (more than 1 minute apart)
            time_diff = abs((record.created_at - original_created).total_seconds())
            if time_diff > 60:  # More than 1 minute difference
                mismatches.append({
                    'record': record,
                    'current_created_at': record.created_at,
                    'original_created_at': original_created,
                    'time_difference': time_diff
                })

    logger.info(f"Found {len(mismatches)} records with timestamp mismatches")
    return mismatches, sus_records


def analyze_mismatches(mismatches):
    """Analyze the timestamp mismatches to understand the scope."""
    if not mismatches:
        logger.info("No timestamp mismatches found!")
        return

    logger.info("Timestamp Mismatch Analysis:")
    logger.info("=" * 60)

    total_records = len(mismatches)

    # Group by time difference ranges
    ranges = {
        'under_1_hour': 0,
        'under_1_day': 0,
        'under_1_week': 0,
        'over_1_week': 0
    }

    earliest_original = None
    latest_original = None
    earliest_current = None
    latest_current = None

    for mismatch in mismatches:
        time_diff = mismatch['time_difference']
        original = mismatch['original_created_at']
        current = mismatch['current_created_at']

        if earliest_original is None or original < earliest_original:
            earliest_original = original
        if latest_original is None or original > latest_original:
            latest_original = original
        if earliest_current is None or current < earliest_current:
            earliest_current = current
        if latest_current is None or current > latest_current:
            latest_current = current

        if time_diff < 3600:  # 1 hour
            ranges['under_1_hour'] += 1
        elif time_diff < 86400:  # 1 day
            ranges['under_1_day'] += 1
        elif time_diff < 604800:  # 1 week
            ranges['under_1_week'] += 1
        else:
            ranges['over_1_week'] += 1

    logger.info(f"Total records with timestamp issues: {total_records}")
    logger.info("Time difference distribution:")
    logger.info(f"  Under 1 hour:  {ranges['under_1_hour']} ({ranges['under_1_hour']/total_records*100:.1f}%)")
    logger.info(f"  Under 1 day:   {ranges['under_1_day']} ({ranges['under_1_day']/total_records*100:.1f}%)")
    logger.info(f"  Under 1 week:  {ranges['under_1_week']} ({ranges['under_1_week']/total_records*100:.1f}%)")
    logger.info(f"  Over 1 week:   {ranges['over_1_week']} ({ranges['over_1_week']/total_records*100:.1f}%)")
    logger.info("")
    logger.info(f"Original timestamp range: {earliest_original} to {latest_original}")
    logger.info(f"Current timestamp range:  {earliest_current} to {latest_current}")
    logger.info("")

    # Show some examples
    logger.info("Sample mismatches:")
    for i, mismatch in enumerate(mismatches[:5]):
        record = mismatch['record']
        player_name = record.known_player.name if record.known_player else "Unknown"
        time_diff_days = mismatch['time_difference'] / 86400
        logger.info(f"  {i+1}. Player {record.tower_id} ({player_name})")
        logger.info(f"     Original: {mismatch['original_created_at']}")
        logger.info(f"     Current:  {mismatch['current_created_at']}")
        logger.info(f"     Diff:     {time_diff_days:.1f} days")

    if len(mismatches) > 5:
        logger.info(f"  ... and {len(mismatches) - 5} more")


def fix_timestamps(mismatches, dry_run=True):
    """Fix the timestamp mismatches."""
    if not mismatches:
        logger.info("No timestamps to fix!")
        return

    if dry_run:
        logger.info(f"DRY RUN: Would fix {len(mismatches)} timestamp mismatches")
        return

    logger.info(f"Fixing {len(mismatches)} timestamp mismatches...")

    with transaction.atomic():
        fixed_count = 0
        for mismatch in mismatches:
            record = mismatch['record']
            original_created = mismatch['original_created_at']

            # Update the created_at timestamp
            record.created_at = original_created
            record.save(update_fields=['created_at'])

            fixed_count += 1
            if fixed_count % 100 == 0:
                logger.info(f"  Fixed {fixed_count}/{len(mismatches)} records...")

        logger.info(f"✅ Successfully fixed {fixed_count} timestamp mismatches")


def main():
    parser = argparse.ArgumentParser(description="Fix ModerationRecord created_at timestamps")
    parser.add_argument('--dry-run', action='store_true', help='Test run without making changes')
    parser.add_argument('--execute', action='store_true', help='Actually fix the timestamps')

    args = parser.parse_args()

    if not args.dry_run and not args.execute:
        parser.error("Must specify either --dry-run or --execute")

    if args.execute and args.dry_run:
        parser.error("Cannot specify both --dry-run and --execute")

    logger.info("ModerationRecord Timestamp Fix Tool")
    logger.info("=" * 50)
    logger.info("")

    try:
        # Find mismatches
        mismatches, sus_records = find_timestamp_mismatches()

        # Analyze the issues
        analyze_mismatches(mismatches)

        if mismatches:
            logger.info("")
            if args.dry_run:
                logger.info("This was a DRY RUN - no changes made")
                logger.info("To actually fix these timestamps, run with --execute")
            else:
                # Ask for confirmation before making changes
                logger.info("This will update the created_at timestamps for the affected records.")
                response = input("Continue with timestamp fixes? [y/N]: ").strip().lower()

                if response == 'y':
                    fix_timestamps(mismatches, dry_run=False)
                    logger.info("")
                    logger.info("✅ Timestamp fix complete!")

                    # Verify the fixes
                    logger.info("Verifying fixes...")
                    new_mismatches, _ = find_timestamp_mismatches()
                    if not new_mismatches:
                        logger.info("🎉 All timestamp issues resolved!")
                    else:
                        logger.info(f"⚠️  {len(new_mismatches)} issues remain (may need manual review)")
                else:
                    logger.info("No changes made.")

        logger.info("")
        logger.info("Timestamp fix tool completed.")

    except KeyboardInterrupt:
        logger.info("Script interrupted by user.")
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
