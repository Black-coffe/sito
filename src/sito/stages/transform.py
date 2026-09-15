"""Stages that clean and filter a project's keywords.

Non-destructive by design: a keyword is never deleted. It is either renamed
(when normalizing its text) or excluded with a short, visible reason.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from sito.core.text import to_float
from sito.models import Keyword
from sito.plugins.base import Stage, StageKind

_SPECIAL_CHARS_RE = re.compile(r"[^\w\s\-]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")

FilterOperator = Literal[">=", "<=", "==", "!=", "contains", "not contains", "is empty", "is not empty"]
FILTER_PREFIX = "filter: "


def _clean_text(text: str, remove_special_chars: bool) -> str:
    cleaned = text
    if remove_special_chars:
        cleaned = _SPECIAL_CHARS_RE.sub("", cleaned)
    return _WHITESPACE_RE.sub(" ", cleaned).strip().lower()


def _matches_stop_word(text: str, word: str, whole_words_only: bool) -> bool:
    if not word:
        return False
    if whole_words_only:
        return re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE) is not None
    return word.lower() in text.lower()


def _rule_violation(text: str, config: Clean.Config) -> tuple[str, str] | None:
    """The first broken rule for ``text``, as ``(reason_kind, reason)``, or ``None``."""
    length = len(text)
    if length < config.min_length:
        return "too_short", f"too short (<{config.min_length} chars)"
    if length > config.max_length:
        return "too_long", f"too long (>{config.max_length} chars)"
    if config.max_words and len(text.split()) > config.max_words:
        return "too_many_words", f"too many words (>{config.max_words})"
    if config.exclude_digit_only and text and text.replace(" ", "").isdigit():
        return "digits_only", "digits only"
    digit_count = sum(ch.isdigit() for ch in text)
    percent = round(digit_count * 100 / length) if length else 0
    if percent > config.max_digit_percent:
        return "digits_percent", f"digits {percent}% (>{config.max_digit_percent}%)"
    for word in config.stop_words:
        if _matches_stop_word(text, word, config.whole_words_only):
            return "stop_word", f"stop word '{word}'"
    return None


class Clean(Stage):
    id = "clean"
    name = "Clean & normalize"
    kind = StageKind.TRANSFORM
    summary = "Normalize keyword text and exclude junk keywords."
    docs = """
Normalizes each active keyword's text — removes stray punctuation, collapses
whitespace, lower-cases it — and excludes keywords that don't look useful.
Nothing is ever deleted: excluded keywords stay in the project with a short
reason attached.

If normalizing a keyword makes its text match another keyword already in
the project (active or excluded), the newer one is excluded as a duplicate
instead of being renamed.

