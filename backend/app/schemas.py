from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Status = Literal["draft", "published"]
UserRole = Literal["super_admin", "operator"]

LANGUAGE_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"


class SiteLanguage(BaseModel):
    key: str = Field(min_length=1, max_length=64, pattern=LANGUAGE_KEY_PATTERN)
    label: str = Field(min_length=1, max_length=120)

    @field_validator("key", "label", mode="before")
    @classmethod
    def strip_value(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        return value.strip()


def default_site_languages() -> list[SiteLanguage]:
    return [SiteLanguage(key="en", label="English")]


def validate_site_languages(languages: list[SiteLanguage]) -> list[SiteLanguage]:
    keys = [language.key for language in languages]
    if len(keys) != len(set(keys)):
        raise ValueError("Language keys must be unique")
    return languages


class UserBase(BaseModel):
    email: EmailStr
    nickname: str | None = None
    avatar_url: str | None = None


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    nickname: str | None = Field(default=None, max_length=120)
    avatar_url: str | None = Field(default=None, max_length=1000)


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserAdminUpdate(BaseModel):
    nickname: str | None = Field(default=None, max_length=120)
    avatar_url: str | None = Field(default=None, max_length=1000)
    role: UserRole | None = None
    is_active: bool | None = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class AccessKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class AccessKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    key_prefix: str
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class AccessKeyCreated(AccessKeyRead):
    access_key: str


class SiteBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    base_url: str | None = Field(default=None, max_length=1000)
    languages: list[SiteLanguage] = Field(default_factory=default_site_languages, min_length=1, max_length=50)
    description: str | None = None

    @field_validator("languages")
    @classmethod
    def unique_language_keys(cls, languages: list[SiteLanguage]) -> list[SiteLanguage]:
        return validate_site_languages(languages)


class SiteCreate(SiteBase):
    pass


class SiteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    slug: str | None = Field(default=None, min_length=1, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    base_url: str | None = Field(default=None, max_length=1000)
    languages: list[SiteLanguage] | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = None

    @field_validator("languages")
    @classmethod
    def unique_language_keys(cls, languages: list[SiteLanguage] | None) -> list[SiteLanguage] | None:
        if languages is None:
            return languages
        return validate_site_languages(languages)


class SiteRead(SiteBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    icon_url: str | None = None
    created_at: datetime
    updated_at: datetime


class CategoryBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, min_length=1, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None


class CategoryRead(CategoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    site_id: str
    created_at: datetime
    updated_at: datetime


class PostBase(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    language: str = Field(default="en", min_length=1, max_length=64, pattern=LANGUAGE_KEY_PATTERN)
    markdown_content: str = Field(min_length=1)
    excerpt: str | None = None
    cover_image_url: str | None = Field(default=None, max_length=1000)
    meta_title: str | None = Field(default=None, max_length=255)
    meta_description: str | None = Field(default=None, max_length=500)
    canonical_url: str | None = Field(default=None, max_length=1000)
    author_display_name: str | None = Field(default=None, max_length=160)
    category_id: str | None = None


class PostCreate(PostBase):
    model_config = ConfigDict(extra="forbid")


class PostUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: datetime | None = None
    title: str | None = Field(default=None, min_length=1, max_length=240)
    slug: str | None = Field(default=None, min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    language: str | None = Field(default=None, min_length=1, max_length=64, pattern=LANGUAGE_KEY_PATTERN)
    markdown_content: str | None = Field(default=None, min_length=1)
    excerpt: str | None = None
    cover_image_url: str | None = Field(default=None, max_length=1000)
    meta_title: str | None = Field(default=None, max_length=255)
    meta_description: str | None = Field(default=None, max_length=500)
    canonical_url: str | None = Field(default=None, max_length=1000)
    author_display_name: str | None = Field(default=None, max_length=160)
    category_id: str | None = None


class AuthorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    nickname: str | None
    avatar_url: str | None


class PostRead(PostBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    site_id: str
    author_id: str
    status: Status
    markdown_content: str
    html_content: str
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    author: AuthorRead
    category: CategoryRead | None = None


class PostListResponse(BaseModel):
    items: list[PostRead]
    total: int
    limit: int
    offset: int


class IntegrationPost(BaseModel):
    id: str
    site_slug: str
    title: str
    slug: str
    language: str
    path: str
    html_content: str
    excerpt: str | None
    cover_image_url: str | None
    meta_title: str | None
    meta_description: str | None
    canonical_url: str | None
    author_display_name: str | None
    published_at: datetime | None
    updated_at: datetime
    author: AuthorRead
    category: CategoryRead | None = None


class ImportedPostUpsert(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    language: str = Field(min_length=1, max_length=64, pattern=LANGUAGE_KEY_PATTERN)
    html_content: str = Field(min_length=1)
    markdown_content: str | None = None
    excerpt: str | None = None
    cover_image_url: str | None = Field(default=None, max_length=1000)
    meta_title: str | None = Field(default=None, max_length=255)
    meta_description: str | None = Field(default=None, max_length=500)
    canonical_url: str | None = Field(default=None, max_length=1000)
    author_display_name: str | None = Field(default=None, max_length=160)
    category_id: str | None = None
    status: Status = "draft"
    published_at: datetime | None = None


class TranslationTemplateArticleInput(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    language: str = Field(min_length=1, max_length=64, pattern=LANGUAGE_KEY_PATTERN)
    html_content: str = Field(min_length=1)
    markdown_content: str | None = Field(default=None, min_length=1)
    excerpt: str | None = None
    cover_image_url: str | None = Field(default=None, max_length=1000)
    meta_title: str | None = Field(default=None, max_length=255)
    meta_description: str | None = Field(default=None, max_length=500)
    canonical_url: str | None = Field(default=None, max_length=1000)
    author_display_name: str | None = Field(default=None, max_length=160)
    category_id: str | None = None


class TranslationGenerateRequest(BaseModel):
    languages: list[str] = Field(min_length=1, max_length=50)
    overwrite_existing: bool = False

    @field_validator("languages")
    @classmethod
    def unique_languages(cls, languages: list[str]) -> list[str]:
        normalized = [language.strip() for language in languages if language.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Language keys must be unique")
        if not normalized:
            raise ValueError("At least one language is required")
        return normalized


class TranslationGenerateFromArticleRequest(BaseModel):
    article: TranslationTemplateArticleInput
    languages: list[str] = Field(default_factory=list, max_length=50)
    overwrite_existing: bool = False

    @field_validator("languages")
    @classmethod
    def unique_languages(cls, languages: list[str]) -> list[str]:
        normalized = [language.strip() for language in languages if language.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Language keys must be unique")
        return normalized


class TranslationGenerateResult(BaseModel):
    language: str
    action: Literal["created", "updated", "skipped"]
    reason: str | None = None
    post_id: str | None = None


class TranslationGenerateResponse(BaseModel):
    source_post_id: str
    source_language: str
    results: list[TranslationGenerateResult]


class TranslationGeneratePublishResult(TranslationGenerateResult):
    status: Status | None = None


class TranslationGeneratePublishResponse(BaseModel):
    source_post_id: str
    source_language: str
    results: list[TranslationGeneratePublishResult]


class UploadResponse(BaseModel):
    url: str
