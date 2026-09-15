"""Built-in AI enrichment stages: keyword classification and cluster naming.

Both stages are generic ports of the legacy per-project analyzer scripts: instead of a
prompt hard-coded for one business, the prompt is assembled from the project's own
``context`` text and the fields the user asked for in the step settings.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from sito.core.context import StageContext
from sito.core.text import normalize_keyword
from sito.models import Cluster, Keyword
from sito.plugins.base import (
    Cancelled,
    LLMConnector,
    PluginError,
    Stage,
    StageKind,
    connection_field,
    textarea_field,
)

INTENTS = ("commercial", "informational", "navigational", "transactional", "local")
CONTENT_TYPES = ("landing", "category", "product", "blog_post", "comparison", "faq")


def _extract_results(payload: Any) -> list[dict]:
    """Pull a list of per-item dicts out of whatever shape the model answered with.

    OpenAI's JSON mode requires an object, so we ask for ``{"results": [...]}``, but
    also accept a bare list or any list-of-dicts value (some models/providers ignore
    the requested shape).
    """
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("results", "data", "items", "keywords", "clusters", "response"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        for value in payload.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return [item for item in value if isinstance(item, dict)]
    snippet = str(payload)[:200]
    raise PluginError(f"The model's answer had no recognizable results list: {snippet!r}")


def _clamp_relevance(value: Any) -> int | None:
    try:
        return max(1, min(10, int(value)))
    except (TypeError, ValueError):
        return None


def _clean_intent(value: Any) -> str | None:
    if isinstance(value, list) and value:
        value = value[0]
    text = str(value or "").strip().lower()
    return text if text in INTENTS else None


def _clean_category(value: Any, categories: list[str]) -> str:
    text = str(value or "").strip()
    return text if text in categories else "other"


def _clean_language(value: Any) -> str | None:
    if isinstance(value, list) and value:
        value = value[0]
    text = str(value or "").strip().lower()
    return text[:10] or None


def _parse_extra_fields(lines: list[str]) -> list[tuple[str, str]]:
    """Parse ``name: description`` lines into ``(field_name, description)`` pairs."""
    fields = []
    for line in lines:
        name, _, description = line.partition(":")
        name = name.strip().lower().replace(" ", "_")
        if name:
            fields.append((name, description.strip()))
    return fields


# --- AIClassify ------------------------------------------------------------------------


def _classify_system_prompt(
    project_context: str, config: AIClassify.Config, extra_fields: list[tuple[str, str]]
) -> str:
    lines = [
        "You are an expert SEO analyst classifying search keywords for this business:",
        project_context or "(no business description was provided)",
        "",
        "For each keyword in the batch, return a JSON object with these fields:",
        '- "keyword": the exact keyword text, unchanged',
    ]
    if config.relevance:
        lines.append(
            '- "relevance": integer 1-10, how relevant the keyword is to this business '
            "(1 = unrelated, 10 = exact match)"
        )
    if config.intent:
        lines.append(f'- "intent": one of {", ".join(INTENTS)}')
    if config.categories:
        lines.append(f'- "category": one of {", ".join(config.categories)}, or "other" if none fit')
    if config.language:
        lines.append('- "language": lower-case ISO 639-1 language code, e.g. "en"')
    for name, description in extra_fields:
        lines.append(f'- "{name}": {description}' if description else f'- "{name}"')
    if config.instructions:
        lines += ["", "Additional instructions:", config.instructions]
    lines += [
        "",
        'Respond with a JSON object: {"results": [{...}, ...]}, one entry per keyword.',
        "Return JSON only, no prose, no markdown fences.",
    ]
    return "\n".join(lines)


def _classify_user_prompt(batch: list[Keyword]) -> str:
    lines = ["Classify these keywords:"]
    for kw in batch:
        volume = f" (volume: {kw.volume})" if kw.volume else ""
        lines.append(f"- {kw.keyword}{volume}")
    return "\n".join(lines)


def _classify_batch(connector: LLMConnector, system_prompt: str, batch: list[Keyword]) -> list[dict]:
    """Runs in a worker thread: only talks to the LLM, never touches the database."""
    payload = connector.complete_json(system_prompt, _classify_user_prompt(batch))
    return _extract_results(payload)


class AIClassify(Stage):
    id = "ai_classify"
    name = "AI classification"
    kind = StageKind.ENRICH
    summary = "Classify keywords with an LLM: relevance, intent, category, language, custom fields."
    docs = """
