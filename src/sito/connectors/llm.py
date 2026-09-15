"""Built-in LLM connectors.

Both connectors only need to satisfy :class:`~sito.plugins.base.LLMConnector`:
``complete_json(system, prompt) -> dict | list``. Retries, rate-limit backoff and usage
accounting are shared here so the AI stages (:mod:`sito.stages.ai`) stay simple.
"""

from __future__ import annotations

import threading
import time
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, SecretStr

from sito.plugins.base import LLMConnector, PluginError, parse_json_payload

MAX_BACKOFF = 30.0
_DEFAULT_RETRYABLE = frozenset({429, 500, 502, 503, 504})


def _backoff_seconds(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(float(retry_after), MAX_BACKOFF)
        except ValueError:
            pass
    return min(2.0**attempt, MAX_BACKOFF)


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)
    if isinstance(error, str):
        return error
    return response.text[:300]


def _post_with_retries(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any],
    max_retries: int,
    retryable_statuses: frozenset[int] = _DEFAULT_RETRYABLE,
) -> httpx.Response:
    """POST JSON, retrying on 429/5xx/timeouts/connection errors with exponential backoff.

    Raises :class:`PluginError` with a message meant for the user once retries are
    exhausted, or immediately when the provider rejects the request outright. Returns
    the raw response on success; the caller still has to make sense of its body.
    """
    attempts = max(0, max_retries) + 1
    last_error = ""
    for attempt in range(attempts):
        try:
            response = client.post(url, headers=headers, json=json_body)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt + 1 < attempts:
                time.sleep(_backoff_seconds(attempt, None))
                continue
            raise PluginError(f"The LLM API did not respond after {attempts} attempts: {last_error}") from exc

        if response.status_code in (401, 403):
            detail = _error_message(response)
            code = response.status_code
            raise PluginError(f"The LLM API key was rejected (HTTP {code}): {detail}")
        if response.status_code in retryable_statuses:
            last_error = f"HTTP {response.status_code}: {_error_message(response)}"
            if attempt + 1 < attempts:
                time.sleep(_backoff_seconds(attempt, response.headers.get("Retry-After")))
                continue
            raise PluginError(f"The LLM API kept failing after {attempts} attempts: {last_error}")
        if response.status_code >= 400:
            raise PluginError(f"The LLM API rejected the request: {_error_message(response)}")
        return response
    raise PluginError(f"The LLM API kept failing: {last_error}")  # pragma: no cover - unreachable


def _parse_json_body(response: httpx.Response) -> dict[str, Any]:
    """The success path still has to guard against a 200 with a broken/unexpected body."""
    try:
        data = response.json()
    except ValueError as exc:
        excerpt = response.text[:200]
        raise PluginError(f"The model returned a non-JSON response (HTTP {response.status_code}): {excerpt!r}") from exc
    if not isinstance(data, dict):
        excerpt = str(data)[:200]
        raise PluginError(f"The model returned an unexpected response shape (HTTP {response.status_code}): {excerpt!r}")
    return data


def _require_text(content: Any) -> str:
    if not isinstance(content, str) or not content.strip():
        raise PluginError("The model returned an empty answer.")
    return content


class _HttpLLMConnector(LLMConnector):
    """Shared plumbing for HTTP-based LLM connectors: usage totals and an httpx client."""

    # Set by tests to an httpx.MockTransport; left alone, httpx makes real requests.
    transport: ClassVar[httpx.BaseTransport | None] = None

    def __init__(self, settings: BaseModel) -> None:
        super().__init__(settings)
        self.usage: dict[str, int] = {"requests": 0, "input_tokens": 0, "output_tokens": 0}
        self._usage_lock = threading.Lock()

    def _record_usage(self, input_tokens: int, output_tokens: int) -> None:
        with self._usage_lock:
            self.usage["requests"] += 1
            self.usage["input_tokens"] += int(input_tokens or 0)
            self.usage["output_tokens"] += int(output_tokens or 0)

    def _client(self) -> httpx.Client:
        kwargs: dict[str, Any] = {"timeout": self.settings.timeout}
        if self.transport is not None:
            kwargs["transport"] = self.transport
        return httpx.Client(**kwargs)

    def test(self) -> str:
        result = self.complete_json("Reply with JSON only, no prose.", 'Reply with exactly {"ok": true}')
        return f"OK: {self.settings.model} answered {result!r}"


