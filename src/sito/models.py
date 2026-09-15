"""Data model.

A *project* is one keyword research. It owns keywords, an ordered *pipeline* of
steps, the *runs* of those steps, *snapshots* (the keyword table as it was
before/after each run), SERP results and clusters. *Connections* (API keys and
endpoints) are global and shared by all projects.

Stages keep their per-keyword results in ``Keyword.data`` (a JSON object), so a
new plugin never needs a schema migration: an AI stage writes
``{"relevance": 8, "intent": "commercial"}``, a volume stage writes
``{"volume_source": "..."}`` and so on.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

RUN_QUEUED = "queued"
RUN_RUNNING = "running"
RUN_DONE = "done"
RUN_FAILED = "failed"
RUN_CANCELLED = "cancelled"
RUN_ACTIVE = (RUN_QUEUED, RUN_RUNNING)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


JSONDict = MutableDict.as_mutable(JSON)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    # Free-text description of the business/site. AI stages put it into their prompts.
    context: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    steps: Mapped[list[Step]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Step.position"
    )


class Keyword(Base):
    __tablename__ = "keywords"
    __table_args__ = (
        UniqueConstraint("project_id", "keyword", name="uq_keywords_project_keyword"),
        Index("ix_keywords_project_excluded", "project_id", "excluded"),
        # Never reuse ids: snapshots and SERP rows refer to keywords by id.
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    keyword: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(100), default="manual")
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpc: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Excluded keywords stay in the table (nothing is destroyed) but stages skip them.
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cluster_id: Mapped[int | None] = mapped_column(
        ForeignKey("clusters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    data: Mapped[dict] = mapped_column(JSONDict, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Cluster(Base):
    __tablename__ = "clusters"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    main_keyword: Mapped[str | None] = mapped_column(String(500), nullable=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    total_volume: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[dict] = mapped_column(JSONDict, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SerpResult(Base):
    __tablename__ = "serp_results"
    __table_args__ = (Index("ix_serp_project_keyword", "project_id", "keyword_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    keyword_id: Mapped[int] = mapped_column(ForeignKey("keywords.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(300), default="", index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(50), default="organic")
    provider: Mapped[str] = mapped_column(String(100), default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Connection(Base):
    """A configured instance of a connector: e.g. "OpenAI (work key)"."""

    __tablename__ = "connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    connector_id: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200))
    # Raw settings, secrets included. Values of the form "env:VAR" are read from the environment.
    settings: Mapped[dict] = mapped_column(JSONDict, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Step(Base):
    """One configured stage in a project's pipeline."""

    __tablename__ = "pipeline_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    stage_id: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200))
    config: Mapped[dict] = mapped_column(JSONDict, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="steps")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    step_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_steps.id", ondelete="SET NULL"), nullable=True, index=True
    )
    stage_id: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default=RUN_QUEUED, index=True)
    done: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(String(500), default="")
    log: Mapped[str] = mapped_column(Text, default="")
    stats: Mapped[dict] = mapped_column(JSONDict, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Snapshot(Base):
    """The project's keywords and clusters frozen at a point in time (gzipped JSON)."""

    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"), nullable=True)
    label: Mapped[str] = mapped_column(String(300))
    keyword_count: Mapped[int] = mapped_column(Integer, default=0)
    active_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