Sends keywords to an LLM in batches and writes the results into each keyword's data.

Settings:
- **LLM connection** - which connector/model to use.
- **Batch size** - keywords per request (1-200). Bigger batches cost less overhead but risk
  truncated answers on weaker models.
- **Parallel requests** - how many batches run at once (1-16).
- **Only unclassified** - skip keywords that already have an `ai_model` value, so a rerun
  only fills in gaps (failed batches, new keywords).
- **Relevance / Intent / Categories / Language** - which fields to ask for.
- **Extra fields** - one per line, `name: description`, for anything project-specific, e.g.
  `priority: 1-5, how valuable for sales`.
- **Instructions** - free text appended to the prompt.

Cost tip: rough request count = keywords / batch size.
"""

    class Config(BaseModel):
        llm: int | None = connection_field("llm", title="Language model")
        batch_size: int = Field(
            50, title="Keywords per request", description="1–200. Fewer = more requests, sturdier answers."
        )
        parallel_requests: int = Field(
            4, title="Parallel requests", description="1–16. Lower it if the provider rate-limits you."
        )
        only_unclassified: bool = Field(
            True, title="Skip keywords already classified", description="Re-runs continue where they stopped."
        )
        relevance: bool = Field(
            True, title="Score relevance 1–10", description="Against the project's About the business text."
        )
        intent: bool = Field(True, title="Detect search intent")
        categories: list[str] = Field(
            default=[],
            title="Categories to choose from",
            description="One per line. Leave empty to skip categorisation.",
        )
        language: bool = Field(True, title="Detect language")
        extra_fields: list[str] = Field(
            default=[],
            title="Extra fields",
            description="One per line as name: description, e.g. priority: 1-5, value for sales.",
        )
        instructions: str = textarea_field("", description="Extra guidance for the model.")

    def run(self, ctx: StageContext, config: Config) -> None:
        connector = ctx.connection(config.llm, "llm")
        batch_size = max(1, min(200, config.batch_size))
        parallel = max(1, min(16, config.parallel_requests))
        extra_fields = _parse_extra_fields(config.extra_fields)

        keywords = ctx.keywords(missing="ai_model") if config.only_unclassified else ctx.keywords()
        if not keywords:
            ctx.stat(classified=0, missing=0, failed_batches=0)
            return

        system_prompt = _classify_system_prompt(ctx.project_context, config, extra_fields)
        batches = [keywords[i : i + batch_size] for i in range(0, len(keywords), batch_size)]

        classified = 0
        failed_batches = 0
        first_error: Exception | None = None
        done = 0

        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = {pool.submit(_classify_batch, connector, system_prompt, batch): batch for batch in batches}
            try:
                for future in as_completed(futures):
                    batch = futures[future]
                    try:
                        results = future.result()
                    except Cancelled:
                        raise
                    except Exception as exc:  # noqa: BLE001 - one bad answer must not sink the whole run
                        failed_batches += 1
                        first_error = first_error or exc
                        ctx.log(f"A batch of {len(batch)} keywords failed: {exc}")
                        done += len(batch)
                        ctx.progress(done, len(keywords))
                        continue

                    by_keyword = {normalize_keyword(kw.keyword): kw for kw in batch}
                    matched = 0
                    model_name = getattr(connector.settings, "model", connector.id)
                    for item in results:
                        kw = by_keyword.get(normalize_keyword(item.get("keyword")))
                        if kw is None:
                            continue
                        matched += 1
                        values: dict[str, Any] = {"ai_model": model_name}
                        if config.relevance:
                            values["relevance"] = _clamp_relevance(item.get("relevance"))
                        if config.intent:
                            values["intent"] = _clean_intent(item.get("intent"))
                        if config.categories:
                            values["category"] = _clean_category(item.get("category"), config.categories)
                        if config.language:
                            values["language"] = _clean_language(item.get("language"))
                        for name, _ in extra_fields:
                            if name in item:
                                values[name] = item[name]
                        ctx.set_data(kw, **values)
                        classified += 1
                    if matched < len(batch):
                        missing_n = len(batch) - matched
                        ctx.log(f"{missing_n} keyword(s) were missing from the model's answer.")
                    done += len(batch)
                    ctx.commit()
                    ctx.progress(done, len(keywords), f"{done}/{len(keywords)} classified")
            except Cancelled:
                for pending in futures:
                    pending.cancel()
                raise

        if batches and failed_batches == len(batches):
            raise PluginError(f"Every batch failed. First error: {first_error}")

        ctx.stat(
            classified=classified,
            missing=len(keywords) - classified,
            failed_batches=failed_batches,
            **getattr(connector, "usage", {}),
        )


# --- AIClusterNames --------------------------------------------------------------------


def _top_keywords(session: Session, cluster_id: int, limit: int) -> list[Keyword]:
    rows = list(session.scalars(select(Keyword).where(Keyword.cluster_id == cluster_id)))
    rows.sort(key=lambda k: k.volume or 0, reverse=True)
    return rows[:limit]


def _cluster_system_prompt(project_context: str, config: AIClusterNames.Config) -> str:
    lines = [
        "You are an SEO expert naming keyword clusters for this business:",
        project_context or "(no business description was provided)",
        "",
        "For each cluster in the batch, return a JSON object with these fields:",
        '- "cluster_id": the cluster id, unchanged',
        '- "name": a short, human-readable cluster name (2-5 words)',
        f'- "intent": one of {", ".join(INTENTS)}',
    ]
    if config.landing_page_ideas:
        lines += [
            '- "page_title": a compelling page title targeting the cluster',
            f'- "content_type": one of {", ".join(CONTENT_TYPES)}',
        ]
    if config.ads_copy:
        lines += [
            '- "ads": {"headline_1": "...", "headline_2": "...", "description_1": "...", "description_2": "..."}',
            "  headlines must be at most 30 characters, descriptions at most 90 characters",
        ]
    lines += [
        "",
        'Respond with a JSON object: {"results": [{...}, ...]}, one entry per cluster.',
        "Return JSON only, no prose, no markdown fences.",
    ]
    return "\n".join(lines)


def _cluster_user_prompt(batch: list[Cluster], samples: dict[int, list[Keyword]]) -> str:
    lines = ["Name these keyword clusters:"]
    for cluster in batch:
        kws = samples.get(cluster.id, [])
        kw_lines = "\n".join(f"  - {kw.keyword} (volume: {kw.volume or 0})" for kw in kws)
        lines.append(
            f"\nCluster {cluster.id} (current name: {cluster.name!r}, {cluster.size} keywords, "
            f"total volume {cluster.total_volume}):\n{kw_lines}"
        )
    return "\n".join(lines)


def _trim_at_word(text: str, limit: int) -> tuple[str, bool]:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text, False
    cut = text[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(), True


def _build_ads(raw: dict) -> tuple[dict, int]:
    ads: dict[str, str] = {}
    trimmed = 0
    limits = (("headline_1", 30), ("headline_2", 30), ("description_1", 90), ("description_2", 90))
    for key, limit in limits:
        text, was_trimmed = _trim_at_word(raw.get(key), limit)
        ads[key] = text
        trimmed += int(was_trimmed)
    return ads, trimmed


class AIClusterNames(Stage):
    id = "ai_cluster_names"
    name = "AI cluster naming"
    kind = StageKind.GROUP
    summary = "Name keyword clusters with an LLM; optionally draft landing page and ad copy ideas."
    docs = """
