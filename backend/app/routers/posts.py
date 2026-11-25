from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, cast, func, or_, select, update
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql.elements import ColumnElement

from app import models, schemas
from app.dependencies import require_super_admin, require_super_admin_access_key, require_user
from app.db import get_db
from app.markdown_render import clean_article_markdown, render_markdown, sanitize_html_fragment
from app.post_paths import localized_post_canonical_url
from app.routers.sites import language_keys, owned_site_or_404
from app.translation_service import (
    TranslationResult as GeneratedTranslationResult,
    TranslationSource,
    TranslationUnavailableError,
    translate_post,
)

router = APIRouter(prefix="/api/sites/{site_id}/posts", tags=["posts"])


@dataclass(frozen=True)
class TranslationWorkItem:
    language: str
    target_language_label: str
    skip_reason: str | None = None
    post_id: str | None = None
    status: schemas.Status | None = None


@dataclass(frozen=True)
class TranslationOptions:
    languages: list[str]
    overwrite_existing: bool


def owned_post_or_404(db: Session, site_id: str, post_id: str) -> models.Post:
    post = db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author), selectinload(models.Post.category))
        .where(models.Post.id == post_id, models.Post.site_id == site_id)
    ).scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return post


def assert_post_slug_available(
    db: Session,
    site_id: str,
    language: str,
    slug: str,
    current_id: str | None = None,
) -> None:
    post = db.execute(
        select(models.Post).where(
            models.Post.site_id == site_id,
            models.Post.language == language,
            models.Post.slug == slug,
        )
    ).scalar_one_or_none()
    if post and post.id != current_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Post slug already exists")


def assert_category_belongs_to_site(db: Session, site_id: str, category_id: str | None) -> None:
    if category_id is None:
        return
    category = db.get(models.Category, category_id)
    if not category or category.site_id != site_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid category")


def assert_language_belongs_to_site(site: models.Site, language: str | None) -> None:
    if language is None:
        return
    if language not in language_keys(site):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid language for site")


def post_markdown_fields(markdown_content: str) -> dict[str, str]:
    markdown_content = clean_article_markdown(markdown_content)
    return {"markdown_content": markdown_content, "html_content": render_markdown(markdown_content)}


def create_draft_post(
    db: Session,
    site: models.Site,
    author_id: str,
    payload: schemas.PostCreate,
) -> models.Post:
    assert_language_belongs_to_site(site, payload.language)
    assert_post_slug_available(db, site.id, payload.language, payload.slug)
    assert_category_belongs_to_site(db, site.id, payload.category_id)
    data = payload.model_dump()
    data.update(post_markdown_fields(payload.markdown_content))
    post = models.Post(site_id=site.id, author_id=author_id, status="draft", **data)
    db.add(post)
    db.commit()
    return owned_post_or_404(db, site.id, post.id)


