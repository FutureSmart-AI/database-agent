"""Validation and S3 upload for widget icons and avatars.

Credentials and bucket come from `s3_export_utils`, so there is one place that knows how this
service talks to S3. When the bucket is not configured — which is the case in any environment
without `BUCKET_NAME` — uploads fail loudly with 503 rather than silently storing nothing. Callers
can still set an icon by URL, which needs no S3 at all.
"""
import re
from typing import Optional

from fastapi import HTTPException, UploadFile, status

from agent.services.logger import logger
from agent.utils.s3_export_utils import get_public_s3_url, s3_bucket, s3_client, s3_is_configured

_PREFIX = "nl2sql_widgets"

ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "image/bmp",
    "image/tiff",
    "image/avif",
    "image/heic",
    "image/heif",
}

# Not in the dashboard's version, but these files are served to every widget visitor and an
# unbounded upload is an easy way to fill the bucket.
MAX_IMAGE_BYTES = 2 * 1024 * 1024

_HEX_COLOR = re.compile(r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")


def validate_hex_color(value: str) -> str:
    """Return the colour unchanged, or raise 400."""
    if not _HEX_COLOR.match(value or ""):
        raise HTTPException(
            status_code=400,
            detail="Invalid hex color code. Must be in #RRGGBB or #RGB format.",
        )
    return value


def validate_image(file: Optional[UploadFile]) -> None:
    if file is None:
        return
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type for {file.filename}. Only image files are allowed.",
        )


def _extension(filename: Optional[str], fallback: str = "png") -> str:
    if filename and "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    return fallback


async def upload_widget_image(file: UploadFile, agent_id: str, is_icon: bool) -> str:
    """Upload one image and return its public URL.

    Raises 503 when S3 is not configured for this environment, so a caller is never told the
    upload succeeded when nothing was stored.
    """
    if not s3_is_configured():
        logger.error("[Widget] BUCKET_NAME not configured — cannot upload widget image")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Image upload is not available: object storage is not configured for this "
                "environment. Supply widget_icon_url / widget_avatar_url instead."
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail=f"{file.filename} is empty")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"{file.filename} is larger than {MAX_IMAGE_BYTES // (1024 * 1024)}MB",
        )

    name = "widget_icon" if is_icon else "widget_avatar"
    key = f"{_PREFIX}/{agent_id}/{name}.{_extension(file.filename)}"
    put_kwargs = {
        "Bucket": s3_bucket(),
        "Key": key,
        "Body": content,
        "ContentType": file.content_type or "application/octet-stream",
    }

    try:
        async with s3_client() as s3:
            try:
                # Public-read matches the dashboard, and the widget is embedded on third-party
                # pages that fetch this URL anonymously.
                await s3.put_object(ACL="public-read", **put_kwargs)
            except Exception as acl_error:
                # Buckets with Object Ownership set to "bucket owner enforced" reject any ACL.
                # There the object is public via bucket policy instead, so retry without it.
                if "AccessControlListNotSupported" not in str(acl_error):
                    raise
                logger.info("[Widget] bucket rejects ACLs — retrying upload without one")
                await s3.put_object(**put_kwargs)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Widget] upload failed | key={key} | error={e}")
        raise HTTPException(status_code=500, detail="Error uploading widget image")

    url = get_public_s3_url(key)
    logger.info(f"[Widget] uploaded | key={key} | bytes={len(content)}")
    return url


async def resolve_widget_image(
    file: Optional[UploadFile], url: Optional[str], agent_id: str, is_icon: bool
) -> Optional[str]:
    """Work out the stored value: an uploaded file wins, then a URL, then "leave unchanged"."""
    if file is not None:
        return await upload_widget_image(file, agent_id, is_icon)
    if url and url.strip():
        return url.strip()
    return None
