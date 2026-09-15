from __future__ import annotations

import pytest
from sqlalchemy import select

from sito.core.pipeline import add_step
from sito.core.runner import Runner
from sito.models import Keyword, Run, Step
from sito.plugins.registry import PluginRegistry
from sito.stages import transform


@pytest.fixture
def registry():
    reg = PluginRegistry()
    reg.register_module(transform, "test")
    return reg


@pytest.fixture
def runner(session_factory, registry, config):
    return Runner(session_factory, registry, config)


def _step(session_factory, registry, project, stage_id, **overrides):
    with session_factory() as s:
        step = add_step(s, registry, project, stage_id)
        if overrides:
            step.config = {**step.config, **overrides}
        s.commit()
        return step.id


def _run(runner, project, step_id):
    [run_id] = runner.enqueue(project.id, [step_id], background=False)
    return run_id


def _keywords_by_text(session_factory) -> dict[str, Keyword]:
    with session_factory() as s:
        return {k.keyword: k for k in s.scalars(select(Keyword)).all()}


# --- Clean -----------------------------------------------------------------------------------


def test_clean_normalizes_and_renames(session_factory, registry, runner, project):
    with session_factory() as s:
        s.add(Keyword(project_id=project.id, keyword="Buy-Server!!", source="manual"))
        s.commit()

    step_id = _step(session_factory, registry, project, "clean")
    run_id = _run(runner, project, step_id)

    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.status == "done"
        assert run.stats["renamed"] == 1
        kw = s.scalars(select(Keyword)).one()
        assert kw.keyword == "buy-server"
        assert kw.data["original"] == "Buy-Server!!"


def test_clean_excludes_duplicate_after_normalizing(session_factory, registry, runner, project):
    with session_factory() as s:
        s.add(Keyword(project_id=project.id, keyword="buy server", source="manual"))
        s.add(Keyword(project_id=project.id, keyword="Buy  Server!", source="manual"))
        s.commit()

    step_id = _step(session_factory, registry, project, "clean")
    run_id = _run(runner, project, step_id)

    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.stats["reasons"]["duplicate"] == 1
    kws = _keywords_by_text(session_factory)
    assert kws["buy server"].excluded is False
    excluded = [k for k in kws.values() if k.excluded]
    assert len(excluded) == 1
    assert excluded[0].excluded_reason == "duplicate of 'buy server'"


def test_clean_excludes_by_structural_rules(session_factory, registry, runner, project):
    long_keyword = "x" * 101
    with session_factory() as s:
        s.add(Keyword(project_id=project.id, keyword="ab", source="manual"))
        s.add(Keyword(project_id=project.id, keyword=long_keyword, source="manual"))
        s.add(Keyword(project_id=project.id, keyword="one two three four five six seven", source="manual"))
        s.add(Keyword(project_id=project.id, keyword="12345", source="manual"))
        s.add(Keyword(project_id=project.id, keyword="12345 ab", source="manual"))
        s.commit()

    step_id = _step(session_factory, registry, project, "clean", max_words=6)
    run_id = _run(runner, project, step_id)

    with session_factory() as s:
        run = s.get(Run, run_id)
        reasons = run.stats["reasons"]
        assert reasons["too_short"] == 1
        assert reasons["too_long"] == 1
        assert reasons["too_many_words"] == 1
        assert reasons["digits_only"] == 1
        assert reasons["digits_percent"] == 1
    kws = _keywords_by_text(session_factory)
    assert kws["ab"].excluded_reason == "too short (<3 chars)"
    assert kws[long_keyword].excluded_reason == "too long (>100 chars)"
    assert kws["one two three four five six seven"].excluded_reason == "too many words (>6)"
    assert kws["12345"].excluded_reason == "digits only"
    assert kws["12345 ab"].excluded_reason == "digits 62% (>60%)"


def test_clean_stop_word_substring_match_by_default(session_factory, registry, runner, project):
    with session_factory() as s:
        s.add(Keyword(project_id=project.id, keyword="best category ever", source="manual"))
        s.commit()

    step_id = _step(session_factory, registry, project, "clean", stop_words=["cat"])
    _run(runner, project, step_id)

    kw = _keywords_by_text(session_factory)["best category ever"]
    assert kw.excluded is True
    assert kw.excluded_reason == "stop word 'cat'"


def test_clean_stop_word_whole_words_only(session_factory, registry, runner, project):
    with session_factory() as s:
        s.add(Keyword(project_id=project.id, keyword="best category ever", source="manual"))
        s.commit()

    step_id = _step(session_factory, registry, project, "clean", stop_words=["cat"], whole_words_only=True)
    _run(runner, project, step_id)

    kw = _keywords_by_text(session_factory)["best category ever"]
    assert kw.excluded is False


# --- Filter ----------------------------------------------------------------------------------


def test_filter_by_volume(session_factory, registry, runner, project):
    with session_factory() as s:
        s.add(Keyword(project_id=project.id, keyword="low", source="m", volume=10))
        s.add(Keyword(project_id=project.id, keyword="high", source="m", volume=10000))
        s.add(Keyword(project_id=project.id, keyword="none", source="m", volume=None))
        s.add(Keyword(project_id=project.id, keyword="ok", source="m", volume=500))
        s.commit()

    step_id = _step(session_factory, registry, project, "filter", min_volume=100, max_volume=5000)
    run_id = _run(runner, project, step_id)

    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.stats["excluded"] == 2
    kws = _keywords_by_text(session_factory)
    assert kws["low"].excluded_reason == "filter: volume < 100"
    assert kws["high"].excluded_reason == "filter: volume > 5000"
    assert kws["none"].excluded is False
    assert kws["ok"].excluded is False


