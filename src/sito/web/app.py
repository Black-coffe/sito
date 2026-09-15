"""Application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from sito.config import AppConfig
from sito.core.connections import ensure_default_connections
from sito.core.runner import Runner
from sito.db import init_db, make_engine, make_session_factory
from sito.plugins.base import PluginError
from sito.plugins.registry import PluginRegistry, load_registry
from sito.web.deps import back_to
from sito.web.security import LocalOnlyMiddleware


@dataclass
class AppState:
    config: AppConfig
    engine: Engine
    session_factory: sessionmaker[Session]
    registry: PluginRegistry
    runner: Runner


def create_app(
    config: AppConfig | None = None, registry: PluginRegistry | None = None, recover: bool = True
) -> FastAPI:
    """Build the app. ``recover=False`` skips marking left-over runs as failed — for
    one-off commands that may share a data folder with a running server."""
    config = config or AppConfig.from_env()
    config.ensure_dirs()
    engine = make_engine(config.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    registry = registry or load_registry(config.plugins_dir)
    with session_factory() as session:
        ensure_default_connections(session, registry)
    runner = Runner(session_factory, registry, config)
    if recover:
        runner.recover()
    state = AppState(config, engine, session_factory, registry, runner)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        runner.shutdown()
        engine.dispose()

    app = FastAPI(title="sito", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
    app.state.sito = state
    app.add_middleware(LocalOnlyMiddleware, allowed_hosts=config.allowed_hosts)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

    from sito.web.routes import (
        connections,
        docs,
        history,
        keywords,
        pipeline,
        plugins,
        projects,
        transfer,
    )

    for module in (projects, pipeline, keywords, transfer, history, connections, plugins, docs):
        app.include_router(module.router)

    @app.exception_handler(PluginError)
    async def _plugin_error(request: Request, exc: PluginError):
        return back_to(request, error=str(exc))

    return app
