import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone

from httpx import ASGITransport, AsyncClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy.orm import sessionmaker

from app import blog_mcp, db, main, models


def test_blog_mcp_scoped_draft_workflow(tmp_path, monkeypatch):
    engine = db.create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'blog-mcp.sqlite'}")
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(db, "SessionLocal", sessions)
    monkeypatch.setattr(main, "settings", replace(main.settings, auto_create_tables=False))

    token = "blog_mcp_" + "a" * 43
    grants = [{
        "key_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "user_id": "writer",
        "site_ids": ["first"],
    }]
    monkeypatch.setattr(blog_mcp, "mcp_grants", blog_mcp.parse_grants(json.dumps(grants)))
    with sessions.begin() as session:
        for user_id in ("editor", "writer"):
            session.add(models.User(id=user_id, email=f"{user_id}@example.com", hashed_password="test-only"))
        for site_id in ("first", "second"):
            session.add(models.Site(id=site_id, slug=site_id, name=site_id, owner_id="editor"))
        for post_id, site_id, status in (
            ("live", "first", "published"),
            ("private", "first", "draft"),
            ("other", "second", "published"),
        ):
            session.add(models.Post(
                id=post_id, slug=post_id, title=post_id, status=status, author_id="editor", site_id=site_id,
                published_at=datetime.now(timezone.utc) if status == "published" else None,
            ))

    async def exercise_tools(client):
        info = await client.initialize()
        assert info.serverInfo.name == "Blogger"
        assert {tool.name for tool in (await client.list_tools()).tools} == {
            "list_sites", "list_posts", "get_post", "create_draft", "update_draft",
        }
        sites = await client.call_tool("list_sites", {})
        assert [site["id"] for site in sites.structuredContent["items"]] == ["first"]
        posts = await client.call_tool("list_posts", {"site_id": "first"})
        assert [post["id"] for post in posts.structuredContent["items"]] == ["live"]

        async def call_error(name, args, code):
            result = await client.call_tool(name, args)
            assert result.isError
            assert f"{code}:" in result.content[0].text

        for site_id, post_id in (("first", "private"), ("second", "other")):
            await call_error("get_post", {"site_id": site_id, "post_id": post_id}, 404)
        live = (await client.call_tool("get_post", {"site_id": "first", "post_id": "live"})).structuredContent
        assert live["path"] == "/blog/live"
        assert "author" not in live
        await call_error(
            "update_draft",
            {"site_id": "first", "post_id": "live", "expected_updated_at": live["updated_at"],
             "changes": {"title": "attempted live change"}},
            403,
        )

        args = {
            "site_id": "first",
            "post": {"slug": "new-draft", "title": "Demo", "language": "en", "markdown_content": "# Demo"},
        }
        await call_error("create_draft", {**args, "site_id": "second"}, 404)
        created = await client.call_tool("create_draft", args)
        assert not created.isError, created.content
        draft = created.structuredContent
        assert draft["status"] == "draft" and draft["path"] is None
        await call_error("create_draft", args, 409)
        update = {
            "site_id": "first", "post_id": draft["id"], "expected_updated_at": draft["updated_at"],
            "changes": {"markdown_content": "# Updated"},
        }
        updated = await client.call_tool("update_draft", update)
        assert not updated.isError, updated.content
        assert updated.structuredContent["updated_at"] != draft["updated_at"]
        assert "Updated</h1>" in updated.structuredContent["html_content"]
        await call_error("update_draft", update, 409)
        return draft["id"]

    async def run():
        async with main.app.router.lifespan_context(main.app):
            async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://testserver") as http:
                assert (await http.post("/api/mcp")).status_code == 401
                http.headers["Authorization"] = f"Bearer {token}"
                assert (await http.post("/api/mcp", headers={"Origin": "https://example.com"})).status_code == 403
                assert (await http.get("/api/sites")).status_code == 401
                async with streamable_http_client("http://testserver/api/mcp", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as client:
                        return await exercise_tools(client)

    try:
        draft_id = asyncio.run(run())
        with sessions() as session:
            draft = session.get(models.Post, draft_id)
            assert (draft.author_id, draft.status, draft.markdown_content) == ("writer", "draft", "# Updated")
            assert session.get(models.Post, "live").title == "live"
    finally:
        engine.dispose()
