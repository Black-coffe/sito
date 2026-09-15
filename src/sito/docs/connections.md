# Connections and API keys

A **connection** is one configured external service: an API key plus its options. Steps ask for a
connection of a certain kind, so any provider of that kind works with any step:

| Kind | Used by | Built-in connectors |
|---|---|---|
| Language model (`llm`) | AI classification, AI cluster naming | OpenAI / OpenAI-compatible, Anthropic Claude |
| Search results (`serp`) | Collect SERP | XMLRiver (Google), Serper.dev (Google) |
| Search suggestions (`suggest`) | Autocomplete expansion | Google Autocomplete (no key) |

## Adding a connection

1. *Connections → Add connection*, pick a provider.
2. The right-hand panel explains where to get the key and what to fill in; **Get a key** opens the
   provider's site.
3. Paste the key, adjust the options, press **Save and test**. The test makes one small real request
   and shows the answer or the provider's error.
4. In a step's settings, choose the connection from the drop-down. New steps pre-select the first
   matching connection.

You can have several connections of the same provider (a personal and a work key, two models, a
local and a cloud LLM) and pick per step.

## Where keys are stored

- Keys typed into the form are saved in the local SQLite database (`sito-data/sito.db` by
  default) on your computer, and sent only to the address configured in that connection when a
  step or a test runs. Changing the address (e.g. the Base URL) requires typing the key again.
- After saving, a key is never sent back to the browser: the form shows `Saved ••••1234 — leave
  blank to keep`.
- To keep keys out of the database entirely, type `env:VARIABLE_NAME` instead of the key, e.g.
  `env:OPENAI_API_KEY`. sito reads the variable every time the connection is used. With Docker,
  put the variables in a `.env` file next to `docker-compose.yml`.
- The database holds your keys: don't commit it, and back it up like any secret. `sito-data/` is in
  `.gitignore`.

## Providers

### OpenAI and OpenAI-compatible servers

The *OpenAI / OpenAI-compatible* connector talks to anything that implements the OpenAI Chat
Completions API. Change **Base URL** to switch provider:

| Provider | Base URL | Key |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | <https://platform.openai.com/api-keys> |
| OpenRouter | `https://openrouter.ai/api/v1` | <https://openrouter.ai/keys> |
| DeepSeek | `https://api.deepseek.com` | <https://platform.deepseek.com/> |
| Ollama (local) | `http://localhost:11434/v1` | none — leave empty |
| LM Studio (local) | `http://localhost:1234/v1` | none — leave empty |

Base URLs as documented by each provider (checked September 2026). Model names change often; use
the provider's model list. **JSON mode** asks the server for a JSON object; turn it off if a local
server rejects `response_format`.

Local models (Ollama, LM Studio) cost nothing per request and keep data on your machine; they are
slower and less accurate on nuanced relevance scoring. A good pattern is a cheap model for bulk
classification and a stronger one for cluster naming.

### Anthropic Claude

Key from <https://console.anthropic.com/>. The default model is a fast, inexpensive one suitable
for bulk classification; switch the model name for higher quality.

### XMLRiver (Google results)

Sign up at xmlriver.com; your user id and key are on the account's queries page. `country`, `lr`
(language), `domain` (Google domain) and `loc` take the numeric ids from XMLRiver's reference
files linked in their API documentation. XMLRiver returns the top 10 results.

### Serper.dev (Google results)

Sign up at <https://serper.dev>; the key is in the dashboard. `gl` is the country code and `hl` the
interface language (`us` / `en`, `ua` / `uk`, `de` / `de`, …).

### Google Autocomplete

Needs no key and is created automatically. It uses Google's public suggestion endpoint, which is
unofficial: keep the pause between requests, expect occasional blocking on large runs, and make sure
your use complies with Google's terms.

## Costs, roughly

- AI classification sends one request per batch of keywords (50 by default): 10,000 keywords ≈ 200
  requests. Check your provider's pricing for the model you choose.
- SERP collection is one request per keyword.
- Every run's token or request counts appear on the run page.

## Adding a provider

A connector is a short Python class. See [Writing plugins](/docs/writing-plugins).
