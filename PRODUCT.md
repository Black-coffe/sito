# Product

<!-- impeccable:product-schema 1 -->

> Product record for design and contribution decisions. Items marked *(inferred)* are working
> assumptions, not measured facts.

## Platform

web

## Stack

delegated: Python + FastAPI, server-rendered Jinja2 templates, HTMX for partial updates, vanilla
CSS, SQLite. Chosen so an open-source user installs with `pip install` or `docker compose up` and
no Node build step, and so plugin authors never write frontend code.

## Users

SEO specialists, marketers and developers building a keyword list ("semantic core") for a site:
importing keyword exports, cleaning them, enriching them with AI and SERP data, grouping them into
clusters and handing the result to content and ads teams. They run sito locally on their own
machine with their own API keys. *(inferred)* Lists range from hundreds to hundreds of thousands of
keywords; jobs run for minutes to hours.

## Product Purpose

An open-source, visual, modular framework for keyword research. A project is a sequential pipeline
of steps (collect → clean → enrich → group → export). At any step the user can add, edit, import,
export and run the next step. Success: someone downloads it, connects their keys by following the
built-in instructions, and gets a clean, classified, clustered keyword list without writing code.

## Positioning

Local-first and fully open: bring your own keys and any LLM (OpenAI-compatible, Anthropic, local
Ollama) or SERP provider; every step is snapshotted, reversible and exportable; new stages and
connectors are plain Python files whose settings forms are generated automatically.

## Operating Context

Desktop browser on localhost, next to spreadsheets (Excel, Google Sheets) and keyword exports
(Ahrefs, Semrush CSV). Long-running background jobs with live progress. API keys are entered on
a Connections page or referenced from environment variables.

## Capabilities and Constraints

- Projects, ordered pipeline steps, runs with live progress and cancel, snapshots before/after
  every run with restore and export.
- Keyword table: filter, sort, inline edit, add, exclude/include, delete; import CSV/XLSX/TXT with
  column mapping and merge modes; export CSV/XLSX/JSON of the current state or any snapshot.
- Built-in plugins: manual list, Google Autocomplete expansion, clean, filter, AI classification,
  AI cluster naming, SERP collection (XMLRiver, Serper), SERP-overlap clustering, file export.
- Nothing is deleted by stages: keywords are excluded with a reason.
- UI language: English *(inferred: global open-source audience)*.

## Brand Commitments

Name: **sito** — Ukrainian/Russian for "sieve". MIT licence.

## Evidence on Hand

None yet: no users, testimonials, benchmarks or case studies. Do not fabricate any.

## Product Principles

1. Nothing is destroyed: exclude with a reason, snapshot every step, allow restore.
2. Every step is a checkpoint: import and export are available anywhere, not only at the end.
3. Plugins are Python only: a settings model is enough for a working form.
4. Keys stay local and visible in where they live, never echoed back to the browser.
5. Honest state: show what ran, what failed and why, in plain language.

## Accessibility & Inclusion

*(inferred)* WCAG 2.2 AA: keyboard operable, visible focus, contrast ≥ 4.5:1, light and dark themes.
