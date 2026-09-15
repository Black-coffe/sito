# Import and export

Import and export work at any point of the pipeline, not only at the start and the end.

## Importing

**Import** (in the project header) accepts:

| Format | Notes |
|---|---|
| `.csv`, `.tsv` | Delimiter detected automatically (`,` `;` tab `|`). UTF-8, UTF-16 (Google Keyword Planner) and Windows-1251 are recognised. |
| `.xlsx` | First sheet, first row is the header. |
| `.txt` | One keyword per line. |
| Pasted text | One keyword per line. |

After uploading you see the first rows and a target for every column:

- **Keyword**, **Volume**, **KD**, **CPC**, **Source** — the built-in fields;
- **Data: name** — kept as an extra attribute of the keyword (shows as a column, can be filtered,
  exported, and used by later steps);
- **Ignore**.

Headers from Ahrefs, Semrush, Google Keyword Planner, common Russian/Ukrainian headers and sito's own
exports are recognised automatically.

### Modes

| Mode | What happens |
|---|---|
| Add only | New keywords are added; existing ones are left alone. |
| Add + update | New keywords are added; existing ones get the non-empty values from the file. |
| Update only | Only keywords already in the project are updated; nothing is added. |

Keywords are matched case-insensitively with spaces collapsed, so `Buy  Server` and `buy server`
are the same keyword. A snapshot is taken before every import, so an import can be undone from
*Snapshots*.

### Round trip through a spreadsheet

1. Export after any step (for example after *AI classification*).
2. Edit in Excel or Google Sheets: fix categories, change intent, mark rows as `excluded`.
3. Import the file with **Update only**. The `status` and `reason` columns of sito's own
   exports are understood, so marking a row `excluded` in the sheet excludes it in sito.

## Exporting

| Where | What you get |
|---|---|
| **Export** in the header | The current list: passing keywords only, or everything including excluded. |
| Download icon on a step | The list as it was right after that step last ran. |
| *Snapshots* tab | Any snapshot. |
| *Export to file* stage | A file written to the project's exports folder as part of the pipeline; download it from the step menu or the run page. |

Formats: **Excel** (`.xlsx`, header frozen, filters on), **CSV** (UTF-8 with BOM so Excel opens
Cyrillic correctly) and **JSON**.

Columns: `keyword`, `volume`, `kd`, `cpc`, `source`, `cluster`, `status` (`passing` / `excluded`),
`reason`, then every data attribute collected by the steps (`relevance`, `intent`, `category`,
`language`, `serp_results`, …).
