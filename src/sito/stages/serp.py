"""Collect SERP data for the project's keywords."""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import ClassVar

from pydantic import BaseModel
from sqlalchemy import delete

from sito.core.context import StageContext
from sito.core.text import domain_of, to_float
from sito.models import Keyword, SerpResult
from sito.plugins.base import Cancelled, PluginError, SerpPage, Stage, StageKind, connection_field


class SerpCollectConfig(BaseModel):
    serp: int | None = connection_field("serp")
    only_missing: bool = True
    # Requires an earlier AI classification step that writes keyword.data["relevance"].
    min_relevance: int = 0
    max_keywords: int = 0
    parallel_requests: int = 4
    top_n: int = 10
    add_related_searches: bool = False
    add_questions: bool = False


class SerpCollect(Stage):
    id: ClassVar[str] = "serp_collect"
    name: ClassVar[str] = "Collect SERP"
    kind: ClassVar[StageKind] = StageKind.ENRICH
    summary: ClassVar[str] = "Fetch Google search results for each keyword from a SERP connection."
    docs: ClassVar[str] = """
Runs one search per keyword through the chosen SERP connection and stores the
top results (`serp_results` table) plus a `serp_at` timestamp on the keyword.

- **Only missing** re-runs skip keywords that already have SERP data — turn it
  off to refresh everything.
- **Min IT/topic relevance** needs an AI classification step to have run first
  (it filters on `keyword.data["relevance"]`); leave at 0 to skip filtering.
- **Add related searches / questions** grows the keyword list from "related
  searches" and "People Also Ask" — handy before clustering or a second pass.
- Requests run in parallel (`parallel_requests`, 1–10); a failed keyword is
  logged and counted, not fatal, unless every keyword fails.
"""
    Config: ClassVar[type[BaseModel]] = SerpCollectConfig

    def run(self, ctx: StageContext, config: SerpCollectConfig) -> None:
        connector = ctx.connection(config.serp, kind="serp")
        keywords = ctx.keywords(missing="serp_at") if config.only_missing else ctx.keywords()
        if config.min_relevance > 0:
            keywords = [
                kw for kw in keywords if (relevance := _relevance(kw)) is not None and relevance >= config.min_relevance
            ]
        if config.max_keywords > 0:
            keywords = keywords[: config.max_keywords]

        if not keywords:
            ctx.log("No keywords to collect SERP data for.")
            ctx.stat(collected=0, failed=0, added_keywords=0)
            return

        workers = max(1, min(10, config.parallel_requests))
        top_n = max(1, config.top_n)
        total = len(keywords)
        done = collected = failed = added_keywords = 0

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="serp-collect") as pool:
            futures = {pool.submit(connector.search, kw.keyword): kw for kw in keywords}
            try:
                for future in as_completed(futures):
                    kw = futures[future]
                    done += 1
                    try:
                        page = future.result()
                    except PluginError as exc:
                        failed += 1
                        ctx.log(f"'{kw.keyword}': {exc}")
                    else:
                        added_keywords += self._store(ctx, connector.id, kw, page, top_n, config)
                        collected += 1
                    ctx.progress(done, total, kw.keyword)
                    if done % 20 == 0:
                        ctx.commit()
            except Cancelled:
                for pending in futures:
                    pending.cancel()
                raise

        ctx.commit()
        if collected == 0 and failed > 0:
            raise PluginError(f"All {failed} SERP requests failed; check the connection's key and try again.")
        ctx.stat(collected=collected, failed=failed, added_keywords=added_keywords)

    def _store(
        self,
        ctx: StageContext,
        provider: str,
        kw: Keyword,
        page: SerpPage,
        top_n: int,
        config: SerpCollectConfig,
    ) -> int:
        items = page.items[:top_n]
        ctx.session.execute(
            delete(SerpResult).where(SerpResult.project_id == ctx.project_id, SerpResult.keyword_id == kw.id)
        )
        for item in items:
            ctx.session.add(
                SerpResult(
                    project_id=ctx.project_id,
                    keyword_id=kw.id,
                    position=item.position,
                    url=item.url,
                    domain=domain_of(item.url),
                    title=item.title,
                    snippet=item.snippet,
                    kind=item.kind,
                    provider=provider,
                )
            )
        ctx.set_data(kw, serp_at=datetime.now(UTC).isoformat(), serp_results=len(items))

        added = 0
        if config.add_related_searches and page.related:
            added += self._add_expansion(ctx, page.related, kw.keyword, "serp_related")
        if config.add_questions and page.questions:
            added += self._add_expansion(ctx, page.questions, kw.keyword, "serp_question")
        return added

    def _add_expansion(self, ctx: StageContext, texts: Iterable[str], seed: str, source: str) -> int:
        items = [{"keyword": text, "data": {"seed": seed}} for text in texts]
        return ctx.add_keywords(items, source=source)


def _relevance(kw: Keyword) -> float | None:
    """The keyword's AI relevance score, tolerating values imported as text (e.g. "8")."""
    return to_float((kw.data or {}).get("relevance"))
