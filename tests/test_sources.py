from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from sito.connectors import suggest as suggest_module
from sito.connectors.suggest import GoogleSuggest
from sito.core.pipeline import add_step
from sito.core.runner import Runner
from sito.models import Connection, Keyword, Run
from sito.plugins.base import PluginError
from sito.plugins.registry import PluginRegistry
from sito.stages import sources


@pytest.fixture
def registry():
    reg = PluginRegistry()
    reg.register_module(suggest_module, "test")
    reg.register_module(sources, "test")
    return reg


@pytest.fixture
def runner(session_factory, registry, config):
    return Runner(session_factory, registry, config)


def _step(session_factory, registry, project, stage_id, **overrides):
    with session_factory() as s:
        step = add_step(s, registry, project, stage_id)
        if overrides:
            step.config = {**step.config, **overrides}
        s.commit()
        return step.id


def _suggest_transport(calls: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["q"]
        calls.append(query)
        return httpx.Response(200, json=[query, [f"{query} tool", f"{query} price"]])

    return httpx.MockTransport(handler)


# --- GoogleSuggest connector --------------------------------------------------------------


def test_google_suggest_parses_suggestions(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(GoogleSuggest, "transport", _suggest_transport(calls))
    connector = GoogleSuggest(GoogleSuggest.Settings(pause_seconds=0))
    assert connector.suggest("seo") == ["seo tool", "seo price"]
    assert calls == ["seo"]


def test_google_suggest_test_method(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(GoogleSuggest, "transport", _suggest_transport(calls))
    connector = GoogleSuggest(GoogleSuggest.Settings(pause_seconds=0))
    assert connector.test() == "OK: 2 suggestions for 'seo'"


def test_google_suggest_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(GoogleSuggest, "transport", httpx.MockTransport(lambda request: httpx.Response(403)))
    connector = GoogleSuggest(GoogleSuggest.Settings(pause_seconds=0))
    with pytest.raises(PluginError):
        connector.suggest("seo")


def test_google_suggest_raises_on_bad_json(monkeypatch):
    monkeypatch.setattr(
        GoogleSuggest,
        "transport",
        httpx.MockTransport(lambda request: httpx.Response(200, text="nope")),
    )
    connector = GoogleSuggest(GoogleSuggest.Settings(pause_seconds=0))
    with pytest.raises(PluginError):
        connector.suggest("seo")


# --- ManualList ----------------------------------------------------------------------------


def test_manual_list_adds_and_dedupes(session_factory, registry, runner, project):
    step_id = _step(
        session_factory,
        registry,
        project,
        "manual_list",
        keywords="Buy Server\nbuy  server\nRent VPS",
    )
    [run_id] = runner.enqueue(project.id, [step_id], background=False)
    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.status == "done"
        assert run.stats["added"] == 2
        assert run.stats["skipped_duplicates"] == 1
        words = sorted(s.scalars(select(Keyword.keyword)).all())
        assert words == ["buy server", "rent vps"]


def test_manual_list_uses_source_label(session_factory, registry, runner, project):
    step_id = _step(session_factory, registry, project, "manual_list", keywords="vpn", source_label="import")
    runner.enqueue(project.id, [step_id], background=False)
    with session_factory() as s:
        kw = s.scalars(select(Keyword)).one()
        assert kw.source == "import"


# --- Autocomplete ----------------------------------------------------------------------------


def _add_suggest_connection(session_factory) -> None:
    with session_factory() as s:
        s.add(Connection(connector_id="google_suggest", name="G", settings={"pause_seconds": 0}))
        s.commit()


def test_autocomplete_uses_project_keywords_as_seeds(session_factory, registry, runner, project, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(GoogleSuggest, "transport", _suggest_transport(calls))
    _add_suggest_connection(session_factory)
    with session_factory() as s:
        s.add(Keyword(project_id=project.id, keyword="vpn", source="manual"))
        s.commit()

    step_id = _step(session_factory, registry, project, "autocomplete")
    runner.enqueue(project.id, [step_id], background=False)

    assert calls == ["vpn"]


def test_autocomplete_adds_suggestions_for_extra_seeds(session_factory, registry, runner, project, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(GoogleSuggest, "transport", _suggest_transport(calls))
    _add_suggest_connection(session_factory)

    step_id = _step(
        session_factory,
        registry,
        project,
        "autocomplete",
        use_project_keywords=False,
        extra_seeds="vpn",
    )
    [run_id] = runner.enqueue(project.id, [step_id], background=False)

    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.status == "done"
        assert run.stats["added"] == 2
        assert run.stats["requests"] == 1
        words = sorted(s.scalars(select(Keyword.keyword)).all())
        assert words == ["vpn price", "vpn tool"]
        kw = s.scalars(select(Keyword).where(Keyword.keyword == "vpn tool")).one()
        assert kw.source == "autocomplete"
        assert kw.data["seed"] == "vpn"
    assert calls == ["vpn"]


def test_autocomplete_depth_two_expands_new_suggestions(session_factory, registry, runner, project, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(GoogleSuggest, "transport", _suggest_transport(calls))
    _add_suggest_connection(session_factory)

    step_id = _step(
        session_factory,
        registry,
        project,
        "autocomplete",
        use_project_keywords=False,
        extra_seeds="vpn",
        depth=2,
    )
    runner.enqueue(project.id, [step_id], background=False)

    with session_factory() as s:
        words = set(s.scalars(select(Keyword.keyword)).all())
    assert {"vpn tool", "vpn price", "vpn tool tool", "vpn price price"} <= words
    assert sorted(calls) == ["vpn", "vpn price", "vpn tool"]


def test_autocomplete_expands_alphabet_and_question_prefixes(session_factory, registry, runner, project, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(GoogleSuggest, "transport", _suggest_transport(calls))
    _add_suggest_connection(session_factory)

    step_id = _step(
        session_factory,
        registry,
        project,
        "autocomplete",
        use_project_keywords=False,
        extra_seeds="vpn",
        alphabet_suffixes=True,
        question_prefixes=["how"],
    )
    [run_id] = runner.enqueue(project.id, [step_id], background=False)

    with session_factory() as s:
        run = s.get(Run, run_id)
        # base query + 26 letters + 10 digits + 1 question prefix
        assert run.stats["requests"] == 1 + 36 + 1
    assert "vpn" in calls
    assert "vpn a" in calls
    assert "vpn 0" in calls
    assert "how vpn" in calls


def test_autocomplete_stops_once_max_new_keywords_reached(session_factory, registry, runner, project, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(GoogleSuggest, "transport", _suggest_transport(calls))
    _add_suggest_connection(session_factory)

    step_id = _step(
        session_factory,
        registry,
        project,
        "autocomplete",
        use_project_keywords=False,
        extra_seeds="vpn\nfirewall",
        max_new_keywords=1,
    )
    [run_id] = runner.enqueue(project.id, [step_id], background=False)

    with session_factory() as s:
        run = s.get(Run, run_id)
        # the first request alone already yields 2 new keywords, past the cap of 1
        assert run.stats["added"] == 2
        assert run.stats["requests"] == 1
    assert calls == ["vpn"]
