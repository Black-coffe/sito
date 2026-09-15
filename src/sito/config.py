"""Runtime configuration, read from environment variables.

Only infrastructure lives here (where data is stored, which port to use).
API keys are NOT configured here: they are entered on the Connections page
and stored in the local database (or referenced as ``env:VAR_NAME``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    database_url: str
    plugins_dir: Path
    snapshot_limit: int
    host: str
    port: int
    # Host names the browser may use to reach sito (DNS-rebinding protection). "*" disables the check.
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "::1")

    @classmethod
    def from_env(cls, **overrides: object) -> AppConfig:
        """Build config from ``SITO_*`` environment variables; keyword overrides win."""
        env = os.environ
        data_dir = Path(str(overrides.get("data_dir") or env.get("SITO_DATA_DIR", "./sito-data")))
        data_dir = data_dir.expanduser().resolve()
        database_url = str(
            overrides.get("database_url")
            or env.get("SITO_DATABASE_URL")
            or f"sqlite:///{(data_dir / 'sito.db').as_posix()}"
        )
        plugins_dir = Path(str(overrides.get("plugins_dir") or env.get("SITO_PLUGINS_DIR") or data_dir / "plugins"))
        host = str(overrides.get("host") or env.get("SITO_HOST", "127.0.0.1"))
        extra = str(overrides.get("allowed_hosts") or env.get("SITO_ALLOWED_HOSTS", ""))
        allowed = ["localhost", "127.0.0.1", "::1", *(h.strip() for h in extra.split(",") if h.strip())]
        if host not in ("0.0.0.0", "::", ""):
            allowed.append(host)
        return cls(
            data_dir=data_dir,
            database_url=database_url,
            plugins_dir=plugins_dir.expanduser().resolve(),
            snapshot_limit=int(str(overrides.get("snapshot_limit") or env.get("SITO_SNAPSHOT_LIMIT", "30"))),
            host=host,
            port=int(str(overrides.get("port") or env.get("SITO_PORT", "8765"))),
            allowed_hosts=tuple(dict.fromkeys(allowed)),
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "exports").mkdir(exist_ok=True)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
