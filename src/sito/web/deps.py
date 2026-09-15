"""Shared helpers for routes and templates."""

from __future__ import annotations

import inspect
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import markdown as _markdown
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlalchemy.orm import Session

from sito import __version__
from sito.core.forms import humanize

WEB_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

T = TypeVar("T")


def icon(name: str, label: str | None = None, cls: str = "") -> Markup:
    """Inline icon from the Lucide sprite. Pass ``label`` for icon-only buttons."""
    svg = (
        f'<svg class="icon {escape(cls)}" aria-hidden="true" focusable="false">'
        f'<use href="#i-{escape(name)}"></use></svg>'
    )
    if label:
        svg += f'<span class="sr-only">{escape(label)}</span>'
    return Markup(svg)


def fmt_num(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.2f}"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def fmt_ago(dt: datetime | None) -> str:
    if not dt:
        return "—"
    seconds = (datetime.now(UTC) - _aware(dt)).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    return fmt_dt(dt)


def fmt_dt(dt: datetime | None) -> str:
    return _aware(dt).astimezone().strftime("%Y-%m-%d %H:%M") if dt else "—"


def fmt_duration(start: datetime | None, end: datetime | None) -> str:
    if not start:
        return "—"
    seconds = int(((_aware(end) if end else datetime.now(UTC)) - _aware(start)).total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"


_LIST_ITEM = r"[ \t]*(?:[-*+]|\d+\.)[ \t]"
# A non-empty, non-list, non-table line directly followed by a list item.
_LIST_AFTER_TEXT = re.compile(rf"(?m)^(?!{_LIST_ITEM}|[ \t]*$|[ \t]*\|)(.+)\n(?={_LIST_ITEM})")


def render_markdown(text: str | None) -> Markup:
    """Markdown → HTML. Plugin docs are indented class attributes, so dedent them first, and
    allow a list to follow a paragraph line directly (Python-Markdown needs a blank line)."""
    source = inspect.cleandoc(text or "")
    source = _LIST_AFTER_TEXT.sub(r"\1\n\n", source)
    return Markup(_markdown.markdown(source, extensions=["tables", "fenced_code", "sane_lists", "toc"]))


templates.env.globals.update(
    icon=icon,
    version=__version__,
    icon_sprite=Markup((WEB_DIR / "templates" / "_icons.svg").read_text(encoding="utf-8")),
)
templates.env.filters.update(
    humanize=humanize, num=fmt_num, ago=fmt_ago, dt=fmt_dt, markdown=render_markdown, duration=fmt_duration
)


def app_state(request: Request) -> Any:
    """The :class:`sito.web.app.AppState` (config, session_factory, registry, runner)."""
    return request.app.state.sito


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.sito.session_factory() as session:
        yield session


def get_or_404(session: Session, model: type[T], ident: int) -> T:
    obj = session.get(model, ident)
    if obj is None:
        raise HTTPException(status_code=404, detail="Not found")
    return obj


def render(request: Request, template_name: str, /, status_code: int = 200, **context: Any):
    return templates.TemplateResponse(request, template_name, context, status_code=status_code)


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def redirect(url: str, *, notice: str | None = None, error: str | None = None, **params: Any) -> RedirectResponse:
    """303 redirect to a local ``url``; ``notice``/``error`` show as a message on the next page.

    Extra keyword params are set on the query string (``None`` removes them).
    """
    parts = urlsplit(url)
    drop = {"notice", "error", *params}
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in drop]
    for key, value in (("notice", notice), ("error", error), *params.items()):
        if value is not None:
            query.append((key, str(value)))
    target = urlunsplit(("", "", parts.path or "/", urlencode(query), parts.fragment))
    return RedirectResponse(target, status_code=303)


def safe_next(request: Request, value: str | None, fallback: str = "/") -> str:
    """Only allow local absolute paths as redirect targets."""
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    referer = request.headers.get("referer")
    if referer:
        parts = urlsplit(referer)
        if parts.netloc == request.url.netloc:
            return parts.path + (f"?{parts.query}" if parts.query else "")
    return fallback


def back_to(request: Request, *, fallback: str = "/", **kwargs: Any) -> RedirectResponse:
    return redirect(safe_next(request, None, fallback), **kwargs)
