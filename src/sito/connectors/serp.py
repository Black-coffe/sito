"""Built-in SERP connectors: XMLRiver and Serper.dev (both proxy Google search)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import ClassVar, Literal
from xml.etree.ElementTree import Element  # type only; all parsing goes through defusedxml below

import httpx
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException
from pydantic import BaseModel, SecretStr

from sito.plugins.base import PluginError, SerpConnector, SerpItem, SerpPage

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_BACKOFF = (1.0, 2.0, 4.0)  # seconds, between attempts


def _send_with_retry(perform: Callable[[], httpx.Response], *, retries: int, name: str) -> httpx.Response:
    """Run ``perform`` (an HTTP call), retrying on 429/5xx/timeouts with backoff.

    Raises :class:`PluginError` immediately on 401/403 (bad key, no point retrying).
    Returns the last response otherwise, even if it never became a "good" one.
    """
    last_exc: Exception | None = None
    response: httpx.Response | None = None
    for attempt in range(retries):
        try:
            response = perform()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc, response = exc, None
        else:
            last_exc = None
            if response.status_code in (401, 403):
                raise PluginError(
                    f"{name} rejected the API key (HTTP {response.status_code}). "
                    "Check the key on this connection's settings."
                )
            if response.status_code not in _RETRYABLE_STATUS:
                return response
        if attempt < retries - 1:
            time.sleep(_BACKOFF[min(attempt, len(_BACKOFF) - 1)])
    if response is not None:
        return response
    raise PluginError(f"{name}: could not reach the SERP provider ({last_exc}).")


def _raise_for_status(response: httpx.Response, name: str) -> None:
    if response.status_code >= 400:
        raise PluginError(f"{name}: HTTP {response.status_code} — {response.text[:200]}")


class XMLRiverSettings(BaseModel):
    user_id: str = ""
    api_key: SecretStr = SecretStr("")
    country: int = 2840
    lr: str = "EN"
    domain: int = 10
    loc: str = ""
    device: Literal["desktop", "tablet", "mobile"] = "desktop"
    timeout: float = 60


class XMLRiver(SerpConnector):
    id: ClassVar[str] = "xmlriver"
    name: ClassVar[str] = "XMLRiver (Google)"
    summary: ClassVar[str] = "Google SERP via XMLRiver: one request per keyword, top 10 organic results."
    docs: ClassVar[str] = """
Sign up at https://xmlriver.com/, top up your balance and grab your **user id**
and **key** from https://xmlriver.com/queries/.

`country`, `lr` (language) and `domain` (Google domain) are the numeric/short
codes from the reference files linked on https://xmlriver.com/apidoc/api-about/
(`countries.xlsx`, `langs.xlsx`, `domains.xlsx`). `loc` is an optional
location id from `geo.csv` for city-level results.

