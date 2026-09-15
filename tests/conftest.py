from __future__ import annotations

import pytest

from sito.config import AppConfig
from sito.db import init_db, make_engine, make_session_factory
from sito.models import Project


@pytest.fixture
def config(tmp_path):
    # "testserver" is the Host header FastAPI's TestClient sends.
    cfg = AppConfig.from_env(data_dir=tmp_path / "data", allowed_hosts="testserver")
    cfg.ensure_dirs()
    return cfg


@pytest.fixture
def session_factory(config):
    engine = make_engine(config.database_url)
    init_db(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def project(session_factory):
    with session_factory() as s:
        p = Project(name="Test project", context="We sell dedicated servers.")
        s.add(p)
        s.commit()
        return p
