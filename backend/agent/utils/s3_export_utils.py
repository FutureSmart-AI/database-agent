import csv
import io
import os
from typing import Any, List, Optional

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from agent.services.logger import logger

_BUCKET = os.getenv("BUCKET_NAME", "")
_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
_SECRET = os.getenv("AWS_SECRET_ACCESS_KEY", "")
_REGION = os.getenv("AWS_REGION", "us-east-1")

# Pre-signed URL validity in seconds (default 24 h). Override via env.
CSV_EXPORT_URL_EXPIRY = int(os.getenv("CSV_EXPORT_URL_EXPIRY", str(7 * 24 * 3600)))
# Set CSV_USE_PUBLIC_URL=true to upload objects as public-read and return
# permanent direct S3 URLs instead of expiring pre-signed URLs.
# Requires the S3 bucket to have ACLs enabled and Block Public Access disabled
# for the nl2sql_exports/ prefix (or the whole bucket).
CSV_USE_PUBLIC_URL = os.getenv("CSV_USE_PUBLIC_URL", "false").strip().lower() in ("1", "true", "yes")
_PREFIX = "nl2sql_exports"


def build_export_s3_key(agent_id: str, session_id: str, chat_id: str) -> str:
    return f"{_PREFIX}/{agent_id}/{session_id}/{chat_id}.csv"


def _to_csv_bytes(columns: List[str], rows: List[Any]) -> bytes:
    from agent.utils.common_utils import serialize_db_value

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for row in rows:
        if isinstance(row, dict):
            writer.writerow([serialize_db_value(row.get(c)) for c in columns])
        elif isinstance(row, (list, tuple)):
            writer.writerow([serialize_db_value(v) for v in row])
        else:
            writer.writerow([serialize_db_value(row)])
    return buf.getvalue().encode("utf-8")


def _s3_client():
    session = aioboto3.Session()
    return session.client(
        "s3",
        aws_access_key_id=_KEY_ID or None,
        aws_secret_access_key=_SECRET or None,
        region_name=_REGION,
        config=Config(signature_version="s3v4"),
    )


def get_public_s3_url(s3_key: str) -> str:
    """Return the permanent public URL for an S3 object (no expiry)."""
    return f"https://{_BUCKET}.s3.{_REGION}.amazonaws.com/{s3_key}"


# --- Shared with other uploaders (widget icons/avatars) -------------------------------
# Exposed so S3 credentials and bucket configuration are resolved in exactly one place.

def s3_client():
    """An configured aioboto3 S3 client context manager."""
    return _s3_client()


def s3_bucket() -> str:
    """The configured bucket name, or "" when S3 is not configured for this environment."""
    return _BUCKET


def s3_is_configured() -> bool:
    return bool(_BUCKET)


async def upload_csv_to_s3(columns: List[str], rows: List[Any], s3_key: str) -> bool:
    """Upload CSV data to S3. Returns True on success, False on failure (non-fatal).

    When CSV_USE_PUBLIC_URL is enabled the object is uploaded with ACL=public-read
    so that get_public_s3_url() returns a permanently accessible URL.
    """
    if not _BUCKET:
        logger.warning("[S3Export] BUCKET_NAME not configured — skipping CSV upload")
        return False
    try:
        csv_bytes = _to_csv_bytes(columns, rows)
        put_kwargs = {
            "Bucket": _BUCKET,
            "Key": s3_key,
            "Body": csv_bytes,
            "ContentType": "text/csv",
        }
        if CSV_USE_PUBLIC_URL:
            put_kwargs["ACL"] = "public-read"
        async with _s3_client() as s3:
            await s3.put_object(**put_kwargs)
        logger.info(f"[S3Export] Uploaded | key={s3_key} | rows={len(rows)} | public={CSV_USE_PUBLIC_URL}")
        return True
    except Exception as e:
        logger.error(f"[S3Export] Upload failed | key={s3_key} | error={e}")
        return False


async def generate_export_presigned_url(
    s3_key: str, expiry: int = CSV_EXPORT_URL_EXPIRY
) -> Optional[str]:
    """Generate a fresh GET pre-signed URL for an existing S3 object."""
    if not _BUCKET or not s3_key:
        return None
    try:
        async with _s3_client() as s3:
            url = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": _BUCKET, "Key": s3_key},
                ExpiresIn=expiry,
            )
        logger.info(f"[S3Export] Pre-signed URL generated | key={s3_key} | expiry={expiry}s")
        return url
    except Exception as e:
        logger.error(f"[S3Export] Pre-signed URL failed | key={s3_key} | error={e}")
        return None


async def get_export_url(s3_key: str) -> Optional[str]:
    """Return a download URL for an S3 export object.

    When CSV_USE_PUBLIC_URL=true: returns a permanent public URL instantly (no AWS call).
    Otherwise: generates a pre-signed URL valid for CSV_EXPORT_URL_EXPIRY seconds.
    """
    if not _BUCKET or not s3_key:
        return None
    if CSV_USE_PUBLIC_URL:
        return get_public_s3_url(s3_key)
    return await generate_export_presigned_url(s3_key)


async def check_s3_object_exists(s3_key: str) -> bool:
    """Return True if the S3 object exists."""
    if not _BUCKET or not s3_key:
        return False
    try:
        async with _s3_client() as s3:
            await s3.head_object(Bucket=_BUCKET, Key=s3_key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        logger.error(f"[S3Export] head_object error | key={s3_key} | error={e}")
        return False
    except Exception as e:
        logger.error(f"[S3Export] Existence check failed | key={s3_key} | error={e}")
        return False
