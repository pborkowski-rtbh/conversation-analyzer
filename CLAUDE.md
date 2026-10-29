# Conversation Analyzer

Automated quality assessment of Bolek's (Gemini Enterprise) answers, stored as derived values only
(AIENGLAB-543 / AIENGLAB-782). The spec is `design-doc.md`; the build plan, progress and every deviation from the
spec are in `plan.md`. Read `plan.md` **Status** and **Next steps** first when resuming work.

## Hard rules

- **Never touch real BigQuery.** No `bq`, no `gcloud bigquery`, no client pointed at a real project. Everything
  local and every test runs on the BigQuery emulator from `docker-compose.yml`. `gcloud` is read-only.
- **No text leaves the assessor.** Stored rows hold only counts, scores, closed codes, hashes and IDs (§6.10).
  Every write goes through `bq/client.write`, which runs the leak guard (`leak_guard.py`) on every row: a column's
  `kind` in `bq/schema.py` decides what may be stored. A new column needs a kind; never add a free-text column.
- **Logs and errors carry no text either.** Log only with `safe_log.log(event, **fields)` (non-closed strings become
  `<rejected>`); never `print`/`logging` with content. Sentry gets the error class only (`errors.report`).
- **Paid calls are the exception.** Tests use `FakeJudge` and `FakeEmbedder`. Paid Vertex calls only: the judge
  suite (`make suite-live`) and small real-embedding index runs; spend cap 50 USD total, log each run in the
  **Spend log** of `plan.md`. Vertex project `rtb-ai-engineering-indexers`, judge location `eu` (never `global`).
- **Closed lists live in `vocab.py`.** Any value written to a code column must be a member; changing a list changes
  `closed_lists_version()`.
- **Judge changes go through `judge_versions/`.** Rubric, prompts, form schemas and models are hashed into the judge
  version ID; a new version is a new directory, kept only if the suite passes (§11.3).
- Docstrings: one line, 1–2 sentences, no `Args:`/`Returns:` sections.

## Layout

```text
config/settings.yaml   every tunable (§12.14); env-specific values come from CA_* variables (local.env)
judge_versions/v1/     rubric (en, pl), prompts, models.yaml
suite_cases/           judge test suite cases (YAML, §11.1)
src/conversation_analyzer/
  cli.py               `ca <job>`: quality-assessor, quality-monitor, quality-daily, quality-weekly,
                       quality-judge-suite, quality-record, quality-alert-lookup, db-init, dev-seed
  settings.py vocab.py safe_log.py errors.py secrets.py keys.py leak_guard.py
  bq/                  schema (all tables), client (query, guarded MERGE writes), views, external tables, init
  log/                 audit-log parsing (turns, references, spans, feedback, searches) and the window read
  pii/                 Presidio en/pl scrubber with per-session placeholders
  judge/               forms, version, case rendering, Vertex client, fake judge, stage 1, evidence check,
                       stage 2, session grades
  docs/                content bucket reader, embedder, document index search
  assessor/            sessions/segments, stored state, canary, the assessment run
  reporting/           monitor, daily, weekly, record, alerts
  suite/               judge test suite runner and keep rule
  devtools/            synthetic log rows and the demo scenario (emulator only)
docker/stubs/server.py Slack, GitHub and Cloud Run stubs for local runs
aiel-content-indexers/ git submodule (branch AIENGLAB-782): the doc-index sink (§12.7); its own CLAUDE.md applies
                       there (Python 3.14, line length 100)
```

## Running

```bash
make install          # uv sync (pulls the spaCy lg models, ~1 GB)
make up               # emulator :9050, fake GCS :4443, stubs :8088, then db-init
make demo             # reset, seed the synthetic scenario, run every job once
make test             # all tests except paid ones (~5 min; needs make up)
make coverage         # same with branch coverage; fails under 90 %
make lint / make fmt
make help             # every target
```

Single test: `uv run pytest -q -p no:logging --no-cov tests/test_assessor_e2e.py::test_segments`.
The tests load `local.env` themselves; for `uv run ca ...` by hand run `set -a; . ./local.env; set +a` first.
`CA_NOW=2026-10-28T12:00:00+00:00` pins the clock of a job.

## Emulator (goccy/bigquery-emulator) pitfalls

- Never drop tables or datasets on it: it corrupts the catalog. Reset = `make db-reset` (container restart).
- It slows down as its job history grows (`SELECT 1` goes from 0.3 s to 2+ s over a long session), and refusing a
  duplicate `CREATE TABLE IF NOT EXISTS` takes ~5 s. `make test`/`make coverage` reset it first; `create_all` only
  creates missing tables, and the reused staging tables `_stg_<table>` are made there, not on every write.
- `CREATE TABLE IF NOT EXISTS` doesn't add new columns: after a schema change run `make db-reset`.
- No `VECTOR_SEARCH`, no load jobs, no array-of-struct params, MERGE needs a table source,
  `SELECT *` of nested repeated structs fails, numeric params must be strings. All are handled in `bq/client.py`
  and `docs/index.py`; the full table is in `plan.md` (**Emulator quirks**).
- Tests read nested rows with `TO_JSON_STRING` (see `rows()` in `tests/test_assessor_e2e.py`).

## Testing conventions

- Markers: `emulator` (needs `make up`), `live` (paid, excluded by default via `addopts`).
- Synthetic turns script the fake judge with markers in their text: `[[fake codes=CONTRADICTED_CLAIM severity=HIGH
  why=CHUNKING_ISSUE]]` (keys in `judge/fake.py`).
- `tests/conftest.py::wipe()` empties tables (DELETE, never DROP).
- Vertex code is tested with `httpx.MockTransport`; nothing in the default test run reaches the network beyond
  localhost.

## Git

Branch `AIENGLAB-782` here and in the submodule. Commit and push both after each milestone; update `plan.md`
(checkboxes, Status, Spend log) in the same commit.
