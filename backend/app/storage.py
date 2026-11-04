from __future__ import annotations

import base64
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml"}
IMAGE_TYPES_BY_EXTENSION = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


@dataclass(frozen=True)
class StoredFile:
    url: str


def _extension(filename: str, content_type: str) -> str:
    suffix = Path(filename).suffix.lower()
    if IMAGE_TYPES_BY_EXTENSION.get(suffix) == content_type:
        return suffix
    guessed = mimetypes.guess_extension(content_type)
    if guessed == ".jpe":
        return ".jpg"
    return guessed or ".bin"


def _content_type_from_bytes(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"

    header = data[:512].lstrip().lower()
    if header.startswith(b"<svg") or (header.startswith(b"<?xml") and b"<svg" in header):
        return "image/svg+xml"

    return None


def _resolve_image_content_type(file: UploadFile, data: bytes) -> str:
    declared = (file.content_type or "").split(";", 1)[0].strip().lower()
    if declared in IMAGE_TYPES:
        return declared

    detected = _content_type_from_bytes(data)
    if detected:
        return detected

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only image uploads are supported")


def _safe_kind(kind: str) -> str:
    if not re.fullmatch(r"[a-z0-9-]+", kind):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid upload kind")
    return kind


def store_upload(file: UploadFile, kind: str, user_id: str) -> StoredFile:
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty upload")
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Upload must be <= 5MB")

    content_type = _resolve_image_content_type(file, data)
    safe_kind = _safe_kind(kind)
    name = f"{settings.upload_prefix}/{safe_kind}/{user_id}/{uuid4().hex}{_extension(file.filename or '', content_type)}"

    if settings.local_asset_dir:
        if not settings.public_asset_base_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="PUBLIC_ASSET_BASE_URL is required for local asset storage",
            )
        path = Path(settings.local_asset_dir) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredFile(url=f"{settings.public_asset_base_url.rstrip('/')}/{name}")

    if not settings.gcs_bucket:
        encoded = base64.b64encode(data).decode("ascii")
        return StoredFile(url=f"data:{content_type};base64,{encoded}")

    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(settings.gcs_bucket)
    blob = bucket.blob(name)
    blob.upload_from_string(data, content_type=content_type)

    if settings.public_asset_base_url:
        return StoredFile(url=f"{settings.public_asset_base_url.rstrip('/')}/{name}")

    return StoredFile(url=f"https://storage.googleapis.com/{settings.gcs_bucket}/{name}")
