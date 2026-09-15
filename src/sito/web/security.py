"""Protection for a login-less app bound to localhost.

sito has no accounts, so two browser attacks matter even on 127.0.0.1:

* **Cross-site requests (CSRF).** Any website you visit can submit a form to
  ``http://127.0.0.1:8765``. Unsafe requests (POST, PUT, PATCH, DELETE) are
  therefore rejected unless the browser says they come from sito's own pages:
  a matching ``Origin`` header, or ``Sec-Fetch-Site: same-origin``/``none``.
  Requests without either header (curl, scripts, tests) are allowed: they are
  not made by a browser on someone else's behalf.
* **DNS rebinding.** A malicious domain can re-point itself to 127.0.0.1 and
  then read pages "same-origin". Requests whose ``Host`` is not an allowed name
  are rejected.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
DEFAULT_HOSTS = ("localhost", "127.0.0.1", "::1")


def host_name(value: str) -> str:
    """``example.com:8765`` → ``example.com``; ``[::1]:8765`` → ``::1``."""
    value = value.strip().lower()
    if value.startswith("["):
        return value[1 : value.find("]")] if "]" in value else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class LocalOnlyMiddleware:
    def __init__(self, app: ASGIApp, allowed_hosts: Iterable[str] = DEFAULT_HOSTS) -> None:
        self.app = app
        hosts = {h.strip().lower() for h in allowed_hosts if h.strip()}
        self.any_host = "*" in hosts
        self.allowed_hosts = {host_name(h) for h in hosts if h != "*"}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        if not self.any_host and host_name(host) not in self.allowed_hosts:
            response = PlainTextResponse(
                f"Host '{host}' is not allowed. Open sito via http://127.0.0.1 or add the name to SITO_ALLOWED_HOSTS.",
                status_code=400,
            )
            await response(scope, receive, send)
            return
        if scope["method"] in UNSAFE_METHODS and not self._same_origin(headers, host):
            response = PlainTextResponse(
                "Blocked: this request came from another website. sito only accepts changes made from its own pages.",
                status_code=403,
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _same_origin(headers: dict[str, str], host: str) -> bool:
        origin = headers.get("origin")
        if origin is not None:
            if origin == "null":
                return False
            return urlsplit(origin).netloc.lower() == host.lower()
        fetch_site = headers.get("sec-fetch-site")
        if fetch_site is not None:
            return fetch_site in ("same-origin", "none")
        return True
