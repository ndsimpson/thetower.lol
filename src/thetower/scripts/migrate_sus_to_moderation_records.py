#!/usr/bin/env python3
"""
Phase 2 Data Migration: SusPerson → ModerationRecord

This script migrates existing SusPerson data to the new ModerationRecord system,
reconstructing full history from HistoricalSusPerson records.

Features:
- Full history reconstruction from django-simple-history
- Hybrid linking: auto-link to KnownPlayer where possible
- Dry-run mode for safe testing
- Comprehensive validation and reporting
- Support for API vs manual attribution
- Edge case handling (orphaned records, missing history)

Usage:
    python migrate_sus_to_moderation_records.py --dry-run    # Test run
    python migrate_sus_to_moderation_records.py --execute    # Real migration
"""

import argparse
import logging
import os
import sys
from collections import defaultdict
from typing import Dict, List, Optional

import django
from django.utils import timezone

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.backend.towerdb.settings")
django.setup()

from django.db import transaction

from thetower.backend.sus.models import (
    ApiKey,
    HistoricalSusPerson,
    KnownPlayer,
    ModerationRecord,
    PlayerId,
    SusPerson,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('migration.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class ModerationMigrator:
    """Handles migration from SusPerson to ModerationRecord system."""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.stats = {
            'sus_records_found': 0,
            'historical_records_found': 0,
            'moderation_records_created': 0,
            'auto_linked_players': 0,
            'unverified_players': 0,
            'api_attributed': 0,
            'manual_attributed': 0,
            'errors': 0,
        }

        # Cache for performance
        self.player_id_cache: Dict[str, KnownPlayer] = {}
        self.api_key_cache: Dict[str, ApiKey] = {}

    def load_caches(self):
        """Pre-load caches for better performance."""
        logger.info("Loading caches...")

        # Load PlayerId → KnownPlayer mapping
        for player_id in PlayerId.objects.select_related('player'):
            self.player_id_cache[player_id.id] = player_id.player

        # Load API keys
        for api_key in ApiKey.objects.all():
            self.api_key_cache[api_key.key] = api_key

        logger.info(f"Cached {len(self.player_id_cache)} player IDs and {len(self.api_key_cache)} API keys")

    def cleanup_data_issues(self):
        """Clean up known data issues in SusPerson and HistoricalSusPerson records."""
        logger.info("Cleaning up data issues...")

        cleanup_actions = []

        # Define cleanup mappings
        PLAYER_ID_FIXES = {
            # Remove trailing comma
            'DB72BC63F5F5D8BD,': 'DB72BC63F5F5D8BD',
            # Discord ID to proper Tower ID
            '570066733717782538': 'B3326FD8B667EE6C',
        }

        # Player IDs to delete (invalid entries)
        DELETE_PLAYER_IDS = {
            'Abuse of bracket hopping/offline',  # This is descriptive text, not a player ID
        }

        # Player moderation type corrections
        MODERATION_TYPE_FIXES = {
            'E4F73339F5A39675': 'ban',  # Change from sus to ban
        }

        # Fix player ID mappings
        for old_id, new_id in PLAYER_ID_FIXES.items():
            logger.info(f"Fixing player ID: '{old_id}' -> '{new_id}'")

            if not self.dry_run:
                # Update SusPerson records
                sus_updated = SusPerson.objects.filter(player_id=old_id).update(player_id=new_id)
                if sus_updated:
                    logger.info(f"  Updated {sus_updated} SusPerson records")
                    cleanup_actions.append(f"Updated SusPerson {old_id} -> {new_id}")

                # Update HistoricalSusPerson records
                hist_updated = HistoricalSusPerson.objects.filter(player_id=old_id).update(player_id=new_id)
                if hist_updated:
                    logger.info(f"  Updated {hist_updated} HistoricalSusPerson records")
                    cleanup_actions.append(f"Updated HistoricalSusPerson {old_id} -> {new_id}")
            else:
                # Dry run - just count what would be updated
                sus_count = SusPerson.objects.filter(player_id=old_id).count()
                hist_count = HistoricalSusPerson.objects.filter(player_id=old_id).count()
                logger.info(f"  [DRY RUN] Would update {sus_count} SusPerson + {hist_count} HistoricalSusPerson records")

        # Delete invalid entries
        for invalid_id in DELETE_PLAYER_IDS:
            logger.info(f"Deleting invalid player ID: '{invalid_id}'")

            if not self.dry_run:
                # Delete SusPerson records
                sus_deleted = SusPerson.objects.filter(player_id=invalid_id).delete()
                if sus_deleted[0]:
                    logger.info(f"  Deleted {sus_deleted[0]} SusPerson records")
                    cleanup_actions.append(f"Deleted SusPerson {invalid_id}")

                # Delete HistoricalSusPerson records
                hist_deleted = HistoricalSusPerson.objects.filter(player_id=invalid_id).delete()
                if hist_deleted[0]:
                    logger.info(f"  Deleted {hist_deleted[0]} HistoricalSusPerson records")
                    cleanup_actions.append(f"Deleted HistoricalSusPerson {invalid_id}")
            else:
                # Dry run - just count what would be deleted
                sus_count = SusPerson.objects.filter(player_id=invalid_id).count()
                hist_count = HistoricalSusPerson.objects.filter(player_id=invalid_id).count()
                logger.info(f"  [DRY RUN] Would delete {sus_count} SusPerson + {hist_count} HistoricalSusPerson records")

        # Apply moderation type corrections
        for player_id, correct_type in MODERATION_TYPE_FIXES.items():
            logger.info(f"Correcting moderation type for {player_id} to '{correct_type}'")

            if not self.dry_run:
                # Update SusPerson records to reflect correct moderation type
                sus_records = SusPerson.objects.filter(player_id=player_id)
                hist_records = HistoricalSusPerson.objects.filter(player_id=player_id)

                if correct_type == 'ban':
                    # Set to banned status
                    sus_updated = sus_records.update(sus=False, banned=True, soft_banned=False, shun=False)
                    hist_updated = hist_records.update(sus=False, banned=True, soft_banned=False, shun=False)
                elif correct_type == 'sus':
                    # Set to sus status
                    sus_updated = sus_records.update(sus=True, banned=False, soft_banned=False, shun=False)
                    hist_updated = hist_records.update(sus=True, banned=False, soft_banned=False, shun=False)
                elif correct_type == 'soft_banned':
                    # Set to soft banned status
                    sus_updated = sus_records.update(sus=False, banned=False, soft_banned=True, shun=False)
                    hist_updated = hist_records.update(sus=False, banned=False, soft_banned=True, shun=False)
                elif correct_type == 'shun':
                    # Set to shun status
                    sus_updated = sus_records.update(sus=False, banned=False, soft_banned=False, shun=True)
                    hist_updated = hist_records.update(sus=False, banned=False, soft_banned=False, shun=True)

                if sus_updated:
                    logger.info(f"  Updated {sus_updated} SusPerson records to {correct_type}")
                    cleanup_actions.append(f"Changed {player_id} moderation type to {correct_type} (SusPerson)")

                if hist_updated:
                    logger.info(f"  Updated {hist_updated} HistoricalSusPerson records to {correct_type}")
                    cleanup_actions.append(f"Changed {player_id} moderation type to {correct_type} (Historical)")
            else:
                # Dry run - just count what would be updated
                sus_count = SusPerson.objects.filter(player_id=player_id).count()
                hist_count = HistoricalSusPerson.objects.filter(player_id=player_id).count()
                logger.info(f"  [DRY RUN] Would update {sus_count} SusPerson + {hist_count} HistoricalSusPerson records to {correct_type}")

        logger.info(f"Data cleanup completed: {len(cleanup_actions)} actions taken")
        return cleanup_actions

    def fix_moderation_records(self):
        """Fix ModerationRecord entries after migration."""
        logger.info("Fixing ModerationRecord entries...")

        # Player moderation corrections - these should replace existing moderation types
        MODERATION_CORRECTIONS = {
            'E4F73339F5A39675': 'ban',  # Should be banned only, not sus
        }

        corrections_made = []

        for player_id, correct_type in MODERATION_CORRECTIONS.items():
            logger.info(f"Correcting ModerationRecord for {player_id} to only '{correct_type}'")

            if not self.dry_run:
                # Get all active moderation records for this player
                active_records = ModerationRecord.objects.filter(
                    tower_id=player_id,
                    resolved_at__isnull=True
                )

                # Resolve all current records
                now = timezone.now()
                deactivated = active_records.update(resolved_at=now)
                if deactivated:
                    logger.info(f"  Resolved {deactivated} existing ModerationRecord entries")

                # Create new record with correct type
                ModerationRecord.objects.create(
                    tower_id=player_id,
                    moderation_type=correct_type,
                    started_at=now,
                    reason="120 relics\nNo record on tower.lol",
                    created_by_api_key=None,
                    created_by=None,
                    created_by_discord_id="migration_correction"
                )
                logger.info(f"  Created new {correct_type} ModerationRecord")
                corrections_made.append(f"Corrected {player_id} to {correct_type} only")
            else:
                # Dry run
                active_count = ModerationRecord.objects.filter(
                    tower_id=player_id,
                    resolved_at__isnull=True
                ).count()
                logger.info(f"  [DRY RUN] Would resolve {active_count} records and create 1 new {correct_type} record")

        logger.info(f"ModerationRecord corrections completed: {len(corrections_made)} corrections made")
        return corrections_made

    def analyze_current_data(self) -> Dict:
        """Analyze existing SusPerson data."""
        logger.info("Analyzing current data...")

        sus_records = SusPerson.objects.all()
        historical_records = HistoricalSusPerson.objects.all().order_by('history_date')

        analysis = {
            'total_sus_records': sus_records.count(),
            'total_historical_records': historical_records.count(),
            'moderation_types': defaultdict(int),
            'attribution_sources': defaultdict(int),
            'players_with_history': set(),
            'orphaned_records': [],
        }

        # Analyze current moderation states
        for sus_record in sus_records:
            if sus_record.sus:
                analysis['moderation_types']['sus'] += 1
            if sus_record.banned:
                analysis['moderation_types']['banned'] += 1
            if sus_record.soft_banned:
                analysis['moderation_types']['soft_banned'] += 1
            if sus_record.shun:
                analysis['moderation_types']['shun'] += 1

            # Check attribution
            if sus_record.api_ban or sus_record.api_sus:
                analysis['attribution_sources']['api'] += 1
            else:
                analysis['attribution_sources']['manual'] += 1

            # Check if player exists in KnownPlayer system
            if sus_record.player_id not in self.player_id_cache:
                analysis['orphaned_records'].append(sus_record.player_id)

        # Track players with history
        for hist_record in historical_records:
            analysis['players_with_history'].add(hist_record.player_id)

        self.stats.update({
            'sus_records_found': analysis['total_sus_records'],
            'historical_records_found': analysis['total_historical_records'],
        })

        return analysis

    def reconstruct_player_history(self, player_id: str) -> List[Dict]:
        """Reconstruct full moderation history for a player."""

        # Get all historical records for this player, ordered by date
        historical_records = list(
            HistoricalSusPerson.objects
            .filter(player_id=player_id)
            .order_by('history_date')
        )

        if not historical_records:
            # No history - use current state
            try:
                current = SusPerson.objects.get(player_id=player_id)
                return self._create_moderation_events_from_current(current)
            except SusPerson.DoesNotExist:
                return []

        # Reconstruct timeline from history
        events = []
        previous_state = None

        for record in historical_records:
            if previous_state is None:
                # First record - all active flags are "created" events
                events.extend(self._detect_creation_events(record))
            else:
                # Compare with previous state to detect changes
                events.extend(self._detect_change_events(previous_state, record))

            previous_state = record

        return events

    def _create_moderation_events_from_current(self, sus_record: SusPerson) -> List[Dict]:
        """Create moderation events from current SusPerson state (no history)."""
        events = []
        base_event = {
            'player_id': sus_record.player_id,
            'created_at': sus_record.created,
            'source': self._determine_source(sus_record),
            'reason': sus_record.notes or "Migrated from existing SusPerson record",
        }

        # Create events for active moderation types
        if sus_record.sus:
            events.append({
                **base_event,
                'moderation_type': ModerationRecord.ModerationType.SUS,
                'api_key_hint': sus_record.api_sus,
            })

        if sus_record.banned:
            events.append({
                **base_event,
                'moderation_type': ModerationRecord.ModerationType.BAN,
                'api_key_hint': sus_record.api_ban,
            })

        if sus_record.soft_banned:
            events.append({
                **base_event,
                'moderation_type': ModerationRecord.ModerationType.SOFT_BAN,
                'api_key_hint': False,  # soft_ban doesn't have API flag
            })

        if sus_record.shun:
            events.append({
                **base_event,
                'moderation_type': ModerationRecord.ModerationType.SHUN,
                'api_key_hint': False,  # shun doesn't have API flag
            })

        return events

    def _detect_creation_events(self, record: HistoricalSusPerson) -> List[Dict]:
        """Detect initial moderation events from first historical record."""
        events = []
        base_event = {
            'player_id': record.player_id,
            'created_at': record.history_date,
            'source': self._determine_source_from_history(record),
            'reason': record.notes or "Migrated from historical record",
            'history_user': record.history_user,
        }

        if record.sus:
            events.append({
                **base_event,
                'moderation_type': ModerationRecord.ModerationType.SUS,
                'api_key_hint': getattr(record, 'api_sus', False),
            })

        if record.banned:
            events.append({
                **base_event,
                'moderation_type': ModerationRecord.ModerationType.BAN,
                'api_key_hint': getattr(record, 'api_ban', False),
            })

        if getattr(record, 'soft_banned', False):
            events.append({
                **base_event,
                'moderation_type': ModerationRecord.ModerationType.SOFT_BAN,
                'api_key_hint': False,
            })

        if getattr(record, 'shun', False):
            events.append({
                **base_event,
                'moderation_type': ModerationRecord.ModerationType.SHUN,
                'api_key_hint': False,
            })

        return events

    def _detect_change_events(self, prev: HistoricalSusPerson, curr: HistoricalSusPerson) -> List[Dict]:
        """Detect moderation changes between two historical records."""
        events = []
        base_event = {
            'player_id': curr.player_id,
            'created_at': curr.history_date,
            'source': self._determine_source_from_history(curr),
            'reason': curr.notes or "Migrated from historical change",
            'history_user': curr.history_user,
        }

        # Check sus changes
        if not prev.sus and curr.sus:
            events.append({
                **base_event,
                'moderation_type': ModerationRecord.ModerationType.SUS,
                'api_key_hint': getattr(curr, 'api_sus', False),
            })
        elif prev.sus and not curr.sus:
            # Resolution event
            events.append({
                **base_event,
                'moderation_type': ModerationRecord.ModerationType.SUS,
                'is_resolution': True,
            })

        # Check ban changes
        if not prev.banned and curr.banned:
            events.append({
                **base_event,
                'moderation_type': ModerationRecord.ModerationType.BAN,
                'api_key_hint': getattr(curr, 'api_ban', False),
            })
        elif prev.banned and not curr.banned:
            events.append({
                **base_event,
                'moderation_type': ModerationRecord.ModerationType.BAN,
                'is_resolution': True,
            })

        # Check soft_ban changes (if field exists)
        prev_soft_banned = getattr(prev, 'soft_banned', False)
        curr_soft_banned = getattr(curr, 'soft_banned', False)
        if not prev_soft_banned and curr_soft_banned:
            events.append({
                **base_event,
                'moderation_type': ModerationRecord.ModerationType.SOFT_BAN,
                'api_key_hint': False,
            })
        elif prev_soft_banned and not curr_soft_banned:
            events.append({
                **base_event,
                'moderation_type': ModerationRecord.ModerationType.SOFT_BAN,
                'is_resolution': True,
            })

        # Check shun changes (if field exists)
        prev_shun = getattr(prev, 'shun', False)
        curr_shun = getattr(curr, 'shun', False)
        if not prev_shun and curr_shun:
            events.append({
                **base_event,
                'moderation_type': ModerationRecord.ModerationType.SHUN,
                'api_key_hint': False,
            })
        elif prev_shun and not curr_shun:
            events.append({
                **base_event,
                'moderation_type': ModerationRecord.ModerationType.SHUN,
                'is_resolution': True,
            })

        return events

    def _determine_source(self, sus_record: SusPerson) -> str:
        """Determine the source of a moderation action."""
        if sus_record.api_ban or sus_record.api_sus:
            return ModerationRecord.ModerationSource.API
        return ModerationRecord.ModerationSource.MANUAL

    def _determine_source_from_history(self, hist_record: HistoricalSusPerson) -> str:
        """Determine source from historical record."""
        if getattr(hist_record, 'api_ban', False) or getattr(hist_record, 'api_sus', False):
            return ModerationRecord.ModerationSource.API
        return ModerationRecord.ModerationSource.MANUAL

    def create_moderation_record(self, event: Dict) -> Optional[ModerationRecord]:
        """Create a ModerationRecord from an event."""
        try:
            # Determine known_player (auto-linking)
            known_player = self.player_id_cache.get(event['player_id'])

            # Handle resolution vs creation
            if event.get('is_resolution', False):
                # This is a resolution event - find the original record to resolve
                original = ModerationRecord.objects.filter(
                    tower_id=event['player_id'],
                    moderation_type=event['moderation_type'],
                    resolved_at__isnull=True  # Active = not resolved
                ).first()

                if original:
                    original.resolve(
                        resolved_by_user=event.get('history_user'),
                        resolution_note="Resolved during migration from historical data"
                    )
                    logger.debug(f"Resolved {event['moderation_type']} for {event['player_id']}")
                return None  # No new record created for resolution

            # Create new moderation record
            record_kwargs = {
                'tower_id': event['player_id'],
                'known_player': known_player,
                'moderation_type': event['moderation_type'],
                'source': event['source'],
                'started_at': event['created_at'],
                'reason': event['reason'],
                'created_at': event['created_at'],
            }

            # Set attribution based on source
            if event['source'] == ModerationRecord.ModerationSource.API and event.get('api_key_hint'):
                # Try to find the API key (this is tricky without more context)
                # For now, we'll leave API key attribution empty
                # In a real scenario, you might need additional logic to determine which API key
                pass
            elif event.get('history_user'):
                record_kwargs['created_by'] = event['history_user']

            if not self.dry_run:
                record = ModerationRecord.objects.create(**record_kwargs)
            else:
                record = ModerationRecord(**record_kwargs)
                logger.debug(f"[DRY RUN] Would create: {record}")

            # Update stats
            self.stats['moderation_records_created'] += 1
            if known_player:
                self.stats['auto_linked_players'] += 1
            else:
                self.stats['unverified_players'] += 1

            if event['source'] == ModerationRecord.ModerationSource.API:
                self.stats['api_attributed'] += 1
            else:
                self.stats['manual_attributed'] += 1

            return record

        except Exception as e:
            logger.error(f"Error creating moderation record for {event}: {e}")
            self.stats['errors'] += 1
            return None

    def migrate_all_players(self) -> bool:
        """Migrate all SusPerson records to ModerationRecord."""
        logger.info("Starting migration of all players...")

        # Get all unique player IDs
        sus_player_ids = set(SusPerson.objects.values_list('player_id', flat=True))
        historical_player_ids = set(HistoricalSusPerson.objects.values_list('player_id', flat=True))
        all_player_ids = sus_player_ids | historical_player_ids

        logger.info(f"Found {len(all_player_ids)} unique players to migrate")

        success_count = 0

        for i, player_id in enumerate(all_player_ids, 1):
            if i % 100 == 0:
                logger.info(f"Processed {i}/{len(all_player_ids)} players...")

            try:
                # Reconstruct history for this player
                events = self.reconstruct_player_history(player_id)

                # Create ModerationRecord entries
                for event in events:
                    self.create_moderation_record(event)

                success_count += 1

            except Exception as e:
                logger.error(f"Error migrating player {player_id}: {e}")
                self.stats['errors'] += 1

        logger.info(f"Migration completed: {success_count}/{len(all_player_ids)} players processed successfully")
        return self.stats['errors'] == 0

    def validate_migration(self) -> bool:
        """Validate that migration preserved all data correctly."""
        logger.info("Validating migration...")

        validation_errors = []

        # Check that all SusPerson records have corresponding ModerationRecord entries
        for sus_record in SusPerson.objects.all():
            moderation_records = ModerationRecord.objects.filter(tower_id=sus_record.player_id)

            expected_types = []
            if sus_record.sus:
                expected_types.append(ModerationRecord.ModerationType.SUS)
            if sus_record.banned:
                expected_types.append(ModerationRecord.ModerationType.BAN)
            if sus_record.soft_banned:
                expected_types.append(ModerationRecord.ModerationType.SOFT_BAN)
            if sus_record.shun:
                expected_types.append(ModerationRecord.ModerationType.SHUN)

            existing_types = set(moderation_records.filter(
                resolved_at__isnull=True  # Active = not resolved
            ).values_list('moderation_type', flat=True))

            missing_types = set(expected_types) - existing_types
            if missing_types:
                validation_errors.append(
                    f"Player {sus_record.player_id} missing moderation types: {missing_types}"
                )

        if validation_errors:
            logger.error(f"Validation failed with {len(validation_errors)} errors:")
            for error in validation_errors[:10]:  # Show first 10 errors
                logger.error(f"  {error}")
            if len(validation_errors) > 10:
                logger.error(f"  ... and {len(validation_errors) - 10} more errors")

        return len(validation_errors) == 0

    def print_statistics(self):
        """Print migration statistics."""
        print("\n" + "="*60)
        print("MIGRATION STATISTICS")
        print("="*60)

        for key, value in self.stats.items():
            print(f"{key.replace('_', ' ').title()}: {value:,}")

        print("="*60)

        if self.dry_run:
            print("🧪 DRY RUN COMPLETED - No actual changes made")
        else:
            print("✅ MIGRATION COMPLETED")

    def clear_existing_moderation_records(self):
        """Clear existing ModerationRecord data to avoid duplicates."""
        logger.info("Clearing existing ModerationRecord data...")

        if not self.dry_run:
            count = ModerationRecord.objects.count()
            if count > 0:
                ModerationRecord.objects.all().delete()
                logger.info(f"Deleted {count} existing ModerationRecord entries")
            else:
                logger.info("No existing ModerationRecord entries to delete")
        else:
            count = ModerationRecord.objects.count()
            logger.info(f"[DRY RUN] Would delete {count} existing ModerationRecord entries")

    def run(self) -> bool:
        """Run the complete migration process."""
        logger.info(f"Starting migration (dry_run={self.dry_run})...")

        try:
            # Step 1: Load caches
            self.load_caches()

            # Step 2: Clear existing ModerationRecord data
            self.clear_existing_moderation_records()

            # Step 3: Clean up data issues
            self.cleanup_data_issues()

            # Step 4: Analyze current data
            analysis = self.analyze_current_data()
            logger.info(f"Analysis complete: {analysis['total_sus_records']} SusPerson records, "
                        f"{analysis['total_historical_records']} historical records")

            # Step 5: Migrate all players
            if not self.dry_run:
                with transaction.atomic():
                    success = self.migrate_all_players()
            else:
                success = self.migrate_all_players()

            # Step 6: Fix ModerationRecord entries (post-migration corrections)
            if success:
                self.fix_moderation_records()

            # Step 7: Validate (only for real runs)
            if not self.dry_run and success:
                success = self.validate_migration()

            # Step 7: Print statistics
            self.print_statistics()

            return success

        except Exception as e:
            logger.error(f"Migration failed: {e}")
            return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Migrate SusPerson to ModerationRecord")
    parser.add_argument('--dry-run', action='store_true',
                        help='Run in dry-run mode (no actual changes)')
    parser.add_argument('--execute', action='store_true',
                        help='Execute the actual migration')

    args = parser.parse_args()

    if not args.dry_run and not args.execute:
        print("ERROR: Must specify either --dry-run or --execute")
        print("Use --dry-run to test the migration safely")
        sys.exit(1)

    if args.execute:
        response = input("This will modify the database. Are you sure? (yes/no): ")
        if response.lower() != 'yes':
            print("Migration cancelled.")
            sys.exit(0)

    # Run migration
    migrator = ModerationMigrator(dry_run=args.dry_run)
    success = migrator.run()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
