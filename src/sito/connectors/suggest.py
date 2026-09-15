"""Connectors that turn a seed keyword into autocomplete suggestions."""

from __future__ import annotations

import time
from typing import ClassVar

import httpx
from pydantic import BaseModel

from sito.plugins.base import PluginError, SuggestConnector

SUGGEST_URL = "https://suggestqueries.google.com/complete/search"


class GoogleSuggest(SuggestConnector):
    id = "google_suggest"
    name = "Google Autocomplete"
    summary = "Google's public autocomplete suggestions, no API key required."
    docs = """
No API key is needed: this uses Google's public, unofficial suggest endpoint
— the same one that powers the search box dropdown. Be polite and keep a
pause between requests, because Google can rate-limit or block an IP that
sends too many requests too fast (HTTP 429 or 403). This is an undocumented,
unofficial endpoint, so it can change or disappear without notice; you are
responsible for complying with Google's terms of service when you use it.
"""
    auto_create = True

    # Tests replace this with an ``httpx.MockTransport`` so no real network call is made.
    transport: ClassVar[httpx.BaseTransport | None] = None

    class Settings(BaseModel):
        hl: str = "en"
        gl: str = ""
        pause_seconds: float = 0.5
        timeout: float = 15

    def suggest(self, query: str) -> list[str]:
        params = {
            "client": "firefox",
            "hl": self.settings.hl,
            "ie": "utf-8",
            "oe": "utf-8",
            "q": query,
        }
        if self.settings.gl:
            params["gl"] = self.settings.gl
        client_kwargs = {"timeout": self.settings.timeout}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.get(SUGGEST_URL, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise PluginError(f"Google Autocomplete request failed: {exc}") from exc
        except ValueError as exc:
            raise PluginError(f"Google Autocomplete returned invalid JSON: {exc}") from exc
        finally:
            time.sleep(self.settings.pause_seconds)
        try:
            return [str(s) for s in data[1]]
        except (IndexError, TypeError) as exc:
            raise PluginError(f"Google Autocomplete returned an unexpected response: {data!r}") from exc

    def test(self) -> str:
        suggestions = self.suggest("seo")
        return f"OK: {len(suggestions)} suggestions for 'seo'"
