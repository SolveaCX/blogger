from sqlalchemy import String, Text, inspect, text

from app import db, models, schema_guard
from app.schema_guard import _should_resize_post_language_column


def test_should_resize_post_language_column_only_when_needed() -> None:
    assert not _should_resize_post_language_column({"language": {"type": String(64)}})
    assert _should_resize_post_language_column({"language": {"type": String(32)}})
    assert _should_resize_post_language_column({"language": {"type": Text()}})
    assert not _should_resize_post_language_column({})


def test_add_access_key_scope_without_changing_legacy_keys(tmp_path, monkeypatch):
    engine = db.create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'old-blogger.sqlite'}")
    monkeypatch.setattr(schema_guard, "engine", engine)
    db.Base.metadata.create_all(engine, tables=[
        models.User.__table__, models.Site.__table__, models.Category.__table__, models.Post.__table__,
    ])
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE access_keys (id VARCHAR(36) PRIMARY KEY, key_hash VARCHAR(64))"))
            connection.execute(text("INSERT INTO access_keys (id, key_hash) VALUES ('existing', 'existing-hash')"))
        schema_guard.ensure_schema()
        schema_guard.ensure_schema()
        assert any(
            foreign_key["constrained_columns"] == ["site_id"] and foreign_key["referred_table"] == "sites"
            for foreign_key in inspect(engine).get_foreign_keys("access_keys")
        )
        with engine.connect() as connection:
            assert connection.execute(text("SELECT id, key_hash, site_id FROM access_keys")).one() == (
                "existing", "existing-hash", None,
            )
    finally:
        engine.dispose()
