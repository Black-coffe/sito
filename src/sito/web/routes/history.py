"""Snapshots, Clusters and SERP tabs: browsing the results earlier steps produced."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sito.core.runner import Runner
from sito.core.snapshots import create_snapshot, prune_snapshots, restore_snapshot
from sito.models import Cluster, Keyword, Project, SerpResult, Snapshot
from sito.web.deps import app_state, get_or_404, get_session, redirect, render
from sito.web.workspace import workspace_context

router = APIRouter()


def _guard_active(session: Session, pid: int) -> str | None:
    if Runner.active_runs(session, pid):
        return "A step is currently running in this project; wait for it to finish."
    return None


# --- snapshots -------------------------------------------------------------------------------


@router.get("/projects/{pid}/snapshots")
def snapshots_page(request: Request, pid: int, session: Session = Depends(get_session)):
    get_or_404(session, Project, pid)
    snapshots = list(session.scalars(select(Snapshot).where(Snapshot.project_id == pid).order_by(Snapshot.id.desc())))
    context = workspace_context(request, session, pid, "snapshots")
    context.update(
        snapshots=snapshots,
        snapshot_limit=app_state(request).config.snapshot_limit,
        run_blocked=bool(Runner.active_runs(session, pid)),
    )
    return render(request, "snapshots.html", **context)


@router.post("/projects/{pid}/snapshots")
def snapshot_now(request: Request, pid: int, label: str = Form(""), session: Session = Depends(get_session)):
    project = get_or_404(session, Project, pid)
    blocked = _guard_active(session, pid)
    if blocked:
        return redirect(f"/projects/{pid}/snapshots", error=blocked)
    create_snapshot(session, project.id, label.strip()[:300] or "Manual snapshot")
    prune_snapshots(session, project.id, app_state(request).config.snapshot_limit)
    session.commit()
    return redirect(f"/projects/{pid}/snapshots", notice="Snapshot taken.")


@router.post("/projects/{pid}/snapshots/{sid}/restore")
def snapshot_restore(request: Request, pid: int, sid: int, session: Session = Depends(get_session)):
    snapshot = get_or_404(session, Snapshot, sid)
    if snapshot.project_id != pid:
        return redirect(f"/projects/{pid}/snapshots", error="That snapshot doesn't belong to this project.")
    blocked = _guard_active(session, pid)
    if blocked:
        return redirect(f"/projects/{pid}/snapshots", error=blocked)
    create_snapshot(session, pid, f"Before restore of «{snapshot.label}»")
    restore_snapshot(session, snapshot)
    prune_snapshots(session, pid, app_state(request).config.snapshot_limit)
    session.commit()
    return redirect(f"/projects/{pid}/snapshots", notice=f"Restored «{snapshot.label}».")


@router.post("/projects/{pid}/snapshots/{sid}/delete")
def snapshot_delete(pid: int, sid: int, session: Session = Depends(get_session)):
    snapshot = get_or_404(session, Snapshot, sid)
    if snapshot.project_id != pid:
        return redirect(f"/projects/{pid}/snapshots", error="That snapshot doesn't belong to this project.")
    session.delete(snapshot)
    session.commit()
    return redirect(f"/projects/{pid}/snapshots", notice="Snapshot deleted.")


# --- clusters --------------------------------------------------------------------------------


@router.get("/projects/{pid}/clusters")
def clusters_page(request: Request, pid: int, session: Session = Depends(get_session)):
    get_or_404(session, Project, pid)
    clusters = list(
        session.scalars(
            select(Cluster).where(Cluster.project_id == pid).order_by(Cluster.total_volume.desc(), Cluster.name)
        )
    )
    has_serp = session.scalar(select(SerpResult.id).where(SerpResult.project_id == pid).limit(1)) is not None
    context = workspace_context(request, session, pid, "clusters")
    context.update(clusters=clusters, has_serp=has_serp)
    return render(request, "clusters.html", **context)


# --- SERP ------------------------------------------------------------------------------------


@router.get("/projects/{pid}/serp")
def serp_page(request: Request, pid: int, session: Session = Depends(get_session)):
    get_or_404(session, Project, pid)
    total_keywords = session.scalar(select(func.count()).select_from(Keyword).where(Keyword.project_id == pid)) or 0
    with_serp = (
        session.scalar(select(func.count(func.distinct(SerpResult.keyword_id))).where(SerpResult.project_id == pid))
        or 0
    )

    domain_rows = session.execute(
        select(
            SerpResult.domain,
            func.count(SerpResult.id).label("results"),
            func.count(func.distinct(SerpResult.keyword_id)).label("keywords"),
            func.avg(SerpResult.position).label("avg_position"),
            func.min(SerpResult.position).label("best_position"),
        )
        .where(SerpResult.project_id == pid, SerpResult.domain != "")
        .group_by(SerpResult.domain)
        .order_by(func.count(SerpResult.id).desc())
        .limit(100)
    ).all()

    recent = session.execute(
        select(SerpResult.keyword_id, func.max(SerpResult.fetched_at).label("at"))
        .where(SerpResult.project_id == pid)
        .group_by(SerpResult.keyword_id)
        .order_by(func.max(SerpResult.fetched_at).desc())
        .limit(50)
    ).all()
    recent_ids = [row.keyword_id for row in recent]
    by_id = {}
    if recent_ids:
        by_id = {k.id: k for k in session.scalars(select(Keyword).where(Keyword.id.in_(recent_ids)))}
    recent_keywords = [by_id[i] for i in recent_ids if i in by_id]

    context = workspace_context(request, session, pid, "serp")
    context.update(
        total_keywords=total_keywords,
        with_serp=with_serp,
        domain_rows=domain_rows,
        recent_keywords=recent_keywords,
    )
    return render(request, "serp.html", **context)


@router.get("/projects/{pid}/serp/{kid}")
def serp_keyword_page(request: Request, pid: int, kid: int, session: Session = Depends(get_session)):
    kw = get_or_404(session, Keyword, kid)
    if kw.project_id != pid:
        return redirect(f"/projects/{pid}/serp", error="That keyword doesn't belong to this project.")
    results = list(
        session.scalars(
            select(SerpResult)
            .where(SerpResult.project_id == pid, SerpResult.keyword_id == kid)
            .order_by(SerpResult.position)
        )
    )
    context = workspace_context(request, session, pid, "serp")
    context.update(kw=kw, results=results)
    return render(request, "serp_keyword.html", **context)
