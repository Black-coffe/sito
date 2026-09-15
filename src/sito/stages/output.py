"""Stages that write a project's keywords out as a file."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from sito.core.context import StageContext
from sito.core.io import export_filename, keyword_table, write_table
from sito.plugins.base import Stage, StageKind


class ExportFileConfig(BaseModel):
    format: Literal["xlsx", "csv", "json"] = "xlsx"
    scope: Literal["active", "all"] = "active"
    filename_prefix: str = Field("keywords", description="Used to name the exported file.")


class ExportFile(Stage):
    id: ClassVar[str] = "export_file"
    name: ClassVar[str] = "Export to file"
    kind: ClassVar[StageKind] = StageKind.OUTPUT
    summary: ClassVar[str] = "Write the project's keywords to a CSV, Excel or JSON file."
    docs: ClassVar[str] = """
Writes the keyword table to a file in the project's exports folder — the same
data the workspace's Export menu downloads, but produced as a pipeline step
so it runs unattended, e.g. at the end of a template.

**Scope** `active` writes only passing keywords; `all` also includes
excluded ones with their status and reason. The file this step wrote is
linked from its card once it finishes.
"""
    Config: ClassVar[type[BaseModel]] = ExportFileConfig

    def run(self, ctx: StageContext, config: ExportFileConfig) -> None:
        columns, rows = keyword_table(ctx.session, ctx.project_id, config.scope)
        payload = write_table(columns, rows, config.format)
        filename = export_filename(ctx.project.name, config.filename_prefix, config.format)
        ctx.output_path(filename).write_bytes(payload)
        ctx.stat(file=filename, rows=len(rows))
