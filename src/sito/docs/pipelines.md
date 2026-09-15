# Pipelines, runs and snapshots

## The sieve stack

A project's pipeline is an ordered stack of **steps**. Each step is one stage plugin with its own
settings. Stages come in five kinds:

| Kind | What it does | Built-in examples |
|---|---|---|
| Collect | adds keywords | Add keywords manually, Autocomplete expansion |
| Clean & filter | excludes keywords that should not go further | Clean & normalize, Filter by rules |
| Enrich | adds data to each keyword | AI classification, Collect SERP |
| Group | builds clusters | Cluster by SERP overlap, AI cluster naming |
| Export | writes files | Export to file |

The order is up to you. Typical stacks:

- *clean → AI classify → filter by relevance → collect SERP → cluster → name clusters → export*
- *autocomplete → clean → AI classify → export*

Insert a step anywhere with **Insert step** between two steps, move it with the ⋯ menu, turn it off
to make *Run all* skip it, or remove it. Removing a step never touches keywords.

## Running

- **Run** runs one step on the current passing keywords.
- **Run from here** runs this step, then every enabled step below it, in order.
- **Run all** runs every enabled step from the top.

Only one run happens in a project at a time. If a step fails or is cancelled, the steps queued after
it are skipped. Steps that need a connection show **Needs setup** until you choose one.

Long steps (AI classification, SERP collection) save their work in batches and skip keywords they
already processed, so re-running a step after a cancel or a failure continues where it stopped.
Turn off *only unclassified* / *only missing* in the step settings to redo everything.

**Runs** lists every run with its numbers, and the log of each one. A failed run shows the error
there in full.

## Nothing is destroyed

Clean and filter steps do not delete keywords: they mark them **excluded** with a reason such as
`too short (<3 chars)` or `filter: volume < 100`. Excluded rows stay visible (hatched) in the
*Keywords* tab; filter by status to see them, and include them again in bulk if a rule was too
strict. Steps only work on passing keywords.

## Snapshots

Before every run sito saves a snapshot of the keyword list (and clusters), and another one after a
successful run. On the *Snapshots* tab you can:

- **export** any snapshot to Excel, CSV or JSON — the list exactly as it was at that moment;
- **restore** one — the list becomes what the snapshot holds (a safety snapshot is taken first, so
  a restore can be undone too);
- take a snapshot by hand before a risky manual edit.

The ⋯ menu of a step offers **Undo this step**, which restores the snapshot taken before that step
last ran. The oldest snapshots are pruned automatically (30 per project by default,
`SITO_SNAPSHOT_LIMIT`).

SERP results are not part of snapshots; they are kept per keyword and survive restores for
keywords that still exist.

## Editing between steps

The pipeline does not lock the data. Between runs you can edit a keyword, fix a volume, add a few
keywords, exclude a group, or export → edit in a spreadsheet → import with *update*. The next step
simply works on whatever the list is at that moment.
