# Configuration and deployment

sito reads a handful of environment variables. API keys are not among them: they are set on the
*Connections* page (or referenced there as `env:VAR`).

| Variable | Default | Meaning |
|---|---|---|
| `SITO_DATA_DIR` | `./sito-data` | Database, exports, uploaded import files and the local plugins folder. |
| `SITO_DATABASE_URL` | `sqlite:///<data dir>/sito.db` | SQLAlchemy URL. Only SQLite is tested. |
| `SITO_PLUGINS_DIR` | `<data dir>/plugins` | Folder scanned for `*.py` plugins on start. |
| `SITO_SNAPSHOT_LIMIT` | `30` | Snapshots kept per project; the oldest are pruned. |
| `SITO_HOST` | `127.0.0.1` | Interface to bind. |
| `SITO_PORT` | `8765` | Port. |
| `SITO_ALLOWED_HOSTS` | *(empty)* | Extra host names the browser may use, comma-separated (e.g. `sito.lan`). `localhost`, `127.0.0.1`, `::1` and `SITO_HOST` are always allowed. `*` turns the check off. |

Command line:

```bash
sito serve --host 127.0.0.1 --port 8765 --data-dir ./sito-data
python -m sito serve          # same thing
```

## Security

sito has **no login**. Anyone who can reach the port can read your keywords, run paid API calls
and change connections (saved keys are never displayed, but they can be used). Therefore:

- keep the default `127.0.0.1` binding on your own machine;
- the provided `docker-compose.yml` publishes the port on `127.0.0.1` only — keep it that way;
- to reach it from elsewhere, put it behind something that authenticates (an SSH tunnel, a VPN, or
  a reverse proxy with authentication) and add its host name to `SITO_ALLOWED_HOSTS`. The proxy
  must pass the browser's host through (nginx: `proxy_set_header Host $host;`), otherwise the
  cross-site check below sees a different host and refuses every change.

Even on `127.0.0.1`, other websites open in your browser could try to talk to sito. Two built-in
checks stop that:

- **Cross-site requests.** Every change (a form post) must come from sito's own pages: the
  browser's `Origin` / `Sec-Fetch-Site` headers are checked, and a request from another site is
  refused with *403*. Scripts and command-line tools that send neither header are allowed.
- **DNS rebinding.** Requests addressed to an unknown host name are refused with *400*, so a
  malicious domain that re-points itself to your machine cannot read sito's pages.

Saved keys are also protected in the app itself: `env:VAR` references are resolved only in key
fields, and changing a connection's address (for example its Base URL) requires typing the key
again, so a stored key is never sent to a new address silently.

## Docker

```bash
docker compose up -d        # http://127.0.0.1:8765
docker compose logs -f
```

Everything lives in the `sito-data` Docker volume; back it up with
`docker compose cp sito:/data ./sito-backup`. Keys referenced as `env:NAME` are read from the
container environment; put them in a `.env` file next to `docker-compose.yml` (it is passed in via
`env_file`, and git-ignored).

## Backups and moving to another machine

Stop sito and copy the data folder. `sito.db` contains your projects **and saved API keys**.

## Database changes between versions

sito 0.x creates missing tables on start but does not migrate existing ones. Before upgrading,
export what you need; the changelog says when a version needs a fresh database.
