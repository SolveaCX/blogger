import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ACCESS_KEY_PREFIX = "blog_sk_"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(subject: str) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    payload = {"sub": subject, "exp": expires_at}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None


def hash_access_key(raw_key: str, *, site_scoped: bool = False) -> str:
    # Scoped keys must remain unusable by versions that do not enforce site scope.
    if site_scoped:
        return hmac.new(
            settings.access_key_pepper.encode("utf-8"),
            f"site-scoped:{raw_key}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    value = f"{settings.access_key_pepper}:{raw_key}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def create_raw_access_key(*, site_scoped: bool = False) -> tuple[str, str, str]:
    raw_key = f"{ACCESS_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    key_prefix = raw_key[:18]
    return raw_key, key_prefix, hash_access_key(raw_key, site_scoped=site_scoped)
