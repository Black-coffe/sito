"""Snapshots: the keyword table frozen before and after every run.

They make every step reversible (restore) and exportable ("give me the list as
it was after cleaning"). Stored as gzipped JSON; the oldest are pruned.
"""

from __future__ import annotations

import gzip
import json
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from sito.models import Cluster, Keyword, SerpResult, Snapshot

PAYLOAD_VERSION = 1
KEYWORD_FIELDS = ("id", "keyword", "source", "volume", "kd", "cpc", "excluded", "excluded_reason", "cluster_id", "data")
CLUSTER_FIELDS = ("id", "name", "main_keyword", "size", "total_volume", "data")


def _row(obj: Any, fields: tuple[str, ...]) -> dict:
    return {f: getattr(obj, f) for f in fields}


def create_snapshot(session: Session, project_id: int, label: str, run_id: int | None = None) -> Snapshot:
    session.flush()
    keywords = session.scalars(select(Keyword).where(Keyword.project_id == project_id).order_by(Keyword.id)).all()
    clusters = session.scalars(select(Cluster).where(Cluster.project_id == project_id).order_by(Cluster.id)).all()
    payload = {
        "version": PAYLOAD_VERSION,
        "keywords": [_row(k, KEYWORD_FIELDS) for k in keywords],
        "clusters": [_row(c, CLUSTER_FIELDS) for c in clusters],
    }
    snap = Snapshot(
        project_id=project_id,
        run_id=run_id,
        label=label[:300],
        keyword_count=len(keywords),
        active_count=sum(1 for k in keywords if not k.excluded),
        payload=gzip.compress(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")),
    )
    session.add(snap)
    session.flush()
    return snap


def load_payload(snapshot: Snapshot) -> dict:
    return json.loads(gzip.decompress(snapshot.payload).decode("utf-8"))


def restore_snapshot(session: Session, snapshot: Snapshot) -> None:
    """Make the project's keywords and clusters exactly what the snapshot holds.

    Keywords keep their ids where possible, so SERP data collected for them survives.
    """
    payload = load_payload(snapshot)
    pid = snapshot.project_id

    session.execute(update(Keyword).where(Keyword.project_id == pid).values(cluster_id=None))
    session.execute(delete(Cluster).where(Cluster.project_id == pid))
    cluster_map: dict[int, int] = {}
    for c in payload.get("clusters", []):
        obj = Cluster(
            project_id=pid,
            name=c["name"],
            main_keyword=c.get("main_keyword"),
            size=c.get("size") or 0,
            total_volume=c.get("total_volume") or 0,
            data=c.get("data") or {},
        )
        session.add(obj)
        session.flush()
        cluster_map[c["id"]] = obj.id

    rows = payload.get("keywords", [])
    wanted = {r["id"] for r in rows}
    current = {k.id: k for k in session.scalars(select(Keyword).where(Keyword.project_id == pid))}
    for kid in [k for k in current if k not in wanted]:
        session.delete(current.pop(kid))
    session.flush()

    # Two passes so renames never collide with the (project, keyword) unique constraint.
    renamed: list[int] = []
    for r in rows:
        kw = current.get(r["id"])
        if kw is not None and kw.keyword != r["keyword"]:
            kw.keyword = f"\x00restoring-{kw.id}"
            renamed.append(kw.id)
    if renamed:
        # Results fetched for a different text do not belong to the restored keyword.
        session.execute(delete(SerpResult).where(SerpResult.keyword_id.in_(renamed)))
    session.flush()

    for r in rows:
        values = {
            "keyword": r["keyword"],
            "source": r.get("source") or "manual",
            "volume": r.get("volume"),
            "kd": r.get("kd"),
            "cpc": r.get("cpc"),
            "excluded": bool(r.get("excluded")),
            "excluded_reason": r.get("excluded_reason"),
            "cluster_id": cluster_map.get(r.get("cluster_id")) if r.get("cluster_id") else None,
            "data": r.get("data") or {},
        }
        kw = current.get(r["id"])
        if kw is None:
            kw = Keyword(project_id=pid, **values)
            if session.get(Keyword, r["id"]) is None:
                kw.id = r["id"]
            session.add(kw)
        else:
            for key, value in values.items():
                setattr(kw, key, value)
    session.flush()

    # SERP rows are not part of snapshots. Where a restored keyword has none (they were
    # deleted with it), drop the "collected" markers so Collect SERP fetches it again.
    with_serp = set(session.scalars(select(SerpResult.keyword_id).where(SerpResult.project_id == pid).distinct()))
    for kw in session.scalars(select(Keyword).where(Keyword.project_id == pid)):
        data = kw.data or {}
        if "serp_at" in data and kw.id not in with_serp:
            kw.data = {k: v for k, v in data.items() if k not in ("serp_at", "serp_results")}
    session.flush()


def prune_snapshots(session: Session, project_id: int, keep: int) -> int:
    total = session.scalar(select(func.count()).select_from(Snapshot).where(Snapshot.project_id == project_id)) or 0
    if total <= keep:
        return 0
    old_ids = session.scalars(
        select(Snapshot.id).where(Snapshot.project_id == project_id).order_by(Snapshot.id).limit(total - keep)
    ).all()
    session.execute(delete(Snapshot).where(Snapshot.id.in_(old_ids)))
    return len(old_ids)
