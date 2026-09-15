# Getting started

sito is a local web app for keyword research. You bring a keyword list (or grow one), and a
**pipeline** of steps cleans it, enriches it with AI and Google results, groups it into clusters and
exports it. Every step can be re-run, undone and exported, and you can import edited files back at
any point.

## Install

sito needs Python 3.11 or newer.

```bash
pip install git+https://github.com/Black-coffe/sito.git   # or: pipx install ...
sito serve
```

Open <http://127.0.0.1:8765>. Data (the database with your projects and saved keys, exports,
local plugins) goes to `./sito-data` in the folder you started from; change it with
`--data-dir` or `SITO_DATA_DIR`.

With Docker instead:

```bash
git clone https://github.com/Black-coffe/sito.git && cd sito
docker compose up -d
```

The app is published on `127.0.0.1:8765` only, and data lives in the `sito-data` Docker volume.

### Try it without any keys

```bash
sito demo
```

creates a sample project (dedicated-server keywords), adds two offline **demo connections** that
return synthetic AI answers and search results, runs the whole pipeline and opens the app. Every
number in it is made up; it exists so you can click through every step before connecting real
services. Delete the project and the demo connections when you are done.

From a clone, for development:

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"     # Windows: .venv\Scripts\pip
.venv/bin/sito serve
```

## Your first project, step by step

1. **Create a project.** On *Projects*, give it a name and describe the business in *About the
   business* (what you sell, to whom, where). AI steps read that text to judge relevance. Pick a
   starter pipeline; you can change every step later.
2. **Bring keywords in.** Press **Import** and upload an Ahrefs, Semrush or Google Keyword Planner
   export, any CSV/XLSX, or a plain text list. sito guesses the columns; check the mapping and
   import. You can also paste keywords, or add a *Collect* step such as *Autocomplete expansion*.
3. **Connect services** (only for AI and SERP steps). Open *Connections → Add connection*, pick a
   provider, paste the key and press **Save and test**. Each provider page says where to get a key.
   Cleaning, filtering, autocomplete and export need no keys.
4. **Configure the steps.** In the pipeline on the left, press the settings icon on a step. The
   form comes from the plugin itself; the *How this stage works* section explains every option.
5. **Run.** **Run** runs one step, the *run from here* icon runs that step and everything below it,
   **Run all** runs the whole stack. Progress shows live; **Cancel run** stops at the next
   checkpoint and keeps finished batches.
6. **Look at the result.** The bar under each step shows how many keywords came in, how many the
   step excluded (hatched) and how many passed. The *Keywords* tab shows the current list: filter,
   sort, edit a cell, exclude or delete in bulk.
7. **Export whenever you like.** **Export** in the header downloads the current list. The download
   icon on a step exports the list *as it was right after that step*. *Snapshots* keeps a copy
   before and after every run.

## Words used in the app

| Word | Meaning |
|---|---|
| Step / stage | A stage is a plugin (e.g. *Clean & normalize*); a step is that stage placed in your pipeline with its settings. |
| Passing | Keywords still in play. Steps work on passing keywords. |
| Excluded | Keywords a step took out, with the reason. Nothing is deleted; you can include them again. |
| Snapshot | A frozen copy of the keyword list, taken before and after every run. Restore or export any of them. |
| Connection | A configured service: an API key plus its settings. |

## Where to go next

- [Pipelines, runs and snapshots](/docs/pipelines)
- [Import and export](/docs/import-export)
- [Connections and API keys](/docs/connections)
- [Stages and connectors](/docs/reference) — generated from the installed plugins
- [Writing plugins](/docs/writing-plugins)