Use **Stop words** for terms you never want in the semantic core — adult
words, competitor brand names, and so on. Matching is case-insensitive;
turn on **Whole words only** so a stop word doesn't match inside a longer
word (e.g. "cat" inside "category").
"""

    class Config(BaseModel):
        remove_special_chars: bool = Field(
            True, description="Strip punctuation and symbols (keeps letters, digits, spaces, -)."
        )
        min_length: int = Field(3, description="Exclude keywords shorter than this many characters.")
        max_length: int = Field(100, description="Exclude keywords longer than this many characters.")
        max_words: int = Field(0, description="Exclude keywords with more words than this. 0 = no limit.")
        max_digit_percent: int = Field(60, description="Exclude keywords with a higher percentage of digits.")
        exclude_digit_only: bool = Field(True, description="Exclude keywords made up only of digits.")
        stop_words: list[str] = Field(
            [], description="Keywords containing any of these are excluded (case-insensitive)."
        )
        whole_words_only: bool = Field(False, description="Match stop words as whole words only.")

    def run(self, ctx, config: Config) -> None:
        keywords = ctx.keywords()
        existing_texts = {k.keyword for k in ctx.keywords(include_excluded=True)}
        renamed = 0
        excluded = 0
        reasons: dict[str, int] = {}

        def mark_excluded(kw: Keyword, reason_kind: str, reason: str) -> None:
            nonlocal excluded
            ctx.exclude(kw, reason)
            excluded += 1
            reasons[reason_kind] = reasons.get(reason_kind, 0) + 1

        for index, kw in enumerate(keywords, start=1):
            if index % 500 == 0:
                ctx.progress(index, len(keywords))

            original = kw.keyword
            cleaned = _clean_text(original, config.remove_special_chars)
            if cleaned != original:
                existing_texts.discard(original)
                if cleaned in existing_texts:
                    mark_excluded(kw, "duplicate", f"duplicate of '{cleaned}'")
                    existing_texts.add(original)
                    continue
                kw.keyword = cleaned
                ctx.set_data(kw, original=original)
                existing_texts.add(cleaned)
                renamed += 1

            violation = _rule_violation(kw.keyword, config)
            if violation:
                mark_excluded(kw, *violation)

        ctx.progress(len(keywords), len(keywords))
        ctx.stat(renamed=renamed, excluded=excluded, reasons=reasons)


def _field_matches(data_value: Any, operator: FilterOperator, value: str) -> bool:
    """Whether ``data_value`` satisfies the rule (i.e. the keyword should be kept)."""
    if operator == "is empty":
        return data_value in (None, "")
    if operator == "is not empty":
        return data_value not in (None, "")
    text_value = "" if data_value is None else str(data_value)
    if operator == "contains":
        return value in text_value
    if operator == "not contains":
        return value not in text_value
    left, right = to_float(data_value), to_float(value)
    if left is None or right is None:
        left, right = text_value, value
    if operator == ">=":
        return left >= right
    if operator == "<=":
        return left <= right
    if operator == "==":
        return left == right
    return left != right  # "!="


def _filter_violation(kw: Keyword, config: Filter.Config) -> str | None:
    """The reason ``kw`` fails the filter (without the ``filter: `` prefix), or ``None``."""
    if config.min_volume is not None and kw.volume is not None and kw.volume < config.min_volume:
        return f"volume < {config.min_volume}"
    if config.max_volume is not None and kw.volume is not None and kw.volume > config.max_volume:
        return f"volume > {config.max_volume}"
    if config.max_kd is not None and kw.kd is not None and kw.kd > config.max_kd:
        return f"kd > {config.max_kd}"
    if config.min_cpc is not None and kw.cpc is not None and kw.cpc < config.min_cpc:
        return f"cpc < {config.min_cpc}"
    if config.field:
        data_value = (kw.data or {}).get(config.field)
        if not _field_matches(data_value, config.operator, config.value):
            if config.operator in ("is empty", "is not empty"):
                return f"{config.field} {config.operator} not met"
            return f"{config.field} {config.operator} {config.value} not met"
    if config.must_contain:
        text = kw.keyword.lower()
        if not any(term.lower() in text for term in config.must_contain if term):
            return f"doesn't contain any of {', '.join(config.must_contain)}"
    if config.must_not_contain:
        text = kw.keyword.lower()
        for term in config.must_not_contain:
            if term and term.lower() in text:
                return f"contains '{term}'"
    return None


class Filter(Stage):
    id = "filter"
    name = "Filter by rules"
    kind = StageKind.TRANSFORM
    summary = "Exclude keywords that don't meet volume, KD, CPC or data rules."
    docs = """
Excludes active keywords that don't meet the rules below; nothing is
deleted, keywords are marked excluded with a reason starting with
`filter: `. Keywords with an empty **Volume** are never excluded by the
volume rules (there's nothing to compare).

**Field / operator / value** compares a key in the keyword's data (set by
an earlier AI or SERP stage, e.g. `relevance`, `intent`, `category`) against
a value. Numbers are compared as numbers when both sides parse as one,
otherwise as text.

**Must contain / must not contain** match the keyword text itself
(case-insensitive).

Turn on **Reset previous** to re-include keywords this step excluded before
running it again — handy after changing settings, so a rerun starts from a
clean slate instead of stacking exclusions.
"""

    class Config(BaseModel):
        min_volume: int | None = Field(None, description="Exclude keywords with a lower search volume.")
        max_volume: int | None = Field(None, description="Exclude keywords with a higher search volume.")
        max_kd: float | None = Field(None, description="Exclude keywords with a higher keyword difficulty.")
        min_cpc: float | None = Field(None, description="Exclude keywords with a lower CPC.")
        field: str = Field("", description="A key in the keyword's data, e.g. relevance or intent.")
        operator: FilterOperator = ">="
        value: str = Field("", description="Value to compare the field against.")
        must_contain: list[str] = Field([], description="Keep only keywords containing one of these.")
        must_not_contain: list[str] = Field([], description="Exclude keywords containing any of these.")
        reset_previous: bool = Field(
            True, description="Re-include keywords this step excluded before re-applying the rules."
        )

    def run(self, ctx, config: Config) -> None:
        reincluded = 0
        if config.reset_previous:
            for kw in ctx.keywords(include_excluded=True):
                if kw.excluded and (kw.excluded_reason or "").startswith(FILTER_PREFIX):
                    ctx.include(kw)
                    reincluded += 1

        keywords = ctx.keywords()
        excluded = 0
        for index, kw in enumerate(keywords, start=1):
            if index % 500 == 0:
                ctx.progress(index, len(keywords))
            reason = _filter_violation(kw, config)
            if reason:
                ctx.exclude(kw, FILTER_PREFIX + reason)
                excluded += 1

        ctx.progress(len(keywords), len(keywords))
        ctx.stat(excluded=excluded, reincluded=reincluded)
