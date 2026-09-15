"""Projects list, creation, settings and deletion."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from sito.core.pipeline import TEMPLATES, apply_template, step_count
from sito.core.runner import Runner
from sito.models import Connection, Project, Run
from sito.web.deps import app_state, get_or_404, get_session, redirect, render
from sito.web.workspace import project_counts, workspace_context

router = APIRouter()


@router.get("/")
def projects_page(request: Request, session: Session = Depends(get_session)):
    rows = []
    for project in session.scalars(select(Project).order_by(Project.created_at.desc())):
        last_run = session.scalars(
            select(Run).where(Run.project_id == project.id).order_by(Run.id.desc()).limit(1)
        ).first()
        rows.append(
            {
                "project": project,
                "counts": project_counts(session, project.id),
                "steps": step_count(session, project.id),
                "last_run": last_run,
            }
        )
    registry = app_state(request).registry
    needs_keys = any(c.kind in ("llm", "serp") for c in registry.connectors.values())
    return render(
        request,
        "projects.html",
        nav="projects",
        rows=rows,
        templates=TEMPLATES,
        show_keys_hint=needs_keys and not _has_keyed_connection(session, registry),
    )


def _has_keyed_connection(session: Session, registry) -> bool:
    for row in session.scalars(select(Connection)):
        cls = registry.connectors.get(row.connector_id)
        if cls is not None and cls.kind in ("llm", "serp"):
            return True
    return False


@router.post("/projects")
def create_project(
    request: Request,
    name: str = Form(""),
    description: str = Form(""),
    context: str = Form(""),
    template: str = Form("classic"),
    session: Session = Depends(get_session),
):
    name = name.strip()
    if not name:
        return redirect("/#new", error="Give the project a name.")
    project = Project(name=name[:200], description=description.strip(), context=context.strip())
    session.add(project)
    session.flush()
    skipped = apply_template(session, app_state(request).registry, project, template)
    session.commit()
    notice = "Project created. Import keywords (or add them) to start sifting."
    if skipped:
        notice += f" Skipped steps whose plugins are not installed: {', '.join(skipped)}."
    return redirect(f"/projects/{project.id}/keywords", notice=notice)


@router.get("/projects/{pid}")
def project_home(pid: int):
    return redirect(f"/projects/{pid}/keywords")


@router.get("/projects/{pid}/settings")
def project_settings(request: Request, pid: int, session: Session = Depends(get_session)):
    context = workspace_context(request, session, pid, "settings")
    st = app_state(request)
    context["exports_dir"] = st.config.data_dir / "exports" / f"project-{pid}"
    return render(request, "project_settings.html", **context)


@router.post("/projects/{pid}/settings")
def save_project_settings(
    pid: int,
    name: str = Form(""),
    description: str = Form(""),
    context: str = Form(""),
    session: Session = Depends(get_session),
):
    project = get_or_404(session, Project, pid)
    if not name.strip():
        return redirect(f"/projects/{pid}/settings", error="The project name can't be empty.")
    project.name = name.strip()[:200]
    project.description = description.strip()
    project.context = context.strip()
    session.commit()
    return redirect(f"/projects/{pid}/settings", notice="Project settings saved.")


@router.post("/projects/{pid}/delete")
def delete_project(pid: int, confirm_name: str = Form(""), session: Session = Depends(get_session)):
    project = get_or_404(session, Project, pid)
    if Runner.active_runs(session, pid):
        return redirect(f"/projects/{pid}/settings", error="Cancel the running step before deleting the project.")
    if confirm_name.strip() != project.name:
        return redirect(f"/projects/{pid}/settings", error="Type the project name exactly to confirm deletion.")
    session.execute(delete(Project).where(Project.id == pid))
    session.commit()
    return redirect("/", notice=f"Project «{project.name}» deleted.")
