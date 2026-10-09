import pytest
from sqlalchemy import text
from sqlalchemy.pool import QueuePool

from app.db import create_database_engine


def test_postgres_pool_is_bounded_without_connecting(monkeypatch):
    for name in ("DB_POOL_SIZE", "DB_MAX_OVERFLOW", "DB_POOL_TIMEOUT_SECONDS", "DB_POOL_RECYCLE_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    engine = create_database_engine("postgresql+psycopg://unused:unused@localhost/unused")
    assert isinstance(engine.pool, QueuePool)
    assert engine.pool.size() == 2
    assert engine.pool._max_overflow == 0
    assert engine.pool.timeout() == 10
    assert engine.pool._recycle == 300
    engine.dispose()


def test_pool_configuration(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "3")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "1")
    monkeypatch.setenv("DB_POOL_TIMEOUT_SECONDS", "4")
    engine = create_database_engine("postgresql+psycopg://unused:unused@localhost/unused")
    assert engine.pool.size() == 3
    assert engine.pool._max_overflow == 1
    assert engine.pool.timeout() == 4
    engine.dispose()


@pytest.mark.parametrize(
    "name,value",
    [
        ("DB_POOL_SIZE", "0"),
        ("DB_MAX_OVERFLOW", "-1"),
        ("DB_POOL_TIMEOUT_SECONDS", "0"),
        ("DB_POOL_RECYCLE_SECONDS", "-1"),
        ("DB_CONNECT_TIMEOUT_SECONDS", "0"),
        ("DB_STATEMENT_TIMEOUT_MS", "0"),
        ("DB_LOCK_TIMEOUT_MS", "0"),
        ("DB_TCP_USER_TIMEOUT_MS", "0"),
    ],
)
def test_rejects_unbounded_or_invalid_settings(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        create_database_engine("postgresql+psycopg://unused:unused@localhost/unused")


def test_sqlite_still_works(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "0")
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
    engine.dispose()
