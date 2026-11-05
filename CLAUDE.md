# Conversation Analyzer

Automated quality assessment of Bolek's (Gemini Enterprise) answers, stored as derived values only
(AIENGLAB-543 / AIENGLAB-782). The spec is `design-doc.md`; the build plan, progress and every deviation from the
spec are in `plan.md`. Read `plan.md` **Status** and **Next steps** first when resuming work.

## Hard rules

- **Never touch real BigQuery.** No `bq`, no `gcloud bigquery`, no client pointed at a real project. Everything
  local and every test runs on the BigQuery emulator from `docker-compose.yml`. `gcloud` is read-only.
- **Only what runs locally lives here.** Everything in this repo must be verifiable with the emulator, fake GCS and
  the stubs. What only GCP needs (CI/CD and ops workflows, stage and prod settings, targets that reach real GCS or
  BigQuery) is written during the migration, in the official repo (`deployment-plan.md`), even if a ticket lists it.
- **No text leaves the assessor.** Stored rows hold only counts, scores, closed codes, hashes and IDs (§6.10).
  Every write goes through `bq/client.write`, which runs the leak guard (`leak_guard.py`) on every row: a column's
  `kind` in `bq/schema.py` decides what may be stored. A new column needs a kind; never add a free-text column.
- **Logs and errors carry no text either.** Log only with `safe_log.log(event, **fields)` (non-closed strings become
  `<rejected>`); never `print`/`logging` with content. Sentry gets the error class only (`errors.report`).
- **Paid calls are the exception.** Tests use `FakeJudge`. Paid Vertex calls only: the judge suite
  (`make suite-live`); spend cap 50 USD total, log each run in the **Spend log** of `plan.md`. Vertex project
  `rtb-ai-engineering-indexers`, judge location `eu` (never `global`).
- **Closed lists live in `vocab.py`.** Any value written to a code column must be a member; changing a list changes
  `closed_lists_version()`.
- **Judge changes go through `judge_versions/`.** Rubric, prompts, form schemas and models are hashed into the judge
  version ID; a new version is a new directory, kept only if the suite passes (§11.3).
- Docstrings: one line, 1–2 sentences, no `Args:`/`Returns:` sections.

## Layout

```text
config/settings.yaml   every tunable (§12.14); stage and prod run the same file in two projects. A job's own project,
                       endpoints, tokens and the run gate come from CA_* variables (local.env)
judge_versions/vN/     rubric (en, pl), prompts, models.yaml; v4 is current (`judge.current_version`)
suite_cases/           judge test suite cases (YAML, §11.1)
src/conversation_analyzer/
  cli.py               `ca <job>`: quality-assessor, quality-monitor, quality-daily, quality-weekly,
                       quality-judge-suite, quality-record, quality-alert-lookup, db-init [--check],
                       leak-audit, run-gate, dev-seed, dev-load-suite-runs
  settings.py vocab.py safe_log.py errors.py secrets.py keys.py leak_guard.py run_gate.py
  bq/                  schema (all tables), client (query, guarded MERGE writes), views, external tables, init,
                       check (live schema vs schema.py), audit (stored rows back through the leak guard)
  log/                 audit-log parsing (turns, references, spans, feedback, searches) and the window read
  judge/               forms, version, case rendering, Vertex client, fake judge, stage 1, evidence check,
                       stage 2, session grades
  docs/                content bucket reader; links resolved to documents (no search, §12.7)
  assessor/            sessions/segments, stored state, canary, the assessment run
  reporting/           monitor, daily (changes, completeness, metrics, anomaly, release, judge_quality),
                       weekly (clusters, documents, eval sets, digest), record, messages, slack
  suite/               judge test suite runner and keep rule
  devtools/            synthetic log rows and the demo scenario (emulator only)
docker/stubs/server.py Slack, GitHub and Cloud Run stubs for local runs
```

## Running

