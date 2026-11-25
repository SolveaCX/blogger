from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app import models
from app.core.security import ACCESS_KEY_PREFIX, decode_access_token, hash_access_key
from app.db import get_db


@dataclass
class Principal:
    user: models.User
    auth_type: str
    access_key: models.AccessKey | None = None


ACCESS_KEY_USAGE_UPDATE_INTERVAL = timedelta(minutes=5)


def should_update_access_key_usage(last_used_at: datetime | None, now: datetime) -> bool:
    if last_used_at is None:
        return True
    if last_used_at.tzinfo is None:
        last_used_at = last_used_at.replace(tzinfo=timezone.utc)
    return now - last_used_at >= ACCESS_KEY_USAGE_UPDATE_INTERVAL


def _bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("Authorization")
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def authenticate_access_key(db: Session, raw_key: str) -> Principal:
    access_key = db.scalar(
        select(models.AccessKey).where(
            models.AccessKey.revoked_at.is_(None),
            or_(
                and_(models.AccessKey.site_id.is_(None), models.AccessKey.key_hash == hash_access_key(raw_key)),
                and_(
                    models.AccessKey.site_id.is_not(None),
                    models.AccessKey.key_hash == hash_access_key(raw_key, site_scoped=True),
                ),
            ),
        )
    )
    if access_key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access key")
    user = db.get(models.User, access_key.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    now = datetime.now(timezone.utc)
    if should_update_access_key_usage(access_key.last_used_at, now):
        access_key.last_used_at = now
        db.commit()
    return Principal(user=user, auth_type="access_key", access_key=access_key)


def get_authenticated_principal(
    request: Request,
    db: Session = Depends(get_db),
    x_access_key: str | None = Header(default=None, alias="X-Access-Key"),
) -> Principal:
    token = _bearer_token(request)
    raw_access_key = x_access_key or (token if token and token.startswith(ACCESS_KEY_PREFIX) else None)

    if raw_access_key:
        return authenticate_access_key(db, raw_access_key)

    if token:
        user_id = decode_access_token(token)
        if user_id:
            user = db.get(models.User, user_id)
            if user and user.is_active:
                return Principal(user=user, auth_type="jwt")

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


def get_current_principal(principal: Principal = Depends(get_authenticated_principal)) -> Principal:
    if principal.access_key is not None and principal.access_key.site_id is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Site-scoped access key")
    return principal


def require_user(principal: Principal = Depends(get_current_principal)) -> models.User:
    return principal.user


def require_super_admin(user: models.User = Depends(require_user)) -> models.User:
    if user.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin role required")
    return user


def require_access_key_principal(principal: Principal = Depends(get_current_principal)) -> Principal:
    if principal.auth_type != "access_key":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access key required")
    return principal


def require_super_admin_access_key(principal: Principal = Depends(require_access_key_principal)) -> models.User:
    if principal.user.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin role required")
    return principal.user
