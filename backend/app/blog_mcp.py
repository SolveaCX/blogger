import hashlib
import logging
import re
from collections.abc import Callable
from contextlib import aclosing
from datetime import datetime
from functools import partial
from typing import Annotated, TypeVar

from anyio import to_thread
from fastapi import HTTPException
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, defer
from sqlalchemy.sql.elements import ColumnElement
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app import models, schemas
from app.core.config import settings
from app.db import get_db
from app.post_paths import localized_post_path
from app.routers.posts import (
    apply_post_compare_and_swap,
    assert_language_belongs_to_site,
    create_draft_post,
    post_markdown_fields,
    post_version_utc,
)

RecordID = Annotated[str, Field(min_length=1, max_length=36)]
Language = Annotated[str, Field(pattern=schemas.LANGUAGE_KEY_PATTERN)]
Title = Annotated[str, Field(min_length=1, max_length=240)]
Markdown = Annotated[str, Field(min_length=1, max_length=250_000)]
Result = TypeVar("Result")
MCP_PATH = "/api/mcp"
TOKEN_PATTERN = re.compile(r"blog_mcp_[A-Za-z0-9_-]{43}")
logger = logging.getLogger(__name__)


class McpGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    user_id: RecordID
    site_ids: Annotated[frozenset[RecordID], Field(min_length=1)]


def parse_grants(value: str) -> dict[str, McpGrant]:
    try:
        grants = TypeAdapter(list[McpGrant]).validate_json(value)
    except ValidationError:
        raise ValueError("Invalid BLOGGER_MCP_GRANTS configuration") from None
    by_hash = {grant.key_sha256: grant for grant in grants}
    if len(by_hash) != len(grants):
        raise ValueError("BLOGGER_MCP_GRANTS contains duplicate key hashes")
    return by_hash


mcp_grants = parse_grants(settings.mcp_grants_json)


class McpCredentialMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers = Headers(scope=scope)
        # This endpoint serves native clients using explicit bearer credentials.
        # Reject browser origins to prevent cross-origin access and DNS rebinding.
        if "origin" in headers:
            response = JSONResponse({"detail": "Browser origin is not allowed"}, status_code=403)
            await response(scope, receive, send)
            return

        scheme, _, token = headers.get("authorization", "").partition(" ")
        grant = None
        if scheme.lower() == "bearer" and TOKEN_PATTERN.fullmatch(token):
            grant = mcp_grants.get(hashlib.sha256(token.encode()).hexdigest())
        if grant is None:
            response = JSONResponse(
                {"detail": "Blogger MCP credential required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        scope.setdefault("state", {})["blogger_mcp_grant"] = grant
        await self.app(scope, receive, send)


class PostMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    excerpt: str | None = Field(default=None, max_length=10_000)
    cover_image_url: str | None = Field(default=None, max_length=1000)
    meta_title: str | None = Field(default=None, max_length=255)
    meta_description: str | None = Field(default=None, max_length=500)


class DraftInput(PostMetadata):
    title: Title
    slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    language: Language
    markdown_content: Markdown


class DraftChanges(PostMetadata):
    title: Title | None = None
    markdown_content: Markdown | None = None

    @model_validator(mode="after")
    def check_changes(self) -> "DraftChanges":
        if not self.model_fields_set:
            raise ValueError("Supply at least one change")
        for field in ("title", "markdown_content"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class SiteInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    base_url: str | None
    languages: list[schemas.SiteLanguage]


class SiteList(BaseModel):
    items: list[SiteInfo]


class PostSummary(BaseModel):
    id: str
    site_id: str
    title: str
    slug: str
    language: str
    status: schemas.Status
    updated_at: datetime
    published_at: datetime | None
    path: str | None
    excerpt: str | None
    cover_image_url: str | None
    meta_title: str | None
    meta_description: str | None


class PostDetail(PostSummary):
    markdown_content: str
    html_content: str
    canonical_url: str | None


class PostPage(BaseModel):
    items: list[PostSummary]
    total: int
    limit: int
    offset: int


mcp = FastMCP(
    "Blogger",
    instructions="Query published blog posts and work on your drafts at authorized Blogger sites.",
    host="0.0.0.0",
    streamable_http_path=MCP_PATH,
    stateless_http=True,
    json_response=True,
)


async def run_tool(ctx: Context, operation: Callable[[Session, McpGrant], Result]) -> Result:
    request = ctx.request_context.request
    grant = getattr(request.state, "blogger_mcp_grant", None) if request is not None else None
    if not isinstance(grant, McpGrant):
        raise ToolError("401: Blogger MCP credential required")

    def invoke(db: Session) -> Result:
        user = db.get(models.User, grant.user_id)
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="Inactive Blogger account")
        return operation(db, grant)

    try:
        async with aclosing(get_db()) as sessions:
            db = await anext(sessions)
            return await to_thread.run_sync(invoke, db)
    except HTTPException as exc:
        raise ToolError(f"{exc.status_code}: {exc.detail}") from None
    except SQLAlchemyError as exc:
        logger.error("Blogger MCP database operation failed (%s)", type(exc).__name__)
        raise ToolError("503: Blogger database operation failed") from None


def granted_site_or_404(db: Session, grant: McpGrant, site_id: str) -> models.Site:
    site = db.get(models.Site, site_id) if site_id in grant.site_ids else None
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


def own_draft(user_id: str) -> ColumnElement[bool]:
    return and_(
        models.Post.author_id == user_id,
        models.Post.status == "draft",
        models.Post.published_at.is_(None),
    )


def visible_posts(user_id: str) -> ColumnElement[bool]:
    return or_(models.Post.status == "published", own_draft(user_id))


def visible_post_or_404(db: Session, site_id: str, post_id: str, user_id: str) -> models.Post:
    post = db.scalar(
        select(models.Post).where(
            models.Post.site_id == site_id,
            models.Post.id == post_id,
            visible_posts(user_id),
        )
    )
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


def summarize(site: models.Site, post: models.Post) -> PostSummary:
    return PostSummary(
        id=post.id,
        site_id=post.site_id,
        title=post.title,
        slug=post.slug,
        language=post.language,
        status=post.status,
        updated_at=post_version_utc(post.updated_at),
        published_at=post_version_utc(post.published_at) if post.published_at is not None else None,
        path=localized_post_path(site, post.language, post.slug) if post.status == "published" else None,
        excerpt=post.excerpt,
        cover_image_url=post.cover_image_url,
        meta_title=post.meta_title,
        meta_description=post.meta_description,
    )


def detail(site: models.Site, post: models.Post) -> PostDetail:
    return PostDetail(
        **summarize(site, post).model_dump(),
        markdown_content=post.markdown_content,
        html_content=post.html_content,
        canonical_url=post.canonical_url,
    )


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def list_sites(ctx: Context) -> SiteList:
    """List the Blogger sites granted to this credential, including their supported language keys."""
    def operation(db: Session, grant: McpGrant) -> SiteList:
        sites = db.scalars(
            select(models.Site).where(models.Site.id.in_(grant.site_ids)).order_by(models.Site.slug)
        )
        return SiteList(items=[SiteInfo.model_validate(site) for site in sites])

    return await run_tool(ctx, operation)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def list_posts(
    ctx: Context,
    site_id: RecordID,
    status: schemas.Status | None = None,
    language: Language | None = None,
    q: Annotated[str, Field(max_length=240)] | None = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> PostPage:
    """Search published posts and your own drafts by title or slug; use get_post to read the body."""
    def operation(db: Session, grant: McpGrant) -> PostPage:
        site = granted_site_or_404(db, grant, site_id)
        assert_language_belongs_to_site(site, language)
        post = models.Post
        filters = [post.site_id == site.id, visible_posts(grant.user_id)]
        if status is not None:
            filters.append(post.status == status)
        if language is not None:
            filters.append(post.language == language)
        if q and (search := q.strip()):
            filters.append(or_(post.title.icontains(search, autoescape=True), post.slug.icontains(search, autoescape=True)))
        total = db.execute(select(func.count(post.id)).where(*filters)).scalar_one()
        items = db.scalars(
            select(post)
            .options(defer(post.markdown_content), defer(post.html_content))
            .where(*filters)
            .order_by(post.updated_at.desc(), post.id)
            .limit(limit)
            .offset(offset)
        )
        return PostPage(items=[summarize(site, item) for item in items], total=total, limit=limit, offset=offset)

    return await run_tool(ctx, operation)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def get_post(ctx: Context, site_id: RecordID, post_id: RecordID) -> PostDetail:
    """Read a published post or your draft by ID, including its article body and update timestamp."""
    def operation(db: Session, grant: McpGrant) -> PostDetail:
        site = granted_site_or_404(db, grant, site_id)
        return detail(site, visible_post_or_404(db, site_id, post_id, grant.user_id))

    return await run_tool(ctx, operation)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, openWorldHint=False))
async def create_draft(ctx: Context, site_id: RecordID, post: DraftInput) -> PostDetail:
    """Import Markdown into a new unpublished draft; an existing site, language and slug is never overwritten."""
    def operation(db: Session, grant: McpGrant) -> PostDetail:
        site = granted_site_or_404(db, grant, site_id)
        payload = schemas.PostCreate.model_validate(post.model_dump())
        try:
            created = create_draft_post(db, site, grant.user_id, payload)
        except IntegrityError:
            db.rollback()
            # The unique constraint also covers a concurrent create of the same slug.
            duplicate = db.scalar(
                select(models.Post.id).where(
                    models.Post.site_id == site_id,
                    models.Post.language == post.language,
                    models.Post.slug == post.slug,
                )
            )
            if duplicate is not None:
                raise HTTPException(status_code=409, detail="Post slug already exists") from None
            raise
        return detail(site, created)

    return await run_tool(ctx, operation)


def save_draft_changes(
    db: Session,
    grant: McpGrant,
    *,
    site_id: str,
    post_id: str,
    expected_updated_at: datetime,
    changes: DraftChanges,
) -> PostDetail:
    site = granted_site_or_404(db, grant, site_id)
    post = visible_post_or_404(db, site_id, post_id, grant.user_id)
    if post.status != "draft":
        raise HTTPException(status_code=403, detail="Published posts are read-only")
    if post_version_utc(post.updated_at) != expected_updated_at:
        raise HTTPException(status_code=409, detail="Post version changed; read it again before editing")

    data = changes.model_dump(exclude_unset=True)
    if "markdown_content" in data:
        data.update(post_markdown_fields(data["markdown_content"]))
    apply_post_compare_and_swap(db, post, data, own_draft(grant.user_id))
    db.refresh(post)
    db.commit()
    return detail(site, post)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True, openWorldHint=False))
async def update_draft(
    ctx: Context,
    site_id: RecordID,
    post_id: RecordID,
    expected_updated_at: AwareDatetime,
    changes: DraftChanges,
) -> PostDetail:
    """Change your own draft using the exact updated_at returned by get_post; published content stays live as-is."""
    return await run_tool(
        ctx,
        partial(
            save_draft_changes,
            site_id=site_id,
            post_id=post_id,
            expected_updated_at=expected_updated_at,
            changes=changes,
        ),
    )


mcp_app = mcp.streamable_http_app()
mcp_app.add_middleware(McpCredentialMiddleware)
