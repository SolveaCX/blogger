from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from app import storage
from app.routers import assets


def local_settings(tmp_path, public_url="https://blog.solvea.io/api/assets"):
    return SimpleNamespace(
        upload_prefix="uploads",
        local_asset_dir=str(tmp_path),
        public_asset_base_url=public_url,
        gcs_bucket=None,
    )


def cover_upload():
    return UploadFile(
        filename="cover.png",
        file=BytesIO(b"\x89PNG\r\n\x1a\nlocal-image"),
        headers={"content-type": "image/png"},
    )


def test_local_upload_returns_public_url_and_asset_is_served(monkeypatch, tmp_path):
    settings = local_settings(tmp_path)
    monkeypatch.setattr(storage, "settings", settings)
    monkeypatch.setattr(assets, "settings", settings)

    stored = storage.store_upload(cover_upload(), kind="cover", user_id="user-1")
    asset_path = stored.url.removeprefix(f"{settings.public_asset_base_url}/")
    response = assets.get_asset(asset_path)

    assert stored.url.startswith("https://blog.solvea.io/api/assets/uploads/cover/user-1/")
    assert response.body == b"\x89PNG\r\n\x1a\nlocal-image"
    assert response.media_type == "image/png"


def test_local_upload_requires_public_base_url(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "settings", local_settings(tmp_path, public_url=None))

    with pytest.raises(HTTPException) as exc_info:
        storage.store_upload(cover_upload(), kind="cover", user_id="user-1")

    assert exc_info.value.status_code == 503
    assert not list(tmp_path.iterdir())


def test_local_asset_path_cannot_escape_storage_root(monkeypatch, tmp_path):
    monkeypatch.setattr(assets, "settings", local_settings(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        assets.get_asset("uploads/../../etc/passwd")

    assert exc_info.value.status_code == 404
