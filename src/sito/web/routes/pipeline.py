"""Pipeline editing and execution: steps, runs, undo, run logs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from sito.core.forms import dump_model, first_error, parse_form
from sito.core.pipeline import add_step, delete_step, list_steps, move_step
from sito.core.runner import Runner
from sito.core.snapshots import create_snapshot, restore_snapshot
from sito.models import RUN_RUNNING, Project, Run, Snapshot, Step
from sito.plugins.base import PluginError
from sito.web.deps import app_state, get_or_404, get_session, redirect, render, safe_next
from sito.web.workspace import pipeline_context, workspace_context

router = APIRouter(prefix="/projects/{pid}")

BUSY = "Wait for the current run to finish (or cancel it) first."
NEXT = Form(None, alias="next")


def _default(pid: int) -> str:
    return f"/projects/{pid}/keywords"


def _step(session: Session, pid: int, sid: int) -> Step:
    step = get_or_404(session, Step, sid)
    if step.project_id != pid:
        raise HTTPException(status_code=404, detail="Not found")
    return step


def _busy(session: Session, pid: int) -> bool:
    return bool(Runner.active_runs(session, pid))


@router.get("/pipeline")
def pipeline_partial(request: Request, pid: int, session: Session = Depends(get_session)):
    project = get_or_404(session, Project, pid)
    path = request.query_params.get("path") or _default(pid)
    if not path.startswith(f"/projects/{pid}/"):
        path = _default(pid)
    context = pipeline_context(request, session, project, path)
    if request.query_params.get("was_active") and not context["is_active"]:
        # The run just finished: reload the page so the table and counters are fresh.
        return HTMLResponse("", headers={"HX-Refresh": "true"})
    return render(request, "_pipeline.html", project=project, **context)


@router.post("/steps")
def create_step(
    request: Request,
    pid: int,
    stage_id: str = Form(...),
    position: int | None = Form(None),
    nxt: str | None = NEXT,
    session: Session = Depends(get_session),
):
    project = get_or_404(session, Project, pid)
    target = safe_next(request, nxt, _default(pid))
    step = add_step(session, app_state(request).registry, project, stage_id, position)
    session.commit()
    return redirect(f"{target}#step-{step.id}", edit=step.id, add_at=None)


@router.post("/steps/{sid}/settings")
async def save_step_settings(request: Request, pid: int, sid: int, session: Session = Depends(get_session)):
    form = await request.form()
    target = safe_next(request, str(form.get("next") or ""), _default(pid))
    step = _step(session, pid, sid)
    stage_cls = app_state(request).registry.stage(step.stage_id)
    try:
        config = parse_form(stage_cls.Config, form, existing=step.config or {})
    except ValidationError as exc:
        return redirect(f"{target}#step-{sid}", error=f"Settings not saved — {first_error(exc)}", edit=sid)
    step.config = dump_model(config)
    title = str(form.get("__title") or "").strip()
    if title:
        step.title = title[:200]
    session.commit()
    if form.get("__then") == "run":
        app_state(request).runner.enqueue(pid, [sid])
        return redirect(target, notice=f"Saved. «{step.title}» is running.", edit=None)
    return redirect(f"{target}#step-{sid}", notice="Step settings saved.", edit=None)


@router.post("/steps/{sid}/move")
def move(
    request: Request,
    pid: int,
    sid: int,
    direction: int = Form(...),
    nxt: str | None = NEXT,
    session: Session = Depends(get_session),
):
    step = _step(session, pid, sid)
    move_step(session, step, 1 if direction > 0 else -1)
    session.commit()
    return redirect(f"{safe_next(request, nxt, _default(pid))}#step-{sid}")


@router.post("/steps/{sid}/toggle")
def toggle(request: Request, pid: int, sid: int, nxt: str | None = NEXT, session: Session = Depends(get_session)):
    step = _step(session, pid, sid)
    step.enabled = not step.enabled
    session.commit()
    state = "on" if step.enabled else "off (Run all will skip it)"
    return redirect(f"{safe_next(request, nxt, _default(pid))}#step-{sid}", notice=f"«{step.title}» turned {state}.")


@router.post("/steps/{sid}/delete")
def remove(request: Request, pid: int, sid: int, nxt: str | None = NEXT, session: Session = Depends(get_session)):
    target = safe_next(request, nxt, _default(pid))
    if _busy(session, pid):
        return redirect(target, error=BUSY)
    step = _step(session, pid, sid)
    title = step.title
    delete_step(session, step)
    session.commit()
    return redirect(target, notice=f"Step «{title}» removed. Keywords were not changed.", edit=None)


def _enqueue(request: Request, pid: int, step_ids: list[int], target: str, what: str):
    try:
        app_state(request).runner.enqueue(pid, step_ids)
    except PluginError as exc:
        return redirect(target, error=str(exc))
    return redirect(target, notice=f"{what} started. Progress shows in the pipeline.", edit=None, add_at=None)


@router.post("/steps/{sid}/run")
def run_step(request: Request, pid: int, sid: int, nxt: str | None = NEXT, session: Session = Depends(get_session)):
    step = _step(session, pid, sid)
    return _enqueue(request, pid, [step.id], safe_next(request, nxt, _default(pid)), f"«{step.title}»")


@router.post("/steps/{sid}/run-from")
def run_from(request: Request, pid: int, sid: int, nxt: str | None = NEXT, session: Session = Depends(get_session)):
    steps = list_steps(session, pid)
    start = next((i for i, s in enumerate(steps) if s.id == sid), None)
    if start is None:
        raise HTTPException(status_code=404, detail="Not found")
    ids = [s.id for s in steps[start:] if s.enabled]
    return _enqueue(request, pid, ids, safe_next(request, nxt, _default(pid)), f"{len(ids)} steps")


@router.post("/run-all")
def run_all(request: Request, pid: int, nxt: str | None = NEXT, session: Session = Depends(get_session)):
    ids = [s.id for s in list_steps(session, pid) if s.enabled]
    return _enqueue(request, pid, ids, safe_next(request, nxt, _default(pid)), "The whole pipeline")


@router.post("/cancel")
def cancel(request: Request, pid: int, nxt: str | None = NEXT):
    count = app_state(request).runner.cancel(pid)
    target = safe_next(request, nxt, _default(pid))
    if not count:
        return redirect(target, notice="Nothing is running.")
    return redirect(target, notice="Cancelling… the step stops at its next checkpoint; finished batches are kept.")


@router.post("/steps/{sid}/undo")
def undo(request: Request, pid: int, sid: int, nxt: str | None = NEXT, session: Session = Depends(get_session)):
    target = safe_next(request, nxt, _default(pid))
    if _busy(session, pid):
        return redirect(target, error=BUSY)
    step = _step(session, pid, sid)
    run = session.scalars(select(Run).where(Run.step_id == sid).order_by(Run.id.desc()).limit(1)).first()
    before = None
    if run is not None:
        before = session.scalars(
            select(Snapshot).where(Snapshot.run_id == run.id).order_by(Snapshot.id).limit(1)
        ).first()
    if before is None or not before.label.startswith("Before"):
        return redirect(target, error="There is no «before» snapshot for this step any more (it may have been pruned).")
    create_snapshot(session, pid, f"Before undo of «{step.title}»")
    restore_snapshot(session, before)
    session.commit()
    return redirect(
        target, notice=f"Restored the list as it was before «{step.title}». Undo it from Snapshots if needed."
    )


@router.get("/runs")
def runs_tab(request: Request, pid: int, session: Session = Depends(get_session)):
    context = workspace_context(request, session, pid, "runs")
    context["runs"] = session.scalars(select(Run).where(Run.project_id == pid).order_by(Run.id.desc()).limit(300)).all()
    return render(request, "runs.html", **context)


@router.get("/runs/{rid}")
def run_detail(request: Request, pid: int, rid: int, session: Session = Depends(get_session)):
    run = get_or_404(session, Run, rid)
    if run.project_id != pid:
        raise HTTPException(status_code=404, detail="Not found")
    context = workspace_context(request, session, pid, "runs")
    live = app_state(request).runner.live(rid) if run.status == RUN_RUNNING else None
    context.update(
        run=run,
        live=live,
        log_text="\n".join(live.lines) if live else (run.log or ""),
        stats=dict(run.stats or {}),
    )
    return render(request, "run.html", **context)


@router.get("/runs/{rid}/file")
def run_file(request: Request, pid: int, rid: int, session: Session = Depends(get_session)):
    run = get_or_404(session, Run, rid)
    name = (run.stats or {}).get("file")
    if run.project_id != pid or not name:
        raise HTTPException(status_code=404, detail="This run did not produce a file.")
    folder = (app_state(request).config.data_dir / "exports" / f"project-{pid}").resolve()
    path = (folder / str(name)).resolve()
    if folder not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="The file is no longer on disk.")
    return FileResponse(path, filename=path.name)
