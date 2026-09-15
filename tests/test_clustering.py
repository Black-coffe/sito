from __future__ import annotations

import pytest
from sqlalchemy import select

from sito.core.pipeline import add_step
from sito.core.runner import Runner
from sito.core.text import domain_of
from sito.models import RUN_DONE, Cluster, Keyword, Run, SerpResult
from sito.plugins.registry import PluginRegistry
from sito.stages.clustering import SerpCluster


@pytest.fixture
def registry():
    reg = PluginRegistry()
    reg.add_stage(SerpCluster, "test")
    return reg


@pytest.fixture
def runner(session_factory, registry, config):
    return Runner(session_factory, registry, config)


def _add_cluster_step(session_factory, registry, project, **overrides):
    with session_factory() as s:
        step = add_step(s, registry, project, "serp_cluster")
        step.config = {**step.config, **overrides}
        s.commit()
        return step.id


def _add_keyword(session, project, keyword, volume):
    kw = Keyword(project_id=project.id, keyword=keyword, source="test", volume=volume)
    session.add(kw)
    session.flush()
    return kw


def _add_results(session, project, kw, urls):
    # domain is set the way SerpCollect stores it in production (domain_of(url)); clustering's
    # top_domains reporting reads that column, not the raw url.
    for position, url in enumerate(urls, start=1):
        session.add(
            SerpResult(
                project_id=project.id,
                keyword_id=kw.id,
                position=position,
                url=url,
                domain=domain_of(url),
            )
        )


def _run(session_factory, registry, runner, project, **overrides):
    step_id = _add_cluster_step(session_factory, registry, project, **overrides)
    [run_id] = runner.enqueue(project.id, [step_id], background=False)
    with session_factory() as s:
        return s.get(Run, run_id)


def _seed_chain(session_factory, project):
    """A (volume 100) overlaps B (80), B overlaps C (60), A and C don't overlap directly.
    D has no SERP data at all."""
    with session_factory() as s:
        a = _add_keyword(s, project, "dedicated server", 100)
        b = _add_keyword(s, project, "buy dedicated server", 80)
        c = _add_keyword(s, project, "rent dedicated server", 60)
        _add_keyword(s, project, "cloud hosting", 10)  # no SERP rows: excluded from clustering
        _add_results(s, project, a, ["https://a.com/1", "https://a.com/2", "https://a.com/3"])
        _add_results(s, project, b, ["https://a.com/1", "https://a.com/2", "https://b.com/9"])
        _add_results(s, project, c, ["https://b.com/9", "https://c.com/10", "https://c.com/11"])
        s.commit()


def test_soft_mode_groups_by_overlap_with_the_main_keyword_only(session_factory, registry, runner, project):
    _seed_chain(session_factory, project)
    run = _run(session_factory, registry, runner, project, min_shared=1, top_n=3)
    assert run.status == RUN_DONE
    # A-B share 2 results (>= min_shared) and cluster together under A (higher volume).
    # B-C share 1 result, but C only overlaps with B, not with A, so soft mode leaves it out.
    stats = {k: run.stats[k] for k in ("clusters", "clustered_keywords", "unclustered", "no_serp")}
    assert stats == {"clusters": 1, "clustered_keywords": 2, "unclustered": 1, "no_serp": 1}
    with session_factory() as s:
        [cluster] = s.scalars(select(Cluster)).all()
        assert cluster.main_keyword == "dedicated server"
        assert cluster.size == 2
        assert cluster.total_volume == 180
        assert cluster.data["mode"] == "soft"
        assert cluster.data["top_domains"][0] == "a.com"

        member_query = select(Keyword).where(Keyword.cluster_id == cluster.id)
        members = {kw.keyword for kw in s.scalars(member_query)}
        assert members == {"dedicated server", "buy dedicated server"}


def test_connected_mode_groups_transitively(session_factory, registry, runner, project):
    _seed_chain(session_factory, project)
    run = _run(session_factory, registry, runner, project, min_shared=1, top_n=3, mode="connected")
    assert run.status == RUN_DONE
    # A-B and B-C both meet min_shared, so all three join one component even though A and C
    # don't overlap directly.
    stats = {k: run.stats[k] for k in ("clusters", "clustered_keywords", "unclustered", "no_serp")}
    assert stats == {"clusters": 1, "clustered_keywords": 3, "unclustered": 0, "no_serp": 1}
    with session_factory() as s:
        [cluster] = s.scalars(select(Cluster)).all()
        assert cluster.main_keyword == "dedicated server"
        assert cluster.size == 3
        assert cluster.data["mode"] == "connected"


def test_singletons_as_clusters_option(session_factory, registry, runner, project):
    with session_factory() as s:
        lonely = _add_keyword(s, project, "unrelated topic", 5)
        _add_results(s, project, lonely, ["https://z.com/1"])
        s.commit()

    run = _run(session_factory, registry, runner, project, min_shared=1)
    assert run.stats["clusters"] == 0
    assert run.stats["unclustered"] == 1

    run = _run(session_factory, registry, runner, project, min_shared=1, singletons_as_clusters=True)
    assert run.stats["clusters"] == 1
    assert run.stats["clustered_keywords"] == 1
    with session_factory() as s:
        [cluster] = s.scalars(select(Cluster)).all()
        assert cluster.main_keyword == "unrelated topic"
        assert cluster.size == 1


def test_ignore_common_above_skips_generic_results_but_keeps_specific_overlap(
    session_factory, registry, runner, project
):
    with session_factory() as s:
        keywords = [_add_keyword(s, project, f"keyword {i}", 10) for i in range(150)]
        for kw in keywords:
            # A big portal page every one of the 150 keywords ranks for: too generic to link them.
            _add_results(s, project, kw, ["https://portal.com/common"])
        # Only these two also share a specific, uncommon result: they should still cluster.
        _add_results(s, project, keywords[0], ["https://specific.com/x"])
        _add_results(s, project, keywords[1], ["https://specific.com/x"])
        s.commit()

    run = _run(session_factory, registry, runner, project, min_shared=1, top_n=2)
    assert run.status == RUN_DONE
    assert run.stats["ignored_common"] == 1
    assert run.stats["clusters"] == 1
    assert run.stats["clustered_keywords"] == 2
    assert run.stats["unclustered"] == 148

    with session_factory() as s:
        [cluster] = s.scalars(select(Cluster)).all()
        member_query = select(Keyword).where(Keyword.cluster_id == cluster.id)
        members = {kw.keyword for kw in s.scalars(member_query)}
        assert members == {"keyword 0", "keyword 1"}


def test_rerun_replaces_previous_clusters(session_factory, registry, runner, project):
    _seed_chain(session_factory, project)
    _run(session_factory, registry, runner, project, min_shared=1, top_n=3)
    with session_factory() as s:
        assert len(s.scalars(select(Cluster)).all()) == 1
        a = s.scalar(select(Keyword).where(Keyword.keyword == "dedicated server"))
        assert a.cluster_id is not None

    # Tighten min_shared so the A-B pair no longer qualifies: nothing should cluster now,
    # and the stale cluster row / cluster_id from the previous run must be gone.
    run = _run(session_factory, registry, runner, project, min_shared=3, top_n=3)
    assert run.stats["clusters"] == 0
    with session_factory() as s:
        assert s.scalars(select(Cluster)).all() == []
        a = s.scalar(select(Keyword).where(Keyword.keyword == "dedicated server"))
        assert a.cluster_id is None
