from collections.abc import Generator
import os

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
    tcp_user_timeout = int(os.getenv("DB_TCP_USER_TIMEOUT_MS", "30000"))
    if (
        pool_size < 1
        or max_overflow < 0
        or pool_timeout <= 0
        or pool_recycle < 1
        or connect_timeout < 1
        or statement_timeout < 1
        or lock_timeout < 1
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
            "options": f"-c statement_timeout={statement_timeout} -c lock_timeout={lock_timeout}",
        },
    )


engine = create_database_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
