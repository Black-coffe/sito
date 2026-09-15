from __future__ import annotations

from typing import ClassVar

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import select

from sito.connectors.serp import Serper, XMLRiver, _parse_serper, _parse_xmlriver
from sito.core.pipeline import add_step
from sito.core.runner import Runner
from sito.models import RUN_DONE, Connection, Keyword, Run, SerpResult
from sito.plugins.base import PluginError, SerpConnector, SerpItem, SerpPage
from sito.plugins.registry import PluginRegistry
from sito.stages.serp import SerpCollect

XMLRIVER_OK = """<?xml version="1.0" encoding="UTF-8"?>
<yandexsearch>
  <response>
    <results>
      <grouping>
        <group>
          <doc>
            <url>https://example.com/a</url>
            <title>Example A</title>
            <passages>
              <passage>First bit.</passage>
              <passage>Second bit.</passage>
            </passages>
          </doc>
        </group>
        <group>
          <doc>
            <url>https://example.com/b</url>
            <title>Example B</title>
          </doc>
        </group>
      </grouping>
    </results>
    <relatedSearches>
      <query><title>buy cheap vps</title></query>
      <query><title>best vps hosting</title></query>
    </relatedSearches>
  </response>
</yandexsearch>"""

XMLRIVER_ERROR = """<?xml version="1.0" encoding="UTF-8"?>
<yandexsearch><response><error code="15">Insufficient funds</error></response></yandexsearch>"""

SERPER_OK = {
    "organic": [
        {"title": "A", "link": "https://example.com/a", "snippet": "snip a", "position": 1},
        {"title": "B", "link": "https://example.com/b", "snippet": "snip b", "position": 2},
    ],
    "peopleAlsoAsk": [{"question": "what is vps?"}],
    "relatedSearches": [{"query": "cheap vps"}],
}


# --- XML / JSON parsing -----------------------------------------------------------------


def test_parse_xmlriver_extracts_results_and_related():
    page = _parse_xmlriver(XMLRIVER_OK, "vps hosting")
    assert page.query == "vps hosting"
    assert [i.url for i in page.items] == ["https://example.com/a", "https://example.com/b"]
    assert page.items[0].title == "Example A"
    assert page.items[0].snippet == "First bit. Second bit."
    assert page.items[0].position == 1
    assert page.related == ["buy cheap vps", "best vps hosting"]


def test_parse_xmlriver_raises_on_error_element():
    with pytest.raises(PluginError, match="Insufficient funds"):
        _parse_xmlriver(XMLRIVER_ERROR, "vps hosting")


def test_parse_serper_extracts_organic_paa_and_related():
    page = _parse_serper(SERPER_OK, "vps hosting")
    assert [i.url for i in page.items] == ["https://example.com/a", "https://example.com/b"]
    assert page.items[0].snippet == "snip a"
    assert page.questions == ["what is vps?"]
    assert page.related == ["cheap vps"]


# --- HTTP: retries, auth errors, connectors ----------------------------------------------


def test_retry_then_success(monkeypatch):
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500, text="server error")
        return httpx.Response(200, text=XMLRIVER_OK)

    monkeypatch.setattr("sito.connectors.serp.time.sleep", lambda s: sleeps.append(s))
    XMLRiver.transport = httpx.MockTransport(handler)
    try:
        connector = XMLRiver(XMLRiver.Settings(user_id="u", api_key="k"))
        page = connector.search("vps hosting")
    finally:
        XMLRiver.transport = None
    assert calls["n"] == 3
    assert sleeps == [1.0, 2.0]
    assert len(page.items) == 2


def test_auth_error_raises_plugin_error_about_the_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    XMLRiver.transport = httpx.MockTransport(handler)
    try:
        connector = XMLRiver(XMLRiver.Settings(user_id="u", api_key="k"))
        with pytest.raises(PluginError, match="key"):
            connector.search("vps hosting")
    finally:
        XMLRiver.transport = None


def test_serper_search_and_test_method_via_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "sk"
        return httpx.Response(200, json=SERPER_OK)

    Serper.transport = httpx.MockTransport(handler)
    try:
        connector = Serper(Serper.Settings(api_key="sk"))
        page = connector.search("vps hosting")
        assert len(page.items) == 2
        assert connector.test() == "OK: 2 results"
    finally:
        Serper.transport = None


# --- SerpCollect stage --------------------------------------------------------------------