Only the top 10 organic results are returned per query (XMLRiver stopped
grouping results in September 2025, so `groupby` is not sent).
"""
    signup_url: ClassVar[str] = "https://xmlriver.com/queries/"
    Settings: ClassVar[type[BaseModel]] = XMLRiverSettings

    # Tests point this at an httpx.MockTransport; production leaves it None.
    transport: ClassVar[httpx.BaseTransport | None] = None
    retries: ClassVar[int] = 3

    def _client(self) -> httpx.Client:
        kwargs: dict = {"timeout": self.settings.timeout}
        if self.transport is not None:
            kwargs["transport"] = self.transport
        return httpx.Client(**kwargs)

    def search(self, query: str) -> SerpPage:
        params = {
            "user": self.settings.user_id,
            "key": self.settings.api_key.get_secret_value(),
            "query": query,
            "country": self.settings.country,
            "lr": self.settings.lr,
            "domain": self.settings.domain,
            "device": self.settings.device,
        }
        if self.settings.loc:
            params["loc"] = self.settings.loc
        with self._client() as client:
            response = _send_with_retry(
                lambda: client.get("https://xmlriver.com/search/xml", params=params),
                retries=self.retries,
                name=self.name,
            )
        _raise_for_status(response, self.name)
        return _parse_xmlriver(response.text, query)

    def test(self) -> str:
        page = self.search("seo")
        return f"OK: {len(page.items)} results"


def _text(elem: Element | None) -> str:
    return (elem.text or "").strip() if elem is not None else ""


def _parse_xmlriver(xml_text: str, query: str) -> SerpPage:
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, DefusedXmlException) as exc:
        raise PluginError(f"XMLRiver returned unparseable XML: {exc}") from exc

    error = root.find(".//error")
    if error is not None:
        raise PluginError(f"XMLRiver error {error.get('code', '?')}: {_text(error)}")

    page = SerpPage(query=query)
    for position, group in enumerate(root.findall(".//group"), start=1):
        doc = group.find(".//doc")
        if doc is None:
            continue
        url = _text(doc.find("url"))
        if not url:
            continue
        passages = [_text(p) for p in doc.findall(".//passage")]
        page.items.append(
            SerpItem(
                position=position,
                url=url,
                title=_text(doc.find("title")),
                snippet=" ".join(p for p in passages if p),
            )
        )

    related = root.find(".//relatedSearches")
    if related is not None:
        for query_elem in related.findall("query"):
            title = _text(query_elem.find("title"))
            if title:
                page.related.append(title)

    return page


class SerperSettings(BaseModel):
    api_key: SecretStr = SecretStr("")
    gl: str = "us"
    hl: str = "en"
    num: int = 10
    timeout: float = 30


class Serper(SerpConnector):
    id: ClassVar[str] = "serper"
    name: ClassVar[str] = "Serper.dev (Google)"
    summary: ClassVar[str] = "Google SERP via Serper.dev: fast JSON API with organic, PAA and related searches."
    docs: ClassVar[str] = """
Sign up at https://serper.dev and copy the API key from the dashboard. New
accounts get free trial credits; usage beyond that is billed per search.

`gl` is the target country (e.g. `us`, `de`), `hl` the interface language
(e.g. `en`), `num` how many organic results to request.
"""
    signup_url: ClassVar[str] = "https://serper.dev"
    Settings: ClassVar[type[BaseModel]] = SerperSettings

    transport: ClassVar[httpx.BaseTransport | None] = None
    retries: ClassVar[int] = 3

    def _client(self) -> httpx.Client:
        kwargs: dict = {"timeout": self.settings.timeout}
        if self.transport is not None:
            kwargs["transport"] = self.transport
        return httpx.Client(**kwargs)

    def search(self, query: str) -> SerpPage:
        headers = {
            "X-API-KEY": self.settings.api_key.get_secret_value(),
            "Content-Type": "application/json",
        }
        settings = self.settings
        body = {"q": query, "gl": settings.gl, "hl": settings.hl, "num": settings.num}
        with self._client() as client:
            response = _send_with_retry(
                lambda: client.post("https://google.serper.dev/search", headers=headers, json=body),
                retries=self.retries,
                name=self.name,
            )
        _raise_for_status(response, self.name)
        try:
            payload = response.json()
        except ValueError as exc:
            raise PluginError(f"Serper.dev returned invalid JSON: {exc}") from exc
        return _parse_serper(payload, query)

    def test(self) -> str:
        page = self.search("seo")
        return f"OK: {len(page.items)} results"


def _parse_serper(payload: dict, query: str) -> SerpPage:
    page = SerpPage(query=query)
    for index, item in enumerate(payload.get("organic") or [], start=1):
        link = str(item.get("link") or "")
        if not link:
            continue
        page.items.append(
            SerpItem(
                position=int(item.get("position") or index),
                url=link,
                title=str(item.get("title") or ""),
                snippet=str(item.get("snippet") or ""),
            )
        )
    for item in payload.get("peopleAlsoAsk") or []:
        question = str(item.get("question") or "").strip()
        if question:
            page.questions.append(question)
    for item in payload.get("relatedSearches") or []:
        related = str(item.get("query") or "").strip()
        if related:
            page.related.append(related)
    return page
