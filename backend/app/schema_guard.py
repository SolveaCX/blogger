from __future__ import annotations

import json

from sqlalchemy import inspect, text

from app.db import engine

DEFAULT_LANGUAGES = [{"key": "en", "label": "English"}]
DEFAULT_LANGUAGES_JSON = json.dumps(DEFAULT_LANGUAGES)


def _columns(table: str) -> dict[str, dict[str, object]]:
    inspector = inspect(engine)
    if not inspector.has_table(table):
        return {}
    return {column["name"]: column for column in inspector.get_columns(table)}


def _column_names(table: str) -> set[str]:
    return set(_columns(table))


def _should_resize_post_language_column(posts_columns: dict[str, dict[str, object]]) -> bool:
    language_column = posts_columns.get("language")
    if not language_column:
        return False
    return getattr(language_column.get("type"), "length", None) != 64


def _unique_constraint_names(table: str) -> set[str]:
    inspector = inspect(engine)
    if not inspector.has_table(table):
        return set()
    return {constraint["name"] for constraint in inspector.get_unique_constraints(table) if constraint.get("name")}


def _add_column(table: str, ddl: str) -> None:
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def ensure_schema() -> None:
    users = _column_names("users")
    if users and "role" not in users:
        _add_column("users", "role VARCHAR(24) NOT NULL DEFAULT 'operator'")

    access_keys = _column_names("access_keys")
    if access_keys and "site_id" not in access_keys:
        if_not_exists = "IF NOT EXISTS " if engine.dialect.name == "postgresql" else ""
        _add_column("access_keys", f"{if_not_exists}site_id VARCHAR(36) REFERENCES sites(id) ON DELETE CASCADE")

    sites = _column_names("sites")
    if sites and "icon_url" not in sites:
        _add_column("sites", "icon_url VARCHAR(1000)")
    if sites and "languages" not in sites:
        if engine.dialect.name == "postgresql":
            _add_column("sites", f"languages JSONB NOT NULL DEFAULT '{DEFAULT_LANGUAGES_JSON}'::jsonb")
        else:
            _add_column("sites", f"languages JSON NOT NULL DEFAULT '{DEFAULT_LANGUAGES_JSON}'")

    posts_columns = _columns("posts")
    posts = set(posts_columns)
    if posts and "language" not in posts:
        _add_column("posts", "language VARCHAR(64) NOT NULL DEFAULT 'en'")
    if posts and "author_display_name" not in posts:
        _add_column("posts", "author_display_name VARCHAR(160)")

    with engine.begin() as connection:
        if engine.dialect.name == "postgresql" and _should_resize_post_language_column(posts_columns):
            connection.execute(text("ALTER TABLE posts ALTER COLUMN language TYPE VARCHAR(64)"))
            post_constraints = _unique_constraint_names("posts")
            if "uq_posts_site_slug" in post_constraints:
                connection.execute(text("ALTER TABLE posts DROP CONSTRAINT uq_posts_site_slug"))
                post_constraints.remove("uq_posts_site_slug")
            if "uq_posts_site_language_slug" not in post_constraints:
                connection.execute(
                    text(
                        "ALTER TABLE posts "
                        "ADD CONSTRAINT uq_posts_site_language_slug UNIQUE (site_id, language, slug)"
                    )
                )
        connection.execute(text("UPDATE users SET role = 'operator' WHERE role IS NULL"))
        if sites:
            if engine.dialect.name == "postgresql":
                connection.execute(
                    text("UPDATE sites SET languages = CAST(:languages AS jsonb) WHERE languages IS NULL"),
                    {"languages": DEFAULT_LANGUAGES_JSON},
                )
            else:
                connection.execute(
                    text("UPDATE sites SET languages = :languages WHERE languages IS NULL"),
                    {"languages": DEFAULT_LANGUAGES_JSON},
                )
        connection.execute(text("UPDATE posts SET language = 'en' WHERE language IS NULL"))
        super_admin_id = connection.execute(
            text("SELECT id FROM users WHERE role = 'super_admin' LIMIT 1")
        ).scalar_one_or_none()
        if super_admin_id is None:
            first_user_id = connection.execute(
                text("SELECT id FROM users ORDER BY created_at ASC LIMIT 1")
            ).scalar_one_or_none()
            if first_user_id is not None:
                connection.execute(
                    text("UPDATE users SET role = 'super_admin' WHERE id = :id"),
                    {"id": first_user_id},
                )