def post_version_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def apply_post_compare_and_swap(
    db: Session, post: models.Post, data: dict, *guards: ColumnElement[bool],
) -> None:
    current = post.updated_at
    next_version = max(datetime.now(timezone.utc), post_version_utc(current) + timedelta(microseconds=1))
    version_matches = models.Post.updated_at == current
    if db.get_bind().dialect.name == "sqlite" and current.microsecond == 0:
        # SQLite's CURRENT_TIMESTAMP omits fractional seconds.
        version_matches = or_(
            version_matches,
            cast(models.Post.updated_at, String) == current.isoformat(sep=" ", timespec="seconds"),
        )
    result = db.execute(
        update(models.Post)
        .where(models.Post.id == post.id, models.Post.site_id == post.site_id, version_matches, *guards)
        .values(**data, updated_at=next_version)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Post version changed")


def site_language_label(site: models.Site, language: str) -> str:
    for item in site.languages or []:
        if isinstance(item, dict) and item.get("key") == language:
            return str(item.get("label") or language)
    return language


def ordered_language_keys(site: models.Site) -> list[str]:
    return [
        str(language.get("key"))
        for language in (site.languages or [])
        if isinstance(language, dict) and language.get("key")
    ]


def post_by_language_and_slug(db: Session, site_id: str, language: str, slug: str) -> models.Post | None:
    return db.execute(
        select(models.Post).where(
            models.Post.site_id == site_id,
            models.Post.language == language,
            models.Post.slug == slug,
        )
    ).scalar_one_or_none()


def sync_publish_state(post: models.Post, status_value: str | None) -> None:
    if status_value == "published" and post.published_at is None:
        post.published_at = datetime.now(timezone.utc)
    if status_value == "draft":
        post.published_at = None


def template_article_from_post(post: models.Post) -> schemas.TranslationTemplateArticleInput:
    return schemas.TranslationTemplateArticleInput(
        title=post.title,
        slug=post.slug,
        language=post.language,
        html_content=post.html_content,
        markdown_content=post.markdown_content,
        excerpt=post.excerpt,
        cover_image_url=post.cover_image_url,
        meta_title=post.meta_title,
        meta_description=post.meta_description,
        canonical_url=post.canonical_url,
        author_display_name=post.author_display_name,
        category_id=post.category_id,
    )


def upsert_template_article_post(
    db: Session,
    site: models.Site,
    article: schemas.TranslationTemplateArticleInput,
    *,
    author_id: str,
) -> tuple[models.Post, str]:
    existing = post_by_language_and_slug(db, site.id, article.language, article.slug)
    post = existing or models.Post(
        site_id=site.id,
        language=article.language,
        slug=article.slug,
        author_id=author_id,
    )
    sanitized_html = sanitize_html_fragment(article.html_content)
    sanitized_markdown = clean_article_markdown(article.markdown_content) if article.markdown_content else sanitized_html
    post.title = article.title
    post.language = article.language
    post.slug = article.slug
    post.markdown_content = sanitized_markdown
    post.html_content = sanitized_html
    post.excerpt = article.excerpt
    post.cover_image_url = article.cover_image_url
    post.meta_title = article.meta_title
    post.meta_description = article.meta_description
    post.canonical_url = article.canonical_url or localized_post_canonical_url(site, article.language, article.slug)
    post.author_display_name = article.author_display_name
    post.category_id = article.category_id
    post.status = "draft"
    sync_publish_state(post, "draft")
    db.add(post)
    db.flush()
    return post, ("updated" if existing else "created")


def publish_posts(
    posts: list[models.Post],
    results: list[schemas.TranslationGeneratePublishResult],
) -> None:
    published_ids: set[str] = set()
    for post in posts:
        post.status = "published"
        sync_publish_state(post, "published")
        published_ids.add(post.id)

    for result in results:
        if result.post_id in published_ids and result.action != "skipped":
            result.status = "published"


def _plan_translation_work(
    db: Session,
    site: models.Site,
    source_article: schemas.TranslationTemplateArticleInput,
    *,
    source_post_id: str | None,
    source_status: schemas.Status,
    options: TranslationOptions,
    allow_overwrite_published: bool,
) -> list[TranslationWorkItem]:
    work_items: list[TranslationWorkItem] = []

    for language in options.languages:
        if language == source_article.language:
            work_items.append(
                TranslationWorkItem(
                    language=language,
                    target_language_label=site_language_label(site, language),
                    skip_reason="same_as_source_language",
                    post_id=source_post_id,
                    status=source_status,
                )
            )
            continue

        existing = post_by_language_and_slug(db, site.id, language, source_article.slug)
        if existing and existing.status == "published" and (not allow_overwrite_published or not options.overwrite_existing):
            work_items.append(
                TranslationWorkItem(
                    language=language,
                    target_language_label=site_language_label(site, language),
                    skip_reason="published_translation_exists",
                    post_id=existing.id,
                    status=existing.status,
                )
            )
            continue
        if existing and not options.overwrite_existing:
            work_items.append(
                TranslationWorkItem(
                    language=language,
                    target_language_label=site_language_label(site, language),
                    skip_reason="draft_translation_exists",
                    post_id=existing.id,
                    status=existing.status,
                )
            )
            continue

        work_items.append(
            TranslationWorkItem(
                language=language,
                target_language_label=site_language_label(site, language),
            )
        )

    return work_items


def _end_transaction(db: Session) -> None:
    if db.in_transaction():
        db.rollback()


def _translate_work_items(
    source_article: schemas.TranslationTemplateArticleInput,
    work_items: list[TranslationWorkItem],
) -> dict[str, GeneratedTranslationResult]:
    translated_by_language: dict[str, GeneratedTranslationResult] = {}
    sanitized_source_html = sanitize_html_fragment(source_article.html_content)

    for item in work_items:
        if item.skip_reason:
            continue

        translated = translate_post(
            TranslationSource(
                title=source_article.title,
                excerpt=source_article.excerpt,
                meta_title=source_article.meta_title,
                meta_description=source_article.meta_description,
                html_content=sanitized_source_html,
                source_language=source_article.language,
                target_language=item.language,
                target_language_label=item.target_language_label,
            )
        )

        translated_by_language[item.language] = translated

    return translated_by_language


def _apply_generated_translations(
    db: Session,
    site: models.Site,
    source_article: schemas.TranslationTemplateArticleInput,
    *,
    author_id: str,
    options: TranslationOptions,
    allow_overwrite_published: bool,
    work_items: list[TranslationWorkItem],
    translated_by_language: dict[str, GeneratedTranslationResult],
) -> tuple[list[schemas.TranslationGeneratePublishResult], list[models.Post]]:
    results: list[schemas.TranslationGeneratePublishResult] = []
    changed_posts: list[models.Post] = []

    for item in work_items:
        if item.skip_reason:
            results.append(
                schemas.TranslationGeneratePublishResult(
                    language=item.language,
                    action="skipped",
                    reason=item.skip_reason,
                    post_id=item.post_id,
                    status=item.status,
                )
            )
            continue

        existing = post_by_language_and_slug(db, site.id, item.language, source_article.slug)
        if existing and existing.status == "published" and (not allow_overwrite_published or not options.overwrite_existing):
            results.append(
                schemas.TranslationGeneratePublishResult(
                    language=item.language,
                    action="skipped",
                    reason="published_translation_exists",
                    post_id=existing.id,
                    status=existing.status,
                )
            )
            continue
        if existing and not options.overwrite_existing:
            results.append(
                schemas.TranslationGeneratePublishResult(
                    language=item.language,
                    action="skipped",
                    reason="draft_translation_exists",
                    post_id=existing.id,
                    status=existing.status,
                )
            )
            continue

        translated = translated_by_language[item.language]
        post = existing or models.Post(
            site_id=site.id,
            language=item.language,
            slug=source_article.slug,
            author_id=author_id,
        )
        sanitized_html = sanitize_html_fragment(translated.html_content)
        post.title = translated.title
        post.language = item.language
        post.slug = source_article.slug
        post.status = "draft"
        post.markdown_content = sanitized_html
        post.html_content = sanitized_html
        post.excerpt = translated.excerpt
        post.cover_image_url = source_article.cover_image_url
        post.meta_title = translated.meta_title
        post.meta_description = translated.meta_description
        post.canonical_url = localized_post_canonical_url(site, item.language, source_article.slug)
        post.author_display_name = source_article.author_display_name
        post.category_id = source_article.category_id
        sync_publish_state(post, post.status)
        db.add(post)
        db.flush()
        changed_posts.append(post)
        results.append(
            schemas.TranslationGeneratePublishResult(
                language=item.language,
                action="updated" if existing else "created",
                post_id=post.id,
                status=post.status,
            )
        )

    return results, changed_posts


@router.get("", response_model=schemas.PostListResponse)
def list_posts(
    site_id: str,
    status_filter: schemas.Status | None = Query(default=None, alias="status"),
    category_id: str | None = None,
    language: str | None = Query(default=None, min_length=1, max_length=64, pattern=schemas.LANGUAGE_KEY_PATTERN),
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
) -> schemas.PostListResponse:
    site = owned_site_or_404(db, user.id, site_id)
    assert_language_belongs_to_site(site, language)
    filters = [models.Post.site_id == site_id]
    if status_filter:
        filters.append(models.Post.status == status_filter)
    if category_id:
        filters.append(models.Post.category_id == category_id)
    if language:
        filters.append(models.Post.language == language)
    if q and (search := q.strip()):
        term = f"%{search}%"
        filters.append(or_(models.Post.title.ilike(term), models.Post.slug.ilike(term)))

    total = db.execute(select(func.count(models.Post.id)).where(*filters)).scalar_one()
    stmt = (
        select(models.Post)
        .options(selectinload(models.Post.author), selectinload(models.Post.category))
        .where(*filters)
        .order_by(models.Post.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = list(db.execute(stmt).scalars().all())
    return schemas.PostListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=schemas.PostRead, status_code=status.HTTP_201_CREATED)
def create_post(
    site_id: str,
    payload: schemas.PostCreate,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
) -> models.Post:
    site = owned_site_or_404(db, user.id, site_id)
    return create_draft_post(db, site, user.id, payload)


@router.post("/import", response_model=schemas.PostRead)
def import_post(
    site_id: str,
    payload: schemas.ImportedPostUpsert,
    user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> models.Post:
    site = owned_site_or_404(db, user.id, site_id)
    assert_language_belongs_to_site(site, payload.language)
    assert_category_belongs_to_site(db, site_id, payload.category_id)

    post = post_by_language_and_slug(db, site_id, payload.language, payload.slug)
    if not post:
        post = models.Post(
            site_id=site_id,
            language=payload.language,
            slug=payload.slug,
            author_id=user.id,
        )

    sanitized_html = sanitize_html_fragment(payload.html_content)
    sanitized_markdown = clean_article_markdown(payload.markdown_content) if payload.markdown_content else sanitized_html
    post.title = payload.title
    post.language = payload.language
    post.slug = payload.slug
    post.markdown_content = sanitized_markdown
    post.html_content = sanitized_html
    post.excerpt = payload.excerpt
    post.cover_image_url = payload.cover_image_url
    post.meta_title = payload.meta_title
    post.meta_description = payload.meta_description
    post.canonical_url = payload.canonical_url or localized_post_canonical_url(site, payload.language, payload.slug)
    post.author_display_name = payload.author_display_name
    post.category_id = payload.category_id
    post.status = payload.status
    if payload.status == "published":
        post.published_at = payload.published_at or post.published_at or datetime.now(timezone.utc)
    else:
        post.published_at = None

    db.add(post)
    db.commit()
    return owned_post_or_404(db, site_id, post.id)


@router.get("/{post_id}", response_model=schemas.PostRead)
def get_post(
    site_id: str,
    post_id: str,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
) -> models.Post:
    owned_site_or_404(db, user.id, site_id)
    return owned_post_or_404(db, site_id, post_id)


@router.post(
    "/translations/generate-and-publish",
    response_model=schemas.TranslationGeneratePublishResponse,
)
def generate_and_publish_translations_from_article(
    site_id: str,
    payload: schemas.TranslationGenerateFromArticleRequest,
    user: models.User = Depends(require_super_admin_access_key),
    db: Session = Depends(get_db),
) -> schemas.TranslationGeneratePublishResponse:
    site = owned_site_or_404(db, user.id, site_id)
    article = payload.article

    assert_language_belongs_to_site(site, article.language)
    assert_category_belongs_to_site(db, site_id, article.category_id)
    for language in payload.languages:
        assert_language_belongs_to_site(site, language)

    requested_languages = payload.languages or [language for language in ordered_language_keys(site) if language != article.language]
    target_languages = [language for language in requested_languages if language != article.language]
    translation_options = TranslationOptions(languages=target_languages, overwrite_existing=payload.overwrite_existing)

    try:
        work_items = _plan_translation_work(
            db,
            site,
            article,
            source_post_id=None,
            source_status="draft",
            options=translation_options,
            allow_overwrite_published=True,
        )
        _end_transaction(db)
        translated_by_language = _translate_work_items(article, work_items)

        site = owned_site_or_404(db, user.id, site_id)
        assert_category_belongs_to_site(db, site_id, article.category_id)
        for language in target_languages:
            assert_language_belongs_to_site(site, language)

        source_post, source_action = upsert_template_article_post(db, site, article, author_id=user.id)
        translation_results, changed_posts = _apply_generated_translations(
            db,
            site,
            article,
            author_id=source_post.author_id,
            options=translation_options,
            allow_overwrite_published=True,
            work_items=work_items,
            translated_by_language=translated_by_language,
        )
    except TranslationUnavailableError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    source_result = schemas.TranslationGeneratePublishResult(
        language=article.language,
        action=source_action,
        post_id=source_post.id,
        status=source_post.status,
    )
    all_results = [source_result, *translation_results]
    publish_posts([source_post, *changed_posts], all_results)
    db.commit()
    return schemas.TranslationGeneratePublishResponse(
        source_post_id=source_post.id,
        source_language=article.language,
        results=all_results,
    )


@router.post(
    "/{post_id}/translations/generate",
    response_model=schemas.TranslationGenerateResponse,
)
def generate_translations(
    site_id: str,
    post_id: str,
    payload: schemas.TranslationGenerateRequest,
    user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> schemas.TranslationGenerateResponse:
    site = owned_site_or_404(db, user.id, site_id)
    source_post = owned_post_or_404(db, site_id, post_id)
    source_article = template_article_from_post(source_post)

    for language in payload.languages:
        assert_language_belongs_to_site(site, language)

    try:
        work_items = _plan_translation_work(
            db,
            site,
            source_article,
            source_post_id=source_post.id,
            source_status=source_post.status,
            options=TranslationOptions(languages=payload.languages, overwrite_existing=payload.overwrite_existing),
            allow_overwrite_published=False,
        )
        _end_transaction(db)
        translated_by_language = _translate_work_items(source_article, work_items)

        site = owned_site_or_404(db, user.id, site_id)
        source_post = owned_post_or_404(db, site_id, post_id)
        results, _ = _apply_generated_translations(
            db,
            site,
            source_article,
            author_id=source_post.author_id,
            options=TranslationOptions(languages=payload.languages, overwrite_existing=payload.overwrite_existing),
            allow_overwrite_published=False,
            work_items=work_items,
            translated_by_language=translated_by_language,
        )
    except TranslationUnavailableError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    db.commit()
    return schemas.TranslationGenerateResponse(
        source_post_id=source_post.id,
        source_language=source_post.language,
        results=[
            schemas.TranslationGenerateResult(
                language=result.language,
                action=result.action,
                reason=result.reason,
                post_id=result.post_id,
            )
            for result in results
        ],
    )


@router.post(
    "/{post_id}/translations/generate-and-publish",
    response_model=schemas.TranslationGeneratePublishResponse,
)
def generate_and_publish_translations(
    site_id: str,
    post_id: str,
    payload: schemas.TranslationGenerateRequest,
    user: models.User = Depends(require_super_admin_access_key),
    db: Session = Depends(get_db),
) -> schemas.TranslationGeneratePublishResponse:
    site = owned_site_or_404(db, user.id, site_id)
    source_post = owned_post_or_404(db, site_id, post_id)
    source_article = template_article_from_post(source_post)

    for language in payload.languages:
        assert_language_belongs_to_site(site, language)

    try:
        work_items = _plan_translation_work(
            db,
            site,
            source_article,
            source_post_id=source_post.id,
            source_status=source_post.status,
            options=TranslationOptions(languages=payload.languages, overwrite_existing=payload.overwrite_existing),
            allow_overwrite_published=False,
        )
        _end_transaction(db)
        translated_by_language = _translate_work_items(source_article, work_items)

        site = owned_site_or_404(db, user.id, site_id)
        source_post = owned_post_or_404(db, site_id, post_id)
        results, changed_posts = _apply_generated_translations(
            db,
            site,
            source_article,
            author_id=source_post.author_id,
            options=TranslationOptions(languages=payload.languages, overwrite_existing=payload.overwrite_existing),
            allow_overwrite_published=False,
            work_items=work_items,
            translated_by_language=translated_by_language,
        )
    except TranslationUnavailableError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    publish_posts(changed_posts, results)
    db.commit()
    return schemas.TranslationGeneratePublishResponse(
        source_post_id=source_post.id,
        source_language=source_post.language,
        results=results,
    )


@router.patch("/{post_id}", response_model=schemas.PostRead)
def update_post(
    site_id: str,
    post_id: str,
    payload: schemas.PostUpdate,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
) -> models.Post:
    site = owned_site_or_404(db, user.id, site_id)
    post = owned_post_or_404(db, site_id, post_id)
    data = payload.model_dump(exclude_unset=True)
    expected_updated_at = data.pop("expected_updated_at", None)
    if expected_updated_at is not None and post_version_utc(expected_updated_at) != post_version_utc(post.updated_at):
        raise HTTPException(status_code=409, detail="Post version changed")
    if "category_id" in data:
        assert_category_belongs_to_site(db, site_id, data["category_id"])
    if "language" in data:
        assert_language_belongs_to_site(site, data["language"])
    if "slug" in data or "language" in data:
        assert_post_slug_available(
            db,
            site_id,
            data.get("language", post.language),
            data.get("slug", post.slug),
            current_id=post.id,
        )
    if "markdown_content" in data:
        data.update(post_markdown_fields(data["markdown_content"] or ""))
    if expected_updated_at is not None:
        if data:
            apply_post_compare_and_swap(db, post, data)
    else:
        for field, value in data.items():
            setattr(post, field, value)
        db.add(post)
    if expected_updated_at is not None:
        db.refresh(post)
        db.commit()
        return post
    db.commit()
    return owned_post_or_404(db, site_id, post.id)


@router.post("/{post_id}/publish", response_model=schemas.PostRead)
def publish_post(
    site_id: str,
    post_id: str,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
) -> models.Post:
    owned_site_or_404(db, user.id, site_id)
    post = owned_post_or_404(db, site_id, post_id)
    post.status = "published"
    sync_publish_state(post, "published")
    db.add(post)
    db.commit()
    return owned_post_or_404(db, site_id, post.id)


@router.post("/{post_id}/unpublish", response_model=schemas.PostRead)
def unpublish_post(
    site_id: str,
    post_id: str,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
) -> models.Post:
    owned_site_or_404(db, user.id, site_id)
    post = owned_post_or_404(db, site_id, post_id)
    post.status = "draft"
    sync_publish_state(post, "draft")
    db.add(post)
    db.commit()
    return owned_post_or_404(db, site_id, post.id)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    site_id: str,
    post_id: str,
    user: models.User = Depends(require_user),
    db: Session = Depends(get_db),
) -> None:
    owned_site_or_404(db, user.id, site_id)
    post = owned_post_or_404(db, site_id, post_id)
    db.delete(post)
    db.commit()
