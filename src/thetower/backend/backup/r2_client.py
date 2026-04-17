"""Cloudflare R2 boto3 client factory.

Credentials are read from environment variables:
    R2_ACCOUNT_ID           - Cloudflare account ID
    R2_BUCKET_NAME          - R2 bucket name
    R2_ACCESS_KEY_ID        - Write-only S3 API token key ID
    R2_SECRET_ACCESS_KEY    - Write-only S3 API token secret
    R2_READ_ACCESS_KEY_ID   - Read-only S3 API token key ID (for status page)
    R2_READ_SECRET_ACCESS_KEY - Read-only S3 API token secret
"""

import os

import boto3
from botocore.config import Config


def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Required environment variable {name} is not set.")
    return val


def _make_client(access_key_id: str, secret_access_key: str) -> boto3.client:
    account_id = _require_env("R2_ACCOUNT_ID")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    )


def get_r2_write_client():
    """Return a boto3 S3 client using the write-only R2 credentials."""
    return _make_client(
        _require_env("R2_ACCESS_KEY_ID"),
        _require_env("R2_SECRET_ACCESS_KEY"),
    )


def get_r2_read_client():
    """Return a boto3 S3 client using the read-only R2 credentials."""
    return _make_client(
        _require_env("R2_READ_ACCESS_KEY_ID"),
        _require_env("R2_READ_SECRET_ACCESS_KEY"),
    )


def get_r2_bucket() -> str:
    """Return the configured R2 bucket name."""
    return _require_env("R2_BUCKET_NAME")
