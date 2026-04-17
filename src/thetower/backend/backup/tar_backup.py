"""Upload completed raw tar archives to Cloudflare R2.

Scans all {league}_raw/ directories for *.tar files not yet present in R2,
uploads each one with SHA-256 integrity verification, and deletes the local
copy only after the upload is confirmed.

R2 key layout:  tar/{league}/{filename}
    e.g.        tar/champion/2025-01-15_raw.tar

Bucket lock (configured in Cloudflare dashboard, not here):
    Prefix tar/ → Indefinite retention
"""

import hashlib
import logging
from pathlib import Path

from botocore.exceptions import ClientError

from thetower.backend.backup.r2_client import get_r2_bucket, get_r2_client
from thetower.backend.env_config import get_csv_data
from thetower.backend.tourney_results.archive_utils import get_raw_path
from thetower.backend.tourney_results.constants import leagues

logger = logging.getLogger(__name__)


def _sha256_file(path: Path) -> str:
    """Compute the SHA-256 hex digest of a file in streaming chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _r2_key(league: str, filename: str) -> str:
    return f"tar/{league}/{filename}"


def _object_exists(client, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise


def backup_new_tars() -> dict:
    """Scan all league raw directories and upload any tars not yet in R2.

    Returns a stats dict: checked, uploaded, skipped, deleted, errors.
    """
    client = get_r2_client()
    bucket = get_r2_bucket()
    live_base = Path(get_csv_data())
    stats = {"checked": 0, "uploaded": 0, "skipped": 0, "deleted": 0, "errors": 0}

    for league in leagues:
        raw_dir = get_raw_path(league, live_base)
        if not raw_dir.exists():
            continue

        for tar_path in sorted(raw_dir.glob("*.tar")):
            stats["checked"] += 1
            key = _r2_key(league, tar_path.name)

            if _object_exists(client, bucket, key):
                logger.debug(f"Already in R2, skipping: {key}")
                stats["skipped"] += 1
                continue

            try:
                size = tar_path.stat().st_size
                sha256 = _sha256_file(tar_path)
                logger.info(f"Uploading {league}/{tar_path.name} ({size:,} bytes)...")

                client.upload_file(
                    str(tar_path),
                    bucket,
                    key,
                    ExtraArgs={
                        "Metadata": {
                            "sha256": sha256,
                            "original_size": str(size),
                            "league": league,
                        }
                    },
                )

                # Verify upload
                head = client.head_object(Bucket=bucket, Key=key)
                uploaded_size = head["ContentLength"]
                uploaded_sha256 = head.get("Metadata", {}).get("sha256", "")

                if uploaded_size != size:
                    raise ValueError(f"Size mismatch after upload: expected {size}, got {uploaded_size}")
                if uploaded_sha256 != sha256:
                    raise ValueError(f"SHA-256 mismatch after upload: expected {sha256}, got {uploaded_sha256}")

                logger.info(f"Verified: {key}")
                stats["uploaded"] += 1

                # Delete local tar only after confirmed upload
                tar_path.unlink()
                logger.info(f"Deleted local tar: {tar_path}")
                stats["deleted"] += 1

            except Exception:
                logger.exception(f"Failed to backup {league}/{tar_path.name}")
                stats["errors"] += 1

    return stats
