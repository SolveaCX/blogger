import asyncio
from collections.abc import AsyncGenerator
import os

from anyio import CancelScope, to_thread
from fastapi import HTTPException, status
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def create_database_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        # Preserve SQLite's existing thread and in-memory pooling behavior.
        return create_engine(database_url, pool_pre_ping=True, connect_args={"check_same_thread": False})

    pool_size = int(os.getenv("DB_POOL_SIZE", "2"))
    max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "0"))
    pool_timeout = float(os.getenv("DB_POOL_TIMEOUT_SECONDS", "10"))
    pool_recycle = int(os.getenv("DB_POOL_RECYCLE_SECONDS", "300"))
    connect_timeout = int(os.getenv("DB_CONNECT_TIMEOUT_SECONDS", "5"))
    statement_timeout = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "30000"))
    lock_timeout = int(os.getenv("DB_LOCK_TIMEOUT_MS", "5000"))
    idle_in_transaction_timeout = int(os.getenv("DB_IDLE_IN_TRANSACTION_TIMEOUT_MS", "60000"))
    tcp_user_timeout = int(os.getenv("DB_TCP_USER_TIMEOUT_MS", "30000"))
    if (
        pool_size < 1
        or max_overflow < 0
        or pool_timeout <= 0
        or pool_recycle < 1
        or connect_timeout < 1
        or statement_timeout < 1
        or lock_timeout < 1
        or idle_in_transaction_timeout < 1
        or tcp_user_timeout < 1
    ):
        raise ValueError("Database pool settings must define a positive bounded pool")

    # Budget across ALL workers/instances, including rolling revisions. The
    # service autoscaling cap must be set separately; process-local pools alone
    # cannot prevent a multi-instance deployment exhausting PostgreSQL slots.
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        pool_use_lifo=True,
        connect_args={
            "connect_timeout": connect_timeout,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
            "tcp_user_timeout": tcp_user_timeout,
            "options": (
                f"-c statement_timeout={statement_timeout} "
                f"-c lock_timeout={lock_timeout} "
                f"-c idle_in_transaction_session_timeout={idle_in_transaction_timeout}"
            ),
        },
    )


engine = create_database_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def database_request_capacity(database_url: str) -> int:
    if database_url.startswith("sqlite"):
        default_capacity = 20
    else:
        pool_capacity = int(os.getenv("DB_POOL_SIZE", "2")) + int(os.getenv("DB_MAX_OVERFLOW", "0"))
        default_capacity = pool_capacity

    capacity = int(os.getenv("DB_REQUEST_CONCURRENCY", str(default_capacity)))
    if capacity < 1:
        raise ValueError("DB_REQUEST_CONCURRENCY must be positive")
    if not database_url.startswith("sqlite") and capacity > pool_capacity:
        raise ValueError("DB_REQUEST_CONCURRENCY cannot exceed the database pool capacity")
    return capacity


_database_request_slots = asyncio.Semaphore(database_request_capacity(settings.database_url))
_database_request_queue_timeout_seconds = float(os.getenv("DB_REQUEST_QUEUE_TIMEOUT_SECONDS", "5"))
if _database_request_queue_timeout_seconds <= 0:
    raise ValueError("DB_REQUEST_QUEUE_TIMEOUT_SECONDS must be positive")


async def get_db() -> AsyncGenerator[Session, None]:
    try:
        await asyncio.wait_for(
            _database_request_slots.acquire(),
            timeout=_database_request_queue_timeout_seconds,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database request capacity is temporarily exhausted",
            headers={"Retry-After": "1"},
        ) from exc

    db: Session | None = None
    try:
        db = SessionLocal()
        yield db
    finally:
        try:
            if db is not None:
                # Cleanup must not be cancelled or queued behind blocked request
                # workers, otherwise checked-out connections can never return.
                with CancelScope(shield=True):
                    await to_thread.run_sync(db.close)
        finally:
            _database_request_slots.release()