class OpenAICompatible(_HttpLLMConnector):
    id = "openai"
    name = "OpenAI / OpenAI-compatible"
    summary = "Chat Completions API - OpenAI itself, or any compatible server (Ollama, vLLM, ...)."
    signup_url = "https://platform.openai.com/api-keys"
    docs = """
Works with OpenAI and any OpenAI-compatible server: just change the Base URL.

Presets:
- **OpenAI** - Base URL `https://api.openai.com/v1`. Get a key at
  <https://platform.openai.com/api-keys>.
- **Local Ollama** - Base URL `http://localhost:11434/v1`, no key needed. Run
  `ollama pull <model>` first.

More presets: see docs/connections.md
"""

    class Settings(BaseModel):
        api_key: SecretStr = SecretStr("")
        base_url: str = "https://api.openai.com/v1"
        model: str = "gpt-4o-mini"
        temperature: float | None = None
        json_mode: bool = True
        timeout: float = 120
        max_retries: int = 3

    def complete_json(self, system: str, prompt: str) -> Any:
        body: dict[str, Any] = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if self.settings.temperature is not None:
            body["temperature"] = self.settings.temperature
        if self.settings.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        key = self.settings.api_key.get_secret_value()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        with self._client() as client:
            response = _post_with_retries(
                client,
                f"{self.settings.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json_body=body,
                max_retries=self.settings.max_retries,
            )
        data = _parse_json_body(response)
        usage = data.get("usage") or {}
        self._record_usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            excerpt = str(data)[:200]
            raise PluginError(
                f"The model's response had an unexpected shape (HTTP {response.status_code}): {excerpt!r}"
            ) from exc
        return parse_json_payload(_require_text(content))


class Anthropic(_HttpLLMConnector):
    id = "anthropic"
    name = "Anthropic Claude"
    summary = "Anthropic's Messages API - a solid default for bulk keyword classification."
    signup_url = "https://console.anthropic.com/"
    docs = """
Get an API key at <https://console.anthropic.com/>.

`claude-haiku-4-5-20251001` is cheap and fast for bulk classification; use
`claude-sonnet-5` or `claude-opus-5` for higher-quality clustering and naming.
"""

    class Settings(BaseModel):
        api_key: SecretStr = SecretStr("")
        model: str = "claude-haiku-4-5-20251001"
        max_tokens: int = 4096
        timeout: float = 120
        max_retries: int = 3

    def complete_json(self, system: str, prompt: str) -> Any:
        body = {
            "model": self.settings.model,
            "max_tokens": self.settings.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": self.settings.api_key.get_secret_value(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        with self._client() as client:
            response = _post_with_retries(
                client,
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json_body=body,
                max_retries=self.settings.max_retries,
                retryable_statuses=_DEFAULT_RETRYABLE | {529},  # 529 = Anthropic "overloaded"
            )
        data = _parse_json_body(response)
        usage = data.get("usage") or {}
        self._record_usage(usage.get("input_tokens", 0), usage.get("output_tokens", 0))
        blocks = data.get("content")
        if not isinstance(blocks, list):
            excerpt = str(data)[:200]
            raise PluginError(
                f"The model's response had an unexpected shape (HTTP {response.status_code}): {excerpt!r}"
            )
        text = "".join(
            block.get("text", "") for block in blocks if isinstance(block, dict) and block.get("type") == "text"
        )
        return parse_json_payload(_require_text(text))
