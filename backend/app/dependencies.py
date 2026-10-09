from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
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


def get_current_principal(
    request: Request,
    db: Session = Depends(get_db),
    x_access_key: str | None = Header(default=None, alias="X-Access-Key"),
) -> Principal:
    token = _bearer_token(request)
    raw_access_key = x_access_key or (token if token and token.startswith(ACCESS_KEY_PREFIX) else None)

    if raw_access_key:
        key_hash = hash_access_key(raw_access_key)
        access_key = db.execute(
            select(models.AccessKey).where(
                models.AccessKey.key_hash == key_hash,
                models.AccessKey.revoked_at.is_(None),
            )
        ).scalar_one_or_none()
        if not access_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access key")
        user = db.get(models.User, access_key.user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
        now = datetime.now(timezone.utc)
        if should_update_access_key_usage(access_key.last_used_at, now):
            access_key.last_used_at = now
            db.add(access_key)
            db.commit()
        return Principal(user=user, auth_type="access_key", access_key=access_key)

    if token:
        user_id = decode_access_token(token)
        if user_id:
            user = db.get(models.User, user_id)
            if user and user.is_active:
                return Principal(user=user, auth_type="jwt")

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


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
