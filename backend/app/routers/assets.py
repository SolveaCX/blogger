from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response, status

from app.core.config import settings

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.get("/{asset_path:path}")
def get_asset(asset_path: str) -> Response:
    if not settings.local_asset_dir and not settings.gcs_bucket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset storage is not configured")

    expected_prefix = f"{settings.upload_prefix.strip('/')}/"
    if not asset_path.startswith(expected_prefix):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    if settings.local_asset_dir:
        root = Path(settings.local_asset_dir).resolve()
        path = (root / asset_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return Response(
            content=path.read_bytes(),
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    from google.cloud import storage
    from google.cloud.exceptions import NotFound

    client = storage.Client()
    blob = client.bucket(settings.gcs_bucket).blob(asset_path)

    try:
        data = blob.download_as_bytes()
    except NotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found") from exc

    content_type = blob.content_type or mimetypes.guess_type(asset_path)[0] or "application/octet-stream"
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
