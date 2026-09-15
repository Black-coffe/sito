"""Connections: API keys and endpoints for external services."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from markupsafe import escape
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from sito.core.connections import build_connector
from sito.core.forms import (
    default_values,
    describe_model,
    dump_model,
    format_errors,
    mask_secret,
    parse_form,
    secret_fields,
)
from sito.models import Connection
from sito.plugins.base import Connector, PluginError
from sito.web.deps import app_state, get_or_404, get_session, is_htmx, redirect, render

router = APIRouter(prefix="/connections")

KINDS: dict[str, tuple[str, str]] = {
    "llm": ("Language models", "Used by AI classification and AI cluster naming."),
    "serp": ("Search results (SERP)", "Used by Collect SERP; SERP data powers clustering and the competitor view."),
    "suggest": ("Search suggestions", "Used by Autocomplete expansion to grow the keyword list."),
}


def _is_address(field_name: str) -> bool:
    return "url" in field_name or field_name in ("host", "endpoint")


def kind_info(kind: str) -> tuple[str, str]:
    return KINDS.get(kind, (kind.replace("_", " ").capitalize(), ""))


def _secret_summary(cls: type[Connector], row: Connection) -> str:
    fields = describe_model(cls.Settings, row.settings or {})
    return ", ".join(f.secret_hint for f in fields if f.widget == "password" and f.secret_hint)


def _test(registry, row: Connection) -> tuple[bool, str]:
    try:
        return True, build_connector(registry, row).test()
    except PluginError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 - show any failure to the user
        return False, f"{type(exc).__name__}: {exc}"


@router.get("")
def connections_page(request: Request, session: Session = Depends(get_session)):
    registry = app_state(request).registry
    groups: dict[str, list[dict]] = {}
    for row in session.scalars(select(Connection).order_by(Connection.name)):
        cls = registry.connectors.get(row.connector_id)
        kind = cls.kind if cls else "missing"
        groups.setdefault(kind, []).append({"row": row, "cls": cls, "secret": _secret_summary(cls, row) if cls else ""})
    ordered = [(kind, kind_info(kind), groups[kind]) for kind in sorted(groups, key=lambda k: (k not in KINDS, k))]
    return render(
        request,
        "connections.html",
        nav="connections",
        groups=ordered,
        db_path=app_state(request).config.database_url,
    )


@router.get("/new")
def new_connection(request: Request, kind: str | None = None):
    registry = app_state(request).registry
    grouped: dict[str, list[type[Connector]]] = {}
    for cls in sorted(registry.connectors.values(), key=lambda c: c.name):
        grouped.setdefault(cls.kind, []).append(cls)
    kinds = sorted(grouped, key=lambda k: (k != kind, k not in KINDS, k))
    return render(
        request,
        "connection_new.html",
        nav="connections",
        catalog=[(k, kind_info(k), grouped[k]) for k in kinds],
        focus=kind,
    )


def _form_page(
    request: Request,
    cls: type[Connector],
    row: Connection | None,
    values: dict,
    errors=None,
    name: str | None = None,
    status_code: int = 200,
):
    return render(
        request,
        "connection_form.html",
        status_code=status_code,
        nav="connections",
        cls=cls,
        row=row,
        name=name if name is not None else (row.name if row else cls.name),
        fields=describe_model(cls.Settings, values),
        errors=errors or {},
        kind_label=kind_info(cls.kind)[0],
    )


@router.get("/new/{connector_id}")
def new_connection_form(request: Request, connector_id: str):
    cls = app_state(request).registry.connector(connector_id)
    return _form_page(request, cls, None, default_values(cls.Settings))


@router.post("/new/{connector_id}")
async def create_connection(request: Request, connector_id: str, session: Session = Depends(get_session)):
    registry = app_state(request).registry
    cls = registry.connector(connector_id)
    form = await request.form()
    name = str(form.get("__name") or cls.name).strip()[:200] or cls.name
    try:
        settings = parse_form(cls.Settings, form)
    except ValidationError as exc:
        return _form_page(request, cls, None, dict(form), format_errors(exc), name, status_code=422)
    row = Connection(connector_id=cls.id, name=name, settings=dump_model(settings))
    session.add(row)
    session.commit()
    if form.get("__then") == "test":
        ok, message = _test(registry, row)
        return redirect(
            f"/connections/{row.id}",
            **(
                {"notice": f"Saved. Test passed: {message}"}
                if ok
                else {"error": f"Saved, but the test failed: {message}"}
            ),
        )
    return redirect("/connections", notice=f"Connection «{row.name}» saved.")


@router.get("/{cid}")
def edit_connection(request: Request, cid: int, session: Session = Depends(get_session)):
    row = get_or_404(session, Connection, cid)
    cls = app_state(request).registry.connectors.get(row.connector_id)
    if cls is None:
        raise HTTPException(status_code=404, detail=f"The connector plugin '{row.connector_id}' is not installed.")
    return _form_page(request, cls, row, row.settings or {})


@router.post("/{cid}")
async def save_connection(request: Request, cid: int, session: Session = Depends(get_session)):
    registry = app_state(request).registry
    row = get_or_404(session, Connection, cid)
    cls = registry.connector(row.connector_id)
    form = await request.form()
    name = str(form.get("__name") or row.name).strip()[:200] or row.name
    try:
        settings = parse_form(cls.Settings, form, existing=row.settings or {})
    except ValidationError as exc:
        return _form_page(request, cls, row, {**(row.settings or {}), **dict(form)}, format_errors(exc), name, 422)
    new_values = dump_model(settings)
    secrets = secret_fields(cls.Settings)
    old = row.settings or {}
    address_changed = any(
        old.get(k) != new_values.get(k) for k in cls.Settings.model_fields if k not in secrets and _is_address(k)
    )
    kept_secrets = [k for k in secrets if old.get(k) and not str(form.get(k) or "").strip()]
    if address_changed and kept_secrets:
        # A saved key is never sent to a new address without the user typing it again.
        errors = {k: "The address changed: type the key again to use it with the new address." for k in kept_secrets}
        return _form_page(request, cls, row, {**old, **dict(form)}, errors, name, 422)
    row.name = name
    row.settings = dump_model(settings)
    session.commit()
    if form.get("__then") == "test":
        ok, message = _test(registry, row)
        return redirect(
            f"/connections/{cid}",
            **(
                {"notice": f"Saved. Test passed: {message}"}
                if ok
                else {"error": f"Saved, but the test failed: {message}"}
            ),
        )
    return redirect("/connections", notice=f"Connection «{row.name}» saved.")


@router.post("/{cid}/test")
def test_connection(request: Request, cid: int, session: Session = Depends(get_session)):
    row = get_or_404(session, Connection, cid)
    ok, message = _test(app_state(request).registry, row)
    if is_htmx(request):
        icon_id, css = ("circle-check", "notice") if ok else ("circle-alert", "error")
        return HTMLResponse(
            f'<div class="flash {css}" role="status">'
            f'<svg class="icon" aria-hidden="true"><use href="#i-{icon_id}"></use></svg>'
            f"<div>{escape(message)}</div></div>"
        )
    return redirect(
        "/connections", **({"notice": f"«{row.name}»: {message}"} if ok else {"error": f"«{row.name}»: {message}"})
    )


@router.post("/{cid}/delete")
def delete_connection(cid: int, session: Session = Depends(get_session)):
    row = get_or_404(session, Connection, cid)
    name = row.name
    session.delete(row)
    session.commit()
    return redirect("/connections", notice=f"Connection «{name}» deleted. Steps that used it will ask for another one.")


__all__ = ["router", "kind_info", "mask_secret"]
