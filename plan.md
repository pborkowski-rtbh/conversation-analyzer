# Implementation plan: Conversation Analyzer

Source of truth: `design-doc.md`. Every checkbox below traces to a section (§) of it. Mark `[x]` when done
and tested; add a short note when something deviates. To resume: read **Status** and **Handover**, then the first
unchecked item of the current milestone.

## Status (2026-10-29, end of session 1)

- Branch `AIENGLAB-782` in this repo; submodule `aiel-content-indexers` checked out on its own branch `AIENGLAB-782`
  (from its `origin/main` at 2b92f03), **no changes in the submodule yet**.
- M0 and M1 done. M2 mostly done: the whole assessor path runs end to end on the emulator (`tests/test_assessor_e2e.py`).
  Big parts of M3 and M4 (evidence check, stage 2, session grades, canary, planted errors, second model) are already
  written inside the assessor and covered by the e2e test.
- `uv run pytest -q --no-cov -p no:logging tests/` → **41 passed** (needs `docker-compose up -d`; ~5 min, spaCy lg models).
- Coverage not measured yet; target > 90 % (`fail_under = 90`). Many modules only have e2e coverage so far.
- Paid Vertex spend so far: **0 USD** (cap 50 USD until 2026-11-01). No real model was called yet.

## Next steps, in order

1. `Dockerfile`, `Makefile` (all targets, see **Make targets planned**), `CLAUDE.md`, `.gitignore`; commit + push.
2. Unit tests to reach > 90 % coverage for what exists (judge client with `httpx.MockTransport`, stage1/stage2 rules,
   sessions edge cases, pii, docs, canary mutations, embedder, content reader with fake GCS).
3. `reporting/monitor.py` (pipeline health per run + hourly log gaps + alerts to the team alerts channel) — finishes M2.
4. M3: indexer sink change in the submodule (Python 3.14, line length 100, its own CLAUDE.md rules) + local run to emulator.
5. M4: judge test suite (case format, cases, scoring, runner, keep rule), live run on flash + argon (spend cap).
6. M5–M7: daily, weekly, record, alerts, digest, anomalies, release impact, eval documents.
7. Feedback-after-window fallback (§12.5): setting exists (`timing.feedback_after_window_fallback`), code path not
   written (currently only counted in `quality_runs.feedback_after_window`).
8. `make pii-eval`: synthetic Polish/English PII set with inflected names + recall measurement (§6.12).

## Decisions (interview, 2026-10-29)

| Topic | Decision |
|---|---|
| Scope | All of `design-doc.md` except Terraform (§12.14) and the Grafana dashboard JSON (§8.8). BigQuery DDL for every dataset, table and view is kept in this repo (needed to run anything). IAM, service accounts, Cloud Run job and Scheduler definitions are not written. |
| Evaluator (AIENGLAB-519) | Out of scope. We define the `aiel_evals` contract we expect (`bq/external.py`: `aiel_evals.results`, `aiel_evals.gate_results`) and build only our side (§12.11). |
| BigQuery | Never the real one. Local and tests use the BigQuery emulator in docker compose. `gcloud` is read-only. |
| Indexer sink (§12.7) | `aiel-content-indexers` is a git submodule; the doc-index step is added there on branch `AIENGLAB-782`. Local indexer runs write vectors to the emulator only, never to real data stores or the bucket. |
| Models | Tests: fake judge + fake embedder. Paid calls only: judge suite on `gemini-3.8-flash` and `gemini-4-argon` (`eu`), and small real-embedding runs. Vertex project `rtb-ai-engineering-indexers`. Full index fill is one switch. Spend cap 50 USD total. |
| Judge suite cases | Written by Claude against the rubric, all `reviewed: false` until an engineer checks them (§11.1). |
| Git | Commit and push both repos after each milestone. |
| Stack | Python 3.12, uv, one image, one CLI (`ca`) with a command per job. Presidio + spaCy `en_core_web_lg` / `pl_core_news_lg` (wheels pinned in `pyproject.toml`). |
| Tests | > 90 % code coverage (branch coverage, `fail_under = 90`), also for new code in the indexers submodule. Paid-model code is tested with mocked transports. |
| Data stores | The production engine's current `rtb-crj-*` set (from `aiel-infrastructure/modules/agentspace-engines` and `infrastructure/terraform/rtbhouse-agentspace`), not the `*-v2` ones of the older analyses. |

