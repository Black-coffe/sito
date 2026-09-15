"""Built-in documentation: the same Markdown files that ship in ``sito/docs``."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from sito.web.deps import app_state, redirect, render
from sito.web.routes.connections import kind_info
from sito.web.workspace import stage_catalog

router = APIRouter()

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
PAGES = (
    ("getting-started", "Getting started"),
    ("pipelines", "Pipelines, runs and snapshots"),
    ("import-export", "Import and export"),
    ("connections", "Connections and API keys"),
    ("reference", "Stages and connectors"),
    ("writing-plugins", "Writing plugins"),
    ("configuration", "Configuration and deployment"),
)


@router.get("/docs")
def docs_home():
    return redirect(f"/docs/{PAGES[0][0]}")


@router.get("/docs/{slug}")
def docs_page(request: Request, slug: str):
    titles = dict(PAGES)
    if slug not in titles:
        raise HTTPException(status_code=404, detail="No such page")
    context = {"nav": "docs", "pages": PAGES, "slug": slug, "title": titles[slug]}
    if slug == "reference":
        registry = app_state(request).registry
        connectors: dict[str, list] = {}
        for cls in sorted(registry.connectors.values(), key=lambda c: c.name):
            connectors.setdefault(cls.kind, []).append(cls)
        context.update(
            stages=stage_catalog(registry),
            connectors=[(k, kind_info(k), v) for k, v in sorted(connectors.items())],
        )
        return render(request, "docs_reference.html", **context)
    path = DOCS_DIR / f"{slug}.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else f"# {titles[slug]}\n\nThis page is not written yet."
    return render(request, "docs.html", body=text, **context)
