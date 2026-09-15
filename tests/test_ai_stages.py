from __future__ import annotations

import pytest
from pydantic import BaseModel
from sqlalchemy import select

import sito.stages.ai as ai_stages
from sito.core.pipeline import add_step
from sito.core.runner import Runner
from sito.models import RUN_DONE, Cluster, Connection, Keyword, Run
from sito.plugins.base import LLMConnector
from sito.plugins.registry import PluginRegistry


class FakeLLM(LLMConnector):
    """A canned connector: answers based on what it is actually asked, no network."""

    id = "fake_llm"
    name = "Fake LLM"

    class Settings(BaseModel):
        model: str = "fake-model"

    def __init__(self, settings):
        super().__init__(settings)
        self.usage = {"requests": 0, "input_tokens": 0, "output_tokens": 0}

    def complete_json(self, system, prompt):
        self.usage["requests"] += 1
        if "Classify these keywords" in prompt:
            if "garbage query" in prompt:
                return "this is not a dict or a list of dicts"
            return {"results": self._classify(prompt)}
        if "Name these keyword clusters" in prompt:
            cluster_lines = [line for line in prompt.splitlines() if line.startswith("Cluster ")]
            if len(cluster_lines) == 1 and "'c2'" in cluster_lines[0]:
                # Only garble a batch that names "c2" alone, not one bundled with others.
                return "this is not a dict or a list of dicts"
            return {"results": self._name_clusters(prompt)}
        raise AssertionError(f"unexpected prompt: {prompt}")

    @staticmethod
    def _classify(prompt: str) -> list[dict]:
        results = []
        for line in prompt.splitlines():
            if not line.startswith("- "):
                continue
            keyword = line[2:].split(" (volume:")[0]
            if keyword == "cheap hosting":
                continue  # simulate the model dropping this one from its answer
            if keyword == "buy server":
                results.append({"keyword": keyword, "relevance": 15, "intent": "COMMERCIAL", "language": "EN"})
            else:
                results.append(
                    {
                        "keyword": keyword,
                        "relevance": 4,
                        "intent": "not-a-real-intent",
                        "language": "ru",
                    }
                )
        return results

    @staticmethod
    def _name_clusters(prompt: str) -> list[dict]:
        results = []
        for line in prompt.splitlines():
            if not line.startswith("Cluster "):
                continue
            cluster_id = int(line.split()[1])
            results.append(
                {
                    "cluster_id": cluster_id,
                    "name": f"Cluster {cluster_id} name",
                    "intent": "commercial",
                    "page_title": "A great landing page",
                    "content_type": "LANDING",
                    "ads": {
                        "headline_1": "A" * 40,
                        "headline_2": "Short",
                        "description_1": "B" * 100,
                        "description_2": "Short desc",
                    },
                }
            )
        return results


@pytest.fixture
def registry():
    reg = PluginRegistry()
    reg.register_module(ai_stages, "test")
    reg.add_connector(FakeLLM, "test")
    return reg


@pytest.fixture
def runner(session_factory, registry, config):
    return Runner(session_factory, registry, config)


@pytest.fixture
def connection(session_factory):
    with session_factory() as s:
        conn = Connection(connector_id="fake_llm", name="Fake", settings={})
        s.add(conn)
        s.commit()
        return conn.id


def test_ai_classify_writes_normalises_and_is_resumable(session_factory, registry, runner, project, connection):
    with session_factory() as s:
        s.add_all(
            [
                Keyword(project_id=project.id, keyword="buy server", volume=100),
                Keyword(project_id=project.id, keyword="rent vps", volume=50),
                Keyword(project_id=project.id, keyword="cheap hosting", volume=10),
            ]
        )
        step = add_step(s, registry, project, "ai_classify")  # auto-fills "llm" connection field
        s.commit()
        step_id = step.id

    [run_id] = runner.enqueue(project.id, [step_id], background=False)
    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.status == RUN_DONE
        kws = {k.keyword: k for k in s.scalars(select(Keyword))}
        assert kws["buy server"].data["relevance"] == 10  # clamped from 15
        assert kws["buy server"].data["intent"] == "commercial"  # normalised to lower case
        assert kws["buy server"].data["language"] == "en"
        assert kws["buy server"].data["ai_model"] == "fake-model"
        assert kws["rent vps"].data["relevance"] == 4
        assert kws["rent vps"].data["intent"] is None  # not one of the allowed values
        assert kws["rent vps"].data["ai_model"] == "fake-model"
        assert "ai_model" not in kws["cheap hosting"].data  # missing from the model's answer
        assert run.stats["classified"] == 2
        assert run.stats["missing"] == 1
        assert run.stats["failed_batches"] == 0
        assert run.stats["requests"] == 1

    # Rerun: only_unclassified=True means the two already-done keywords are never resent.
    [run_id_2] = runner.enqueue(project.id, [step_id], background=False)
    with session_factory() as s:
        run2 = s.get(Run, run_id_2)
        assert run2.status == RUN_DONE
        assert run2.stats["classified"] == 0  # the model still skips "cheap hosting"
        assert run2.stats["missing"] == 1
        kws = {k.keyword: k for k in s.scalars(select(Keyword))}
        assert kws["buy server"].data["ai_model"] == "fake-model"  # untouched


