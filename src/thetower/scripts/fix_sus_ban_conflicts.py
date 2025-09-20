#!/usr/bin/env python3
"""
Script to find and resolve conflicting moderation records where a player
has both active SUS and BAN records (which should not happen according to
our business logic).
"""

import os
import sys
from collections import defaultdict

import django

# Add the backend to Python path so we can import Django settings
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

# Set up Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "towerdb.settings")
django.setup()

from django.utils import timezone

from thetower.backend.sus.models import ModerationRecord


def find_conflicting_records():
    """Find players with both active SUS and BAN records."""
    print("Scanning for conflicting moderation records...")
    print("=" * 80)

    # Find all active sus and ban records
    active_sus = ModerationRecord.objects.filter(
        moderation_type='sus',
        resolved_at__isnull=True
    ).select_related('known_player').order_by('tower_id', 'created_at')

    active_bans = ModerationRecord.objects.filter(
        moderation_type='ban',
        resolved_at__isnull=True
    ).select_related('known_player').order_by('tower_id', 'created_at')

    # Group by tower_id
    sus_dict = defaultdict(list)
    for sus in active_sus:
        sus_dict[sus.tower_id].append(sus)

    ban_dict = defaultdict(list)
    for ban in active_bans:
        ban_dict[ban.tower_id].append(ban)

    # Find conflicting players
    conflicting_players = set(sus_dict.keys()) & set(ban_dict.keys())

    print(f"Total active SUS records: {active_sus.count()}")
    print(f"Total active BAN records: {active_bans.count()}")
    print(f"Players with BOTH active SUS and BAN: {len(conflicting_players)}")
    print()

    if not conflicting_players:
        print("✅ No conflicts found! All moderation records are properly exclusive.")
        return []

    conflicts = []
    for tower_id in sorted(conflicting_players):
        player_name = "Unknown"
        if sus_dict[tower_id] and sus_dict[tower_id][0].known_player:
            player_name = sus_dict[tower_id][0].known_player.name
        elif ban_dict[tower_id] and ban_dict[tower_id][0].known_player:
            player_name = ban_dict[tower_id][0].known_player.name

        print(f"⚠️  CONFLICT - Player: {tower_id} ({player_name})")

        sus_records = sus_dict[tower_id]
        ban_records = ban_dict[tower_id]

        print("   Active SUS records:")
        for sus in sus_records:
            reason = (sus.reason[:60] + '...') if sus.reason and len(sus.reason) > 60 else sus.reason or '(no reason)'
            print(f"     - ID {sus.pk}: {reason}")
            print(f"       Created: {sus.created_at} by {sus.created_by or sus.created_by_discord_id or sus.created_by_api_key or 'unknown'}")

        print("   Active BAN records:")
        for ban in ban_records:
            reason = (ban.reason[:60] + '...') if ban.reason and len(ban.reason) > 60 else ban.reason or '(no reason)'
            print(f"     - ID {ban.pk}: {reason}")
            print(f"       Created: {ban.created_at} by {ban.created_by or ban.created_by_discord_id or ban.created_by_api_key or 'unknown'}")
        print()

        conflicts.append({
            'tower_id': tower_id,
            'player_name': player_name,
            'sus_records': sus_records,
            'ban_records': ban_records
        })

    return conflicts


def resolve_conflicts(conflicts):
    """Resolve conflicts by auto-resolving SUS records when BAN exists."""
    if not conflicts:
        return

    print(f"\nResolving conflicts for {len(conflicts)} players...")

    for i, conflict in enumerate(conflicts, 1):
        tower_id = conflict['tower_id']
        player_name = conflict['player_name']
        sus_records = conflict['sus_records']
        ban_records = conflict['ban_records']

        print(f"  [{i}/{len(conflicts)}] Processing {tower_id} ({player_name})")

        # Resolve all SUS records for this player
        for sus in sus_records:
            sus.resolved_at = timezone.now()
            # Append resolution info to existing reason instead of using resolution_note
            resolution_info = "Automatically resolved due to conflicting ban record (script cleanup)"
            if sus.reason:
                sus.reason = f"{sus.reason}\n\nResolved: {resolution_info}"
            else:
                sus.reason = f"Resolved: {resolution_info}"
            sus.save()
            print(f"    ✅ Resolved SUS record ID {sus.pk}")

        print(f"    Resolved {len(sus_records)} SUS record(s), kept {len(ban_records)} BAN record(s) active")


def main():
    print("Moderation Record Conflict Detection & Resolution")
    print("=" * 60)
    print()

    try:
        conflicts = find_conflicting_records()

        if conflicts:
            # Show summary before asking for confirmation
            print("\n" + "="*80)
            print("CONFLICT RESOLUTION SUMMARY")
            print("="*80)

            # Analyze conflicts for summary
            total_sus_to_resolve = 0
            total_bans_to_keep = 0
            migration_conflicts = 0

            for conflict in conflicts:
                sus_count = len(conflict['sus_records'])
                ban_count = len(conflict['ban_records'])
                total_sus_to_resolve += sus_count
                total_bans_to_keep += ban_count

                # Check if this appears to be from migration (created by migration_correction or very close timestamps)
                sus_times = [sus.created_at for sus in conflict['sus_records']]
                ban_times = [ban.created_at for ban in conflict['ban_records']]

                # Check for migration attribution patterns
                migration_discord_ids = any(
                    sus.created_by_discord_id == 'migration_correction' or ban.created_by_discord_id == 'migration_correction'
                    for sus in conflict['sus_records']
                    for ban in conflict['ban_records']
                )

                # Check for very close timestamps (within 10 seconds, suggesting bulk operation)
                if sus_times and ban_times:
                    # If all records created within 10 seconds, likely migration/bulk operation
                    all_times = sus_times + ban_times
                    time_span = max(all_times) - min(all_times)
                    close_timestamps = time_span.total_seconds() <= 10
                else:
                    close_timestamps = False

                if migration_discord_ids or close_timestamps:
                    migration_conflicts += 1

            print(f"Total conflicts found: {len(conflicts)} players")
            print(f"Estimated migration-related conflicts: {migration_conflicts} players ({migration_conflicts/len(conflicts)*100:.1f}%)")
            print()
            print("Actions that will be taken:")
            print(f"  • Resolve {total_sus_to_resolve} SUS record(s) (mark as resolved)")
            print(f"  • Keep {total_bans_to_keep} BAN record(s) active (no changes)")
            print()
            print("Resolution note will be: 'Automatically resolved due to conflicting ban record (script cleanup)'")
            print("="*80)

            print("\nWould you like to automatically resolve these conflicts?")
            print("This will resolve (deactivate) SUS records when BAN records exist.")
            response = input("Continue with resolution? [y/N]: ").strip().lower()

            if response == 'y':
                resolve_conflicts(conflicts)
                print()
                print("✅ Conflict resolution complete!")
                print("   Re-running scan to verify...")
                print()
                final_conflicts = find_conflicting_records()
                if not final_conflicts:
                    print("🎉 All conflicts resolved successfully!")
                else:
                    print(f"⚠️  {len(final_conflicts)} conflicts remain (may need manual review)")
            else:
                print("No changes made.")

    except KeyboardInterrupt:
        print("\n\nScript interrupted by user.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
if __name__ == "__main__":
    main()
