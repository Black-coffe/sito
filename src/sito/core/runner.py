"""Background execution of pipeline steps.

A run is one execution of one step. "Run from here" queues several runs that
execute one after another; if one fails or is cancelled the rest are skipped.
Only one chain runs per project at a time. Before each run the keyword table is
snapshotted (so the step can be undone), and after a successful run again (so
the result of that step can be exported later).
"""

from __future__ import annotations

import logging
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sito.config import AppConfig
from sito.core.context import LiveState, StageContext
from sito.core.forms import first_error
from sito.core.pipeline import step_issues
from sito.core.snapshots import create_snapshot, prune_snapshots
from sito.models import (
    RUN_ACTIVE,
    RUN_CANCELLED,
    RUN_DONE,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    Project,
    Run,
    Step,
    utcnow,
)
from sito.plugins.base import Cancelled, PluginError
from sito.plugins.registry import PluginRegistry

log = logging.getLogger("sito.runner")


class RunConflict(PluginError):
    """Another run is already active in this project."""


class Runner:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        registry: PluginRegistry,
        config: AppConfig,
        max_workers: int = 2,
    ) -> None:
        self._sf = session_factory
        self.registry = registry
        self.config = config
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sito-run")
        self._live: dict[int, LiveState] = {}
        self._cancel: set[int] = set()
        self._lock = threading.Lock()

    # --- lifecycle --------------------------------------------------------------------
    def recover(self) -> None:
        """Mark runs left active by a previous process as failed."""
        with self._sf() as s:
            for run in s.scalars(select(Run).where(Run.status.in_(RUN_ACTIVE))):
                run.status = RUN_FAILED
                run.error = "Interrupted: sito was stopped while this run was in progress."
                run.finished_at = utcnow()
            s.commit()

    def shutdown(self) -> None:
        self._cancel.update(self._live.keys())
        self._pool.shutdown(wait=False, cancel_futures=True)

    # --- queries ----------------------------------------------------------------------
    def live(self, run_id: int) -> LiveState | None:
        return self._live.get(run_id)

    @staticmethod
    def active_runs(session: Session, project_id: int) -> list[Run]:
        return list(
            session.scalars(
                select(Run).where(Run.project_id == project_id, Run.status.in_(RUN_ACTIVE)).order_by(Run.id)
            )
        )

    # --- commands ---------------------------------------------------------------------
    def enqueue(self, project_id: int, step_ids: list[int], *, background: bool = True) -> list[int]:
        """Queue runs for the given steps (in order). Raises PluginError if not runnable."""
        if not step_ids:
            raise PluginError("There are no enabled steps to run.")
        with self._lock, self._sf() as s:
            if self.active_runs(s, project_id):
                raise RunConflict("A run is already in progress in this project. Wait for it or cancel it.")
            problems: list[str] = []
            steps: list[Step] = []
            for step_id in step_ids:
                step = s.get(Step, step_id)
                if step is None or step.project_id != project_id:
                    raise PluginError("Step not found.")
                steps.append(step)
                problems += [f"«{step.title}»: {issue}" for issue in step_issues(s, self.registry, step)]
            if problems:
                raise PluginError("Fix these first:\n" + "\n".join(problems))
            runs = [
                Run(project_id=project_id, step_id=st.id, stage_id=st.stage_id, title=st.title, status=RUN_QUEUED)
                for st in steps
            ]
            s.add_all(runs)
            s.commit()
            ids = [r.id for r in runs]
        if background:
            self._pool.submit(self._run_chain, ids)
        else:
            self._run_chain(ids)
        return ids

    def cancel(self, project_id: int) -> int:
        with self._sf() as s:
            runs = self.active_runs(s, project_id)
            for run in runs:
                if run.status == RUN_QUEUED:
                    run.status = RUN_CANCELLED
                    run.message = "Cancelled before it started."
                    run.finished_at = utcnow()
                else:
                    self._cancel.add(run.id)
            s.commit()
            return len(runs)

    # --- execution --------------------------------------------------------------------
    def _run_chain(self, run_ids: list[int]) -> None:
        for index, run_id in enumerate(run_ids):
            try:
                status = self._execute(run_id)
            except Exception:  # noqa: BLE001 - never let the worker thread die silently
                log.exception("run %s crashed", run_id)
                status = RUN_FAILED
            if status != RUN_DONE:
                with self._sf() as s:
                    for later_id in run_ids[index + 1 :]:
                        later = s.get(Run, later_id)
                        if later is not None and later.status == RUN_QUEUED:
                            later.status = RUN_CANCELLED
                            later.message = f"Skipped because the previous step {status}."
                            later.finished_at = utcnow()
                    s.commit()
                break

    def _execute(self, run_id: int) -> str:
        state = LiveState()
        self._live[run_id] = state
        try:
            return self._execute_inner(run_id, state)
        finally:
            self._live.pop(run_id, None)
            self._cancel.discard(run_id)

    def _execute_inner(self, run_id: int, state: LiveState) -> str:
        with self._sf() as s:
            run = s.get(Run, run_id)
            if run is None or run.status != RUN_QUEUED:
                return run.status if run else RUN_FAILED
            status, error = RUN_FAILED, None
            try:
                step = s.get(Step, run.step_id) if run.step_id else None
                if step is None:
                    raise PluginError("This step was deleted before it could run.")
                project = s.get(Project, run.project_id)
                stage_cls = self.registry.stage(step.stage_id)
                try:
                    config = stage_cls.Config.model_validate(step.config or {})
                except ValidationError as exc:
                    raise PluginError(f"Step settings are invalid: {first_error(exc)}") from exc
                run.status = RUN_RUNNING
                run.started_at = utcnow()
                s.commit()
                before = create_snapshot(s, run.project_id, f"Before «{step.title}»", run_id=run.id)
                state.stat({"active_before": before.active_count, "total_before": before.keyword_count})
                s.commit()
                ctx = StageContext(
                    session=s,
                    project=project,
                    run=run,
                    state=state,
                    registry=self.registry,
                    cancel_check=lambda: run_id in self._cancel,
                    data_dir=self.config.data_dir,
                )
                state.log(f"Started: {stage_cls.name}")
                stage_cls().run(ctx, config)
                ctx.check_cancelled()
                s.flush()
                state.log("Finished.")
                status = RUN_DONE
            except Cancelled:
                s.rollback()
                status = RUN_CANCELLED
                state.log("Cancelled. Batches committed before cancelling are kept.")
            except PluginError as exc:
                s.rollback()
                error = str(exc)
                state.log(f"Error: {exc}")
            except Exception as exc:  # noqa: BLE001 - surface plugin bugs in the UI
                s.rollback()
                error = f"{type(exc).__name__}: {exc}"
                state.log(traceback.format_exc(limit=8))
                log.exception("stage %s failed", run.stage_id)

            run = s.get(Run, run_id)
            state.apply_to(run)
            run.status = status
            run.error = error
            run.finished_at = utcnow()
            if status == RUN_DONE:
                snap = create_snapshot(s, run.project_id, f"After «{run.title}»", run_id=run.id)
                run.snapshot_id = snap.id
                run.stats = {**(run.stats or {}), "active_after": snap.active_count, "total_after": snap.keyword_count}
            prune_snapshots(s, run.project_id, self.config.snapshot_limit)
            s.commit()
            return status
