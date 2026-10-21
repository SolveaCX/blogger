from __future__ import annotations

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TypeVar

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings


class TranslationUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class TranslationSource:
    title: str
    excerpt: str | None
    meta_title: str | None
    meta_description: str | None
    html_content: str
    source_language: str
    target_language: str
    target_language_label: str


class TranslationResult(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    excerpt: str | None = None
    meta_title: str | None = Field(default=None, max_length=255)
    meta_description: str | None = Field(default=None, max_length=500)
    html_content: str = Field(min_length=1)


class TranslationMetadataResult(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    excerpt: str | None = None
    meta_title: str | None = Field(default=None, max_length=255)
    meta_description: str | None = Field(default=None, max_length=500)


class TranslationHtmlChunkResult(BaseModel):
    html_content: str = Field(min_length=1)


class _TopLevelHtmlFragmentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.fragments: list[str] = []
        self._current: list[str] = []
        self._depth = 0

    def _append(self, value: str) -> None:
        self._current.append(value)

    def _flush(self) -> None:
        if not self._current:
            return
        fragment = "".join(self._current)
        if fragment:
            self.fragments.append(fragment)
        self._current = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._depth == 0 and self._current:
            self._flush()
        self._append(self.get_starttag_text())
        self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        self._append(f"</{tag}>")
        if self._depth > 0:
            self._depth -= 1
        if self._depth == 0:
            self._flush()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._depth == 0 and self._current:
            self._flush()
        self._append(self.get_starttag_text())
        if self._depth == 0:
            self._flush()

    def handle_data(self, data: str) -> None:
        self._append(data)
        if self._depth == 0 and data.strip():
            self._flush()

    def handle_entityref(self, name: str) -> None:
        self._append(f"&{name};")
        if self._depth == 0:
            self._flush()

    def handle_charref(self, name: str) -> None:
        self._append(f"&#{name};")
        if self._depth == 0:
            self._flush()

    def handle_comment(self, data: str) -> None:
        self._append(f"<!--{data}-->")
        if self._depth == 0:
            self._flush()

    def close(self) -> None:
        super().close()
        self._flush()


_SINGLE_REQUEST_HTML_THRESHOLD = 8000
_HTML_CHUNK_TARGET_SIZE = 6000
ModelT = TypeVar("ModelT", bound=BaseModel)


def _endpoint(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return ""


def _load_json_object(raw: str) -> dict[str, object]:
    text = raw.strip()
    if not text:
        raise TranslationUnavailableError("Translation model returned empty content")
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            value = json.loads(text[start : end + 1])
            if isinstance(value, dict):
                return value
    raise TranslationUnavailableError("Translation model did not return a valid JSON object")


def _system_prompt() -> str:
    return (
        "You translate technical B2B blog articles into high-quality localized versions. "
        "Preserve HTML structure, links, tables, code snippets, image URLs, and heading ids when possible. "
        "Translate only user-visible natural language. Keep brand names, product names, model ids, URLs, and code literals unchanged unless a common localized form is clearly required. "
        "Return JSON only with keys: title, excerpt, meta_title, meta_description, html_content."
    )


def _metadata_system_prompt() -> str:
    return (
        "You translate blog article metadata into a high-quality localized version. "
        "Keep brand names, model ids, URLs, and code literals unchanged unless localization is clearly required. "
        "Return JSON only with keys: title, excerpt, meta_title, meta_description."
    )


def _html_chunk_system_prompt() -> str:
    return (
        "You translate an HTML fragment from a technical B2B blog article into a localized version. "
        "Preserve all HTML tags, nesting, links, image URLs, code snippets, tables, lists, and heading ids when possible. "
        "Translate only user-visible natural language. "
        "Return JSON only with the key: html_content."
    )


def _load_model(name: str, raw: str, model: type[ModelT]) -> ModelT:
    data = _load_json_object(raw)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise TranslationUnavailableError(f"{name} payload validation failed: {exc}") from exc


def _request_translation_json(
    *,
    system_prompt: str,
    user_payload: dict[str, object],
) -> dict[str, object]:
    if not settings.translation_api_base_url or not settings.translation_api_key or not settings.translation_model:
        raise TranslationUnavailableError("Translation API is not configured")

    payload = {
        "model": settings.translation_model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            },
        ],
    }

    headers = {
        "Authorization": f"Bearer {settings.translation_api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=settings.translation_timeout_seconds) as client:
            response = client.post(_endpoint(settings.translation_api_base_url), headers=headers, json=payload)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        detail = ""
        if isinstance(exc, httpx.HTTPStatusError):
            detail = exc.response.text.strip()
        suffix = f"; provider_response={detail[:1000]}" if detail else ""
        raise TranslationUnavailableError(f"Translation request failed: {exc}{suffix}") from exc

    try:
        body = response.json()
    except json.JSONDecodeError as exc:
        raise TranslationUnavailableError("Translation provider returned invalid JSON") from exc

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise TranslationUnavailableError("Translation provider returned no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise TranslationUnavailableError("Translation provider returned an invalid choice payload")
    message = first.get("message")
    if not isinstance(message, dict):
        raise TranslationUnavailableError("Translation provider returned no message content")

    raw_content = _message_text(message.get("content"))
    return _load_json_object(raw_content)


def _split_html_into_chunks(html_content: str) -> list[str]:
    if len(html_content) <= _SINGLE_REQUEST_HTML_THRESHOLD:
        return [html_content]

    parser = _TopLevelHtmlFragmentParser()
    parser.feed(html_content)
    parser.close()
    fragments = [fragment for fragment in parser.fragments if fragment.strip()]
    if len(fragments) <= 1:
        return [html_content]

    chunks: list[str] = []
    current: list[str] = []
    current_size = 0

    for fragment in fragments:
        fragment_size = len(fragment)
        if current and current_size + fragment_size > _HTML_CHUNK_TARGET_SIZE:
            chunks.append("".join(current))
            current = [fragment]
            current_size = fragment_size
            continue
        current.append(fragment)
        current_size += fragment_size

    if current:
        chunks.append("".join(current))

    return chunks or [html_content]


def _translate_metadata(source: TranslationSource) -> TranslationMetadataResult:
    response = _request_translation_json(
        system_prompt=_metadata_system_prompt(),
        user_payload={
            "task": "Translate the article metadata into the target language.",
            "source_language": source.source_language,
            "target_language": source.target_language,
            "target_language_label": source.target_language_label,
            "article": {
                "title": source.title,
                "excerpt": source.excerpt,
                "meta_title": source.meta_title,
                "meta_description": source.meta_description,
            },
            "requirements": [
                "Keep output concise in SEO fields when they are present.",
                "Keep names, URLs, and code literals stable unless localization is clearly required.",
            ],
        },
    )
    return _load_model("Translation metadata", json.dumps(response, ensure_ascii=False), TranslationMetadataResult)


def _translate_html_chunk(
    source: TranslationSource,
    html_chunk: str,
    *,
    chunk_index: int,
    chunk_total: int,
    translated_title: str,
) -> TranslationHtmlChunkResult:
    response = _request_translation_json(
        system_prompt=_html_chunk_system_prompt(),
        user_payload={
            "task": "Translate this HTML fragment into the target language.",
            "source_language": source.source_language,
            "target_language": source.target_language,
            "target_language_label": source.target_language_label,
            "article_context": {
                "source_title": source.title,
                "translated_title": translated_title,
                "chunk_index": chunk_index,
                "chunk_total": chunk_total,
            },
            "html_content": html_chunk,
            "requirements": [
                "Preserve HTML tags and structure.",
                "Preserve href, src, code, and product names.",
                "Do not add new sections or remove factual content.",
            ],
        },
    )
    return _load_model("Translation html fragment", json.dumps(response, ensure_ascii=False), TranslationHtmlChunkResult)


def _translate_post_single(source: TranslationSource) -> TranslationResult:
    response = _request_translation_json(
        system_prompt=_system_prompt(),
        user_payload={
            "task": "Translate this blog post into the target language as a draft article.",
            "source_language": source.source_language,
            "target_language": source.target_language,
            "target_language_label": source.target_language_label,
            "article": {
                "title": source.title,
                "excerpt": source.excerpt,
                "meta_title": source.meta_title,
                "meta_description": source.meta_description,
                "html_content": source.html_content,
            },
            "requirements": [
                "Preserve HTML tags and structure.",
                "Preserve href, src, code, and product names.",
                "Do not add new sections or remove factual content.",
                "Keep output concise in SEO fields when they are present.",
            ],
        },
    )
    return _load_model("Translation", json.dumps(response, ensure_ascii=False), TranslationResult)


def translate_post(source: TranslationSource) -> TranslationResult:
    html_chunks = _split_html_into_chunks(source.html_content)
    if len(html_chunks) == 1 and len(source.html_content) <= _SINGLE_REQUEST_HTML_THRESHOLD:
        return _translate_post_single(source)

    metadata = _translate_metadata(source)
    translated_html_chunks: list[str] = []
    for index, html_chunk in enumerate(html_chunks, start=1):
        translated_chunk = _translate_html_chunk(
            source,
            html_chunk,
            chunk_index=index,
            chunk_total=len(html_chunks),
            translated_title=metadata.title,
        )
        translated_html_chunks.append(translated_chunk.html_content)

    return TranslationResult(
        title=metadata.title,
        excerpt=metadata.excerpt,
        meta_title=metadata.meta_title,
        meta_description=metadata.meta_description,
        html_content="".join(translated_html_chunks),
    )
