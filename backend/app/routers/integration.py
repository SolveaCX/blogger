import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import case, select
from sqlalchemy.orm import Session, selectinload

from app import models, schemas
from app.core.config import settings
from app.dependencies import Principal, get_authenticated_principal
from app.db import get_db
from app.post_paths import default_language_key, localized_post_path
from app.routers.sites import language_keys

router = APIRouter(prefix="/api/integration", tags=["integration"])


def require_published_integration_site(
    site_slug: str,
    request: Request,
    db: Session = Depends(get_db),
    x_access_key: str | None = Header(default=None, alias="X-Access-Key"),
) -> models.Site:
    # This credential is accepted only by the published-content routes below.
    # It never authenticates as a user or grants access to management APIs.
    read_key_hash = settings.published_integration_key_sha256
    read_only_access = (
        x_access_key
        and x_access_key.startswith("blog_ro_")
        and site_slug == settings.published_integration_site_slug
        and hmac.compare_digest(hashlib.sha256(x_access_key.encode()).hexdigest(), read_key_hash)
    )
    query = select(models.Site).where(models.Site.slug == site_slug)
    if not read_only_access:
        principal = get_authenticated_principal(request, db, x_access_key)
        if principal.access_key is not None and principal.access_key.site_id is not None:
            query = query.where(models.Site.id == principal.access_key.site_id)
    site = db.execute(query).scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    return site


def integration_post(site: models.Site, post: models.Post) -> schemas.IntegrationPost:
    return schemas.IntegrationPost(
        id=post.id,
        site_slug=site.slug,
        title=post.title,
        slug=post.slug,
        language=post.language,
        path=localized_post_path(site, post.language, post.slug),
        html_content=post.html_content,
        excerpt=post.excerpt,
        cover_image_url=post.cover_image_url,
        meta_title=post.meta_title,
        meta_description=post.meta_description,
        canonical_url=post.canonical_url,
        author_display_name=post.author_display_name,
        published_at=post.published_at,
        updated_at=post.updated_at,
        author=post.author,
        category=post.category,
    )


def assert_language_belongs_to_site(site: models.Site, language: str | None) -> None:
    if language is None:
        return
    if language not in language_keys(site):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid language for site")


@router.get("/sites", response_model=list[schemas.SiteRead])
def list_integration_sites(
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> list[models.Site]:
    if principal.access_key is not None and principal.access_key.site_id is not None:
        scope = models.Site.id == principal.access_key.site_id
    else:
        scope = models.Site.owner_id == principal.user.id
    return list(db.scalars(select(models.Site).where(scope)))


@router.get("/sites/{site_slug}/categories", response_model=list[schemas.CategoryRead])
def list_integration_categories(
    site: models.Site = Depends(require_published_integration_site),
    db: Session = Depends(get_db),
) -> list[models.Category]:
    return list(
        db.execute(
            select(models.Category)
            .where(models.Category.site_id == site.id)
            .order_by(models.Category.name.asc())
        )
        .scalars()
        .all()
    )


@router.get("/sites/{site_slug}/posts", response_model=list[schemas.IntegrationPost])
def list_integration_posts(
    category_slug: str | None = None,
    language: str | None = Query(default=None, min_length=1, max_length=64, pattern=schemas.LANGUAGE_KEY_PATTERN),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    site: models.Site = Depends(require_published_integration_site),
    db: Session = Depends(get_db),
) -> list[schemas.IntegrationPost]:
    assert_language_belongs_to_site(site, language)
    stmt = (
        select(models.Post)
        .options(selectinload(models.Post.author), selectinload(models.Post.category))
        .where(models.Post.site_id == site.id, models.Post.status == "published")
        .order_by(models.Post.published_at.desc(), models.Post.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if category_slug:
        stmt = stmt.join(models.Category).where(models.Category.slug == category_slug)
    if language:
        stmt = stmt.where(models.Post.language == language)
    posts = list(db.execute(stmt).scalars().all())
    return [integration_post(site, post) for post in posts]


@router.get("/sites/{site_slug}/posts/{post_slug}", response_model=schemas.IntegrationPost)
def get_integration_post(
    post_slug: str,
    language: str | None = Query(default=None, min_length=1, max_length=64, pattern=schemas.LANGUAGE_KEY_PATTERN),
    site: models.Site = Depends(require_published_integration_site),
    db: Session = Depends(get_db),
) -> schemas.IntegrationPost:
    assert_language_belongs_to_site(site, language)
    filters = [
        models.Post.site_id == site.id,
        models.Post.slug == post_slug,
        models.Post.status == "published",
    ]
    if language:
        filters.append(models.Post.language == language)
    stmt = (
        select(models.Post)
        .options(selectinload(models.Post.author), selectinload(models.Post.category))
        .where(*filters)
    )
    if not language and (default_language := default_language_key(site)):
        stmt = stmt.order_by(case((models.Post.language == default_language, 0), else_=1))
    post = db.execute(stmt.limit(1)).scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return integration_post(site, post)
