"""Cloudflare R2 boto3 client factory.

Credentials are read from environment variables:
    R2_ACCOUNT_ID        - Cloudflare account ID
    R2_BUCKET_NAME       - R2 bucket name
    R2_ACCESS_KEY_ID     - S3 API token key ID
    R2_SECRET_ACCESS_KEY - S3 API token secret

The backup service uses an Edit+Read token.
The hidden site status page uses a Read-only token.
Both use the same env var names — each service file carries its own credentials.
"""

import os

import boto3
from botocore.config import Config


def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Required environment variable {name} is not set.")
    return val


def get_r2_client():
    """Return a boto3 S3 client using the configured R2 credentials."""
    account_id = _require_env("R2_ACCOUNT_ID")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=_require_env("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=_require_env("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    )


def get_r2_bucket() -> str:
    """Return the configured R2 bucket name."""
    return _require_env("R2_BUCKET_NAME")
