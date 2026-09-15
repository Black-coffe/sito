"""Context shared by every page of a project workspace (header, tabs, sieve stack)."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, defer

from sito.core.connections import connection_kind
from sito.core.forms import describe_model
from sito.core.pipeline import list_steps, step_issues
from sito.core.runner import Runner
from sito.models import (
    RUN_DONE,
    RUN_RUNNING,
    Cluster,
    Connection,
    Keyword,
    Project,
    Run,
    Snapshot,
)
from sito.plugins.base import StageKind
from sito.web.deps import app_state, get_or_404

TABS = (
    ("keywords", "Keywords"),
    ("clusters", "Clusters"),
    ("serp", "SERP"),
    ("snapshots", "Snapshots"),
    ("runs", "Runs"),
    ("settings", "Settings"),
)


def project_counts(session: Session, project_id: int) -> dict[str, int]:
    def count(query) -> int:
        return session.scalar(query) or 0

    total = count(select(func.count()).select_from(Keyword).where(Keyword.project_id == project_id))
    excluded = count(
        select(func.count()).select_from(Keyword).where(Keyword.project_id == project_id, Keyword.excluded.is_(True))
    )
    return {
        "total": total,
        "excluded": excluded,
        "active": total - excluded,
        "clusters": count(select(func.count()).select_from(Cluster).where(Cluster.project_id == project_id)),
        "snapshots": count(select(func.count()).select_from(Snapshot).where(Snapshot.project_id == project_id)),
        "runs": count(select(func.count()).select_from(Run).where(Run.project_id == project_id)),
    }


def connections_by_kind(session: Session, registry) -> dict[str, list[Connection]]:
    grouped: dict[str, list[Connection]] = {}
    for row in session.scalars(select(Connection).order_by(Connection.name)):
        kind = connection_kind(registry, row)
        if kind:
            grouped.setdefault(kind, []).append(row)
    return grouped


def stage_catalog(registry) -> list[tuple[StageKind, list]]:
    groups = []
    for kind in StageKind:
        stages = sorted((s for s in registry.stages.values() if s.kind == kind), key=lambda s: s.name)
        if stages:
            groups.append((kind, stages))
    return groups


def _int_param(request: Request, name: str) -> int | None:
    try:
        return int(request.query_params[name])
    except (KeyError, ValueError):
        return None


def pipeline_context(request: Request, session: Session, project: Project, here: str) -> dict[str, Any]:
    st = app_state(request)
    registry = st.registry
    steps = list_steps(session, project.id)
    last_runs: dict[int, Run] = {}
    recent_runs = select(Run).options(defer(Run.log)).where(Run.project_id == project.id).order_by(Run.id.desc())
    for run in session.scalars(recent_runs.limit(500)):
        if run.step_id is not None and run.step_id not in last_runs:
            last_runs[run.step_id] = run
    active_runs = Runner.active_runs(session, project.id)
    is_active = bool(active_runs)
    edit_id = None if is_active else _int_param(request, "edit")
    add_at = None if is_active else _int_param(request, "add_at")
    counts = project_counts(session, project.id)

    trays = []
    scale = max(counts["total"], 1)
    for index, step in enumerate(steps):
        stage_cls = registry.stages.get(step.stage_id)
        run = last_runs.get(step.id)
        live = st.runner.live(run.id) if run is not None and run.status == RUN_RUNNING else None
        stats = dict(run.stats or {}) if run is not None else {}
        before = stats.get("active_before") if run is not None and run.status == RUN_DONE else None
        after = stats.get("active_after") if run is not None and run.status == RUN_DONE else None
        if before is not None:
            scale = max(scale, before, after or 0)
        progress = None
        if live is not None:
            percent = round(100 * live.done / live.total) if live.total else None
            progress = {"done": live.done, "total": live.total, "message": live.message, "percent": percent}
        trays.append(
            {
                "no": index + 1,
                "index": index,
                "step": step,
                "stage": stage_cls,
                "kind_label": stage_cls.kind.label if stage_cls else "Missing plugin",
                "run": run,
                "progress": progress,
                "issues": step_issues(session, registry, step),
                "before": before,
                "after": after,
                "editing": step.id == edit_id,
                "fields": describe_model(stage_cls.Config, step.config or {})
                if stage_cls and step.id == edit_id
                else [],
            }
        )
    for tray in trays:
        if tray["before"] is not None:
            tray["in_pct"] = round(100 * tray["before"] / scale, 2)
            tray["out_pct"] = round(100 * (tray["after"] or 0) / scale, 2)
    return {
        "trays": trays,
        "is_active": is_active,
        "active_runs": active_runs,
        "edit_id": edit_id,
        "add_at": add_at,
        "here": here,
        "catalog": stage_catalog(registry) if add_at is not None else [],
        "connections": connections_by_kind(session, registry) if edit_id else {},
        "counts": counts,
    }


def workspace_context(request: Request, session: Session, project_id: int, tab: str) -> dict[str, Any]:
    """Everything ``project.html`` needs. Tab routes add their own keys on top."""
    project = get_or_404(session, Project, project_id)
    context = pipeline_context(request, session, project, request.url.path)
    context.update({"project": project, "tab": tab, "tabs": TABS, "nav": "projects"})
    return context
