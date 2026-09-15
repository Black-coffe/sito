"""Stages that add new keywords to a project."""

from __future__ import annotations

import string

from pydantic import BaseModel, Field

from sito.core.text import normalize_keyword
from sito.plugins.base import PluginError, Stage, StageKind, connection_field, textarea_field

ALPHABET_SUFFIXES = list(string.ascii_lowercase) + list(string.digits)


class ManualList(Stage):
    id = "manual_list"
    name = "Add keywords manually"
    kind = StageKind.SOURCE
    summary = "Add a hand-typed list of keywords to the project."
    docs = """
Paste keywords, one per line. Lines are added as new keywords; ones already
in the project (after normalizing case and whitespace) are skipped.
"""

    class Config(BaseModel):
        keywords: str = textarea_field("", "One keyword per line.")
        source_label: str = Field("manual", description="Recorded as the keyword's source.")

    def run(self, ctx, config: Config) -> None:
        lines = [line.strip() for line in config.keywords.splitlines() if line.strip()]
        added = ctx.add_keywords(lines, source=config.source_label)
        ctx.stat(added=added, skipped_duplicates=len(lines) - added)


class Autocomplete(Stage):
    id = "autocomplete"
    name = "Autocomplete expansion"
    kind = StageKind.SOURCE
    summary = "Expand seed keywords into autocomplete suggestions."
    docs = """
Uses a "suggest" connection (e.g. Google Autocomplete) to expand seed
keywords into what people actually type.

For each seed it queries the connection once for plain suggestions. Turn on
**Alphabet suffixes** to also query "seed a" .. "seed z" and "seed 0" ..
"seed 9" (the classic "alphabet soup" trick for surfacing more results), and
list **Question prefixes** (e.g. how, what, best) to also query "how seed".

**Depth** 2 takes the newly found suggestions and queries them once more —
this finds longer, more specific keywords but multiplies the number of
requests, so watch **Max new keywords** and the connection's own pause
setting so you stay polite to the API.
"""

    class Config(BaseModel):
        suggest: int | None = connection_field("suggest")
        use_project_keywords: bool = Field(True, description="Use the project's active keywords as seeds.")
        extra_seeds: str = textarea_field("", "Extra seed keywords, one per line.")
        alphabet_suffixes: bool = Field(False, description='Also query "seed a" .. "seed z" and "seed 0" .. "seed 9".')
        question_prefixes: list[str] = Field(
            [], description='Words to prepend to each seed, e.g. "how" queries "how seed".'
        )
        max_seeds: int = Field(200, description="At most this many seeds are used.")
        depth: int = Field(1, description="1 = suggestions of seeds. 2 = also expand those suggestions once more.")
        max_new_keywords: int = Field(5000, description="Stop once this many new keywords were added.")

    def run(self, ctx, config: Config) -> None:
        connector = ctx.connection(config.suggest, kind="suggest")
        depth = max(1, min(2, config.depth))

        seeds: list[str] = []
        seen_seeds: set[str] = set()

        def add_seed(text: str) -> None:
            norm = normalize_keyword(text)
            if norm and norm not in seen_seeds:
                seen_seeds.add(norm)
                seeds.append(norm)

        if config.use_project_keywords:
            for kw in ctx.keywords():
                add_seed(kw.keyword)
        for line in config.extra_seeds.splitlines():
            add_seed(line)
        seeds = seeds[: config.max_seeds]

        def queries_for(seed: str) -> list[str]:
            queries = [seed]
            if config.alphabet_suffixes:
                queries += [f"{seed} {suffix}" for suffix in ALPHABET_SUFFIXES]
            queries += [f"{prefix} {seed}" for prefix in config.question_prefixes]
            return queries

        known = {kw.keyword for kw in ctx.keywords(include_excluded=True)}
        done = 0
        requests_since_commit = 0
        added_total = 0

        def run_jobs(jobs: list[tuple[str, str]], total: int) -> list[str]:
            nonlocal done, requests_since_commit, added_total
            discovered: list[str] = []
            for seed, query in jobs:
                ctx.progress(done, total, f"Querying '{query}'")
                try:
                    suggestions = connector.suggest(query)
                except PluginError as exc:
                    ctx.log(f"Skipped '{query}': {exc}")
                    suggestions = []
                done += 1
                requests_since_commit += 1

                new_ones = []
                for text in suggestions:
                    norm = normalize_keyword(text)
                    if norm and norm not in known:
                        known.add(norm)
                        new_ones.append(norm)
                if new_ones:
                    added_total += ctx.add_keywords(
                        [{"keyword": text, "data": {"seed": seed}} for text in new_ones],
                        source="autocomplete",
                    )
                    discovered += new_ones

                if requests_since_commit >= 20:
                    ctx.commit()
                    requests_since_commit = 0
                if added_total >= config.max_new_keywords:
                    break
            return discovered

        first_jobs = [(seed, query) for seed in seeds for query in queries_for(seed)]
        discovered = run_jobs(first_jobs, len(first_jobs))

        if depth >= 2 and discovered and added_total < config.max_new_keywords:
            second_jobs = [(seed, seed) for seed in discovered]
            run_jobs(second_jobs, done + len(second_jobs))

        ctx.commit()
        ctx.stat(added=added_total, requests=done)
