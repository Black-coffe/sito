"""Smoke tests for the Queen-owned pages: projects, pipeline, runs, connections, plugins, docs."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, SecretStr

from sito.models import Connection, Keyword, Project, Step
from sito.plugins.base import Connector, Stage, StageKind, connection_field
from sito.plugins.registry import PluginRegistry
from sito.web.app import create_app


class AddThree(Stage):
    id = "t_three"
    name = "Add three"
    kind = StageKind.SOURCE
    summary = "Adds three keywords."

    def run(self, ctx, config):
        ctx.stat(added=ctx.add_keywords(["a b", "c d", "e f"], source="test"))


class FakeLLM(Connector):
    id = "t_llm"
    name = "Fake LLM"
    kind = "llm"
    summary = "For tests."
    docs = "Get a key at **example.com**."

    class Settings(BaseModel):
        api_key: SecretStr = SecretStr("")
        model: str = "m1"

    def test(self):
        return f"model {self.settings.model} ok"


class NeedsLLM(Stage):
    id = "t_needs"
    name = "Needs LLM"
    kind = StageKind.ENRICH

    class Config(BaseModel):
        llm: int | None = connection_field("llm")
        batch: int = 10

    def run(self, ctx, config):
        ctx.connection(config.llm, "llm")


@pytest.fixture
def client(config):
    registry = PluginRegistry()
    for cls in (AddThree, NeedsLLM):
        registry.add_stage(cls, "test")
    registry.add_connector(FakeLLM, "test")
    app = create_app(config, registry=registry)
    with TestClient(app) as c:
        c.app_state = app.state.sito
        yield c


def _project(client) -> int:
    r = client.post("/projects", data={"name": "Servers", "template": "empty"}, follow_redirects=False)
    assert r.status_code == 303
    return int(re.search(r"/projects/(\d+)/", r.headers["location"]).group(1))


def test_pages_render(client):
    for url in ("/", "/connections", "/connections/new", "/plugins", "/docs/getting-started", "/docs/reference"):
        r = client.get(url)
        assert r.status_code == 200, url
    assert "Fake LLM" in client.get("/docs/reference").text


def test_project_pipeline_flow(client):
    pid = _project(client)
    r = client.get(f"/projects/{pid}/keywords")
    assert r.status_code == 200 and "No sieves yet" in r.text
    assert "Add three" in client.get(f"/projects/{pid}/keywords?add_at=0").text

    r = client.post(
        f"/projects/{pid}/steps",
        data={"stage_id": "t_three", "position": 0, "next": f"/projects/{pid}/keywords"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and "edit=" in r.headers["location"]
    with client.app_state.session_factory() as s:
        step = s.query(Step).one()

    # Settings form renders and saves the title.
    assert "Step name" in client.get(f"/projects/{pid}/keywords?edit={step.id}").text
    client.post(
        f"/projects/{pid}/steps/{step.id}/settings", data={"__title": "Seed list", "next": f"/projects/{pid}/keywords"}
    )

    # Run synchronously through the runner, then check the pipeline shows pass counts.
    client.app_state.runner.enqueue(pid, [step.id], background=False)
    page = client.get(f"/projects/{pid}/keywords").text
    assert "Seed list" in page and "pass <strong>3</strong>" in page
    assert client.get(f"/projects/{pid}/runs").status_code == 200
    with client.app_state.session_factory() as s:
        assert s.query(Keyword).count() == 3
        run_id = s.query(Step).one().id
    assert client.get(f"/projects/{pid}/runs/1").status_code == 200

    # Undo restores the list as it was before the step ran (empty).
    r = client.post(
        f"/projects/{pid}/steps/{run_id}/undo", data={"next": f"/projects/{pid}/keywords"}, follow_redirects=False
    )
    assert "notice=" in r.headers["location"]
    with client.app_state.session_factory() as s:
        assert s.query(Keyword).count() == 0

    # Polling endpoint asks for a refresh once nothing runs any more.
    r = client.get(f"/projects/{pid}/pipeline?path=/projects/{pid}/keywords&was_active=1")
    assert r.headers.get("HX-Refresh") == "true"


def test_step_needing_connection_is_blocked_then_runs(client):
    pid = _project(client)
    client.post(f"/projects/{pid}/steps", data={"stage_id": "t_needs"})
    with client.app_state.session_factory() as s:
        step = s.query(Step).one()
    page = client.get(f"/projects/{pid}/keywords").text
    assert "Needs setup" in page
    r = client.post(f"/projects/{pid}/steps/{step.id}/run", follow_redirects=False)
    assert "error=" in r.headers["location"]

    # Create a connection through the UI, then pick it in the step.
    r = client.post(
        "/connections/new/t_llm",
        data={"__name": "Mine", "api_key": "sk-123456789012", "model": "m2"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with client.app_state.session_factory() as s:
        conn = s.query(Connection).one()
        assert conn.settings["api_key"] == "sk-123456789012"
    edit_page = client.get(f"/connections/{conn.id}").text
    assert "sk-123456789012" not in edit_page and "9012" in edit_page  # masked hint only

    # Saving with an empty key keeps the stored one.
    client.post(f"/connections/{conn.id}", data={"__name": "Mine", "api_key": "", "model": "m3"})
    with client.app_state.session_factory() as s:
        assert s.get(Connection, conn.id).settings == {"api_key": "sk-123456789012", "model": "m3"}

    r = client.post(f"/connections/{conn.id}/test", headers={"HX-Request": "true"})
    assert "model m3 ok" in r.text

    client.post(f"/projects/{pid}/steps/{step.id}/settings", data={"llm": str(conn.id), "batch": "5"})
    with client.app_state.session_factory() as s:
        assert s.get(Step, step.id).config == {"llm": conn.id, "batch": 5}
    assert "Needs setup" not in client.get(f"/projects/{pid}/keywords").text


def test_invalid_settings_are_reported(client):
    pid = _project(client)
    client.post(f"/projects/{pid}/steps", data={"stage_id": "t_needs"})
    with client.app_state.session_factory() as s:
        step = s.query(Step).one()
    r = client.post(f"/projects/{pid}/steps/{step.id}/settings", data={"batch": "lots"}, follow_redirects=False)
    assert "error=" in r.headers["location"] and f"edit={step.id}" in r.headers["location"]


def test_project_settings_and_delete(client):
    pid = _project(client)
    client.post(f"/projects/{pid}/settings", data={"name": "Renamed", "description": "d", "context": "We sell VPS"})
    with client.app_state.session_factory() as s:
        assert s.get(Project, pid).context == "We sell VPS"
    r = client.post(f"/projects/{pid}/delete", data={"confirm_name": "wrong"}, follow_redirects=False)
    assert "error=" in r.headers["location"]
    client.post(f"/projects/{pid}/delete", data={"confirm_name": "Renamed"})
    with client.app_state.session_factory() as s:
        assert s.get(Project, pid) is None
