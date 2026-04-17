"""SQLite database backup to Cloudflare R2.

Uses VACUUM INTO to produce a clean, WAL-safe snapshot of the live database,
compresses it with gzip, then uploads to the appropriate generational prefixes.

R2 key layout:
    db/daily/YYYY-MM-DD.db.gz       — every run
    db/weekly/YYYY-Www.db.gz        — Sundays only
    db/monthly/YYYY-MM.db.gz        — first day of month only

Lifecycle expiry (configured in Cloudflare dashboard, not here):
    db/daily/   → 9 days
    db/weekly/  → 36 days  (lock: 35 days)
    db/monthly/ → 13 months (lock: 13 months)
"""

import gzip
import hashlib
import logging
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from botocore.exceptions import ClientError

from thetower.backend.backup.r2_client import get_r2_bucket, get_r2_client
from thetower.backend.env_config import get_django_data

logger = logging.getLogger(__name__)


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file in streaming chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _r2_keys_for_date(dt: datetime) -> list[str]:
    """Return all R2 keys this backup should be uploaded to based on the UTC date."""
    keys = [f"db/daily/{dt.strftime('%Y-%m-%d')}.db.gz"]
    if dt.weekday() == 6:  # Sunday
        keys.append(f"db/weekly/{dt.strftime('%Y-W%W')}.db.gz")
    if dt.day == 1:  # First of month
        keys.append(f"db/monthly/{dt.strftime('%Y-%m')}.db.gz")
    return keys


def _object_exists(client, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise


def backup_database() -> dict:
    """Create a compressed SQLite snapshot and upload to R2 generational prefixes.

    Returns a stats dict: keys_uploaded, keys_skipped, compressed_size_bytes, errors.
    """
    now = datetime.now(timezone.utc)
    client = get_r2_client()
    bucket = get_r2_bucket()
    stats = {"keys_uploaded": 0, "keys_skipped": 0, "compressed_size_bytes": 0, "errors": 0}

    db_path = get_django_data() / "tower.sqlite3"
    if not db_path.exists():
        logger.error(f"Database not found at {db_path}")
        stats["errors"] += 1
        return stats

    r2_keys = _r2_keys_for_date(now)
    daily_key = r2_keys[0]

    # Idempotent: if today's daily already exists, skip everything
    if _object_exists(client, bucket, daily_key):
        logger.info(f"Daily backup already present in R2: {daily_key} — skipping")
        stats["keys_skipped"] += len(r2_keys)
        return stats

    # Use a temp dir on the same partition as the database to avoid filling tmpfs
    tmp_dir = Path(tempfile.mkdtemp(prefix="tower_dbbackup_", dir=db_path.parent))
    try:
        # Step 1: VACUUM INTO — WAL-safe clean copy
        vacuum_path = tmp_dir / f"tower_{now.strftime('%Y%m%d_%H%M%S')}.db"
        logger.info(f"VACUUM INTO {vacuum_path.name} from {db_path}...")
        conn = sqlite3.connect(str(db_path), timeout=60)
        conn.execute(f"VACUUM INTO '{vacuum_path}'")
        conn.close()
        logger.info(f"VACUUM complete: {vacuum_path.stat().st_size:,} bytes")

        # Step 2: gzip compress
        gz_path = tmp_dir / (vacuum_path.name + ".gz")
        logger.info(f"Compressing to {gz_path.name}...")
        with open(vacuum_path, "rb") as f_in, gzip.open(gz_path, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
        vacuum_path.unlink()  # free space immediately

        compressed_size = gz_path.stat().st_size
        sha256 = _sha256_file(gz_path)
        stats["compressed_size_bytes"] = compressed_size
        logger.info(f"Compressed: {compressed_size:,} bytes, sha256={sha256[:16]}...")

        # Step 3: upload to each applicable generational key
        for key in r2_keys:
            if _object_exists(client, bucket, key):
                logger.info(f"Already exists in R2: {key} — skipping")
                stats["keys_skipped"] += 1
                continue
            try:
                logger.info(f"Uploading {key} ({compressed_size:,} bytes)...")
                client.upload_file(
                    str(gz_path),
                    bucket,
                    key,
                    ExtraArgs={
                        "Metadata": {
                            "sha256": sha256,
                            "compressed_size": str(compressed_size),
                            "backup_date": now.isoformat(),
                        }
                    },
                )

                # Verify
                head = client.head_object(Bucket=bucket, Key=key)
                if head["ContentLength"] != compressed_size:
                    raise ValueError(f"Size mismatch: expected {compressed_size}, got {head['ContentLength']}")
                if head.get("Metadata", {}).get("sha256") != sha256:
                    raise ValueError("SHA-256 mismatch after upload")

                logger.info(f"Uploaded and verified: {key}")
                stats["keys_uploaded"] += 1

            except Exception:
                logger.exception(f"Failed to upload DB backup to {key}")
                stats["errors"] += 1

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return stats
