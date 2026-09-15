"""The Keywords tab: browse, filter, sort, edit and bulk-manage a project's keywords."""

from __future__ import annotations

from collections import Counter
from math import ceil
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sito.core.io import format_data_value, parse_data_value
from sito.core.runner import Runner
from sito.core.text import normalize_keyword, to_float, to_int
from sito.models import Cluster, Keyword, Project
from sito.web.deps import get_or_404, get_session, is_htmx, redirect, render
from sito.web.workspace import workspace_context

router = APIRouter()

PER_OPTIONS = (50, 100, 200, 500)
SORT_COLUMNS = {
    "keyword": Keyword.keyword,
    "volume": Keyword.volume,
    "kd": Keyword.kd,
    "cpc": Keyword.cpc,
    "source": Keyword.source,
    "created": Keyword.created_at,
}

# Bookkeeping fields a stage writes for its own use; never worth an auto-shown column
# (still filterable/exportable via the field/value filter and the export menu).
HIDDEN_DATA_KEYS = {"ai_model", "serp_at", "original", "seed"}
# Shown first, in this order, when present; the rest follow by frequency.
PREFERRED_DATA_KEYS = ("relevance", "intent", "category", "language")


def _guard_active(session: Session, pid: int):
    """Refuse mutations while a pipeline step is writing to this project."""
    if Runner.active_runs(session, pid):
        return "A step is currently running in this project; wait for it to finish."
    return None


def _get_keyword_or_404(session: Session, pid: int, kid: int) -> Keyword:
    """Like ``get_or_404``, but also 404s a keyword id that belongs to another project."""
    kw = session.get(Keyword, kid)
    if kw is None or kw.project_id != pid:
        raise HTTPException(status_code=404, detail="Not found")
    return kw


def _to_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value else default
    except ValueError:
        return default


def _sample_data_keys(session: Session, project_id: int, limit: int = 2000, top: int = 8) -> list[str]:
    """The keys most worth auto-showing as columns: preferred ones first, then by frequency."""
    sample = session.scalars(
        select(Keyword.data).where(Keyword.project_id == project_id).order_by(Keyword.id.desc()).limit(limit)
    ).all()
    counter: Counter[str] = Counter()
    for data in sample:
        counter.update(k for k in (data or {}) if k not in HIDDEN_DATA_KEYS)
    by_frequency = [key for key, _ in counter.most_common()]
    preferred = [key for key in PREFERRED_DATA_KEYS if key in counter]
    rest = [key for key in by_frequency if key not in preferred]
    return [*preferred, *rest][:top]


def _field_matches(kw: Keyword, field: str, value: str) -> bool:
    data_value = (kw.data or {}).get(field)
    if value == "-":
        return data_value in (None, "")
    return str(data_value) == value


