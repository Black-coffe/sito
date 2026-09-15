"""StageContext: everything a stage can do, in one object passed to ``Stage.run``."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from sito.core.connections import build_connector
from sito.core.text import normalize_keyword, to_float, to_int
from sito.models import Connection, Keyword, Project, Run
from sito.plugins.base import Cancelled, Connector, PluginError
from sito.plugins.registry import PluginRegistry

MAX_LOG_LINES = 500


class LiveState:
    """In-memory progress of a running step.

    The UI polls it while the step runs; it is written to the ``runs`` table only
    at commit points, so progress updates never compete with the stage for the
    database write lock.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.done = 0
        self.total: int | None = None
        self.message = ""
        self.lines: list[str] = []
        self.stats: dict[str, Any] = {}

    def log(self, message: str) -> None:
        with self.lock:
            self.lines.append(f"{datetime.now():%H:%M:%S}  {message}")
            if len(self.lines) > MAX_LOG_LINES:
                del self.lines[: len(self.lines) - MAX_LOG_LINES]

    def progress(self, done: int, total: int | None = None, message: str | None = None) -> None:
        with self.lock:
            self.done = done
            if total is not None:
                self.total = total
            if message is not None:
                self.message = message

    def stat(self, values: dict[str, Any]) -> None:
        with self.lock:
            self.stats.update(values)

    def apply_to(self, run: Run) -> None:
        with self.lock:
            run.done = self.done
            run.total = self.total
            run.message = self.message[:500]
            run.log = "\n".join(self.lines)
            run.stats = {**(run.stats or {}), **self.stats}


class StageContext:
    def __init__(
        self,
        *,
        session: Session,
        project: Project,
        run: Run,
        state: LiveState,
        registry: PluginRegistry,
        cancel_check: Callable[[], bool],
        data_dir: Path,
    ) -> None:
        self.session = session
        self.project = project
        self.run = run
        self.registry = registry
        self._state = state
        self._cancel_check = cancel_check
        self._data_dir = data_dir
        self._existing: set[str] | None = None  # keyword texts, loaded once per run by add_keywords

    # --- project info -----------------------------------------------------------------
    @property
    def project_id(self) -> int:
        return self.project.id

    @property
    def project_context(self) -> str:
        """The project's business description (for AI prompts)."""
        return self.project.context or ""

    # --- reporting --------------------------------------------------------------------
    def log(self, message: str) -> None:
        self._state.log(message)

    def progress(self, done: int, total: int | None = None, message: str | None = None) -> None:
        """Report progress. Also raises :class:`Cancelled` if the user pressed Cancel."""
        self._state.progress(done, total, message)
        self.check_cancelled()

    def stat(self, **values: Any) -> None:
        """Record summary numbers shown on the run card, e.g. ``ctx.stat(excluded=42)``."""
        self._state.stat(values)

    @property
    def cancelled(self) -> bool:
        return self._cancel_check()

    def check_cancelled(self) -> None:
        if self._cancel_check():
            raise Cancelled()

    # --- keywords ---------------------------------------------------------------------
    def keywords(self, *, include_excluded: bool = False, missing: str | None = None) -> list[Keyword]:
        """The project's keywords, oldest first.

        ``missing="relevance"`` returns only keywords whose ``data`` has no such key,
        which makes long stages resumable: re-running continues where it stopped.
        """
        query = select(Keyword).where(Keyword.project_id == self.project_id)
        if not include_excluded:
            query = query.where(Keyword.excluded.is_(False))
        rows = list(self.session.scalars(query.order_by(Keyword.id)))
        if missing:
            rows = [k for k in rows if missing not in (k.data or {})]
        return rows

    def add_keywords(self, items: Iterable[str | dict[str, Any]], *, source: str) -> int:
        """Add keywords, skipping ones already in the project. Returns how many were added.

        Items are strings or dicts with ``keyword`` and optionally ``volume``, ``kd``,
        ``cpc``, ``data`` (dict) and ``source``.
        """
        if self._existing is None:
            self._existing = set(
                self.session.scalars(select(Keyword.keyword).where(Keyword.project_id == self.project_id))
            )
        existing = self._existing
        added = 0
        for item in items:
            row = item if isinstance(item, dict) else {"keyword": item}
            text = normalize_keyword(row.get("keyword"))
            if not text or len(text) > 500 or text in existing:
                continue
            self.session.add(
                Keyword(
                    project_id=self.project_id,
                    keyword=text,
                    source=str(row.get("source") or source)[:100],
                    volume=to_int(row.get("volume")),
                    kd=to_float(row.get("kd")),
                    cpc=to_float(row.get("cpc")),
                    data=dict(row.get("data") or {}),
                )
            )
            existing.add(text)
            added += 1
        self.session.flush()
        return added

    def exclude(self, keyword: Keyword, reason: str) -> None:
        keyword.excluded = True
        keyword.excluded_reason = reason[:300]

    def include(self, keyword: Keyword) -> None:
        keyword.excluded = False
        keyword.excluded_reason = None

    def set_data(self, keyword: Keyword, **values: Any) -> None:
        """Merge values into ``keyword.data``."""
        keyword.data = {**(keyword.data or {}), **values}

    # --- services ---------------------------------------------------------------------
    def connection(self, connection_id: int | None, kind: str | None = None) -> Connector:
        """A ready-to-use connector for the connection picked in the step settings."""
        if connection_id is None:
            raise PluginError(f"Choose a {kind or ''} connection in this step's settings.".replace("  ", " "))
        row = self.session.get(Connection, connection_id)
        if row is None:
            raise PluginError("The connection selected in this step no longer exists.")
        connector = build_connector(self.registry, row)
        if kind and connector.kind != kind:
            raise PluginError(f"Connection '{row.name}' is a {connector.kind} connection, not {kind}.")
        return connector

    def output_path(self, filename: str) -> Path:
        """Where a stage should write files it produces (exports, reports)."""
        folder = self._data_dir / "exports" / f"project-{self.project_id}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / Path(filename).name

    def commit(self) -> None:
        """Save work so far. Long stages should commit every batch: if the run is
        cancelled or fails later, committed batches are kept."""
        self._state.apply_to(self.run)
        self.session.commit()