def test_filter_by_kd_and_cpc(session_factory, registry, runner, project):
    with session_factory() as s:
        s.add(Keyword(project_id=project.id, keyword="hard", source="m", kd=80.0))
        s.add(Keyword(project_id=project.id, keyword="cheap", source="m", cpc=0.1))
        s.add(Keyword(project_id=project.id, keyword="fine", source="m", kd=10.0, cpc=5.0))
        s.commit()

    step_id = _step(session_factory, registry, project, "filter", max_kd=50, min_cpc=1)
    _run(runner, project, step_id)

    kws = _keywords_by_text(session_factory)
    assert kws["hard"].excluded_reason == "filter: kd > 50.0"
    assert kws["cheap"].excluded_reason == "filter: cpc < 1.0"
    assert kws["fine"].excluded is False


def test_filter_by_data_field_numeric(session_factory, registry, runner, project):
    with session_factory() as s:
        s.add(Keyword(project_id=project.id, keyword="a", source="m", data={"relevance": 8}))
        s.add(Keyword(project_id=project.id, keyword="b", source="m", data={"relevance": 3}))
        s.add(Keyword(project_id=project.id, keyword="c", source="m", data={}))
        s.commit()

    step_id = _step(session_factory, registry, project, "filter", field="relevance", operator=">=", value="6")
    _run(runner, project, step_id)

    kws = _keywords_by_text(session_factory)
    assert kws["a"].excluded is False
    assert kws["b"].excluded_reason == "filter: relevance >= 6 not met"
    assert kws["c"].excluded_reason == "filter: relevance >= 6 not met"


def test_filter_by_data_field_contains(session_factory, registry, runner, project):
    with session_factory() as s:
        s.add(Keyword(project_id=project.id, keyword="a", source="m", data={"category": "cloud hosting"}))
        s.add(Keyword(project_id=project.id, keyword="b", source="m", data={"category": "networking"}))
        s.commit()

    step_id = _step(
        session_factory,
        registry,
        project,
        "filter",
        field="category",
        operator="contains",
        value="cloud",
    )
    _run(runner, project, step_id)

    kws = _keywords_by_text(session_factory)
    assert kws["a"].excluded is False
    assert kws["b"].excluded_reason == "filter: category contains cloud not met"


def test_filter_by_data_field_is_empty(session_factory, registry, runner, project):
    with session_factory() as s:
        s.add(Keyword(project_id=project.id, keyword="a", source="m", data={}))
        s.add(Keyword(project_id=project.id, keyword="b", source="m", data={"note": "x"}))
        s.commit()

    step_id = _step(session_factory, registry, project, "filter", field="note", operator="is empty")
    _run(runner, project, step_id)

    kws = _keywords_by_text(session_factory)
    assert kws["a"].excluded is False
    assert kws["b"].excluded_reason == "filter: note is empty not met"


def test_filter_must_contain_and_must_not_contain(session_factory, registry, runner, project):
    with session_factory() as s:
        s.add(Keyword(project_id=project.id, keyword="buy vpn cheap", source="m"))
        s.add(Keyword(project_id=project.id, keyword="vpn review", source="m"))
        s.add(Keyword(project_id=project.id, keyword="best firewall", source="m"))
        s.commit()

    step_id = _step(
        session_factory,
        registry,
        project,
        "filter",
        must_contain=["vpn"],
        must_not_contain=["cheap"],
    )
    _run(runner, project, step_id)

    kws = _keywords_by_text(session_factory)
    assert kws["buy vpn cheap"].excluded_reason == "filter: contains 'cheap'"
    assert kws["vpn review"].excluded is False
    assert kws["best firewall"].excluded_reason.startswith("filter: doesn't contain")


def test_filter_reset_previous_reincludes_before_reapplying(session_factory, registry, runner, project):
    with session_factory() as s:
        s.add(Keyword(project_id=project.id, keyword="low", source="m", volume=10))
        s.add(Keyword(project_id=project.id, keyword="high", source="m", volume=200))
        s.commit()

    step_id = _step(session_factory, registry, project, "filter", min_volume=100)
    _run(runner, project, step_id)
    assert _keywords_by_text(session_factory)["low"].excluded is True

    with session_factory() as s:
        step = s.get(Step, step_id)
        step.config = {**step.config, "min_volume": 5}
        s.commit()
    run_id = _run(runner, project, step_id)

    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.stats["reincluded"] == 1
    assert _keywords_by_text(session_factory)["low"].excluded is False


def test_filter_reset_previous_false_keeps_old_exclusion(session_factory, registry, runner, project):
    with session_factory() as s:
        s.add(Keyword(project_id=project.id, keyword="low", source="m", volume=10))
        s.commit()

    step_id = _step(session_factory, registry, project, "filter", min_volume=100)
    _run(runner, project, step_id)

    with session_factory() as s:
        step = s.get(Step, step_id)
        step.config = {**step.config, "min_volume": 5, "reset_previous": False}
        s.commit()
    _run(runner, project, step_id)

    assert _keywords_by_text(session_factory)["low"].excluded is True
