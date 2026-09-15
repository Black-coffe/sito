"""Turning stored connections into live connector objects."""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from sito.core.forms import default_values, first_error, resolve_env_refs
from sito.models import Connection
from sito.plugins.base import Connector, PluginError
from sito.plugins.registry import PluginRegistry


def build_connector(registry: PluginRegistry, row: Connection) -> Connector:
    cls = registry.connector(row.connector_id)
    raw = resolve_env_refs(row.settings or {}, cls.Settings)
    try:
        settings = cls.Settings.model_validate(raw)
    except ValidationError as exc:
        raise PluginError(f"Connection '{row.name}' is misconfigured: {first_error(exc)}") from exc
    return cls(settings)


def connection_kind(registry: PluginRegistry, row: Connection) -> str | None:
    cls = registry.connectors.get(row.connector_id)
    return cls.kind if cls else None


def connections_of_kind(session: Session, registry: PluginRegistry, kind: str) -> list[Connection]:
    rows = session.scalars(select(Connection).order_by(Connection.name)).all()
    return [r for r in rows if connection_kind(registry, r) == kind]


def ensure_default_connections(session: Session, registry: PluginRegistry) -> None:
    """Create one connection for each key-less connector marked ``auto_create``."""
    existing = set(session.scalars(select(Connection.connector_id)).all())
    for cls in registry.connectors.values():
        if cls.auto_create and cls.id not in existing:
            session.add(Connection(connector_id=cls.id, name=cls.name, settings=default_values(cls.Settings)))
    session.commit()