## Handover: what exists and how it fits

```text
config/settings.yaml          all tunables (§12.14); env-specific values from CA_* vars (settings.py, local.env)
judge_versions/v1/            rubric/{stage1,stage2,session}.{en,pl}.md, prompts/*.md, models.yaml
src/conversation_analyzer/
  settings.py   get_settings() (cached), now() (CA_NOW pins time), REPO_ROOT
  vocab.py      every closed list (StrEnum), Metric names, strata codes, all_closed_values(), closed_lists_version()
  safe_log.py   log(event, **fields): only counts/codes/IDs survive, else "<rejected>"
  errors.py     AnalyzerError(+subclasses) with ErrorClass; report() sends class only to Sentry; scrub_event()
  secrets.py    secret(name, project) from Secret Manager or CA_SECRET_<NAME> (local)
  keys.py       session_key / turn_key = HMAC (32 hex), parse_answer_name, stable_fraction (samples)
  leak_guard.py check_row(table,row) by column kind; people directory + non-allowlisted docs dropped
  bq/schema.py  ALL tables of §12.10 as Table/Col (kind = leak-guard rule); ddl(); chunk_table(ds)
  bq/external.py audit_logs, ge_metrics, aiel_evals.* (emulator copies only)
  bq/views.py   channel_sql, canary_prefix_sql, engine_filter, the 3 authorized views
  bq/client.py  query(sql, **params), write(table, rows) = leak guard → staging → one MERGE; additive cols
  bq/init.py    create_all() (datasets via get-then-create, tables, views)
  log/parse.py  Turn/Reference/Span/Feedback/Search from audit_logs rows; linked_urls()
  log/reader.py read_window(now, feedback_since, search_since, search_until)
  pii/scrubber.py PiiMap (placeholders per session, Polish stems, surname alias, apply() to documents), scrub()
  pii/presidio.py PresidioAnalyzer: names only from the main language model, trimmed; patterns from both
  judge/forms.py  Stage1Form, EvidenceCheckForm, Stage2Phrasings (in memory only), Stage2Form, SessionGradeForm
  judge/version.py load(name) → JudgeVersion(version_id = name-hash(rubric,prompt,form,models)); current/previous
  judge/case.py   JudgeCase (what the judge sees), DocRef/DocText, DocumentSource protocol, render_turn()
  judge/client.py VertexJudge (REST, aiplatform.eu.rep.googleapis.com, 429 backoff, Usage tokens, token limit),
                  vertex_schema(), generate_validated() (retry once), default_judge()/set_judge()
  judge/fake.py   FakeJudge scripted by markers "[[fake key=value ...]]" in synthetic turn text
  judge/stage1.py apply_rules(): gating, topic, deterministic codes, primary order, severity; Stage1Result
  judge/evidence.py the evidence check (links in answer + index search, read ≤3, contradiction → HIGH)
  judge/stage2.py phrasings call → search with ≥2 phrasings → form → cause path by rule (§7.3) → Stage2Result
  judge/session.py grade(): provisional/final; not_gradable(); counted rephrases; recovered rule
  docs/content.py ContentReader: gs://<bucket>/<ds>/<sha256(uri)>.enc, Fernet PBKDF2 1.2M iterations
  docs/embedder.py FakeEmbedder (hashed bag of words), VertexEmbedder (predict, EU region)
  docs/index.py   DocumentIndex: search_many (VECTOR_SEARCH / emulator COSINE_DISTANCE), cache+prefetch,
                  lookup_uri, data_stores_of; SessionDocuments view applies the session's placeholders
  assessor/sessions.py plan_session(): segments (sticky stored numbers), positions, gaps, context, close states
  assessor/state.py load(session_keys, today) stored rows; stage1_from_row; window_cutoffs
  assessor/canary.py question_hash, expected_documents (aiel_evals), planted mutations, caught()
  assessor/run.py AssessmentRun.execute(): plan → phase1 (stage 1 + 5 % second model) → phase2 (evidence)
                  → flags (late triggers, reactions) → phase3 (stage 2 + grades) → canary → write_all → run record
  devtools/synthetic.py SynthTurn → audit_logs rows; search/change rows; index_documents() (bucket + chunks)
  devtools/scenario.py  demo window that walks every path; seed(now)
  cli.py        ca quality-assessor|quality-monitor|quality-daily|quality-weekly|quality-judge-suite|quality-record|db-init
                (monitor/daily/weekly/suite/record modules NOT written yet)
docker-compose.yml  bigquery (goccy emulator :9050), gcs (fake-gcs-server :4443), stubs (:8088)
docker/stubs/server.py Slack (chat.postMessage, reactions.get), GitHub commits, Cloud Run executions; /_test/*
local.env      all CA_* values for local runs and tests (tests/conftest.py loads it, never real endpoints)
tests/         test_foundations.py, test_bq.py, test_assessor_e2e.py (module fixture seeds + runs the assessor)
```

