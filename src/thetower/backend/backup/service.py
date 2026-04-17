"""Backup service entry point.

Runs as a persistent background service:
  - Tar backup:  on startup and daily at 03:00 UTC (uploads new tars to R2, deletes local copies)
  - DB backup:   on startup and daily at 03:00 UTC (VACUUM INTO → gzip → R2)
                 DB backup is idempotent: skips if today's R2 key already exists.

Environment variables required:
    R2_ACCOUNT_ID, R2_BUCKET_NAME
    R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY   (Edit+Read key for backup service)
    DJANGO_DATA     (path to /data/django — contains tower.sqlite3)
    CSV_DATA        (path to /data/results_cache — contains {league}_raw/)

Usage:
    python -m thetower.backend.backup.service
"""

import logging
import os
import time

import django
import schedule

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.backend.towerdb.settings")
django.setup()

from thetower.backend.backup.db_backup import backup_database
from thetower.backend.backup.tar_backup import backup_new_tars

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s UTC [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run_tar_backup() -> None:
    logger.info("Tar backup: starting scan...")
    try:
        stats = backup_new_tars()
        logger.info(f"Tar backup complete: {stats}")
    except Exception:
        logger.exception("Tar backup run failed")


def run_db_backup() -> None:
    logger.info("DB backup: starting...")
    try:
        stats = backup_database()
        logger.info(f"DB backup complete: {stats}")
    except Exception:
        logger.exception("DB backup run failed")


def main() -> None:
    logger.info("Backup service starting")

    schedule.every().day.at("03:00").do(run_tar_backup)
    schedule.every().day.at("03:00").do(run_db_backup)

    # Run both on startup; DB backup is idempotent and will skip if already done today
    run_tar_backup()
    run_db_backup()

    logger.info("Backup service running (tar + DB on startup and daily at 03:00 UTC)")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
