from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.core.security import create_raw_access_key
from app.dependencies import require_user
from app.db import get_db
from app.routers.sites import owned_site_or_404

router = APIRouter(prefix="/api/access-keys", tags=["access-keys"])


@router.get("", response_model=list[schemas.AccessKeyRead])
def list_access_keys(
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[models.AccessKey]:
    return list(
        db.execute(
            select(models.AccessKey)
            .where(models.AccessKey.user_id == user.id)
            .order_by(models.AccessKey.created_at.desc())
        )
        .scalars()
        .all()
    )


@router.post("", response_model=schemas.AccessKeyCreated, status_code=status.HTTP_201_CREATED)
def create_access_key(
    payload: schemas.AccessKeyCreate,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
) -> schemas.AccessKeyCreated:
    if payload.site_id is not None:
        owned_site_or_404(db, user.id, payload.site_id)
    raw_key, key_prefix, key_hash = create_raw_access_key(site_scoped=payload.site_id is not None)
    access_key = models.AccessKey(
        user_id=user.id,
        site_id=payload.site_id,
        name=payload.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
    )
    db.add(access_key)
    db.commit()
    db.refresh(access_key)
    data = schemas.AccessKeyRead.model_validate(access_key).model_dump()
    return schemas.AccessKeyCreated(**data, access_key=raw_key)


@router.delete("/{access_key_id}", response_model=schemas.AccessKeyRead)
def revoke_access_key(
    access_key_id: str,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
) -> models.AccessKey:
    access_key = db.get(models.AccessKey, access_key_id)
    if not access_key or access_key.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Access key not found")
    access_key.revoked_at = datetime.now(timezone.utc)
    db.add(access_key)
    db.commit()
    db.refresh(access_key)
    return access_key