class FakeSerp(SerpConnector):
    id: ClassVar[str] = "fake_serp"
    name: ClassVar[str] = "Fake SERP"
    calls: ClassVar[list[str]] = []

    class Settings(BaseModel):
        pass

    def search(self, query: str) -> SerpPage:
        FakeSerp.calls.append(query)
        if query == "boom":
            raise PluginError("boom failed")
        return SerpPage(
            query=query,
            items=[
                SerpItem(position=1, url=f"https://example.com/{query}", title=query, snippet="s"),
                SerpItem(position=2, url="https://other.com/x", title="x", snippet="y"),
            ],
            related=[f"{query} related"],
            questions=[f"what is {query}?"],
        )


@pytest.fixture
def registry():
    reg = PluginRegistry()
    reg.add_stage(SerpCollect, "test")
    reg.add_connector(FakeSerp, "test")
    return reg


@pytest.fixture
def connection(session_factory):
    with session_factory() as s:
        conn = Connection(connector_id="fake_serp", name="Fake", settings={})
        s.add(conn)
        s.commit()
        return conn


@pytest.fixture
def runner(session_factory, registry, config):
    return Runner(session_factory, registry, config)


def _add_serp_step(session_factory, registry, project, connection_id, **overrides):
    with session_factory() as s:
        step = add_step(s, registry, project, "serp_collect")
        step.config = {**step.config, "serp": connection_id, **overrides}
        s.commit()
        return step.id


def test_serp_collect_stores_results_and_expands_keywords(session_factory, registry, runner, project, connection):
    FakeSerp.calls.clear()
    with session_factory() as s:
        s.add(Keyword(project_id=project.id, keyword="buy vps", source="test"))
        s.commit()
    step_id = _add_serp_step(
        session_factory,
        registry,
        project,
        connection.id,
        add_related_searches=True,
        add_questions=True,
    )
    [run_id] = runner.enqueue(project.id, [step_id], background=False)
    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.status == RUN_DONE
        assert run.stats["collected"] == 1
        assert run.stats["failed"] == 0
        assert run.stats["added_keywords"] == 2

        kw = s.scalar(select(Keyword).where(Keyword.keyword == "buy vps"))
        assert kw.data["serp_results"] == 2
        assert "serp_at" in kw.data

        results = s.scalars(select(SerpResult).where(SerpResult.keyword_id == kw.id)).all()
        assert len(results) == 2
        assert {r.domain for r in results} == {"example.com", "other.com"}

        other_query = select(Keyword).where(Keyword.keyword != "buy vps")
        added = {k.keyword for k in s.scalars(other_query)}
        assert added == {"buy vps related", "what is buy vps?"}


def test_only_missing_skips_already_collected_keywords(session_factory, registry, runner, project, connection):
    FakeSerp.calls.clear()
    with session_factory() as s:
        s.add(Keyword(project_id=project.id, keyword="buy vps", source="test"))
        s.commit()
    step_id = _add_serp_step(session_factory, registry, project, connection.id)
    runner.enqueue(project.id, [step_id], background=False)
    assert FakeSerp.calls == ["buy vps"]

    with session_factory() as s:
        s.add(Keyword(project_id=project.id, keyword="rent vps", source="test"))
        s.commit()
    FakeSerp.calls.clear()
    runner.enqueue(project.id, [step_id], background=False)
    assert FakeSerp.calls == ["rent vps"]


def test_failed_keyword_is_logged_not_fatal(session_factory, registry, runner, project, connection):
    FakeSerp.calls.clear()
    with session_factory() as s:
        s.add_all(
            [
                Keyword(project_id=project.id, keyword="buy vps", source="test"),
                Keyword(project_id=project.id, keyword="boom", source="test"),
            ]
        )
        s.commit()
    step_id = _add_serp_step(session_factory, registry, project, connection.id)
    [run_id] = runner.enqueue(project.id, [step_id], background=False)
    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.status == RUN_DONE
        assert run.stats["collected"] == 1
        assert run.stats["failed"] == 1


def test_min_relevance_needs_ai_classification_first(session_factory, registry, runner, project, connection):
    FakeSerp.calls.clear()
    with session_factory() as s:
        s.add_all(
            [
                Keyword(project_id=project.id, keyword="relevant", source="test", data={"relevance": 8}),
                # Spreadsheet imports can round-trip the score as text; it must still count.
                Keyword(project_id=project.id, keyword="relevant text", source="test", data={"relevance": "8"}),
                Keyword(project_id=project.id, keyword="irrelevant", source="test", data={"relevance": 2}),
                Keyword(project_id=project.id, keyword="unclassified", source="test"),
            ]
        )
        s.commit()
    step_id = _add_serp_step(session_factory, registry, project, connection.id, min_relevance=5)
    runner.enqueue(project.id, [step_id], background=False)
    assert set(FakeSerp.calls) == {"relevant", "relevant text"}
