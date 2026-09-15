from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel, SecretStr
from sqlalchemy import select

from sito.core.forms import describe_model, dump_model, parse_form, resolve_env_refs
from sito.core.pipeline import add_step, step_issues
from sito.core.runner import RunConflict, Runner
from sito.core.snapshots import restore_snapshot
from sito.models import RUN_CANCELLED, RUN_DONE, RUN_FAILED, Keyword, Run, Snapshot
from sito.plugins.base import (
    PluginError,
    Stage,
    StageKind,
    connection_field,
    parse_json_payload,
)
from sito.plugins.registry import PluginRegistry, load_registry


class AddWords(Stage):
    id = "t_add"
    name = "Add words"
    kind = StageKind.SOURCE

    class Config(BaseModel):
        words: list[str] = ["Buy Server", "buy  server", "rent vps"]

    def run(self, ctx, config):
        ctx.stat(added=ctx.add_keywords(config.words, source="test"))


class ExcludeAll(Stage):
    id = "t_exclude"
    name = "Exclude all"

    def run(self, ctx, config):
        for kw in ctx.keywords():
            ctx.exclude(kw, "test")


class Boom(Stage):
    id = "t_boom"
    name = "Boom"

    def run(self, ctx, config):
        ctx.add_keywords(["should be rolled back"], source="boom")
        raise PluginError("broken on purpose")


class NeedsLLM(Stage):
    id = "t_llm"
    name = "Needs LLM"

    class Config(BaseModel):
        llm: int | None = connection_field("llm")

    def run(self, ctx, config):  # pragma: no cover - never runnable in tests
        pass


@pytest.fixture
def registry():
    reg = PluginRegistry()
    for cls in (AddWords, ExcludeAll, Boom, NeedsLLM):
        reg.add_stage(cls, "test")
    return reg


@pytest.fixture
def runner(session_factory, registry, config):
    return Runner(session_factory, registry, config)


def _steps(session_factory, registry, project, *stage_ids):
    with session_factory() as s:
        steps = [add_step(s, registry, project, sid) for sid in stage_ids]
        s.commit()
        return [st.id for st in steps]


def test_run_adds_and_dedupes_keywords(session_factory, registry, runner, project):
    [step_id] = _steps(session_factory, registry, project, "t_add")
    [run_id] = runner.enqueue(project.id, [step_id], background=False)
    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.status == RUN_DONE
        assert run.stats["added"] == 2
        words = s.scalars(select(Keyword.keyword).order_by(Keyword.id)).all()
        assert words == ["buy server", "rent vps"]
        # one snapshot before, one after
        assert s.scalar(select(Snapshot.id).where(Snapshot.id == run.snapshot_id)) is not None
        assert len(s.scalars(select(Snapshot)).all()) == 2


def test_failure_rolls_back_and_skips_following_steps(session_factory, registry, runner, project):
    step_ids = _steps(session_factory, registry, project, "t_boom", "t_add")
    run_ids = runner.enqueue(project.id, step_ids, background=False)
    with session_factory() as s:
        first, second = (s.get(Run, rid) for rid in run_ids)
        assert first.status == RUN_FAILED
        assert "broken on purpose" in first.error
        assert second.status == RUN_CANCELLED
        assert s.scalars(select(Keyword)).all() == []


def test_restore_snapshot_undoes_a_step(session_factory, registry, runner, project):
    add_id, exclude_id = _steps(session_factory, registry, project, "t_add", "t_exclude")
    runner.enqueue(project.id, [add_id, exclude_id], background=False)
    with session_factory() as s:
        assert all(k.excluded for k in s.scalars(select(Keyword)))
        before_exclude = s.scalars(select(Snapshot).where(Snapshot.label.like("Before «Exclude all»"))).one()
        restore_snapshot(s, before_exclude)
        s.commit()
        kws = s.scalars(select(Keyword).order_by(Keyword.id)).all()
        assert [k.keyword for k in kws] == ["buy server", "rent vps"]
        assert not any(k.excluded for k in kws)


def test_step_requires_connection(session_factory, registry, runner, project):
    [step_id] = _steps(session_factory, registry, project, "t_llm")
    with session_factory() as s:
        from sito.models import Step

        assert step_issues(s, registry, s.get(Step, step_id))
    with pytest.raises(PluginError, match="connection"):
        runner.enqueue(project.id, [step_id], background=False)


def test_one_active_run_per_project(session_factory, registry, runner, project):
    [step_id] = _steps(session_factory, registry, project, "t_add")
    with session_factory() as s:
        s.add(Run(project_id=project.id, step_id=step_id, stage_id="t_add", status="running"))
        s.commit()
    with pytest.raises(RunConflict):
        runner.enqueue(project.id, [step_id], background=False)


class _Settings(BaseModel):
    api_key: SecretStr = SecretStr("")
    model: Literal["small", "large"] = "small"
    stop_words: list[str] = []
    strict: bool = False
    batch: int = 50


def test_forms_roundtrip_keeps_saved_secret():
    existing = {"api_key": "sk-secret-123456"}
    fields = {f.name: f for f in describe_model(_Settings, existing)}
    assert fields["api_key"].widget == "password"
    assert fields["api_key"].value == ""  # secrets never go back to the browser
    assert fields["api_key"].secret_hint.endswith("3456")
    assert fields["model"].options == [("small", "small"), ("large", "large")]

    parsed = parse_form(
        _Settings,
        {"api_key": "", "model": "large", "stop_words": "a\n b \n\n", "batch": "10"},
        existing=existing,
    )
    data = dump_model(parsed)
    assert data == {
        "api_key": "sk-secret-123456",
        "model": "large",
        "stop_words": ["a", "b"],
        "strict": False,
        "batch": 10,
    }


def test_env_references(monkeypatch):
    monkeypatch.setenv("MY_KEY", "from-env")
    assert resolve_env_refs({"api_key": "env:MY_KEY", "other": "x"}) == {"api_key": "from-env", "other": "x"}


def test_local_plugin_file_is_discovered(tmp_path):
    (tmp_path / "my_stage.py").write_text(
        "from sito.plugins import Stage\n"
        "class Hello(Stage):\n"
        "    id = 'hello'\n"
        "    name = 'Hello'\n"
        "    def run(self, ctx, config):\n"
        "        pass\n",
        encoding="utf-8",
    )
    (tmp_path / "broken.py").write_text("raise RuntimeError('nope')\n", encoding="utf-8")
    reg = load_registry(tmp_path, builtin=False)
    assert "hello" in reg.stages
    assert any("broken.py" in e for e in reg.errors)


def test_parse_json_payload_tolerates_fences_and_prose():
    assert parse_json_payload('```json\n[{"a": 1}]\n```') == [{"a": 1}]
    assert parse_json_payload('Sure! {"results": []} Hope it helps') == {"results": []}
    with pytest.raises(PluginError):
        parse_json_payload("no json here")
