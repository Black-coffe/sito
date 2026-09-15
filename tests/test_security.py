"""Browser-attack protections and key handling (see sito/web/security.py)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, SecretStr
from sqlalchemy import select

from sito.config import AppConfig
from sito.core.connections import build_connector
from sito.core.snapshots import create_snapshot, restore_snapshot
from sito.models import Connection, Keyword, Project, SerpResult
from sito.plugins.base import Connector
from sito.plugins.registry import PluginRegistry
from sito.web.app import create_app
from sito.web.security import host_name


class KeyedConnector(Connector):
    id = "t_keyed"
    name = "Keyed"
    kind = "llm"

    class Settings(BaseModel):
        api_key: SecretStr = SecretStr("")
        base_url: str = "https://api.example.com/v1"


@pytest.fixture
def client(config):
    registry = PluginRegistry()
    registry.add_connector(KeyedConnector, "test")
    app = create_app(config, registry=registry)
    with TestClient(app) as c:
        c.app_state = app.state.sito
        yield c


def _projects(client) -> int:
    with client.app_state.session_factory() as s:
        return len(s.scalars(select(Project)).all())


def test_cross_site_post_is_blocked(client):
    r = client.post("/projects", data={"name": "x"}, headers={"Origin": "https://attacker.example"})
    assert r.status_code == 403
    r = client.post("/projects", data={"name": "x"}, headers={"Origin": "null"})
    assert r.status_code == 403
    r = client.post("/projects", data={"name": "x"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert _projects(client) == 0


def test_same_origin_and_non_browser_posts_are_allowed(client):
    for headers in ({"Origin": "http://testserver"}, {"Sec-Fetch-Site": "same-origin"}, {}):
        r = client.post("/projects", data={"name": "ok", "template": "empty"}, headers=headers, follow_redirects=False)
        assert r.status_code == 303, headers
    assert _projects(client) == 3


def test_unknown_host_is_rejected(client):
    assert client.get("/", headers={"Host": "attacker.example"}).status_code == 400
    assert client.get("/", headers={"Host": "127.0.0.1:8765"}).status_code == 200
    assert client.get("/", headers={"Host": "[::1]:8765"}).status_code == 200


def test_host_name_parsing():
    assert host_name("Example.com:8765") == "example.com"
    assert host_name("[::1]:8765") == "::1"
    assert host_name("localhost") == "localhost"


def test_allowed_hosts_config(monkeypatch, tmp_path):
    monkeypatch.setenv("SITO_ALLOWED_HOSTS", "sito.lan, box")
    cfg = AppConfig.from_env(data_dir=tmp_path, host="0.0.0.0")
    assert {"localhost", "127.0.0.1", "::1", "sito.lan", "box"} <= set(cfg.allowed_hosts)
    assert "0.0.0.0" not in cfg.allowed_hosts


def test_env_references_only_resolve_in_secret_fields(monkeypatch):
    monkeypatch.setenv("SECRET_VAR", "top-secret")
    registry = PluginRegistry()
    registry.add_connector(KeyedConnector, "test")
    row = Connection(
        connector_id="t_keyed", name="k", settings={"api_key": "env:SECRET_VAR", "base_url": "env:SECRET_VAR"}
    )
    connector = build_connector(registry, row)
    assert connector.settings.api_key.get_secret_value() == "top-secret"
    assert connector.settings.base_url == "env:SECRET_VAR"


def test_changing_the_address_requires_the_key_again(client):
    client.post(
        "/connections/new/t_keyed", data={"__name": "k", "api_key": "sk-real-123456789", "base_url": "https://a"}
    )
    with client.app_state.session_factory() as s:
        conn = s.scalars(select(Connection)).one()
    r = client.post(
        f"/connections/{conn.id}", data={"__name": "k", "api_key": "", "base_url": "https://attacker.example"}
    )
    assert r.status_code == 422 and "type the key again" in r.text
    with client.app_state.session_factory() as s:
        assert s.get(Connection, conn.id).settings["base_url"] == "https://a"
    # Re-entering the key makes the change explicit and allowed.
    client.post(f"/connections/{conn.id}", data={"__name": "k", "api_key": "sk-new-123456789", "base_url": "https://b"})
    with client.app_state.session_factory() as s:
        assert s.get(Connection, conn.id).settings == {"api_key": "sk-new-123456789", "base_url": "https://b"}


def test_restore_never_attaches_serp_rows_to_another_keyword(session_factory, project):
    with session_factory() as s:
        alpha = Keyword(project_id=project.id, keyword="alpha", data={})
        beta = Keyword(project_id=project.id, keyword="beta", data={"serp_at": "2026-01-01"})
        s.add_all([alpha, beta])
        s.flush()
        s.add(SerpResult(project_id=project.id, keyword_id=beta.id, position=1, url="https://b.example/", domain="b"))
        snap = create_snapshot(s, project.id, "both")
        beta_id = beta.id
        s.delete(beta)
        s.flush()
        gamma = Keyword(project_id=project.id, keyword="gamma", data={"serp_at": "2026-01-02"})
        s.add(gamma)
        s.flush()
        assert gamma.id != beta_id  # ids are never reused
        s.add(SerpResult(project_id=project.id, keyword_id=gamma.id, position=1, url="https://g.example/", domain="g"))
        s.commit()

        restore_snapshot(s, snap)
        s.commit()
        restored = s.scalars(select(Keyword).where(Keyword.keyword == "beta")).one()
        assert restored.id == beta_id
        assert s.scalars(select(SerpResult).where(SerpResult.keyword_id == restored.id)).all() == []
        assert "serp_at" not in restored.data  # so Collect SERP fetches it again
        assert s.scalars(select(Keyword).where(Keyword.keyword == "gamma")).first() is None
