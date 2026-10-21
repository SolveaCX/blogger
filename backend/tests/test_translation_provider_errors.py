import httpx
import pytest
from types import SimpleNamespace

from app import translation_service
from app.translation_service import TranslationUnavailableError


class _FailingClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(
            503,
            request=request,
            json={"error": {"code": "model_not_found", "message": "no route"}},
        )


def test_translation_error_preserves_provider_response(monkeypatch):
    monkeypatch.setattr(
        translation_service,
        "settings",
        SimpleNamespace(
            translation_api_base_url="https://example.test/v1",
            translation_api_key="test-key",
            translation_model="test-model",
            translation_timeout_seconds=10,
        ),
    )
    monkeypatch.setattr(translation_service.httpx, "Client", _FailingClient)

    with pytest.raises(TranslationUnavailableError) as exc_info:
        translation_service._request_translation_json(system_prompt="translate", user_payload={"text": "hello"})

    message = str(exc_info.value)
    assert "503 Service Unavailable" in message
    assert "model_not_found" in message
    assert "no route" in message
