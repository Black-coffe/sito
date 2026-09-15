# sito

**A visual, modular pipeline for SEO keyword research.** Import a keyword list, or grow one. Then
run it through a stack of steps that clean it, classify it with any LLM, collect Google results,
cluster it and export it. You can edit, re-run, undo, import and export at every step.

sito (Ukrainian/Russian *сито*) means *sieve*. Every step is a sieve: it excludes some keywords, with
a reason, and passes the rest on. The interface shows exactly that: how many keywords came in, how
many each step excluded and why, and what passed through.

![The sito workspace: a stack of steps on the left, each with a bar that shows how many keywords
came in, were excluded and passed; the keyword table on the right](docs/images/workspace.png)

<sub>Screenshot of `sito demo`. All data in it is synthetic.</sub>

- **Local-first.** Runs on your machine with your own API keys. No account, no telemetry.
- **Bring any model.** OpenAI, Anthropic, OpenRouter, DeepSeek, or a local Ollama / LM Studio.
- **Nothing is lost.** Steps exclude keywords instead of deleting them. There is a snapshot before and
  after every run, and any of them can be restored or exported.
- **Checkpoints everywhere.** Export after any step, edit the file in a spreadsheet, import it back.
- **Plugins in plain Python.** A stage or a connector is one class. Its settings form is generated
  from a pydantic model, so you never write frontend code.

> Status: 0.1, early. The core works end to end and is covered by tests. Expect rough edges and
> changes to the plugin API before 1.0.

## Quick start

```bash
pip install git+https://github.com/Black-coffe/sito.git
sito serve                     # → http://127.0.0.1:8765
```

Or with Docker:

```bash
git clone https://github.com/Black-coffe/sito.git && cd sito
docker compose up -d           # → http://127.0.0.1:8765, data in the sito-data volume
```

To look around before connecting anything, run `sito demo`. It creates a sample project, runs the
whole pipeline with offline demo connectors (synthetic AI answers and search results, no keys
needed) and starts the app.

For real work:

1. Create a project and describe the business in one paragraph (the AI steps use it).
2. **Import** an Ahrefs / Semrush / Keyword Planner export, any CSV or XLSX, or paste a list.
3. Add your keys under **Connections**. Every provider page explains where to get a key, and a
   **Save and test** button checks it.
4. Press **Run all**, or run the steps one at a time, and watch the list shrink as it passes through
   the stack.
5. **Export** to Excel, CSV or JSON, either now or later from any snapshot.

Full walkthrough: [Getting started](src/sito/docs/getting-started.md). All of the documentation is
also built into the app under *Docs*.

## How it works

```mermaid
flowchart LR
    I[Import CSV / XLSX / TXT] --> K[(Keywords)]
    subgraph Pipeline — any order, any number of steps
      S1[Collect<br/>manual list · autocomplete] --> S2[Clean & filter<br/>normalize · rules]
      S2 --> S3[Enrich<br/>AI classification · SERP]
      S3 --> S4[Group<br/>SERP clustering · AI naming]
      S4 --> S5[Export<br/>xlsx · csv · json]
    end
    K <--> Pipeline
    Pipeline -. snapshot before/after every run .-> H[(Snapshots)]
    H -->|export or restore| K
```

- A **project** holds keywords and an ordered pipeline of **steps**.
- A step is a **stage plugin** together with its settings. Stages work on *passing* keywords, and a
  keyword a step takes out becomes *excluded*, with the reason attached.
- A step that needs an external service asks for a **connection** of a given kind (`llm`, `serp`,
  `suggest`). Any provider of that kind can fill it.
- Long steps save their work in batches and skip what they already did. After a cancel or a failure,
  a re-run picks up where it stopped.

## Built-in plugins

| Stage | Kind | What it does |
|---|---|---|
| Add keywords manually | Collect | Paste a list. |
| Autocomplete expansion | Collect | Grows the list with Google suggestions (seeds, a–z, question prefixes). |
| Clean & normalize | Clean | Lower-cases, strips special characters, merges duplicates, excludes keywords that are too short or too long, digit-heavy, or contain stop words. |
| Filter by rules | Clean | Volume, KD, CPC, any data field (e.g. `relevance >= 6`), must / must-not contain. |
| AI classification | Enrich | Relevance 1–10 to your business, intent, your own categories, language, plus any extra fields you define. Batched, parallel, resumable. |
| Collect SERP | Enrich | Google top 10 for each keyword. Related searches and People Also Ask can be added as new keywords. |
| Cluster by SERP overlap | Group | Groups keywords whose top results overlap (soft or connected mode). |
| AI cluster naming | Group | Names each cluster and suggests intent, page type, page title and optional Google Ads copy. |
| Export to file | Export | Writes xlsx / csv / json as a pipeline step. |

| Connector | Kind | Key |
|---|---|---|
| OpenAI / OpenAI-compatible | `llm` | OpenAI, OpenRouter, DeepSeek, or none for local Ollama / LM Studio |
| Anthropic Claude | `llm` | Anthropic console |
| XMLRiver (Google) | `serp` | xmlriver.com |
| Serper.dev (Google) | `serp` | serper.dev |
| Google Autocomplete | `suggest` | none |

## Write your own step

```python
# sito-data/plugins/brand_filter.py — restart sito and it appears in "Add step"
from pydantic import BaseModel, Field
from sito.plugins import Stage, StageKind

class BrandFilter(Stage):
    id = "brand_filter"
    name = "Exclude brand keywords"
    kind = StageKind.TRANSFORM
    summary = "Takes out keywords that mention the listed brands."

    class Config(BaseModel):
        brands: list[str] = Field(default=[], description="One brand per line.")

    def run(self, ctx, config):
        for kw in ctx.keywords():
            hit = next((b for b in config.brands if b.lower() in kw.keyword), None)
            if hit:
                ctx.exclude(kw, f"brand '{hit}'")
```

Connectors to new services work the same way, and plugins can be shipped as packages through the
`sito.plugins` entry point. Read [Writing plugins](src/sito/docs/writing-plugins.md).

## Keys and security

- Keys are stored in the local database (`sito-data/sito.db`) and are never sent back to the
  browser. You can also reference an environment variable (`env:OPENAI_API_KEY`) instead of
  storing the key at all.
- sito has **no login**. It binds to `127.0.0.1` by default, and the compose file publishes the port
  on localhost only. Keep it that way, or put an authenticating proxy in front of it. Requests from
  other websites (CSRF) and unknown host names (DNS rebinding) are refused. See
  [Configuration](src/sito/docs/configuration.md).

## Documentation

- [Getting started](src/sito/docs/getting-started.md)
- [Pipelines, runs and snapshots](src/sito/docs/pipelines.md)
- [Import and export](src/sito/docs/import-export.md)
- [Connections and API keys](src/sito/docs/connections.md)
- [Writing plugins](src/sito/docs/writing-plugins.md)
- [Configuration and deployment](src/sito/docs/configuration.md)
- The stage and connector reference is generated inside the app from the installed plugins
  (*Docs → Stages and connectors*).

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
ruff check src tests && pytest -q
sito serve --data-dir ./sito-data
```

Stack: Python 3.11+, FastAPI, SQLAlchemy 2 on SQLite, Jinja2 templates with HTMX. There is no
JavaScript build step. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT, see [LICENSE](LICENSE). Full notices for bundled assets are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Bundled third-party assets: [Golos Text](https://github.com/googlefonts/golos-text)
(SIL Open Font License 1.1, `src/sito/web/static/fonts/OFL.txt`), [Lucide](https://lucide.dev) icons
(ISC), [htmx](https://htmx.org) (0BSD).
