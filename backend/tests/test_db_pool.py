import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.pool import QueuePool

from app import db as db_module
from app.db import create_database_engine, database_request_capacity


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
        ("DB_IDLE_IN_TRANSACTION_TIMEOUT_MS", "0"),
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


def test_database_request_capacity_cannot_exceed_pool(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "2")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "1")
    monkeypatch.setenv("DB_REQUEST_CONCURRENCY", "4")
    with pytest.raises(ValueError):
        database_request_capacity("postgresql+psycopg://unused:unused@localhost/unused")


def test_database_request_slots_are_released_after_session_cleanup(monkeypatch):
    sessions = []

    class FakeSession:
        closed = False

        def close(self):
            self.closed = True

    def session_factory():
        session = FakeSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    monkeypatch.setattr(db_module, "_database_request_slots", asyncio.Semaphore(1))
    monkeypatch.setattr(db_module, "_database_request_queue_timeout_seconds", 1)

    async def exercise_dependency():
        first_dependency = db_module.get_db()
        await anext(first_dependency)
        second_dependency = db_module.get_db()
        second_request = asyncio.create_task(anext(second_dependency))
        await asyncio.sleep(0)
        assert not second_request.done()

        await first_dependency.aclose()
        await asyncio.wait_for(second_request, timeout=0.5)
        await second_dependency.aclose()

    asyncio.run(exercise_dependency())
    assert len(sessions) == 2
    assert all(session.closed for session in sessions)


def test_database_request_queue_times_out_with_503(monkeypatch):
    monkeypatch.setattr(db_module, "_database_request_slots", asyncio.Semaphore(0))
    monkeypatch.setattr(db_module, "_database_request_queue_timeout_seconds", 0.01)

    async def exhaust_capacity():
        dependency = db_module.get_db()
        with pytest.raises(HTTPException) as exc_info:
            await anext(dependency)
        assert exc_info.value.status_code == 503
        assert exc_info.value.headers == {"Retry-After": "1"}

    asyncio.run(exhaust_capacity())


def test_sync_routes_cannot_starve_database_session_cleanup(monkeypatch):
    state = {"open": 0, "maximum": 0}
    lock = threading.Lock()

    class FakeSession:
        def __init__(self):
            with lock:
                state["open"] += 1
                state["maximum"] = max(state["maximum"], state["open"])

        def close(self):
            with lock:
                state["open"] -= 1

    monkeypatch.setattr(db_module, "SessionLocal", FakeSession)
    monkeypatch.setattr(db_module, "_database_request_slots", asyncio.Semaphore(2))
    monkeypatch.setattr(db_module, "_database_request_queue_timeout_seconds", 2)

    app = FastAPI()

    @app.get("/database-work")
    def database_work(db=Depends(db_module.get_db)):
        assert isinstance(db, FakeSession)
        time.sleep(0.02)
        return {"ok": True}

    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=50) as executor:
            responses = list(executor.map(lambda _: client.get("/database-work"), range(50)))

    assert all(response.status_code == 200 for response in responses)
    assert state == {"open": 0, "maximum": 2}
