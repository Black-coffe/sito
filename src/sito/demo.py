"""``sito demo``: a sample project with synthetic data, run through the whole pipeline offline."""

from __future__ import annotations

import random

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sito.config import AppConfig
from sito.core.pipeline import add_step
from sito.core.runner import Runner
from sito.core.text import normalize_keyword
from sito.models import Connection, Keyword, Project
from sito.plugins.registry import PluginRegistry

DEMO_CONTEXT = (
    "We rent dedicated, GPU and bare-metal servers in data centers in the USA and Germany to SaaS "
    "companies and game studios. We do not sell shared hosting, domains or website builders."
)
_SEEDS = ("dedicated server", "gpu server", "bare metal server", "vps hosting", "colocation", "shared hosting")
_MODIFIERS = (
    "buy", "rent", "cheap", "best", "managed", "price", "cost", "for gaming", "germany", "usa", "hourly",
    "with ddos protection", "windows", "linux", "what is", "how to choose", "for ai training", "vs cloud",
)  # fmt: skip
# Rows the clean step should exclude, to show what it does.
_JUNK = ("!!! dedicated server ???", "server 123456789", "xx", "Dedicated  Server", "gpu server free xxx")


def _keywords(rng: random.Random) -> list[dict]:
    rows: dict[str, dict] = {}
    for seed in _SEEDS:
        for modifier in _MODIFIERS:
            text = (
                f"{modifier} {seed}"
                if modifier in ("buy", "rent", "cheap", "best", "managed", "what is", "how to choose")
                else f"{seed} {modifier}"
            )
            rows[text] = {
                "keyword": text,
                "volume": int(rng.lognormvariate(4.6, 1.3)),
                "kd": rng.randint(2, 80),
                "cpc": round(rng.uniform(0.3, 16), 2),
            }
    for text in _JUNK:
        rows[text] = {"keyword": text, "volume": rng.randint(10, 90), "kd": None, "cpc": None}
    return list(rows.values())


def _connection(session: Session, connector_id: str, name: str) -> Connection:
    row = session.scalars(select(Connection).where(Connection.connector_id == connector_id)).first()
    if row is None:
        row = Connection(connector_id=connector_id, name=name, settings={})
        session.add(row)
        session.flush()
    return row


def create_demo(
    session_factory: sessionmaker[Session], registry: PluginRegistry, config: AppConfig, run: bool = True
) -> int:
    """Create the demo project (and demo connections) and, by default, run its pipeline."""
    rng = random.Random(42)
    with session_factory() as s:
        project = Project(
            name="Demo — dedicated servers",
            description=(
                "Synthetic sample created by the sito demo command: "
                "made-up keywords, volumes, AI answers and search results."
            ),
            context=DEMO_CONTEXT,
        )
        s.add(project)
        s.flush()
        seen: set[str] = set()
        for row in _keywords(rng):
            # Store raw text for junk rows so the clean step has work to do.
            key = normalize_keyword(row["keyword"])
            if key in seen:
                continue
            seen.add(key)
            s.add(
                Keyword(
                    project_id=project.id,
                    keyword=row["keyword"].lower().strip(),
                    source="demo",
                    volume=row["volume"],
                    kd=row["kd"],
                    cpc=row["cpc"],
                    data={},
                )
            )
        llm = _connection(s, "demo_llm", "Demo LLM (synthetic)")
        serp = _connection(s, "demo_serp", "Demo SERP (synthetic)")
        plan = [
            ("clean", {"stop_words": ["xxx", "free"]}),
            ("ai_classify", {"llm": llm.id, "categories": ["dedicated", "gpu", "bare metal", "vps", "colocation"]}),
            ("filter", {"field": "relevance", "operator": ">=", "value": "5"}),
            ("serp_collect", {"serp": serp.id}),
            ("serp_cluster", {}),
            ("ai_cluster_names", {"llm": llm.id, "ads_copy": True}),
            ("export_file", {}),
        ]
        step_ids = []
        for stage_id, overrides in plan:
            if stage_id not in registry.stages:
                continue
            step = add_step(s, registry, project, stage_id)
            step.config = {**(step.config or {}), **overrides}
            step_ids.append(step.id)
        s.commit()
        project_id = project.id
    if run and step_ids:
        Runner(session_factory, registry, config).enqueue(project_id, step_ids, background=False)
    return project_id
