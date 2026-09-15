"""Catalog of installed stages and connectors."""

from __future__ import annotations

from fastapi import APIRouter, Request

from sito.plugins.base import StageKind
from sito.web.deps import app_state, render
from sito.web.routes.connections import kind_info
from sito.web.workspace import stage_catalog

router = APIRouter()


@router.get("/plugins")
def plugins_page(request: Request):
    st = app_state(request)
    registry = st.registry
    connectors: dict[str, list] = {}
    for cls in sorted(registry.connectors.values(), key=lambda c: c.name):
        connectors.setdefault(cls.kind, []).append(cls)
    return render(
        request,
        "plugins.html",
        nav="plugins",
        stages=stage_catalog(registry),
        connectors=[(k, kind_info(k), v) for k, v in sorted(connectors.items())],
        origins=registry.origins,
        errors=registry.errors,
        plugins_dir=st.config.plugins_dir,
        kinds=list(StageKind),
    )