@router.get("/projects/{pid}/keywords")
def keywords_page(request: Request, pid: int, session: Session = Depends(get_session)):
    get_or_404(session, Project, pid)
    qp = request.query_params
    q = (qp.get("q") or "").strip()
    status = qp.get("status") or "all"
    source = qp.get("source") or ""
    cluster = qp.get("cluster") or ""
    field = (qp.get("field") or "").strip()
    value = qp.get("value") or ""
    sort = qp.get("sort") or "created"
    direction = qp.get("dir") or "desc"
    per = _to_int(qp.get("per"), 100)
    per = per if per in PER_OPTIONS else 100
    page = max(1, _to_int(qp.get("page"), 1))

    conditions = [Keyword.project_id == pid]
    if q:
        conditions.append(Keyword.keyword.contains(q))
    if status == "passing":
        conditions.append(Keyword.excluded.is_(False))
    elif status in ("excluded", "retained"):
        conditions.append(Keyword.excluded.is_(True))
    if source:
        conditions.append(Keyword.source == source)
    if cluster == "none":
        conditions.append(Keyword.cluster_id.is_(None))
    elif cluster:
        conditions.append(Keyword.cluster_id == _to_int(cluster, -1))

    is_data_sort = sort.startswith("data:")
    column = SORT_COLUMNS.get(sort, Keyword.created_at)
    order_by = (column.desc() if direction == "desc" else column.asc(), Keyword.id)

    if not field and not is_data_sort:
        # The common case (no data-field filter/sort): let the database do the paging.
        total = session.scalar(select(func.count()).select_from(Keyword).where(*conditions)) or 0
        pages = max(1, ceil(total / per))
        page = min(page, pages)
        page_rows = list(
            session.scalars(select(Keyword).where(*conditions).order_by(*order_by).limit(per).offset((page - 1) * per))
        )
    else:
        # A data-field filter or sort needs Python: fetch every matching row once, then slice.
        fetch_order = (Keyword.id,) if is_data_sort else order_by
        rows = list(session.scalars(select(Keyword).where(*conditions).order_by(*fetch_order)))
        if field:
            rows = [kw for kw in rows if _field_matches(kw, field, value)]
        if is_data_sort:
            key = sort.removeprefix("data:")
            rows.sort(key=lambda kw: str((kw.data or {}).get(key) or ""), reverse=(direction == "desc"))

        total = len(rows)
        pages = max(1, ceil(total / per))
        page = min(page, pages)
        page_rows = rows[(page - 1) * per : (page - 1) * per + per]

    cluster_ids = {kw.cluster_id for kw in page_rows if kw.cluster_id}
    cluster_names = {}
    if cluster_ids:
        cluster_names = dict(session.execute(select(Cluster.id, Cluster.name).where(Cluster.id.in_(cluster_ids))).all())
    clusters = list(
        session.execute(select(Cluster.id, Cluster.name).where(Cluster.project_id == pid).order_by(Cluster.name))
    )
    sources = [
        s
        for (s,) in session.execute(
            select(Keyword.source).where(Keyword.project_id == pid).distinct().order_by(Keyword.source)
        )
    ]
    data_fields = _sample_data_keys(session, pid)

    current = {
        "q": q,
        "status": status if status != "all" else "",
        "source": source,
        "cluster": cluster,
        "field": field,
        "value": value,
        "per": str(per),
        "sort": sort,
        "dir": direction,
    }

    def qs(**overrides) -> str:
        params = {k: v for k, v in {**current, **overrides}.items() if v}
        return "?" + urlencode(params)

    context = workspace_context(request, session, pid, "keywords")
    context.update(
        keywords=page_rows,
        total=total,
        page=page,
        pages=pages,
        page_start=(page - 1) * per + 1 if total else 0,
        page_end=min(page * per, total),
        per=per,
        per_options=PER_OPTIONS,
        q=q,
        status=status,
        source=source,
        cluster=cluster,
        field=field,
        value=value,
        sort=sort,
        dir=direction,
        qs=qs,
        clusters=clusters,
        sources=sources,
        cluster_names=cluster_names,
        data_fields=data_fields,
        has_filters=bool(q or (status != "all") or source or cluster or field),
        run_blocked=bool(Runner.active_runs(session, pid)),
    )
    return render(request, "keywords.html", **context)


def _row_context(request: Request, session: Session, pid: int, kw: Keyword, error: str | None = None) -> dict:
    cluster_name = None
    if kw.cluster_id:
        cluster_name = session.scalar(select(Cluster.name).where(Cluster.id == kw.cluster_id))
    data_fields = _sample_data_keys(session, pid)
    return {
        "request": request,
        "pid": pid,
        "kw": kw,
        "cluster_name": cluster_name,
        "data_fields": data_fields,
        "error": error,
    }


def _format_data_text(data: dict) -> str:
    """Render a keyword's data as ``key: value`` lines, non-strings shown as JSON."""
    return "\n".join(f"{k}: {format_data_value(v)}" for k, v in data.items())


def _parse_data_text(text: str) -> dict:
    data = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        if key:
            data[key] = parse_data_value(val.strip())
    return data


@router.get("/projects/{pid}/keywords/{kid}/row")
def keyword_row(request: Request, pid: int, kid: int, session: Session = Depends(get_session)):
    kw = _get_keyword_or_404(session, pid, kid)
    return render(request, "_keyword_row.html", **_row_context(request, session, pid, kw))


@router.get("/projects/{pid}/keywords/{kid}/edit")
def keyword_row_edit(request: Request, pid: int, kid: int, session: Session = Depends(get_session)):
    kw = _get_keyword_or_404(session, pid, kid)
    ctx = _row_context(request, session, pid, kw)
    ctx["data_text"] = _format_data_text(kw.data or {})
    return render(request, "_keyword_row_edit.html", **ctx)


@router.post("/projects/{pid}/keywords/{kid}/edit")
def keyword_row_save(
    request: Request,
    pid: int,
    kid: int,
    keyword: str = Form(""),
    volume: str = Form(""),
    kd: str = Form(""),
    cpc: str = Form(""),
    data: str = Form(""),
    session: Session = Depends(get_session),
):
    kw = _get_keyword_or_404(session, pid, kid)
    blocked = _guard_active(session, pid)
    if blocked:
        if is_htmx(request):
            ctx = _row_context(request, session, pid, kw, error=blocked)
            return render(request, "_keyword_row.html", **ctx)
        return redirect(f"/projects/{pid}/keywords", error=blocked)

    norm = normalize_keyword(keyword)
    if not norm:
        error = "The keyword can't be empty."
    else:
        clash = session.scalar(
            select(Keyword.id).where(Keyword.project_id == pid, Keyword.keyword == norm, Keyword.id != kid)
        )
        error = f"«{norm}» is already in this project." if clash else None

    if error:
        if is_htmx(request):
            ctx = _row_context(request, session, pid, kw, error=error)
            ctx["data_text"] = data
            ctx["form"] = {"keyword": keyword, "volume": volume, "kd": kd, "cpc": cpc}
            return render(request, "_keyword_row_edit.html", **ctx)
        return redirect(f"/projects/{pid}/keywords", error=error)

    kw.keyword = norm
    kw.volume = to_int(volume)
    kw.kd = to_float(kd)
    kw.cpc = to_float(cpc)
    # Only reparse the data textarea if its text actually changed, so an edit that only
    # touches volume/kd/cpc can't accidentally reformat (and subtly retype) untouched values.
    if data.strip() != _format_data_text(kw.data or {}).strip():
        kw.data = _parse_data_text(data)
    session.commit()

    if is_htmx(request):
        return render(request, "_keyword_row.html", **_row_context(request, session, pid, kw))
    return redirect(f"/projects/{pid}/keywords", notice="Keyword updated.")


