"""Import wizard (upload/paste -> map columns -> import) and file downloads."""

from __future__ import annotations

import re
import secrets
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from sito.core.io import (
    MEDIA_TYPES,
    TablePreview,
    export_filename,
    guess_mapping,
    import_rows,
    keyword_table,
    read_table,
    slugify,
    snapshot_table,
    write_table,
)
from sito.core.runner import Runner
from sito.core.snapshots import create_snapshot
from sito.models import Project, Snapshot
from sito.plugins.base import PluginError
from sito.web.deps import app_state, get_or_404, get_session, redirect, render
from sito.web.workspace import workspace_context

router = APIRouter()

PREVIEW_ROWS = 15
IMPORT_MODES = (
    ("add", "Add only", "Only new keywords are added; keywords already in the project are skipped."),
    (
        "merge",
        "Add + update",
        "New keywords are added; existing ones are updated with any non-empty value from the file.",
    ),
    ("update", "Update only", "Only keywords already in the project are updated; new ones are skipped."),
)


MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_FORM_PART_BYTES = 50 * 1024 * 1024
STALE_UPLOAD_SECONDS = 24 * 3600


def _imports_dir(request: Request) -> Path:
    folder = app_state(request).config.data_dir / "imports"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _cleanup_stale_uploads(imports_dir: Path) -> None:
    """Drop leftover uploads from abandoned import wizards, e.g. a closed browser tab."""
    cutoff = time.time() - STALE_UPLOAD_SECONDS
    for path in imports_dir.glob("*__*"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            pass  # another request may be racing to clean up (or read) the same file


def _find_upload(imports_dir: Path, token: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{16}", token):
        return None
    matches = list(imports_dir.glob(f"{token}__*"))
    return matches[0] if matches else None


FIXED_TARGETS = (
    ("keyword", "Keyword"),
    ("volume", "Volume"),
    ("kd", "KD"),
    ("cpc", "CPC"),
    ("source", "Source"),
    ("excluded", "Status (excluded)"),
    ("excluded_reason", "Excluded reason"),
)


def _column_options(columns: list[str], mapping: dict[str, str]) -> dict[str, list[tuple[str, str]]]:
    """The <option>s offered for each column's target select.

    The "Custom field" option always includes whatever guess_mapping() actually guessed
    (which may not be a plain slug of the column name, e.g. a "data.<key>" collision escape)
    so the pre-selected option in the form always matches the mapping shown.
    """
    options: dict[str, list[tuple[str, str]]] = {}
    for col in columns:
        guessed = mapping.get(col, "ignore")
        if guessed.startswith("data:"):
            custom = (guessed, f"Custom field ({guessed[5:]})")
        else:
            slug = slugify(col)
            custom = (f"data:{slug}", f"Custom field ({slug})")
        options[col] = [*FIXED_TARGETS, custom, ("ignore", "Ignore")]
    return options


@router.get("/projects/{pid}/import")
def import_page(request: Request, pid: int, session: Session = Depends(get_session)):
    context = workspace_context(request, session, pid, "keywords")
    return render(request, "import.html", **context)


@router.post("/projects/{pid}/import")
async def import_upload(request: Request, pid: int, session: Session = Depends(get_session)):
    get_or_404(session, Project, pid)
    imports_dir = _imports_dir(request)
    _cleanup_stale_uploads(imports_dir)

    # Parsed by hand (rather than FastAPI's Form()/File() params) so a large pasted list
    # doesn't hit Starlette's default 1 MB per-part guard, which raises a raw 400.
    form = await request.form(max_part_size=MAX_FORM_PART_BYTES)
    file = form.get("file")
    paste = str(form.get("paste") or "")

    if isinstance(file, UploadFile) and file.filename:
        oversized = "That file is larger than 50 MB; split it and import in parts."
        if file.size is not None and file.size > MAX_UPLOAD_BYTES:
            return redirect(f"/projects/{pid}/import", error=oversized)
        data = await file.read()
        if not data:
            return redirect(f"/projects/{pid}/import", error="The uploaded file is empty.")
        if len(data) > MAX_UPLOAD_BYTES:
            return redirect(f"/projects/{pid}/import", error=oversized)
        safe_name = re.sub(r"[^\w.\-]+", "_", file.filename)[-150:]
        token = secrets.token_hex(8)
        path = imports_dir / f"{token}__{safe_name}"
        path.write_bytes(data)
        return redirect(f"/projects/{pid}/import/{token}")

    lines = [line.strip() for line in paste.splitlines() if line.strip()]
    if not lines:
        return redirect(f"/projects/{pid}/import", error="Upload a file or paste at least one keyword.")
    preview = TablePreview(columns=["Keyword"], rows=[{"Keyword": line} for line in lines])
    mapping = guess_mapping(preview.columns)
    context = workspace_context(request, session, pid, "keywords")
    context.update(
        preview=preview,
        preview_rows=preview.rows[:PREVIEW_ROWS],
        mapping=mapping,
        column_options=_column_options(preview.columns, mapping),
        modes=IMPORT_MODES,
        source_label="pasted",
        raw_text="\n".join(lines),
        token=None,
        action=f"/projects/{pid}/import/paste",
        filename="pasted list",
    )
    return render(request, "import_map.html", **context)


@router.get("/projects/{pid}/import/{token}")
def import_map(request: Request, pid: int, token: str, session: Session = Depends(get_session)):
    get_or_404(session, Project, pid)
    path = _find_upload(_imports_dir(request), token)
    if path is None:
        return redirect(f"/projects/{pid}/import", error="This upload has expired; upload the file again.")
    try:
        preview = read_table(path.name, path.read_bytes())
    except PluginError as exc:
        path.unlink(missing_ok=True)
        return redirect(f"/projects/{pid}/import", error=str(exc))
    if not preview.rows:
        path.unlink(missing_ok=True)
        return redirect(f"/projects/{pid}/import", error="No rows were found in that file.")

    original_name = path.name.split("__", 1)[1]
    mapping = guess_mapping(preview.columns)
    context = workspace_context(request, session, pid, "keywords")
    context.update(
        preview=preview,
        preview_rows=preview.rows[:PREVIEW_ROWS],
        mapping=mapping,
        column_options=_column_options(preview.columns, mapping),
        modes=IMPORT_MODES,
        source_label=Path(original_name).stem[:100] or "import",
        raw_text=None,
        token=token,
        action=f"/projects/{pid}/import/{token}",
        filename=original_name,
    )
    return render(request, "import_map.html", **context)


def _run_import(
    request: Request,
    pid: int,
    session: Session,
    preview: TablePreview,
    form,
    filename_for_snapshot: str,
):
    project = get_or_404(session, Project, pid)
    if Runner.active_runs(session, pid):
        error = "A step is running in this project; try again once it's done."
        return redirect(f"/projects/{pid}/keywords", error=error)

    mapping = {col: form.get(f"target_{i}") or "ignore" for i, col in enumerate(preview.columns)}
    mode = form.get("mode") or "merge"
    if mode not in ("add", "merge", "update"):
        mode = "merge"
    source_label = (form.get("source_label") or "import").strip()[:100] or "import"

    create_snapshot(session, project.id, f"Before import «{filename_for_snapshot}»")
    result = import_rows(session, project.id, preview.rows, mapping, mode, source_label)
    session.commit()

    notice = f"Imported: {result.added} added, {result.updated} updated, {result.skipped} skipped."
    if result.errors:
        notice += " " + " ".join(result.errors[:3])
    return redirect(f"/projects/{pid}/keywords", notice=notice)


@router.post("/projects/{pid}/import/paste")
async def import_paste_confirm(request: Request, pid: int, session: Session = Depends(get_session)):
    form = await request.form(max_part_size=MAX_FORM_PART_BYTES)
    raw_text = form.get("raw_text") or ""
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return redirect(f"/projects/{pid}/import", error="Nothing to import.")
    preview = TablePreview(columns=["Keyword"], rows=[{"Keyword": line} for line in lines])
    return _run_import(request, pid, session, preview, form, "pasted list")


@router.post("/projects/{pid}/import/{token}")
async def import_confirm(request: Request, pid: int, token: str, session: Session = Depends(get_session)):
    imports_dir = _imports_dir(request)
    path = _find_upload(imports_dir, token)
    if path is None:
        return redirect(f"/projects/{pid}/import", error="This upload has expired; upload the file again.")
    form = await request.form()
    try:
        preview = read_table(path.name, path.read_bytes())
    except PluginError as exc:
        return redirect(f"/projects/{pid}/import", error=str(exc))
    original_name = path.name.split("__", 1)[1]
    response = _run_import(request, pid, session, preview, form, original_name)
    path.unlink(missing_ok=True)
    return response


def _file_response(payload: bytes, fmt: str, filename: str) -> Response:
    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    media_type = MEDIA_TYPES.get(fmt, "application/octet-stream")
    return Response(content=payload, media_type=media_type, headers={"Content-Disposition": disposition})


@router.get("/projects/{pid}/export")
def export_project(pid: int, format: str = "xlsx", scope: str = "active", session: Session = Depends(get_session)):
    project = get_or_404(session, Project, pid)
    if format not in MEDIA_TYPES:
        return redirect(f"/projects/{pid}/keywords", error=f"Unsupported export format '{format}'.")
    columns, rows = keyword_table(session, pid, scope)
    payload = write_table(columns, rows, format)
    label = "all keywords" if scope == "all" else "passing keywords"
    filename = export_filename(project.name, label, format)
    return _file_response(payload, format, filename)


@router.get("/projects/{pid}/snapshots/{sid}/export")
def export_snapshot(
    pid: int, sid: int, format: str = "xlsx", scope: str = "all", session: Session = Depends(get_session)
):
    snapshot = get_or_404(session, Snapshot, sid)
    project = get_or_404(session, Project, pid)
    if snapshot.project_id != pid:
        return redirect(f"/projects/{pid}/snapshots", error="That snapshot doesn't belong to this project.")
    if format not in MEDIA_TYPES:
        return redirect(f"/projects/{pid}/snapshots", error=f"Unsupported export format '{format}'.")
    columns, rows = snapshot_table(snapshot, scope)
    payload = write_table(columns, rows, format)
    filename = export_filename(project.name, snapshot.label, format)
    return _file_response(payload, format, filename)