Sends each batch of clusters, with their top keywords, to an LLM and asks for a short
human name, search intent, and optionally a landing page idea and Google Ads copy.

Settings:
- **LLM connection**
- **Only unnamed** - skip clusters that already have an `ai_name`, so a rerun only fills
  gaps or renames clusters you cleared manually.
- **Clusters per request** - how many clusters to name in one call.
- **Sample keywords** - how many top-volume keywords per cluster to show the model.
- **Landing page ideas** - ask for a page title and content type.
- **Ads copy** - ask for 2 headlines (<=30 chars) and 2 descriptions (<=90 chars); anything
  longer is trimmed at a word boundary.

Cost tip: rough request count = clusters / clusters per request.
"""

    class Config(BaseModel):
        llm: int | None = connection_field("llm", title="Language model")
        only_unnamed: bool = Field(True, title="Skip clusters already named")
        clusters_per_request: int = Field(10, title="Clusters per request")
        sample_keywords: int = Field(
            15, title="Keywords shown per cluster", description="Top keywords by volume sent to the model."
        )
        landing_page_ideas: bool = Field(True, title="Suggest page title and type")
        ads_copy: bool = Field(
            False, title="Write Google Ads copy", description="2 headlines (≤30 chars) and 2 descriptions (≤90)."
        )

    def run(self, ctx: StageContext, config: Config) -> None:
        connector = ctx.connection(config.llm, "llm")
        per_request = max(1, min(50, config.clusters_per_request))
        sample_size = max(1, min(100, config.sample_keywords))

        clusters = list(
            ctx.session.scalars(select(Cluster).where(Cluster.project_id == ctx.project_id).order_by(Cluster.id))
        )
        if config.only_unnamed:
            clusters = [c for c in clusters if "ai_name" not in (c.data or {})]
        if not clusters:
            ctx.stat(named=0, trimmed=0, failed_batches=0)
            return

        batches = [clusters[i : i + per_request] for i in range(0, len(clusters), per_request)]
        named = 0
        trimmed = 0
        failed_batches = 0
        first_error: Exception | None = None
        done = 0
        total = len(clusters)

        for batch in batches:
            samples = {cluster.id: _top_keywords(ctx.session, cluster.id, sample_size) for cluster in batch}
            system_prompt = _cluster_system_prompt(ctx.project_context, config)
            user_prompt = _cluster_user_prompt(batch, samples)
            try:
                results = _extract_results(connector.complete_json(system_prompt, user_prompt))
            except Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - one bad answer must not sink the whole run
                failed_batches += 1
                first_error = first_error or exc
                ctx.log(f"A batch of {len(batch)} clusters failed: {exc}")
                done += len(batch)
                ctx.progress(done, total)
                continue

            by_id = {c.id: c for c in batch}
            for item in results:
                raw_id = item.get("cluster_id")
                cluster = by_id.get(raw_id) or by_id.get(_to_int(raw_id))
                if cluster is None:
                    continue
                new_data = dict(cluster.data or {})
                ai_name = str(item.get("name") or item.get("cluster_name") or cluster.name).strip()
                new_data["original_name"] = cluster.name
                new_data["ai_name"] = ai_name
                new_data["intent"] = _clean_intent(item.get("intent"))
                if config.landing_page_ideas:
                    new_data["page_title"] = str(item.get("page_title") or "").strip()
                    content_type = str(item.get("content_type") or "").strip().lower()
                    if content_type not in CONTENT_TYPES:
                        content_type = "landing"
                    new_data["content_type"] = content_type
                if config.ads_copy:
                    raw_ads = item.get("ads")
                    ads, batch_trimmed = _build_ads(raw_ads if isinstance(raw_ads, dict) else item)
                    new_data["ads"] = ads
                    trimmed += batch_trimmed
                cluster.data = new_data
                cluster.name = ai_name
                named += 1
            done += len(batch)
            ctx.commit()
            ctx.progress(done, total, f"{done}/{total} clusters named")

        if batches and failed_batches == len(batches):
            raise PluginError(f"Every batch failed. First error: {first_error}")

        ctx.stat(
            named=named,
            trimmed=trimmed,
            failed_batches=failed_batches,
            **getattr(connector, "usage", {}),
        )


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