### How to run (until the Makefile exists)

```bash
docker-compose up -d                     # emulator, fake GCS, stubs
set -a; . ./local.env; set +a
uv run ca db-init                        # creates all datasets/tables/views on the emulator
uv run pytest -q --no-cov -p no:logging tests/
docker-compose restart bigquery          # = full reset of the emulator (in memory); needed after a schema change
```

### Emulator quirks (all handled in code; keep in mind)

| Quirk | Handling |
|---|---|
| No `VECTOR_SEARCH`, no `ML.DISTANCE` | `docs/index.py` uses `COSINE_DISTANCE` + `QUALIFY` on the emulator, `VECTOR_SEARCH` in BigQuery |
| No `CREATE SCHEMA` via query; existing dataset → 500, not 409 | `bq/init.py`: get_dataset, create on NotFound |
| MERGE source must be a table | `bq/client.write`: staging table, then MERGE |
| No load jobs | streaming `insert_rows_json` into staging on the emulator; load job with WRITE_TRUNCATE in prod |
| Dropping tables/datasets panics and corrupts the emulator | emulator staging tables are reused (`_stg_<table>`, emptied with DELETE), never dropped; reset = restart container |
| Numeric query params must be JSON strings; array-of-struct params unsupported | `_EmulatorScalar/_EmulatorArray` stringify; vectors are inlined as literals |
| Retries on 500 hang forever | `retry()` deadline 20 s on the emulator |
| `SELECT *` of nested repeated structs (stage 2 `claims[].documents[]`) fails | code selects only needed columns; tests read `TO_JSON_STRING(t)` |
| `TO_JSON_STRING` writes dates unquoted and BOOL as 0/1 | test helper `rows()` normalizes with the schema |
| `CREATE TABLE IF NOT EXISTS` doesn't add new columns | restart the emulator after schema changes |

### Make targets planned

`help, up, down, db-init, db-reset, seed, run-assessor, run-monitor, run-daily, run-weekly, record, alert-lookup,
suite, suite-coverage, suite-live, pii-eval, index-local (FULL=1), test, coverage, lint, fmt, build`.

---

## M0. Scaffolding

- [x] Branch + submodule on `AIENGLAB-782`
- [x] `pyproject.toml` (uv), package skeleton, ruff (SIM108 ignored), pytest, pytest-cov `fail_under = 90`
- [x] `docker-compose.yml`: BigQuery emulator, fake GCS, stub servers (Slack, GitHub, Cloud Run executions)
- [x] Verify emulator capabilities; gaps recorded in **Emulator quirks**
- [ ] `Dockerfile` (one image, spaCy models), `Makefile`, `CLAUDE.md`, `.gitignore`

## M1. Foundations (§12.16 milestone 1)

