"""Small text helpers shared by stages and import/export."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def normalize_keyword(text: Any) -> str:
    """Canonical form used for de-duplication: trimmed, single spaces, lower case."""
    return " ".join(str(text or "").split()).lower()


def domain_of(url: str) -> str:
    host = urlparse(url if "//" in url else f"//{url}").netloc.lower()
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", "").replace(" ", "")))
    except ValueError:
        return None


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except ValueError:
        return None
