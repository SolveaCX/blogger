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


class _ResponsesClient:
    request_json = None
    request_url = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, **kwargs):
        type(self).request_url = url
        type(self).request_json = kwargs["json"]
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": '{"title":"Olá"}'},
                        ],
                    },
                ],
            },
        )


def test_translation_supports_responses_api(monkeypatch):
    monkeypatch.setattr(
        translation_service,
        "settings",
        SimpleNamespace(
            translation_api_base_url="https://cpr.example.test/v1",
            translation_api_key="test-key",
            translation_model="test-model",
            translation_api_mode="responses",
            translation_timeout_seconds=10,
        ),
    )
    monkeypatch.setattr(translation_service.httpx, "Client", _ResponsesClient)

    result = translation_service._request_translation_json(
        system_prompt="translate",
        user_payload={"text": "hello"},
    )

    assert result == {"title": "Olá"}
    assert _ResponsesClient.request_url == "https://cpr.example.test/v1/responses"
    assert _ResponsesClient.request_json == {
        "model": "test-model",
        "instructions": "translate",
        "input": 'Return a json object only.\n{"text": "hello"}',
        "text": {"format": {"type": "json_object"}},
    }
