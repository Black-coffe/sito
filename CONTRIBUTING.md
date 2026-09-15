# Contributing to sito

Thanks for helping. The most useful contributions are new **stages** and **connectors** (a provider
you use, a cleaning rule you keep writing by hand), bug reports with a small reproducible file, and
documentation fixes.

## Set up

```bash
git clone https://github.com/Black-coffe/sito.git && cd sito
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip install -e ".[dev]"
.venv/bin/sito serve --data-dir ./sito-data
```

Before opening a pull request:

```bash
ruff check src tests
pytest -q
```

## Where things are

| Path | What |
|---|---|
| `src/sito/plugins/` | Public plugin API (`base.py`) and discovery (`registry.py`). Changing `base.py` is an API change: keep it backwards compatible. |
| `src/sito/core/` | Runner, snapshots, pipeline editing, forms from pydantic models, import/export. |
| `src/sito/stages/`, `src/sito/connectors/` | Built-in plugins. They use only the public API. |
| `src/sito/web/` | FastAPI routes, Jinja2 templates, CSS. No build step. |
| `src/sito/docs/` | User documentation, shown in the app under *Docs*. |
| `tests/` | pytest; no network access (use `httpx.MockTransport`). |

## Writing a built-in plugin

Follow [docs/writing-plugins](src/sito/docs/writing-plugins.md). In addition, built-in plugins:

- have English `summary` and `docs` explaining every setting;
- never delete keywords (exclude with a reason);
- commit per batch and are resumable;
- have tests with mocked HTTP (see `tests/test_llm.py`, `tests/test_serp.py`);
- verify external API details against the provider's documentation and link it in `docs`.

## UI changes

The interface follows one visual system (sieve-analysis worksheet: graphite, brass accent, hatch for
excluded material). Use the existing classes in `src/sito/web/static/app.css`; add a class there
rather than inline styles. Check both light and dark themes and a narrow window.

## Reporting bugs

Include the sito version (top right of the app), what you did, what happened, and if possible a
small file that reproduces it. Never paste API keys; the run log does not contain them.

By contributing you agree that your contribution is licensed under the MIT License.
