"""Offline demo connectors: synthetic answers, so every step can be tried without API keys.

Nothing here calls the network. Answers are deterministic and obviously made up; search
results point at reserved ``.example`` domains (RFC 2606).
"""

from __future__ import annotations

import hashlib
import re
from itertools import combinations
from typing import Any, ClassVar

from sito.plugins.base import EmptyConfig, LLMConnector, SerpConnector, SerpItem, SerpPage

_DEMO_DOCS = """
A stand-in that needs no key and never leaves your computer. It returns **made-up** answers,
good enough to see how a pipeline behaves, useless for real research.

`sito demo` creates this connection and a sample project for you. Delete it once you have real
connections.
"""


def _h(text: str) -> int:
    return int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:8], 16)


_TRANSACTIONAL = {"buy", "order", "rent", "download", "book", "hire", "subscribe"}
_COMMERCIAL = {"price", "prices", "cost", "cheap", "best", "top", "review", "reviews", "vs", "compare", "deal"}
_INFORMATIONAL = {"what", "how", "why", "guide", "tutorial", "meaning", "is", "does", "can", "choose"}
_NAVIGATIONAL = {"login", "account", "official", "website", "dashboard"}


def _intent(words: set[str], seed: str) -> str:
    if words & _TRANSACTIONAL:
        return "transactional"
    if words & _INFORMATIONAL:
        return "informational"
    if words & _COMMERCIAL:
        return "commercial"
    if words & _NAVIGATIONAL:
        return "navigational"
    return "commercial" if _h(seed) % 2 else "informational"


class DemoLLM(LLMConnector):
    id = "demo_llm"
    name = "Demo LLM (synthetic answers)"
    summary = "Offline stand-in for an LLM: made-up but consistent answers, no key needed."
    docs = _DEMO_DOCS
    Settings: ClassVar = EmptyConfig

    def test(self) -> str:
        return "OK: the demo LLM answers offline with synthetic data."

    def complete_json(self, system: str, prompt: str) -> Any:
        if prompt.startswith("Name these keyword clusters"):
            return {"results": self._clusters(prompt)}
        if prompt.startswith("Classify these keywords"):
            return {"results": self._classify(system, prompt)}
        return {"ok": True}

    @staticmethod
    def _classify(system: str, prompt: str) -> list[dict]:
        context = set(re.findall(r"\w{4,}", system.lower().split("for each keyword")[0]))
        match = re.search(r'"category": one of (.+?), or "other"', system)
        categories = [c.strip() for c in match.group(1).split(",")] if match else []
        results = []
        for line in prompt.splitlines()[1:]:
            m = re.match(r"-\s+(.+?)(?:\s+\(volume: \d+\))?$", line.strip())
            if not m:
                continue
            keyword = m.group(1)
            words = set(keyword.split())
            overlap = sum(1 for w in words if any(w in c or c in w for c in context if len(w) > 3))
            item = {
                "keyword": keyword,
                "relevance": max(1, min(10, 2 + 3 * overlap + _h(keyword) % 3)),
                "intent": _intent(words, keyword),
                "language": "en" if re.search(r"[a-z]", keyword) else "ru",
            }
            if categories:
                item["category"] = next(
                    (c for c in categories if c.lower() in keyword), categories[_h(keyword) % len(categories)]
                )
            results.append(item)
        return results

    @staticmethod
    def _clusters(prompt: str) -> list[dict]:
        results = []
        for cid, _quote, current in re.findall(r"Cluster (\d+) \(current name: (['\"])(.*?)\2", prompt):
            words = current.split()
            name = " ".join(words[:5]).title()
            intent = _intent(set(words), current)
            content_type = {"informational": "blog_post", "transactional": "landing", "commercial": "comparison"}.get(
                intent, "category"
            )
            results.append(
                {
                    "cluster_id": int(cid),
                    "name": name,
                    "intent": intent,
                    "page_title": f"{name}: options and how to choose",
                    "content_type": content_type,
                    "ads": {
                        "headline_1": name,
                        "headline_2": "Compare the options",
                        "description_1": f"Everything about {current} in one place. Synthetic demo copy.",
                        "description_2": "Made-up text from the sito demo connector.",
                    },
                }
            )
        return results


_DEMO_DOMAINS = (
    "hosting.example", "serverguide.example", "techreviews.example", "forum.example", "wiki.example",
    "cloudcompare.example", "datacenter.example", "news.example", "blog.example", "shop.example",
    "docs.example", "answers.example",
)  # fmt: skip
_STOP = {"the", "a", "an", "for", "and", "of", "in", "to", "with", "what", "is", "how", "vs", "on"}


class DemoSerp(SerpConnector):
    id = "demo_serp"
    name = "Demo SERP (synthetic results)"
    summary = "Offline stand-in for a SERP API: made-up results on .example domains, no key needed."
    docs = _DEMO_DOCS
    Settings: ClassVar = EmptyConfig

    def test(self) -> str:
        return f"OK: {len(self.search('demo query').items)} synthetic results."

    def search(self, query: str) -> SerpPage:
        tokens = sorted({t for t in re.findall(r"\w+", query.lower()) if t not in _STOP}) or [query.lower()]
        candidates: list[str] = []
        # Keywords sharing words share result URLs, so SERP clustering has something to find.
        for a, b in combinations(tokens, 2):
            candidates.append(f"https://{_DEMO_DOMAINS[_h(a + b) % len(_DEMO_DOMAINS)]}/{a}-{b}")
        for token in tokens:
            for k in range(3):
                candidates.append(f"https://{_DEMO_DOMAINS[(_h(token) + k) % len(_DEMO_DOMAINS)]}/{token}")
        urls = sorted(dict.fromkeys(candidates), key=_h)[:10]
        items = [
            SerpItem(
                position=i,
                url=url,
                title=f"{url.rsplit('/', 1)[1].replace('-', ' ').title()} — {url.split('/')[2]}",
                snippet="Synthetic result from the sito demo connector.",
            )
            for i, url in enumerate(urls, 1)
        ]
        head = " ".join(tokens[:2])
        return SerpPage(
            query=query,
            items=items,
            related=[f"{query} alternatives", f"{query} reviews"],
            questions=[f"what is {head}"],
        )
