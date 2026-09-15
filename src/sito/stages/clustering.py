"""Group keywords whose Google top results overlap."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from itertools import combinations
from typing import ClassVar, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from sito.core.context import StageContext
from sito.models import Cluster, Keyword, SerpResult
from sito.plugins.base import Stage, StageKind


class SerpClusterConfig(BaseModel):
    top_n: int = 10
    compare: Literal["url", "domain"] = "url"
    mode: Literal["soft", "connected"] = "soft"
    min_shared: int = 3
    singletons_as_clusters: bool = False
    split_above: int = 30
    ignore_common_above: int = Field(
        default=100,
        description=(
            "Results shared by more keywords than this are too generic to link them"
            " (typical for big portals, e.g. wikipedia.org). 0 = never ignore."
        ),
    )


class SerpCluster(Stage):
    id: ClassVar[str] = "serp_cluster"
    name: ClassVar[str] = "Cluster by SERP overlap"
    kind: ClassVar[StageKind] = StageKind.GROUP
    summary: ClassVar[str] = "Group keywords whose Google top results share URLs or domains."
    docs: ClassVar[str] = """
Two keywords whose top-N Google results overlap by at least `min_shared`
results are considered the same topic. Needs a "Collect SERP" step to have
run first; keywords without SERP data are left out and reported separately.

- **soft** (recommended for most sites): keywords are visited by volume, each
  unassigned one becomes a cluster's main keyword and pulls in every other
  keyword that shares enough results with *it* — fast and stable, but two
  keywords in the same cluster may not directly overlap with each other.
- **connected**: keywords are grouped by transitive overlap (if A overlaps B
  and B overlaps C, all three cluster together) — tighter topics, but a few
  loosely related keywords can chain into one large cluster. `split_above`
  re-clusters (in soft mode) any component bigger than that, to contain it.
- `min_shared` of 3–4 (out of a `top_n` of 10) is a good default: 1–2 shared
  results is often coincidence, 5+ only catches near-duplicate queries.
- **singletons as clusters**: also creates a one-keyword cluster for keywords
  that didn't match anyone, instead of leaving them unclustered.
- **ignore common results above**: a result shared by more keywords than this
  (e.g. a Wikipedia page ranking for hundreds of queries) is too generic to
  link them and is skipped when comparing overlap — this also keeps the stage
  fast on such results, which would otherwise cost O(n²) pair comparisons.
