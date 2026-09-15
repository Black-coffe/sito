# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] — unreleased

First public version.

### Added

- Local web app (FastAPI + server-rendered templates + HTMX, no build step), light and dark themes.
- Projects with an ordered pipeline of steps; run one step, run from a step, run all; live progress;
  cancel; resumable long steps; per-run log and numbers.
- Snapshots before and after every run: export any of them, restore, undo a step.
- Keyword table with filters, sorting, inline edit, bulk exclude/include/delete/set field.
- Import of CSV/TSV/XLSX/TXT (Ahrefs, Semrush, Keyword Planner headers recognised) with column
  mapping and add/merge/update modes; export to XLSX/CSV/JSON at any step.
- Connections page with provider docs, masked secrets, `env:VAR` references and a test button.
- Plugin system: stages and connectors as plain Python classes, settings forms generated from
  pydantic models; plugins from a local folder or the `sito.plugins` entry point.
- Built-in stages: add keywords manually, autocomplete expansion, clean & normalize, filter by
  rules, AI classification, collect SERP, cluster by SERP overlap, AI cluster naming, export to
  file.
- Built-in connectors: OpenAI and OpenAI-compatible servers (OpenRouter, DeepSeek, Ollama,
  LM Studio…), Anthropic Claude, XMLRiver, Serper.dev, Google Autocomplete.
- In-app documentation, Docker image and compose file, CI workflow.
