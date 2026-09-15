"""End-to-end: the demo project runs every built-in stage offline with the demo connectors."""

from __future__ import annotations

from sqlalchemy import func, select

from sito.demo import create_demo
from sito.models import RUN_DONE, Cluster, Keyword, Run, SerpResult
from sito.plugins.registry import load_registry


def test_demo_pipeline_runs_end_to_end(config, session_factory):
    registry = load_registry(None)
    assert not registry.errors
    pid = create_demo(session_factory, registry, config)

    with session_factory() as s:
        runs = s.scalars(select(Run).where(Run.project_id == pid).order_by(Run.id)).all()
        assert [r.stage_id for r in runs] == [
            "clean", "ai_classify", "filter", "serp_collect", "serp_cluster", "ai_cluster_names", "export_file",
        ]  # fmt: skip
        assert all(r.status == RUN_DONE for r in runs), [(r.stage_id, r.status, r.error) for r in runs]

        keywords = s.scalars(select(Keyword).where(Keyword.project_id == pid)).all()
        retained = [k for k in keywords if k.excluded]
        assert any(k.excluded_reason for k in retained)  # clean and filter took something out
        passing = [k for k in keywords if not k.excluded]
        assert passing and all("relevance" in k.data for k in passing)
        assert s.scalar(select(func.count()).select_from(SerpResult).where(SerpResult.project_id == pid))
        clusters = s.scalars(select(Cluster).where(Cluster.project_id == pid)).all()
        assert clusters and all("ai_name" in c.data for c in clusters)

        export = runs[-1]
        assert (config.data_dir / "exports" / f"project-{pid}" / export.stats["file"]).is_file()
