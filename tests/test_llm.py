from __future__ import annotations

import json

import httpx
import pytest

from sito.connectors.llm import Anthropic, OpenAICompatible
from sito.plugins.base import PluginError


@pytest.fixture(autouse=True)
def _reset_transports():
    yield
    OpenAICompatible.transport = None
    Anthropic.transport = None


def test_openai_parses_fenced_json_and_tracks_usage():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer sk-test"
        content = '```json\n{"results": [{"keyword": "a"}]}\n```'
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
        )

    OpenAICompatible.transport = httpx.MockTransport(handler)
    connector = OpenAICompatible(OpenAICompatible.Settings(api_key="sk-test"))
    result = connector.complete_json("system", "prompt")
    assert result == {"results": [{"keyword": "a"}]}
    assert connector.usage == {"requests": 1, "input_tokens": 12, "output_tokens": 4}


def test_openai_no_key_omits_auth_header_and_omits_temperature_when_unset():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        assert "temperature" not in json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}], "usage": {}})

    OpenAICompatible.transport = httpx.MockTransport(handler)
    connector = OpenAICompatible(OpenAICompatible.Settings())
    connector.complete_json("system", "prompt")


def test_openai_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("sito.connectors.llm.time.sleep", lambda seconds: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": {"message": "rate limited"}}, headers={"Retry-After": "0"})
        body = {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}}
        return httpx.Response(200, json=body)

    OpenAICompatible.transport = httpx.MockTransport(handler)
    connector = OpenAICompatible(OpenAICompatible.Settings(max_retries=3))
    result = connector.complete_json("system", "prompt")
    assert result == {"ok": True}
    assert calls["n"] == 2


def test_openai_401_raises_plugin_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    OpenAICompatible.transport = httpx.MockTransport(handler)
    connector = OpenAICompatible(OpenAICompatible.Settings(api_key="bad"))
    with pytest.raises(PluginError, match="rejected"):
        connector.complete_json("system", "prompt")


def test_anthropic_parses_text_blocks_and_tracks_usage():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "ak-test"
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": '{"results": ['},
                    {"type": "text", "text": '{"keyword": "b"}]}'},
                ],
                "usage": {"input_tokens": 7, "output_tokens": 3},
            },
        )

    Anthropic.transport = httpx.MockTransport(handler)
    connector = Anthropic(Anthropic.Settings(api_key="ak-test"))
    result = connector.complete_json("system", "prompt")
    assert result == {"results": [{"keyword": "b"}]}
    assert connector.usage == {"requests": 1, "input_tokens": 7, "output_tokens": 3}


def test_openai_non_json_body_raises_plugin_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>")

    OpenAICompatible.transport = httpx.MockTransport(handler)
    connector = OpenAICompatible(OpenAICompatible.Settings())
    with pytest.raises(PluginError, match="non-JSON"):
        connector.complete_json("system", "prompt")


def test_openai_missing_choices_raises_plugin_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"usage": {}})  # no "choices" key at all

    OpenAICompatible.transport = httpx.MockTransport(handler)
    connector = OpenAICompatible(OpenAICompatible.Settings())
    with pytest.raises(PluginError, match="unexpected shape"):
        connector.complete_json("system", "prompt")


def test_openai_null_content_raises_plugin_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": None}}], "usage": {}})

    OpenAICompatible.transport = httpx.MockTransport(handler)
    connector = OpenAICompatible(OpenAICompatible.Settings())
    with pytest.raises(PluginError, match="empty answer"):
        connector.complete_json("system", "prompt")


def test_anthropic_body_without_text_blocks_raises_plugin_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"content": [{"type": "tool_use", "id": "x"}], "usage": {"input_tokens": 1, "output_tokens": 1}},
        )

    Anthropic.transport = httpx.MockTransport(handler)
    connector = Anthropic(Anthropic.Settings(api_key="ak-test"))
    with pytest.raises(PluginError, match="empty answer"):
        connector.complete_json("system", "prompt")


def test_anthropic_529_is_retryable(monkeypatch):
    monkeypatch.setattr("sito.connectors.llm.time.sleep", lambda seconds: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(529, json={"error": {"message": "overloaded"}})
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": '{"ok": true}'}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    Anthropic.transport = httpx.MockTransport(handler)
    connector = Anthropic(Anthropic.Settings(api_key="ak-test"))
    result = connector.complete_json("system", "prompt")
    assert result == {"ok": True}
    assert calls["n"] == 2