def test_ai_classify_continues_after_one_garbled_batch(session_factory, registry, runner, project, connection):
    with session_factory() as s:
        s.add_all(
            [
                Keyword(project_id=project.id, keyword="buy server", volume=100),
                Keyword(project_id=project.id, keyword="garbage query", volume=1),
            ]
        )
        step = add_step(s, registry, project, "ai_classify")
        step.config = {**step.config, "batch_size": 1}  # force two separate batches
        s.commit()
        step_id = step.id

    [run_id] = runner.enqueue(project.id, [step_id], background=False)
    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.status == RUN_DONE  # one bad batch does not sink the whole run
        assert run.stats["failed_batches"] == 1
        assert run.stats["classified"] == 1
        kws = {k.keyword: k for k in s.scalars(select(Keyword))}
        assert kws["buy server"].data["ai_model"] == "fake-model"
        assert "ai_model" not in kws["garbage query"].data


@pytest.fixture
def clustered_keywords(session_factory, project):
    with session_factory() as s:
        c1 = Cluster(project_id=project.id, name="c1", size=2, total_volume=150)
        c2 = Cluster(project_id=project.id, name="c2", size=1, total_volume=10)
        s.add_all([c1, c2])
        s.flush()
        s.add_all(
            [
                Keyword(project_id=project.id, keyword="buy server", volume=100, cluster_id=c1.id),
                Keyword(project_id=project.id, keyword="rent server", volume=50, cluster_id=c1.id),
                Keyword(project_id=project.id, keyword="cheap hosting", volume=10, cluster_id=c2.id),
            ]
        )
        s.commit()
        return c1.id, c2.id


def test_ai_cluster_names_writes_names_trims_ads_and_is_idempotent(
    session_factory, registry, runner, project, connection, clustered_keywords
):
    c1_id, c2_id = clustered_keywords
    with session_factory() as s:
        step = add_step(s, registry, project, "ai_cluster_names")
        step.config = {**step.config, "ads_copy": True}
        s.commit()
        step_id = step.id

    [run_id] = runner.enqueue(project.id, [step_id], background=False)
    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.status == RUN_DONE
        cluster1 = s.get(Cluster, c1_id)
        assert cluster1.name == f"Cluster {c1_id} name"
        assert cluster1.data["original_name"] == "c1"
        assert cluster1.data["intent"] == "commercial"
        assert cluster1.data["content_type"] == "landing"  # normalised to lower case
        assert len(cluster1.data["ads"]["headline_1"]) <= 30
        assert len(cluster1.data["ads"]["headline_2"]) <= 30
        assert len(cluster1.data["ads"]["description_1"]) <= 90
        assert cluster1.data["ads"]["headline_2"] == "Short"  # short enough, untouched
        assert run.stats["named"] == 2
        assert run.stats["trimmed"] > 0

    # Rerun: only_unnamed=True by default -> nothing left to (re)name.
    [run_id_2] = runner.enqueue(project.id, [step_id], background=False)
    with session_factory() as s:
        run2 = s.get(Run, run_id_2)
        assert run2.status == RUN_DONE
        assert run2.stats["named"] == 0
        cluster1 = s.get(Cluster, c1_id)
        assert cluster1.name == f"Cluster {c1_id} name"  # unchanged


def test_ai_cluster_names_continues_after_one_garbled_batch(
    session_factory, registry, runner, project, connection, clustered_keywords
):
    c1_id, _c2_id = clustered_keywords
    with session_factory() as s:
        step = add_step(s, registry, project, "ai_cluster_names")
        step.config = {**step.config, "clusters_per_request": 1}  # force one cluster per batch
        s.commit()
        step_id = step.id

    [run_id] = runner.enqueue(project.id, [step_id], background=False)
    with session_factory() as s:
        run = s.get(Run, run_id)
        assert run.status == RUN_DONE  # the "c2" batch is garbled, "c1" still gets named
        assert run.stats["failed_batches"] == 1
        assert run.stats["named"] == 1
        cluster1 = s.get(Cluster, c1_id)
        assert cluster1.name == f"Cluster {c1_id} name"