@router.post("/projects/{pid}/keywords/add")
def add_keywords(
    request: Request,
    pid: int,
    keywords: str = Form(""),
    session: Session = Depends(get_session),
):
    get_or_404(session, Project, pid)
    blocked = _guard_active(session, pid)
    if blocked:
        return redirect(f"/projects/{pid}/keywords", error=blocked)

    lines = [line.strip() for line in keywords.splitlines() if line.strip()]
    if not lines:
        return redirect(f"/projects/{pid}/keywords", error="Type at least one keyword.")

    existing = {normalize_keyword(k) for k in session.scalars(select(Keyword.keyword).where(Keyword.project_id == pid))}
    added = 0
    for line in lines:
        norm = normalize_keyword(line)
        if not norm or len(norm) > 500 or norm in existing:
            continue
        session.add(Keyword(project_id=pid, keyword=norm, source="manual"))
        existing.add(norm)
        added += 1
    session.commit()
    skipped = len(lines) - added
    notice = f"Added {added} keyword(s)."
    if skipped:
        notice += f" Skipped {skipped} already in the project."
    return redirect(f"/projects/{pid}/keywords", notice=notice)


@router.post("/projects/{pid}/keywords/bulk")
async def bulk_action(request: Request, pid: int, session: Session = Depends(get_session)):
    get_or_404(session, Project, pid)
    blocked = _guard_active(session, pid)
    if blocked:
        return redirect(f"/projects/{pid}/keywords", error=blocked)

    form = await request.form()
    action = form.get("action", "")
    ids = [int(v) for v in form.getlist("ids") if v.isdigit()]

    query = select(Keyword).where(Keyword.project_id == pid)
    if form.get("apply_all") == "1":
        # Re-apply the current filters server-side instead of trusting the posted id list.
        q = (form.get("q") or "").strip()
        status = form.get("status") or "all"
        source = form.get("source") or ""
        cluster = form.get("cluster") or ""
        field = (form.get("field") or "").strip()
        value = form.get("value") or ""
        if q:
            query = query.where(Keyword.keyword.contains(q))
        if status == "passing":
            query = query.where(Keyword.excluded.is_(False))
        elif status in ("excluded", "retained"):
            query = query.where(Keyword.excluded.is_(True))
        if source:
            query = query.where(Keyword.source == source)
        if cluster == "none":
            query = query.where(Keyword.cluster_id.is_(None))
        elif cluster:
            query = query.where(Keyword.cluster_id == _to_int(cluster, -1))
        keywords = list(session.scalars(query))
        if field:
            keywords = [kw for kw in keywords if _field_matches(kw, field, value)]
    elif ids:
        keywords = list(session.scalars(query.where(Keyword.id.in_(ids))))
    else:
        return redirect(f"/projects/{pid}/keywords", error="No keywords selected.")

    count = len(keywords)
    if action == "exclude":
        reason = (form.get("reason") or "manual").strip()[:300] or "manual"
        for kw in keywords:
            kw.excluded = True
            kw.excluded_reason = reason
        notice = f"Excluded {count} keyword(s)."
    elif action == "include":
        for kw in keywords:
            kw.excluded = False
            kw.excluded_reason = None
        notice = f"Restored {count} keyword(s) to passing."
    elif action == "delete":
        for kw in keywords:
            session.delete(kw)
        notice = f"Deleted {count} keyword(s)."
    elif action == "set_field":
        key = (form.get("field_key") or "").strip()
        if not key:
            return redirect(f"/projects/{pid}/keywords", error="Give the field a name.")
        field_value = form.get("field_value") or ""
        for kw in keywords:
            kw.data = {**(kw.data or {}), key: field_value}
        notice = f"Set '{key}' on {count} keyword(s)."
    else:
        return redirect(f"/projects/{pid}/keywords", error="Unknown bulk action.")

    session.commit()
    return redirect(f"/projects/{pid}/keywords", notice=notice)