```bash
make install          # uv sync
make up               # emulator :9050, fake GCS :4443, stubs :8088, then db-init
make demo             # reset, seed the synthetic scenario, run every job once
make test             # all tests except paid ones (~10 min; needs make up)
make coverage         # same with branch coverage; fails under 90 %
make lint / make fmt
make suite-coverage   # suite cases against the §11.1 scenario minimums (no judge)
make suite LIMIT=20   # the suite runner with the fake judge (free)
make suite-restore    # load the stored suite runs (suite_reports/) back into a reset emulator
make db-check         # live emulator schema vs bq/schema.py (`ca db-init --check`)
make leak-audit SINCE=2026-10-01   # stored rows back through the leak guard; counts only
make help             # every target
```

`uv run ca quality-assessor --dry-run` reads the window and writes only the run record. Stage and prod run the same
code: no environment switch, no dataset prefix; `CA_PROJECT` (required) names the job's own project. A test that needs
a deployed job's settings uses the `deployed` fixture in `tests/test_environments.py`; the run gate is tested on fake
GCS (`gate` fixture there).

## Judge test suite (§11)

- Cases: `suite_cases/cases/*.yaml` (drafted, `reviewed: false` until an engineer checks them), corpus in
  `suite_cases/documents.yaml`, weights and minimums in `suite_cases/suite.yaml`. Any change there is a new suite
  version, and the next full run of it is a new BASELINE.
- `tests/test_suite.py` runs an oracle judge (every form filled with the expected values) over all cases: it must stay
  at distance 0, so a case whose expected form contradicts the deterministic rules fails the tests.
- Never look at held-out cases (`part: HELD_OUT`) while tuning a judge version.
- A judge change: copy `judge_versions/vN` to a new directory, edit, run `make suite-live JUDGE_VERSION=vN+1`
  (paid, ~7 USD and ~35 min per pass; log it in plan.md). The run prints KEEP or REJECT (§11.3). The local
  emulator forgets runs on reset: `make suite-restore` loads them back from `suite_reports/` first.
- Reports in `suite_reports/` (gitignored) hold per-case field distances and the judge's codes (no text).

Single test: `uv run pytest -q -p no:logging --no-cov tests/test_assessor_e2e.py::test_segments`.
The tests load `local.env` themselves; for `uv run ca ...` by hand run `set -a; . ./local.env; set +a` first.
`CA_NOW=2026-10-28T12:00:00+00:00` pins the clock of a job.

## Emulator (goccy/bigquery-emulator) pitfalls

- Never drop tables or datasets on it: it corrupts the catalog. Reset = `make db-reset` (container restart).
- It slows down as its job history grows (`SELECT 1` goes from 0.3 s to 2+ s over a long session), and refusing a
  duplicate `CREATE TABLE IF NOT EXISTS` takes ~5 s. `make test`/`make coverage` reset it first; `create_all` only
  creates missing tables, and the reused staging tables `_stg_<table>` are made there, not on every write.
- `CREATE TABLE IF NOT EXISTS` doesn't add new columns: after a schema change run `make db-reset`.
- No load jobs, no array-of-struct params, MERGE needs a table source, `SELECT *` of nested repeated structs
  fails, numeric params must be strings. All are handled in `bq/client.py`; the full table is in `plan.md`
  (**Emulator quirks**).
- Tests read nested rows with `TO_JSON_STRING` (see `rows()` in `tests/test_assessor_e2e.py`).
- It keeps no partitioning from DDL and returns view SQL rewritten (so `db-init --check` checks those two only on
  real BigQuery), and its `TO_JSON_STRING` writes dates unquoted, booleans as 0/1 and a struct inside a repeated
  struct as a list of one-key objects (`bq/audit.py` undoes all three).

## Testing conventions

- Markers: `emulator` (needs `make up`), `live` (paid, excluded by default via `addopts`).
- Synthetic turns script the fake judge with markers in their text: `[[fake codes=CONTRADICTED_CLAIM severity=HIGH
  why=CHUNKING_ISSUE]]` (keys in `judge/fake.py`).
- `tests/conftest.py::wipe()` empties tables (DELETE, never DROP).
- Vertex code is tested with `httpx.MockTransport`; nothing in the default test run reaches the network beyond
  localhost.

## Git

Work for the deployment happens on branches off `main`, one per ticket in `jira/`, merged by PR. Update
`deployment-plan.md` (checkboxes, Status, Spend log) in the same PR. The `aiel-content-indexers` submodule is gone:
there is no document index any more.
