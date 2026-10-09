import base64
import inspect
import os
from pathlib import Path

TEST_DB = Path("/tmp/blogger-api-test.sqlite3")
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ACCESS_KEY_PEPPER"] = "test-pepper"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import api_healthz, app, healthz  # noqa: E402
from app.translation_service import TranslationResult  # noqa: E402

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

client = TestClient(app)
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
    "AAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def test_health_handlers_do_not_depend_on_the_sync_thread_pool() -> None:
    assert inspect.iscoroutinefunction(healthz)
    assert inspect.iscoroutinefunction(api_healthz)


def reset_db() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_blog_lifecycle_with_access_key() -> None:
    reset_db()
    register = client.post(
        "/api/auth/register",
        json={
            "email": "owner@example.com",
            "password": "password123",
            "nickname": "Owner",
        },
    )
    assert register.status_code == 201, register.text
    assert register.json()["user"]["role"] == "super_admin"
    token = register.json()["access_token"]
    jwt_headers = {"Authorization": f"Bearer {token}"}

    key_response = client.post("/api/access-keys", json={"name": "ci"}, headers=jwt_headers)
    assert key_response.status_code == 201, key_response.text
    access_key = key_response.json()["access_key"]
    key_headers = {"X-Access-Key": access_key}

    site_response = client.post(
        "/api/sites",
        json={"name": "Main Site", "slug": "main-site", "base_url": "https://example.com"},
        headers=key_headers,
    )
    assert site_response.status_code == 201, site_response.text
    site_id = site_response.json()["id"]
    assert site_response.json()["languages"] == [{"key": "en", "label": "English"}]

    language_update = client.patch(
        f"/api/sites/{site_id}",
        json={
            "languages": [
                {"key": "en", "label": "English"},
                {"key": "zh-CN", "label": "中文"},
            ]
        },
        headers=key_headers,
    )
    assert language_update.status_code == 200, language_update.text
    assert language_update.json()["languages"][1]["key"] == "zh-CN"

    category_response = client.post(
        f"/api/sites/{site_id}/categories",
        json={"name": "Product", "slug": "product"},
        headers=key_headers,
    )
    assert category_response.status_code == 201, category_response.text
    category_id = category_response.json()["id"]

    post_response = client.post(
        f"/api/sites/{site_id}/posts",
        json={
            "title": "First Post",
            "slug": "first-post",
            "language": "en",
            "markdown_content": "# Hello\n\n<script>alert(1)</script>\n\nWorld",
            "category_id": category_id,
            "meta_title": "First SEO title",
            "meta_description": "First SEO description",
            "cover_image_url": "https://example.com/cover.png",
        },
        headers=key_headers,
    )
    assert post_response.status_code == 201, post_response.text
    post = post_response.json()
    assert post["author"]["email"] == "owner@example.com"
    assert post["status"] == "draft"
    assert post["language"] == "en"
    assert "<h1" in post["html_content"]
    assert "<script>" not in post["html_content"]
    post_id = post["id"]

    custom_language_post = client.post(
        f"/api/sites/{site_id}/posts",
        json={
            "title": "Chinese Post",
            "slug": "first-post",
            "language": "zh-CN",
            "markdown_content": "# 你好",
        },
        headers=key_headers,
    )
    assert custom_language_post.status_code == 201, custom_language_post.text
    assert custom_language_post.json()["language"] == "zh-CN"
    custom_language_post_id = custom_language_post.json()["id"]

    duplicate_language_slug_post = client.post(
        f"/api/sites/{site_id}/posts",
        json={
            "title": "Duplicate English Post",
            "slug": "first-post",
            "language": "en",
            "markdown_content": "# Duplicate",
        },
        headers=key_headers,
    )
    assert duplicate_language_slug_post.status_code == 409, duplicate_language_slug_post.text

    invalid_language_post = client.post(
        f"/api/sites/{site_id}/posts",
        json={
            "title": "French Post",
            "slug": "french-post",
            "language": "fr",
            "markdown_content": "# Bonjour",
        },
        headers=key_headers,
    )
    assert invalid_language_post.status_code == 400, invalid_language_post.text

    remove_used_language = client.patch(
        f"/api/sites/{site_id}",
        json={"languages": [{"key": "zh-CN", "label": "中文"}]},
        headers=key_headers,
    )
    assert remove_used_language.status_code == 400, remove_used_language.text

    status_rejected = client.patch(
        f"/api/sites/{site_id}/posts/{post_id}",
        json={"status": "published"},
        headers=key_headers,
    )
    assert status_rejected.status_code == 422, status_rejected.text

    list_response = client.get(
        f"/api/sites/{site_id}/posts?language=en&category_id={category_id}&status=draft",
        headers=key_headers,
    )
    assert list_response.status_code == 200, list_response.text
    page = list_response.json()
    assert page["total"] == 1
    assert page["items"][0]["slug"] == "first-post"
    assert page["items"][0]["cover_image_url"] == "https://example.com/cover.png"

    slug_search_response = client.get(
        f"/api/sites/{site_id}/posts?q=first-po",
        headers=key_headers,
    )
    assert slug_search_response.status_code == 200, slug_search_response.text
    slug_search_page = slug_search_response.json()
    assert slug_search_page["total"] == 2
    assert slug_search_page["items"][0]["slug"] == "first-post"

    publish_response = client.post(f"/api/sites/{site_id}/posts/{post_id}/publish", headers=key_headers)
    assert publish_response.status_code == 200, publish_response.text
    assert publish_response.json()["status"] == "published"
    publish_custom_language_response = client.post(
        f"/api/sites/{site_id}/posts/{custom_language_post_id}/publish",
        headers=key_headers,
    )
    assert publish_custom_language_response.status_code == 200, publish_custom_language_response.text

    public_list = client.get("/api/integration/sites/main-site/posts?language=en", headers=key_headers)
    assert public_list.status_code == 200, public_list.text
    assert public_list.json()[0]["path"] == "/blog/first-post"
    assert public_list.json()[0]["language"] == "en"

    public_detail = client.get("/api/integration/sites/main-site/posts/first-post", headers=key_headers)
    assert public_detail.status_code == 200, public_detail.text
    assert public_detail.json()["language"] == "en"
    assert public_detail.json()["meta_title"] == "First SEO title"
    public_custom_language_detail = client.get(
        "/api/integration/sites/main-site/posts/first-post?language=zh-CN",
        headers=key_headers,
    )
    assert public_custom_language_detail.status_code == 200, public_custom_language_detail.text
    assert public_custom_language_detail.json()["language"] == "zh-CN"
    assert public_custom_language_detail.json()["path"] == "/zh-CN/blog/first-post"
    assert public_custom_language_detail.json()["title"] == "Chinese Post"

    upload = client.post(
        "/api/uploads",
        data={"kind": "avatar"},
        files={"file": ("avatar.png", b"fake-png", "image/png")},
        headers=jwt_headers,
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["url"].startswith("data:image/png;base64,")

    png_upload_without_mime = client.post(
        "/api/uploads",
        data={"kind": "cover"},
        files={
            "file": (
                "cover.png",
                PNG_1X1,
                "application/octet-stream",
            )
        },
        headers=jwt_headers,
    )
    assert png_upload_without_mime.status_code == 200, png_upload_without_mime.text
    assert png_upload_without_mime.json()["url"].startswith("data:image/png;base64,")

    invalid_upload_without_mime = client.post(
        "/api/uploads",
        data={"kind": "cover"},
        files={"file": ("cover", b"not an image", "application/octet-stream")},
        headers=jwt_headers,
    )
    assert invalid_upload_without_mime.status_code == 400, invalid_upload_without_mime.text

    invalid_png_upload_without_mime = client.post(
        "/api/uploads",
        data={"kind": "cover"},
        files={"file": ("cover.png", b"not an image", "application/octet-stream")},
        headers=jwt_headers,
    )
    assert invalid_png_upload_without_mime.status_code == 400, invalid_png_upload_without_mime.text

    invalid_upload_with_image_filename = client.post(
        "/api/uploads",
        data={"kind": "cover"},
        files={"file": ("cover.png", b"not an image", "text/plain")},
        headers=jwt_headers,
    )
    assert invalid_upload_with_image_filename.status_code == 400, invalid_upload_with_image_filename.text

    operator_register = client.post(
        "/api/auth/register",
        json={
            "email": "operator@example.com",
            "password": "password123",
            "nickname": "Operator",
        },
    )
    assert operator_register.status_code == 201, operator_register.text
    assert operator_register.json()["user"]["role"] == "operator"
    operator_headers = {"Authorization": f"Bearer {operator_register.json()['access_token']}"}
    forbidden_site = client.post(
        "/api/sites",
        json={"name": "Operator Site", "slug": "operator-site"},
        headers=operator_headers,
    )
    assert forbidden_site.status_code == 403, forbidden_site.text

    users_response = client.get("/api/users", headers=jwt_headers)
    assert users_response.status_code == 200, users_response.text
    assert len(users_response.json()) >= 2


def test_import_post_upsert_preserves_source_fields() -> None:
    reset_db()
    register = client.post(
        "/api/auth/register",
        json={
            "email": "importer@example.com",
            "password": "password123",
            "nickname": "Importer",
        },
    )
    assert register.status_code == 201, register.text
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

    site_response = client.post(
        "/api/sites",
        json={
            "name": "Import Site",
            "slug": "import-site",
            "base_url": "https://example.com",
            "languages": [
                {"key": "en", "label": "English"},
                {"key": "zh-CN", "label": "中文"},
            ],
        },
        headers=headers,
    )
    assert site_response.status_code == 201, site_response.text
    site_id = site_response.json()["id"]

    category_response = client.post(
        f"/api/sites/{site_id}/categories",
        json={"name": "Guides", "slug": "guides"},
        headers=headers,
    )
    assert category_response.status_code == 201, category_response.text
    category_id = category_response.json()["id"]

    import_response = client.post(
        f"/api/sites/{site_id}/posts/import",
        json={
            "title": "Imported Post",
            "slug": "imported-post",
            "language": "en",
            "html_content": "<h1>Imported</h1><script>alert(1)</script><p>Body</p>",
            "excerpt": "Imported excerpt",
            "meta_title": "Imported meta title",
            "meta_description": "Imported meta description",
            "author_display_name": "Big Y",
            "category_id": category_id,
            "status": "published",
            "published_at": "2024-01-02T03:04:05Z",
        },
        headers=headers,
    )
    assert import_response.status_code == 200, import_response.text
    imported = import_response.json()
    assert imported["title"] == "Imported Post"
    assert imported["status"] == "published"
    assert imported["author_display_name"] == "Big Y"
    assert imported["canonical_url"] == "https://example.com/blog/imported-post"
    assert imported["published_at"].startswith("2024-01-02T03:04:05")
    assert "<script>" not in imported["html_content"]
    assert "<script>" not in imported["markdown_content"]
    imported_id = imported["id"]

    update_response = client.post(
        f"/api/sites/{site_id}/posts/import",
        json={
            "title": "Imported Post Updated",
            "slug": "imported-post",
            "language": "en",
            "html_content": "<p>Updated body</p>",
            "author_display_name": "Big Y",
            "category_id": category_id,
            "status": "draft",
        },
        headers=headers,
    )
    assert update_response.status_code == 200, update_response.text
    updated = update_response.json()
    assert updated["id"] == imported_id
    assert updated["title"] == "Imported Post Updated"
    assert updated["status"] == "draft"
    assert updated["published_at"] is None


def test_generate_translation_drafts(monkeypatch) -> None:
    reset_db()
    register = client.post(
        "/api/auth/register",
        json={
            "email": "translator@example.com",
            "password": "password123",
            "nickname": "Translator",
        },
    )
    assert register.status_code == 201, register.text
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

    site_response = client.post(
        "/api/sites",
        json={
            "name": "Translation Site",
            "slug": "translation-site",
            "base_url": "https://example.com",
            "languages": [
                {"key": "en", "label": "English"},
                {"key": "zh-CN", "label": "中文"},
                {"key": "fr", "label": "Francais"},
            ],
        },
        headers=headers,
    )
    assert site_response.status_code == 201, site_response.text
    site_id = site_response.json()["id"]

    category_response = client.post(
        f"/api/sites/{site_id}/categories",
        json={"name": "News", "slug": "news"},
        headers=headers,
    )
    assert category_response.status_code == 201, category_response.text
    category_id = category_response.json()["id"]

    source_response = client.post(
        f"/api/sites/{site_id}/posts/import",
        json={
            "title": "Source Post",
            "slug": "source-post",
            "language": "en",
            "html_content": "<h1>Source</h1><p>Source body</p>",
            "excerpt": "Source excerpt",
            "meta_title": "Source meta title",
            "meta_description": "Source meta description",
            "cover_image_url": "https://example.com/cover.png",
            "author_display_name": "Big Y",
            "category_id": category_id,
            "status": "published",
            "published_at": "2024-01-02T03:04:05Z",
        },
        headers=headers,
    )
    assert source_response.status_code == 200, source_response.text
    source_post_id = source_response.json()["id"]

    zh_existing = client.post(
        f"/api/sites/{site_id}/posts",
        json={
            "title": "Old Chinese Draft",
            "slug": "source-post",
            "language": "zh-CN",
            "markdown_content": "# Old Draft",
        },
        headers=headers,
    )
    assert zh_existing.status_code == 201, zh_existing.text
    zh_existing_id = zh_existing.json()["id"]

    fr_existing = client.post(
        f"/api/sites/{site_id}/posts",
        json={
            "title": "French Published",
            "slug": "source-post",
            "language": "fr",
            "markdown_content": "# Bonjour",
        },
        headers=headers,
    )
    assert fr_existing.status_code == 201, fr_existing.text
    fr_existing_id = fr_existing.json()["id"]
    fr_publish = client.post(f"/api/sites/{site_id}/posts/{fr_existing_id}/publish", headers=headers)
    assert fr_publish.status_code == 200, fr_publish.text

    calls: list[tuple[str, str]] = []

    def fake_translate(source):
        calls.append((source.source_language, source.target_language))
        return TranslationResult(
            title=f"{source.target_language} title",
            excerpt=f"{source.target_language} excerpt",
            meta_title=f"{source.target_language} meta title",
            meta_description=f"{source.target_language} meta description",
            html_content=f"<p>{source.target_language} body</p><script>alert(1)</script>",
        )

    monkeypatch.setattr("app.routers.posts.translate_post", fake_translate)

    generate_response = client.post(
        f"/api/sites/{site_id}/posts/{source_post_id}/translations/generate",
        json={"languages": ["zh-CN", "fr"], "overwrite_existing": True},
        headers=headers,
    )
    assert generate_response.status_code == 200, generate_response.text
    payload = generate_response.json()
    assert payload["source_post_id"] == source_post_id
    assert payload["results"] == [
        {"language": "zh-CN", "action": "updated", "reason": None, "post_id": zh_existing_id},
        {"language": "fr", "action": "skipped", "reason": "published_translation_exists", "post_id": fr_existing_id},
    ]
    assert calls == [("en", "zh-CN")]

    zh_list = client.get(f"/api/sites/{site_id}/posts?language=zh-CN", headers=headers)
    assert zh_list.status_code == 200, zh_list.text
    zh_post = zh_list.json()["items"][0]
    assert zh_post["id"] == zh_existing_id
    assert zh_post["title"] == "zh-CN title"
    assert zh_post["status"] == "draft"
    assert zh_post["author_display_name"] == "Big Y"
    assert zh_post["cover_image_url"] == "https://example.com/cover.png"
    assert zh_post["canonical_url"] == "https://example.com/zh-CN/blog/source-post"
    assert "<script>" not in zh_post["html_content"]
    assert "<script>" not in zh_post["markdown_content"]


def test_generate_and_publish_translations_requires_access_key(monkeypatch) -> None:
    reset_db()
    register = client.post(
        "/api/auth/register",
        json={
            "email": "publisher@example.com",
            "password": "password123",
            "nickname": "Publisher",
        },
    )
    assert register.status_code == 201, register.text
    jwt_headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

    key_response = client.post("/api/access-keys", json={"name": "external"}, headers=jwt_headers)
    assert key_response.status_code == 201, key_response.text
    access_key = key_response.json()["access_key"]
    key_headers = {"Authorization": f"Bearer {access_key}"}

    site_response = client.post(
        "/api/sites",
        json={
            "name": "External Translation Site",
            "slug": "external-translation-site",
            "base_url": "https://example.com",
            "languages": [
                {"key": "en", "label": "English"},
                {"key": "zh-CN", "label": "中文"},
                {"key": "fr", "label": "Francais"},
            ],
        },
        headers=jwt_headers,
    )
    assert site_response.status_code == 201, site_response.text
    site_id = site_response.json()["id"]

    category_response = client.post(
        f"/api/sites/{site_id}/categories",
        json={"name": "Ops", "slug": "ops"},
        headers=jwt_headers,
    )
    assert category_response.status_code == 201, category_response.text
    category_id = category_response.json()["id"]

    source_response = client.post(
        f"/api/sites/{site_id}/posts/import",
        json={
            "title": "External Source Post",
            "slug": "external-source-post",
            "language": "en",
            "html_content": "<h1>Source</h1><p>Source body</p>",
            "excerpt": "Source excerpt",
            "meta_title": "Source meta title",
            "meta_description": "Source meta description",
            "cover_image_url": "https://example.com/cover.png",
            "author_display_name": "Big Y",
            "category_id": category_id,
            "status": "published",
            "published_at": "2024-01-02T03:04:05Z",
        },
        headers=jwt_headers,
    )
    assert source_response.status_code == 200, source_response.text
    source_post_id = source_response.json()["id"]

    zh_existing = client.post(
        f"/api/sites/{site_id}/posts",
        json={
            "title": "Old Chinese Draft",
            "slug": "external-source-post",
            "language": "zh-CN",
            "markdown_content": "# Old Draft",
        },
        headers=jwt_headers,
    )
    assert zh_existing.status_code == 201, zh_existing.text
    zh_existing_id = zh_existing.json()["id"]

    fr_existing = client.post(
        f"/api/sites/{site_id}/posts",
        json={
            "title": "French Published",
            "slug": "external-source-post",
            "language": "fr",
            "markdown_content": "# Bonjour",
        },
        headers=jwt_headers,
    )
    assert fr_existing.status_code == 201, fr_existing.text
    fr_existing_id = fr_existing.json()["id"]
    fr_publish = client.post(f"/api/sites/{site_id}/posts/{fr_existing_id}/publish", headers=jwt_headers)
    assert fr_publish.status_code == 200, fr_publish.text

    calls: list[tuple[str, str]] = []

    def fake_translate(source):
        calls.append((source.source_language, source.target_language))
        return TranslationResult(
            title=f"{source.target_language} title",
            excerpt=f"{source.target_language} excerpt",
            meta_title=f"{source.target_language} meta title",
            meta_description=f"{source.target_language} meta description",
            html_content=f"<p>{source.target_language} body</p><script>alert(1)</script>",
        )

    monkeypatch.setattr("app.routers.posts.translate_post", fake_translate)

    jwt_forbidden = client.post(
        f"/api/sites/{site_id}/posts/{source_post_id}/translations/generate-and-publish",
        json={"languages": ["zh-CN"], "overwrite_existing": True},
        headers=jwt_headers,
    )
    assert jwt_forbidden.status_code == 401, jwt_forbidden.text
    assert jwt_forbidden.json()["detail"] == "Access key required"

    generate_response = client.post(
        f"/api/sites/{site_id}/posts/{source_post_id}/translations/generate-and-publish",
        json={"languages": ["zh-CN", "fr"], "overwrite_existing": True},
        headers=key_headers,
    )
    assert generate_response.status_code == 200, generate_response.text
    payload = generate_response.json()
    assert payload["source_post_id"] == source_post_id
    assert payload["results"] == [
        {"language": "zh-CN", "action": "updated", "reason": None, "post_id": zh_existing_id, "status": "published"},
        {"language": "fr", "action": "skipped", "reason": "published_translation_exists", "post_id": fr_existing_id, "status": "published"},
    ]
    assert calls == [("en", "zh-CN")]

    zh_list = client.get(f"/api/sites/{site_id}/posts?language=zh-CN", headers=key_headers)
    assert zh_list.status_code == 200, zh_list.text
    zh_post = zh_list.json()["items"][0]
    assert zh_post["id"] == zh_existing_id
    assert zh_post["title"] == "zh-CN title"
    assert zh_post["status"] == "published"
    assert zh_post["author_display_name"] == "Big Y"
    assert zh_post["cover_image_url"] == "https://example.com/cover.png"
    assert zh_post["canonical_url"] == "https://example.com/zh-CN/blog/external-source-post"
    assert "<script>" not in zh_post["html_content"]
    assert "<script>" not in zh_post["markdown_content"]


def test_generate_and_publish_translations_from_template_article_requires_access_key(monkeypatch) -> None:
    reset_db()
    register = client.post(
        "/api/auth/register",
        json={
            "email": "template-publisher@example.com",
            "password": "password123",
            "nickname": "Template Publisher",
        },
    )
    assert register.status_code == 201, register.text
    jwt_headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

    key_response = client.post("/api/access-keys", json={"name": "external-template"}, headers=jwt_headers)
    assert key_response.status_code == 201, key_response.text
    access_key = key_response.json()["access_key"]
    key_headers = {"Authorization": f"Bearer {access_key}"}

    site_response = client.post(
        "/api/sites",
        json={
            "name": "Template Translation Site",
            "slug": "template-translation-site",
            "base_url": "https://example.com",
            "languages": [
                {"key": "en", "label": "English"},
                {"key": "zh-CN", "label": "中文"},
                {"key": "fr", "label": "Francais"},
            ],
        },
        headers=jwt_headers,
    )
    assert site_response.status_code == 201, site_response.text
    site_id = site_response.json()["id"]

    category_response = client.post(
        f"/api/sites/{site_id}/categories",
        json={"name": "Ops", "slug": "ops"},
        headers=jwt_headers,
    )
    assert category_response.status_code == 201, category_response.text
    category_id = category_response.json()["id"]

    zh_existing = client.post(
        f"/api/sites/{site_id}/posts",
        json={
            "title": "Old Chinese Draft",
            "slug": "template-source-post",
            "language": "zh-CN",
            "markdown_content": "# Old Draft",
        },
        headers=jwt_headers,
    )
    assert zh_existing.status_code == 201, zh_existing.text
    zh_existing_id = zh_existing.json()["id"]

    fr_existing = client.post(
        f"/api/sites/{site_id}/posts",
        json={
            "title": "French Published",
            "slug": "template-source-post",
            "language": "fr",
            "markdown_content": "# Bonjour",
        },
        headers=jwt_headers,
    )
    assert fr_existing.status_code == 201, fr_existing.text
    fr_existing_id = fr_existing.json()["id"]
    fr_publish = client.post(f"/api/sites/{site_id}/posts/{fr_existing_id}/publish", headers=jwt_headers)
    assert fr_publish.status_code == 200, fr_publish.text

    calls: list[tuple[str, str]] = []

    def fake_translate(source):
        calls.append((source.source_language, source.target_language))
        return TranslationResult(
            title=f"{source.target_language} title",
            excerpt=f"{source.target_language} excerpt",
            meta_title=f"{source.target_language} meta title",
            meta_description=f"{source.target_language} meta description",
            html_content=f"<p>{source.target_language} body</p><script>alert(1)</script>",
        )

    monkeypatch.setattr("app.routers.posts.translate_post", fake_translate)

    request_body = {
        "article": {
            "title": "Template Source Post",
            "slug": "template-source-post",
            "language": "en",
            "html_content": "<h1>Source</h1><p>Source body</p><script>alert(1)</script>",
            "excerpt": "Source excerpt",
            "meta_title": "Source meta title",
            "meta_description": "Source meta description",
            "cover_image_url": "https://example.com/cover.png",
            "author_display_name": "Big Y",
            "category_id": category_id,
        },
        "overwrite_existing": True,
    }

    jwt_forbidden = client.post(
        f"/api/sites/{site_id}/posts/translations/generate-and-publish",
        json=request_body,
        headers=jwt_headers,
    )
    assert jwt_forbidden.status_code == 401, jwt_forbidden.text
    assert jwt_forbidden.json()["detail"] == "Access key required"

    generate_response = client.post(
        f"/api/sites/{site_id}/posts/translations/generate-and-publish",
        json=request_body,
        headers=key_headers,
    )
    assert generate_response.status_code == 200, generate_response.text
    payload = generate_response.json()
    source_post_id = payload["source_post_id"]
    assert payload["source_language"] == "en"
    assert payload["results"] == [
        {"language": "en", "action": "created", "reason": None, "post_id": source_post_id, "status": "published"},
        {"language": "zh-CN", "action": "updated", "reason": None, "post_id": zh_existing_id, "status": "published"},
        {"language": "fr", "action": "updated", "reason": None, "post_id": fr_existing_id, "status": "published"},
    ]
    assert calls == [("en", "zh-CN"), ("en", "fr")]

    en_list = client.get(f"/api/sites/{site_id}/posts?language=en", headers=key_headers)
    assert en_list.status_code == 200, en_list.text
    en_post = en_list.json()["items"][0]
    assert en_post["id"] == source_post_id
    assert en_post["status"] == "published"
    assert en_post["canonical_url"] == "https://example.com/blog/template-source-post"
    assert "<script>" not in en_post["html_content"]

    zh_list = client.get(f"/api/sites/{site_id}/posts?language=zh-CN", headers=key_headers)
    assert zh_list.status_code == 200, zh_list.text
    zh_post = zh_list.json()["items"][0]
    assert zh_post["id"] == zh_existing_id
    assert zh_post["title"] == "zh-CN title"
    assert zh_post["status"] == "published"
    assert zh_post["canonical_url"] == "https://example.com/zh-CN/blog/template-source-post"
    assert "<script>" not in zh_post["html_content"]
    assert "<script>" not in zh_post["markdown_content"]

    fr_list = client.get(f"/api/sites/{site_id}/posts?language=fr", headers=key_headers)
    assert fr_list.status_code == 200, fr_list.text
    fr_post = fr_list.json()["items"][0]
    assert fr_post["id"] == fr_existing_id
    assert fr_post["title"] == "fr title"
    assert fr_post["status"] == "published"
