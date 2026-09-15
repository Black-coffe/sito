"""Editing a project's pipeline: add, reorder, remove and validate steps."""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sito.core.connections import connection_kind, connections_of_kind
from sito.core.forms import _extra, default_values, first_error
from sito.models import Connection, Project, Step
from sito.plugins.registry import PluginRegistry

# Starter pipelines offered when creating a project. Unknown stage ids are skipped,
# so templates keep working if a plugin is removed.
TEMPLATES: dict[str, tuple[str, list[str]]] = {
    "classic": (
        "Classic: clean → AI classify → SERP → cluster → export",
        ["clean", "ai_classify", "serp_collect", "serp_cluster", "ai_cluster_names", "export_file"],
    ),
    "expand": (
        "Expand: autocomplete → clean → AI classify → export",
        ["autocomplete", "clean", "ai_classify", "export_file"],
    ),
    "clean_only": ("Quick clean-up: clean → filter → export", ["clean", "filter", "export_file"]),
    "empty": ("Empty pipeline (add steps yourself)", []),
}


def list_steps(session: Session, project_id: int) -> list[Step]:
    return list(session.scalars(select(Step).where(Step.project_id == project_id).order_by(Step.position, Step.id)))


def _renumber(session: Session, project_id: int) -> None:
    for index, step in enumerate(list_steps(session, project_id)):
        step.position = index


def add_step(
    session: Session,
    registry: PluginRegistry,
    project: Project,
    stage_id: str,
    position: int | None = None,
) -> Step:
    """Append (or insert at ``position``) a step with default settings.

    Connection pickers are pre-filled with the first matching connection.
    """
    stage_cls = registry.stage(stage_id)
    config = default_values(stage_cls.Config)
    for name, info in stage_cls.Config.model_fields.items():
        kind = _extra(info).get("sito_connection")
        if kind and config.get(name) is None:
            matches = connections_of_kind(session, registry, kind)
            if matches:
                config[name] = matches[0].id
    steps = list_steps(session, project.id)
    if position is None or position > len(steps):
        position = len(steps)
    for step in steps[position:]:
        step.position += 1
    step = Step(
        project_id=project.id,
        position=position,
        stage_id=stage_id,
        title=stage_cls.name or stage_id,
        config=config,
    )
    session.add(step)
    session.flush()
    return step


def move_step(session: Session, step: Step, direction: int) -> None:
    steps = list_steps(session, step.project_id)
    index = next(i for i, s in enumerate(steps) if s.id == step.id)
    target = index + direction
    if 0 <= target < len(steps):
        steps[index], steps[target] = steps[target], steps[index]
        for i, s in enumerate(steps):
            s.position = i
    session.flush()


def delete_step(session: Session, step: Step) -> None:
    project_id = step.project_id
    session.delete(step)
    session.flush()
    _renumber(session, project_id)
    session.flush()


def apply_template(session: Session, registry: PluginRegistry, project: Project, template: str) -> list[str]:
    """Add the template's steps; returns stage ids that were skipped (not installed)."""
    skipped = []
    for stage_id in TEMPLATES.get(template, ("", []))[1]:
        if stage_id in registry.stages:
            add_step(session, registry, project, stage_id)
        else:
            skipped.append(stage_id)
    return skipped


def step_issues(session: Session, registry: PluginRegistry, step: Step) -> list[str]:
    """What stops this step from running (empty list = ready)."""
    stage_cls = registry.stages.get(step.stage_id)
    if stage_cls is None:
        return [f"The plugin '{step.stage_id}' is not installed."]
    try:
        config = stage_cls.Config.model_validate(step.config or {})
    except ValidationError as exc:
        return [f"Settings are invalid: {first_error(exc)}"]
    issues: list[str] = []
    for name, info in stage_cls.Config.model_fields.items():
        kind = _extra(info).get("sito_connection")
        if not kind:
            continue
        connection_id = getattr(config, name)
        if connection_id is None:
            issues.append(f"Choose a {kind} connection (add one on the Connections page).")
            continue
        row = session.get(Connection, connection_id)
        if row is None:
            issues.append("The selected connection was deleted; choose another.")
        elif connection_kind(registry, row) != kind:
            issues.append(f"Connection '{row.name}' is not a {kind} connection.")
    return issues


def step_count(session: Session, project_id: int) -> int:
    return session.scalar(select(func.count()).select_from(Step).where(Step.project_id == project_id)) or 0
