"""The public plugin API.

sito is built from two kinds of plugins:

* **Stages** do work on a project's keywords. A pipeline is an ordered list of
  stages: collect → clean → enrich → group → export. Each stage declares a
  pydantic ``Config`` model; sito renders the settings form from it, so a
  plugin never needs any HTML or JavaScript.
* **Connectors** talk to external services (LLMs, SERP APIs, suggestion APIs).
  A connector declares a pydantic ``Settings`` model (API key, endpoint, …) and
  a user creates one or more *connections* from it on the Connections page.
  Stages ask for a connection of a given *kind* ("llm", "serp", "suggest"), so
  any stage works with any provider of that kind.

See ``docs/writing-plugins.md`` for a walk-through.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from sito.core.context import StageContext


class StageKind(StrEnum):
    SOURCE = "source"
    TRANSFORM = "transform"
    ENRICH = "enrich"
    GROUP = "group"
    OUTPUT = "output"

    @property
    def label(self) -> str:
        return {
            "source": "Collect",
            "transform": "Clean & filter",
            "enrich": "Enrich",
            "group": "Group",
            "output": "Export",
        }[self.value]


class EmptyConfig(BaseModel):
    """A stage or connector without settings."""


_KIND_WORDS = {"llm": "language-model", "serp": "search-results (SERP)", "suggest": "search-suggestion"}


def connection_field(kind: str, description: str = "", title: str | None = None) -> Any:
    """A config field that lets the user pick a connection of the given kind.

    Rendered as a drop-down of matching connections. The value is the connection
    id; pass it to ``ctx.connection(config.<field>)`` to get a ready connector.
    """
    return Field(
        default=None,
        title=title,
        description=description or f"Which {_KIND_WORDS.get(kind, kind)} connection to use.",
        json_schema_extra={"sito_connection": kind},
    )


def textarea_field(default: str = "", description: str = "", **kwargs: Any) -> Any:
    """A long text field (rendered as a multi-line text area)."""
    return Field(
        default=default,
        description=description,
        json_schema_extra={"sito_widget": "textarea"},
        **kwargs,
    )


class PluginError(Exception):
    """An error with a message meant for the user (shown as-is in the UI)."""


class Cancelled(Exception):
    """Raised inside a stage when the user pressed Cancel."""


class Stage:
    """Base class for pipeline stages.

    Subclass it, set the class attributes and implement :meth:`run`. Every field
    of ``Config`` must have a default so a new step can be added in one click.
    """

    id: ClassVar[str] = ""
    name: ClassVar[str] = ""
    kind: ClassVar[StageKind] = StageKind.TRANSFORM
    summary: ClassVar[str] = ""
    docs: ClassVar[str] = ""
    Config: ClassVar[type[BaseModel]] = EmptyConfig

    def run(self, ctx: StageContext, config: Any) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class Connector:
    """Base class for connectors to external services."""

    id: ClassVar[str] = ""
    name: ClassVar[str] = ""
    kind: ClassVar[str] = ""
    summary: ClassVar[str] = ""
    # Markdown shown next to the settings form: where to get a key, pricing, limits.
    docs: ClassVar[str] = ""
    signup_url: ClassVar[str] = ""
    # Create a connection automatically on first start (only for connectors without keys).
    auto_create: ClassVar[bool] = False
    Settings: ClassVar[type[BaseModel]] = EmptyConfig

    def __init__(self, settings: BaseModel) -> None:
        self.settings = settings

    def test(self) -> str:
        """Make one cheap real request and return a short human-readable result.

        Raise :class:`PluginError` with a helpful message if it fails.
        """
        return "This connector has no test."


class LLMConnector(Connector):
    kind: ClassVar[str] = "llm"

    def __init__(self, settings: BaseModel) -> None:
        super().__init__(settings)
        # Totals shown on the run page; implementations add to them (under a lock if threaded).
        self.usage: dict[str, int] = {"requests": 0, "input_tokens": 0, "output_tokens": 0}

    def complete_json(self, system: str, prompt: str) -> Any:  # pragma: no cover - interface
        """Send one request and return the parsed JSON answer (dict or list)."""
        raise NotImplementedError


@dataclass
class SerpItem:
    position: int
    url: str
    title: str = ""
    snippet: str = ""
    kind: str = "organic"


@dataclass
class SerpPage:
    query: str
    items: list[SerpItem] = field(default_factory=list)
    # "Related searches" and "People also ask" — handy for expanding the keyword list.
    related: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)


class SerpConnector(Connector):
    kind: ClassVar[str] = "serp"

    def search(self, query: str) -> SerpPage:  # pragma: no cover - interface
        raise NotImplementedError


class SuggestConnector(Connector):
    kind: ClassVar[str] = "suggest"

    def suggest(self, query: str) -> list[str]:  # pragma: no cover - interface
        raise NotImplementedError


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json_payload(text: str) -> Any:
    """Parse JSON returned by an LLM: tolerates code fences and leading/trailing prose."""
    cleaned = _FENCE_RE.sub("", text.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
    if not starts:
        raise PluginError(f"The model did not return JSON: {text[:200]!r}")
    start = min(starts)
    end = max(cleaned.rfind("}"), cleaned.rfind("]"))
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise PluginError(f"The model returned malformed JSON: {exc}") from exc
