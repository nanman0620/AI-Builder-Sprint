import asyncio
from types import SimpleNamespace

import pytest

from app.services import gemini_change_input_client


def test_gemini_client_uses_async_structured_output(monkeypatch):
    captured = {}

    class Models:
        async def generate_content(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(text='{"ok":true}')

    fake_client = SimpleNamespace(aio=SimpleNamespace(models=Models()))
    monkeypatch.setattr(gemini_change_input_client.genai, "Client", lambda **kwargs: fake_client)
    monkeypatch.setattr(gemini_change_input_client, "get_gemini_api_key", lambda: "secret")
    monkeypatch.setattr(gemini_change_input_client, "get_gemini_model", lambda: "gemini-test")
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    result = asyncio.run(gemini_change_input_client.generate_change_input(
        prompt="prompt", response_json_schema=schema
    ))
    assert result == '{"ok":true}'
    assert captured["model"] == "gemini-test"
    assert captured["contents"] == "prompt"
    assert captured["config"].response_mime_type == "application/json"
    assert captured["config"].response_json_schema == schema


def test_gemini_client_rejects_blank_response(monkeypatch):
    class Models:
        async def generate_content(self, **kwargs):
            return SimpleNamespace(text=" ")

    monkeypatch.setattr(
        gemini_change_input_client.genai,
        "Client",
        lambda **kwargs: SimpleNamespace(aio=SimpleNamespace(models=Models())),
    )
    monkeypatch.setattr(gemini_change_input_client, "get_gemini_api_key", lambda: "secret")
    monkeypatch.setattr(gemini_change_input_client, "get_gemini_model", lambda: "gemini-test")
    with pytest.raises(gemini_change_input_client.GeminiChangeInputError):
        asyncio.run(gemini_change_input_client.generate_change_input(
            prompt="prompt", response_json_schema={"type": "object"}
        ))