"""
    Config: ClassVar[type[BaseModel]] = SerpClusterConfig

    def run(self, ctx: StageContext, config: SerpClusterConfig) -> None:
        keywords = ctx.keywords()
        serp_query = select(SerpResult).where(SerpResult.project_id == ctx.project_id)
        rows = list(ctx.session.scalars(serp_query))
        by_keyword: dict[int, list[SerpResult]] = defaultdict(list)
        for row in rows:
            by_keyword[row.keyword_id].append(row)

        candidates = [kw for kw in keywords if kw.id in by_keyword]
        no_serp = len(keywords) - len(candidates)
        ctx.log(f"{len(candidates)} of {len(keywords)} keywords have SERP data; {no_serp} skipped.")
        by_id = {kw.id: kw for kw in candidates}

        shared, ignored_common = _shared_counts(ctx, by_id, by_keyword, config)
        if ignored_common:
            ctx.log(
                f"Ignored {ignored_common} result(s) shared by more than "
                f"{config.ignore_common_above} keywords (too generic to link them)."
            )

        for kw in ctx.keywords(include_excluded=True):
            kw.cluster_id = None
        old_clusters = select(Cluster).where(Cluster.project_id == ctx.project_id)
        for cluster in ctx.session.scalars(old_clusters):
            ctx.session.delete(cluster)
        ctx.session.flush()

        if config.mode == "connected":
            created, clustered = self._connected(ctx, config, by_id, by_keyword, shared)
        else:
            created, clustered = self._soft(ctx, config, by_id, by_keyword, shared)

        ctx.stat(
            clusters=created,
            clustered_keywords=clustered,
            unclustered=len(candidates) - clustered,
            no_serp=no_serp,
            ignored_common=ignored_common,
        )

    def _soft(
        self,
        ctx: StageContext,
        config: SerpClusterConfig,
        by_id: dict[int, Keyword],
        by_keyword: dict[int, list[SerpResult]],
        shared: dict[tuple[int, int], int],
    ) -> tuple[int, int]:
        ordered = sorted(by_id.values(), key=lambda kw: (-(kw.volume or 0), kw.keyword))
        assigned: set[int] = set()
        created = clustered = 0
        total = len(ordered)
        for index, main in enumerate(ordered, start=1):
            if index % 50 == 0:
                ctx.progress(index, total, "Clustering keywords")
            if main.id in assigned:
                continue
            members = [main.id]
            assigned.add(main.id)
            for other in ordered:
                if other.id in assigned:
                    continue
                if _shared(shared, main.id, other.id) >= config.min_shared:
                    members.append(other.id)
                    assigned.add(other.id)
            if len(members) == 1 and not config.singletons_as_clusters:
                continue
            if self._make_cluster(ctx, by_id, by_keyword, members, main_id=main.id, mode="soft"):
                created += 1
                clustered += len(members)
        return created, clustered

    def _connected(
        self,
        ctx: StageContext,
        config: SerpClusterConfig,
        by_id: dict[int, Keyword],
        by_keyword: dict[int, list[SerpResult]],
        shared: dict[tuple[int, int], int],
    ) -> tuple[int, int]:
        adjacency: dict[int, set[int]] = defaultdict(set)
        for (a, b), count in shared.items():
            if count >= config.min_shared:
                adjacency[a].add(b)
                adjacency[b].add(a)

        visited: set[int] = set()
        created = clustered = 0
        total = len(by_id)
        for index, start_id in enumerate(by_id, start=1):
            if index % 50 == 0:
                ctx.progress(index, total, "Clustering keywords")
            if start_id in visited:
                continue
            component = [start_id]
            visited.add(start_id)
            queue: deque[int] = deque([start_id])
            while queue:
                current = queue.popleft()
                for neighbor in adjacency.get(current, ()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        component.append(neighbor)
                        queue.append(neighbor)

            if len(component) == 1 and not config.singletons_as_clusters:
                continue
            if len(component) > config.split_above:
                sub_by_id = {i: by_id[i] for i in component}
                sub_created, sub_clustered = self._soft(ctx, config, sub_by_id, by_keyword, shared)
                created += sub_created
                clustered += sub_clustered
                continue
            main_id = max(component, key=lambda i: (by_id[i].volume or 0, by_id[i].keyword))
            made = self._make_cluster(ctx, by_id, by_keyword, component, main_id=main_id, mode="connected")
            if made:
                created += 1
                clustered += len(component)
        return created, clustered

    def _make_cluster(
        self,
        ctx: StageContext,
        by_id: dict[int, Keyword],
        by_keyword: dict[int, list[SerpResult]],
        member_ids: list[int],
        *,
        main_id: int,
        mode: str,
    ) -> bool:
        if not member_ids:
            return False
        members = [by_id[i] for i in member_ids]
        main = by_id[main_id]
        domains: Counter[str] = Counter()
        for kw in members:
            domains.update(r.domain for r in by_keyword.get(kw.id, ()) if r.domain)
        cluster = Cluster(
            project_id=ctx.project_id,
            name=main.keyword,
            main_keyword=main.keyword,
            size=len(members),
            total_volume=sum(kw.volume or 0 for kw in members),
            data={"top_domains": [d for d, _ in domains.most_common(5)], "mode": mode},
        )
        ctx.session.add(cluster)
        ctx.session.flush()
        for kw in members:
            kw.cluster_id = cluster.id
        return True


def _shared(shared: dict[tuple[int, int], int], a: int, b: int) -> int:
    return shared.get((min(a, b), max(a, b)), 0)


def _shared_counts(
    ctx: StageContext,
    by_id: dict[int, Keyword],
    by_keyword: dict[int, list[SerpResult]],
    config: SerpClusterConfig,
) -> tuple[dict[tuple[int, int], int], int]:
    """Count, for every pair of keywords, how many top-N results they share.

    Only pairs that share at least one result are considered (via an inverted
    index result -> keyword ids), so this stays well short of comparing all pairs.
    A result held by more than ``ignore_common_above`` keywords (e.g. a big
    portal's homepage) is skipped instead: linking it would mean building
    O(k^2) pairs for that one result and would only prove the keywords share
    a generic page, not a topic. Returns the shared-count map and how many
    such results were ignored.
    """
    top_n = max(1, config.top_n)

    def result_key(item: SerpResult) -> str:
        return (item.domain if config.compare == "domain" else item.url) or ""

    inverted: dict[str, list[int]] = defaultdict(list)
    for kw_id in by_id:
        top = sorted(by_keyword[kw_id], key=lambda r: r.position)[:top_n]
        for key in {result_key(r) for r in top if result_key(r)}:
            inverted[key].append(kw_id)

    shared: dict[tuple[int, int], int] = defaultdict(int)
    ignored_common = 0
    total = len(inverted)
    for index, kw_ids in enumerate(inverted.values(), start=1):
        if index % 200 == 0:
            ctx.progress(index, total, "Comparing SERP overlaps")
        if len(kw_ids) < 2:
            continue
        if config.ignore_common_above > 0 and len(kw_ids) > config.ignore_common_above:
            ignored_common += 1
            continue
        for a, b in combinations(sorted(kw_ids), 2):
            shared[(a, b)] += 1
    return shared, ignored_common