- [x] Settings in one place (§12.14) — `config/settings.yaml`
- [x] Closed lists with a version (§6.4, §6.7, §7.4, §7.7) — `vocab.py`
- [x] Logging wrapper; test that planted text never appears in logs (§12.13)
- [x] Sentry: error class only (§12.13)
- [x] Leak guard + planted-PII test (§6.10) — unit tests + e2e `test_no_text_is_stored`
- [x] Keys (§12.5)
- [x] BigQuery DDL for all tables of §12.10 + authorized-view SQL + `aiel_evals` contract + emulator copies
- [x] `ca db-init`; MERGE writer keyed by table key (§12.6)
- [ ] CLI: job modules for monitor, daily, weekly, judge-suite, record (commands exist, modules don't)
- [x] Done when: an assessor run writes its run record (§12.16)

## M2. Stage 1 in shadow (§12.16 milestone 2)

- [x] Synthetic `audit_logs` generator matching the real schema (`devtools/synthetic.py`, `devtools/scenario.py`)
- [x] Window read (§12.6)
- [x] Channel rule; canary by `LTRIM` prefix + accounts
- [x] Sessions & segments, positions, gap buckets, resumed, earlier text missing (§5)
- [x] Session facts per segment (§5.4)
- [x] Context (§5.3), incl. labels/scores of erased earlier turns
- [x] Eligibility, too large, missed (§2.3, §6.3)
- [x] Pace check (§8.2)
- [x] PII scrubbing (Presidio, en/pl, custom recognisers, inflected names, placeholders in documents) (§6.3, §12.13)
- [ ] Polish/English synthetic PII test set + recall measurement (`make pii-eval`) (§6.12)
- [x] Judge client: `eu` only, temperature 0, structured output, 429 backoff, throttled count, tokens, daily limit
- [x] Stage 1 form + rubric en/pl + gating + deterministic codes + primary order + severity + topic (§6.4–§6.8)
- [x] Evidence kind, verifiable, people directory excluded (§6.2, §6.6)
- [x] Answer spans and span counts (§6.4)
- [x] Fingerprint; late-arriving earlier turn re-assesses later ones (§6.1)
- [x] Relation → previous turn's reaction (§5.3)
- [x] Feedback in window: thumbs + reason codes, comment never; dislike = late trigger
- [ ] Feedback after window: fallback by session key + question index behind the setting (§12.5)
- [x] Work list incl. parallel run doubling, 5 % second-model sample, missed at 3h30 (§12.6)
- [x] Phase 1 concurrency + 7-minute stop (§12.6)
- [x] Retrieval counts per document and day (§12.6)
- [x] Run record in `quality_runs` (§12.10, §12.12) — plus `covered`, `search_cutoff`, `feedback_cutoff`
- [ ] `quality-monitor`: pipeline health per run + hourly log gap check + pipeline-health alerts (§9.2, §12.8)
- [ ] Unit tests to > 90 % coverage

## M3. Documents and stage 2 (§12.16 milestone 3)

- [ ] Indexer sink in the submodule (§12.7): chunk at headings, split > ~2,000 chars with overlap, title prefix; embed
  (EU); one table per data store (`quality_chunks_<ds with - → _>`, schema = `bq/schema.CHUNK_COLS`); add before
  delete; one delete at end of a complete run; nothing deleted after a partial run; embedding failure never breaks
  indexing; full reindex embeds docs without vectors for current text; people directory skipped
- [ ] Local indexer runs write vectors to the emulator (`make index-local`, small by default; `FULL=1` full fill)
- [x] Content bucket reader (Fernet, path rule, cap) — `docs/content.py`
- [x] Document index search (`VECTOR_SEARCH` / emulator cosine), top 10, people directory excluded
- [x] Evidence check (§6.9)
- [x] Flagging + late triggers, flagged at most once (§7.1)
- [x] Stage 2 (§7.2–§7.5), cause path by rule, document to fix, findings confirmed/dropped
- [x] Stage 2 kept beside stage 1 (§7.6)
- [x] Session grades: provisional / final / not gradable; re-grade at close (§7.7)
- [x] Phase 3 time budget, pending first, give up at 3h30 (§12.6)
- [ ] Done when: index hit rate and flagged share are measured (daily job, M5)

## M4. Judge trust (§12.16 milestone 4)

- [ ] Suite case format (YAML in `suite_cases/`): fixed input incl. search results + expected forms, `reviewed`, `part`
- [ ] Cases meeting every scenario minimum (§11.1); coverage checker
- [ ] Scoring (§11.2), 3 runs averaged, per case/field/scenario
- [ ] Keep rule (§11.3) → `quality_judge_suite_runs`; 70 % reliability → `experimental`
- [ ] Live suite run on `gemini-3.8-flash` + `gemini-4-argon` (spend cap!)
- [x] Canary assessed like real turns, `quality_canary_results` with question hash (§11.4) — agreement is daily (M5)
- [x] Planted errors (swapped number, dropped step, wrong name), with and without references (§11.4)
- [x] Index hit rate per canary question (expected doc in top 10) (§11.4)
- [x] Second-model check on 5 % → `quality_judge_checks` (§11.5)
- [x] Judge versions: hash, first use recorded; parallel run assesses with both (§6.11, §12.14)

## M5. Metrics (§12.16 milestone 5)

- [x] Authorized views SQL (§12.4)
- [ ] Log completeness (§8.2)
- [ ] Change events from 5 sources (§12.9)
- [ ] Daily metrics (§8.1–§8.5), standardized AQR (§8.4), judge quality measures (§11.4, §11.5), recompute-not-add

## M6. Alerts, clusters, digest (§12.16 milestone 6)

- [ ] Anomaly check + alerts + ✅ acknowledgement (§8.6, §8.7, §12.8)
- [ ] `HIGH` cluster alerts with session grades; alert lookup (§7.7, §9.2, §12.8)
- [ ] Release impact (§10.3)
- [ ] Weekly clusters, document stats, digest (§9)

## M7. Closed loop (§12.16 milestone 7)

- [ ] `quality_eval_documents` (§10.1, §12.11); gate verdicts in digest; turns still in baseline top clusters (§9.3)

## Final

- [ ] `CLAUDE.md` complete; `make help` lists every target; `make test` + coverage green
- [ ] Requirement sweep: re-read `design-doc.md` section by section against this plan

---

## Deviations and assumptions

| Topic | Resolution in code |
|---|---|
| Data stores | `rtb-crj-*` + Drive + people directory (`rtb-crj-associates`, `people-connections_*`); new topic `DOC_REPO`. Content bucket `rtbhouse-agentspace-mcp-document-content`, content secrets in `rtbhouse-agentspace` (Terraform of `infrastructure`). Indexer jobs `indexer-*` in `europe-west4`. |
| Channel | `agentsSpec` → WEB_UI; `query.text` → SLACK_MCP; anything else → WEB_UI. Canary turns have `query.text`, so they carry SLACK_MCP but are excluded via `is_canary`. |
| Feedback reasons | Google's list is not known; a provisional closed list in `vocab.FeedbackReason`, anything else stored as `UNRECOGNIZED`. |
| Employee IDs | Pattern is a placeholder (`pii.employee_id_patterns`), to confirm with HR. |
| Engine change methods | List in `engine_change_methods` is a guess at the export's admin method names. |
| Stage 2 phrasings | "Question and problem claim" search needs claims: one extra in-memory judge call (`Stage2Phrasings`) lists ≤3 claims as search phrases; never stored. Fallback phrasing: first 500 chars of the answer. |
| Stage 2 found documents | Reads up to `sizes.stage2_found_documents` (5) found documents besides all cited ones. |
| Cause path | Judge answers the yes/no path questions; `stage2._cause` derives the why. A turn without references starts at question 3 (§7.3). |
| Canary planted share | `canary.planted_share` = 0.25 (6 extra judge calls per planted canary turn). |
| Retrieval counts | Only document IDs the index resolves to an allowlisted data store are counted (people directory never). |
| Cut-offs | Searches counted once via `quality_runs.search_cutoff` (now − 15 min) and feedback via `feedback_cutoff`. |
| Names in PII | Names only from the main-language model, honorifics trimmed, identifier-like tokens (all caps, `_`) excluded; allow list (`Bolek`, `Gemini`, …). |
| Vertex | REST calls (`aiplatform.eu.rep.googleapis.com` for `eu`), like the evaluator; `responseSchema` from the pydantic form. |
| Fake judge | Scripted by `[[fake key=value]]` markers in synthetic text (see `judge/fake.py`). |

## Spend log (paid Vertex calls, cap 50 USD)

| Date | What | Model | Tokens in / out | Est. USD |
|---|---|---|---|---|
| — | nothing yet | — | — | 0 |
