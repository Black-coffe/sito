# Writing plugins

Everything sito does comes from plugins, and built-in plugins use exactly the same API as yours.
There are two kinds:

- a **stage** does work on keywords and becomes a step in a pipeline;
- a **connector** talks to an external service (an LLM, a SERP API, a suggestion API).

You write Python only. The settings form, validation, the connection picker, progress display,
cancel, snapshots and undo are handled by sito.

## Your first stage in one file

Save this as `sito-data/plugins/brand_filter.py` and restart sito:

```python
from pydantic import BaseModel, Field

from sito.plugins import Stage, StageKind


class BrandFilter(Stage):
    id = "brand_filter"  # unique, never change it once people use it
    name = "Exclude brand keywords"
    kind = StageKind.TRANSFORM
    summary = "Takes out keywords that mention the listed brands."
    docs = """
Excludes every passing keyword containing one of the brands.
Use it to separate branded from non-branded demand.
"""

    class Config(BaseModel):
        brands: list[str] = Field(default=[], description="One brand per line.")
        case_sensitive: bool = False

    def run(self, ctx, config):
        brands = config.brands if config.case_sensitive else [b.lower() for b in config.brands]
        keywords = ctx.keywords()  # passing keywords
        for done, kw in enumerate(keywords, 1):
            text = kw.keyword if config.case_sensitive else kw.keyword.lower()
            hit = next((b for b in brands if b in text), None)
            if hit:
                ctx.exclude(kw, f"brand '{hit}'")
            if done % 500 == 0:
                ctx.progress(done, len(keywords))  # also raises if the user pressed Cancel
        ctx.stat(checked=len(keywords))
```

It now appears in *Add step*, with a form for `brands` and `case_sensitive`, on the *Plugins* page and
in the generated reference.

## Settings forms

`Config` (for stages) and `Settings` (for connectors) are pydantic models. Every field needs a
default. Field types map to inputs:

| Type | Input |
|---|---|
| `str` | text box (`textarea_field(...)` for multi-line text) |
| `int`, `float` | number |
| `bool` | checkbox |
| `Literal["a", "b"]`, `Enum` | drop-down |
| `list[str]` | text area, one item per line |
| `SecretStr` | password box; the saved value is never sent back to the browser, `env:VAR` is supported |
| `int \| None = connection_field("llm")` | drop-down of connections of that kind |

`Field(title=..., description=...)` sets the label and help text. Validation errors are shown to
the user next to the step.

## What a stage can do: `ctx`

| Call | Purpose |
|---|---|
| `ctx.keywords(include_excluded=False, missing=None)` | Keyword rows (ORM objects). `missing="relevance"` returns only keywords whose `data` lacks that key — makes a stage resumable. |
| `ctx.add_keywords(items, source=...)` | Add strings or dicts (`keyword`, `volume`, `kd`, `cpc`, `data`); duplicates are skipped; returns the number added. |
| `ctx.exclude(kw, reason)` / `ctx.include(kw)` | Exclude / bring back a keyword. Never delete. |
| `ctx.set_data(kw, **values)` | Merge values into the keyword's `data` (they become columns in the table and exports). |
| `ctx.connection(config.llm, "llm")` | A ready connector for the connection chosen in the settings. |
| `ctx.progress(done, total, message)` | Live progress; raises `Cancelled` when the user cancels. |
| `ctx.log(text)`, `ctx.stat(name=value)` | Log line / summary numbers on the run page. |
| `ctx.commit()` | Save work so far; long stages should commit every batch. |
| `ctx.output_path(filename)` | Where to write a file; `ctx.stat(file=name)` makes it downloadable. |
| `ctx.project_context` | The project's *About the business* text, for prompts. |
| `ctx.session` | The SQLAlchemy session, for anything else (`Cluster`, `SerpResult` in `sito.models`). |

Raise `sito.plugins.PluginError("message")` for problems the user can fix; the message is shown as
is. Any other exception is shown with its traceback in the run log.

Conventions that keep the whole system predictable:

1. Exclude with a reason instead of deleting.
2. Work only on passing keywords unless the stage is explicitly about excluded ones.
3. Commit per batch and use `missing=` so a re-run continues instead of starting over.
4. Put results in `kw.data` under short, lower-case keys.

## Connectors

```python
import httpx
from pydantic import BaseModel, SecretStr

from sito.plugins import PluginError, SerpConnector, SerpItem, SerpPage


class MySerp(SerpConnector):
    id = "my_serp"
    name = "My SERP API"
    summary = "Google results via My SERP API."
    signup_url = "https://example.com/signup"
    docs = "Create a key under **Account → API**. 1 request per keyword."

    class Settings(BaseModel):
        api_key: SecretStr = SecretStr("")
        country: str = "us"

    def search(self, query: str) -> SerpPage:
        r = httpx.get(
            "https://api.example.com/search",
            params={"q": query, "gl": self.settings.country},
            headers={"Authorization": f"Bearer {self.settings.api_key.get_secret_value()}"},
            timeout=30,
        )
        if r.status_code == 401:
            raise PluginError("The API key was rejected.")
        r.raise_for_status()
        items = [SerpItem(position=i, url=x["url"], title=x["title"]) for i, x in enumerate(r.json()["results"], 1)]
        return SerpPage(query=query, items=items)

    def test(self) -> str:
        return f"OK: {len(self.search('seo').items)} results"
```

Base classes and the method each kind must implement:

| Base class | Kind | Method |
|---|---|---|
| `LLMConnector` | `llm` | `complete_json(system, prompt) -> dict \| list` (use `parse_json_payload` on the model's text) |
| `SerpConnector` | `serp` | `search(query) -> SerpPage` |
| `SuggestConnector` | `suggest` | `suggest(query) -> list[str]` |
| `Connector` | your own | anything; your stages decide |

A new kind needs no core change: define `kind = "volume"` on a connector and use
`connection_field("volume")` in a stage.

## Testing a plugin

Run a stage without the web app:

```python
from sito.config import AppConfig
from sito.core.pipeline import add_step
from sito.core.runner import Runner
from sito.db import init_db, make_engine, make_session_factory
from sito.models import Project
from sito.plugins.registry import PluginRegistry

config = AppConfig.from_env(data_dir="/tmp/sito-test")
config.ensure_dirs()
engine = make_engine(config.database_url)
init_db(engine)
sessions = make_session_factory(engine)
registry = PluginRegistry()
registry.add_stage(BrandFilter, "test")

with sessions() as s:
    project = Project(name="t")
    s.add(project)
    s.commit()
    step = add_step(s, registry, project, "brand_filter")
    s.commit()

Runner(sessions, registry, config).enqueue(project.id, [step.id], background=False)
```

sito's own tests (`tests/`) use the same pattern.

## Sharing a plugin as a package

Expose a module through the `sito.plugins` entry point in your `pyproject.toml`:

```toml
[project.entry-points."sito.plugins"]
my_plugins = "my_package.sito_plugins"
```

Every `Stage` / `Connector` subclass with an `id` defined in that module is registered when sito
starts. Load errors never crash the app; they are listed on the *Plugins* page.
