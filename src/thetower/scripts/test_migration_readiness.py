#!/usr/bin/env python3
"""
Test runner for the SusPerson → ModerationRecord migration.

This script provides safe testing utilities for the migration process.
"""

import os
import sys

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.backend.towerdb.settings")
django.setup()

from thetower.backend.sus.models import HistoricalSusPerson, ModerationRecord, SusPerson


def test_data_availability():
    """Test that we have data to migrate and the environment is set up correctly."""
    print("Testing data availability...")

    sus_count = SusPerson.objects.count()
    hist_count = HistoricalSusPerson.objects.count()
    existing_mod_count = ModerationRecord.objects.count()

    print(f"Current SusPerson records: {sus_count}")
    print(f"Historical SusPerson records: {hist_count}")
    print(f"Existing ModerationRecord records: {existing_mod_count}")

    if sus_count == 0 and hist_count == 0:
        print("⚠️  No SusPerson data found - migration may not be needed")
        return False

    if existing_mod_count > 0:
        print(f"⚠️  Found {existing_mod_count} existing ModerationRecord entries")
        print("   Migration may have already been run or partially run")

    # Sample a few records for inspection
    if sus_count > 0:
        print("\nSample SusPerson records:")
        for sus in SusPerson.objects.all()[:3]:
            print(f"  Player: {sus.player_id}, Sus: {sus.sus}, Banned: {sus.banned}, "
                  f"API flags: sus={getattr(sus, 'api_sus', 'N/A')}, ban={getattr(sus, 'api_ban', 'N/A')}")

    if hist_count > 0:
        print("\nSample Historical records:")
        for hist in HistoricalSusPerson.objects.all()[:3]:
            print(f"  Player: {hist.player_id}, Date: {hist.history_date}, "
                  f"User: {hist.history_user}, Type: {hist.history_type}")

    print("✅ Environment setup looks good!")
    return True


def main():
    """Main test runner."""
    print("="*60)
    print("MIGRATION PRE-FLIGHT CHECK")
    print("="*60)

    try:
        # Test basic environment
        if not test_data_availability():
            print("\n❌ Pre-flight check failed")
            return False

        print("\n✅ Pre-flight check passed!")
        print("\nNext steps:")
        print("1. Run: python migrate_sus_to_moderation_records.py --dry-run")
        print("2. Review the dry-run output carefully")
        print("3. If everything looks good: python migrate_sus_to_moderation_records.py --execute")

        return True

    except Exception as e:
        print(f"❌ Pre-flight check failed with error: {e}")
        return False


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
