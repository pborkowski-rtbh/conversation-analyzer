# Implementation plan: Conversation Analyzer

Source of truth: `design-doc.md`. Every checkbox below traces to a section (§) of it. Mark `[x]` when done
and tested; add a short note when something deviates. To resume: read **Status** and **Handover**, then the first
unchecked item of the current milestone.

## Status (2026-10-30, session 5)

- Branch `AIENGLAB-782` here and in the submodule `aiel-content-indexers` (also `AIENGLAB-782`, from its `origin/main`
  2b92f03). Both pushed; the submodule is unchanged since session 2 (48dc7ad).
- Milestones M0–M7 done in code and tests (see the checklists). `make index-local` ran (fake and real embeddings),
  `make demo` runs end to end (~50 s). §11.3 now applied strictly: experimental labels neither alert nor rank.
- Judge: the suite (264 drafted cases, `reviewed: false`) ran live twice: v1 BASELINE, v2 KEEP (tuning 0.77 → 0.46,
  held-out 1.47 → 1.15, false HIGH 4 → 4, missed HIGH 6 → 0). Settings name v2 as current. Only REASONING_ERROR is
  below 70 % recall (experimental). Cases that look like drafting mistakes, for the engineer review:
  `budget_tab-contradicted` (the "wrong" answer is not strictly contradicted), the `*-reasoning` cases (stage 1
  judges them contradicted, the drafts say unsupported), `people-7` and `unclear-unstated-1` (intent).
- Tests: `make coverage` (~15 min, 98.37 %, 229 tests), `make test-unit` 10 s.
- Paid Vertex spend: **14.51 USD** of the 50 USD cap (Spend log below).

## Next steps, in order

Session 5 (2026-10-30, branch `AIENGLAB-782_v2`, fresh clone: `uv sync`, `git submodule update --init`, stack started).
The Makefile and `tests/conftest.py` fall back to `docker compose` when `docker-compose` is missing. `make lint` and
`make test-unit` pass.

1. Done (session 5): `make coverage` 228 tests, 98.10 % (15 min). One flaky test fixed: suite run IDs had seconds +
   random suffix, so "latest run" was random for two runs in one second; IDs now carry microseconds after the seconds.
2. Done (session 5, on the user's request): `make build` builds the image (1.64 GB); see Final for the checks run in it.
3. Requirement sweep of design-doc.md against the code, section by section (done by hand in session 5; the agents
   were stopped): [x] §1-5 + §12.5-12.6; [x] §6-7; [x] §8-10 + §12.8-12.9; [x] §11 + §12.1-4, 12.7, 12.10-17.
   Spot checks of every concrete rule (settings, closed lists, metrics, health checks, access rules, tables) against
   the code. Gaps found and fixed: KNOWLEDGE_GAP was not shown with its miss rate (§7.5, §11.4): the digest prints
   the week's canary miss rate on every KNOWLEDGE_GAP cluster; quality-daily did not read the release gate verdicts
   (§12.11): `quality_release_impact.gate_verdict` now carries them for the dashboard. New deviation rows below:
   gate verdicts, anchor set rotation, release impact slices. Schema change: `make db-reset` before local runs.
4. Done (session 5) except the push: CLAUDE.md complete, `make help` lists every target, `make coverage` green at
   98.37 % (229 tests). The submodule is unchanged (48dc7ad on `origin/AIENGLAB-782`); this repo's commits are on the
   local branch `AIENGLAB-782_v2`, not pushed yet.

Budget note: 9 USD of conversation budget left when this was written; paid Vertex spend is 14.51 of 50 USD (no further
paid runs are needed for the steps above).

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
  reporting/slack.py   post(), reactions() (Slack Web API; stub locally); errors → ErrorClass.SLACK
  reporting/results.py results(where, version, **params): one result per turn (stage 2 else stage 1) via SQL;
                       ClusterKey/cluster_key() (§9.1): doc to fix / single cited doc / topic; cluster_id
  reporting/messages.py templates: high_cluster, health, session_line, acknowledged (derived values only)
  reporting/monitor.py Monitor.execute(): check_runs (per-run health + alerts), check_log_hour, high_cluster_alerts,
                       acknowledgements; deterministic alert IDs; writes ALERTS, ALERT_SESSIONS, PIPELINE_HEALTH, ACKS
  reporting/lookup.py  lookup(alert_id) for `ca quality-alert-lookup`
  suite/cases.py  SuiteCase/Expected*/Suite, load_suite(), scenarios(), coverage()/short(); suite/scoring.py distances
  suite/runner.py SuiteRun.run_case (live path on fixed documents), summarize, decide (keep rule), run() → row+report
  cli.py        ca quality-assessor|quality-monitor|quality-daily|quality-weekly|quality-judge-suite|quality-record|
                quality-alert-lookup|db-init|dev-seed|dev-load-suite-runs
docker-compose.yml  bigquery (goccy emulator :9050), gcs (fake-gcs-server :4443), stubs (:8088)
docker/stubs/server.py Slack (chat.postMessage, reactions.get), GitHub commits, Cloud Run executions; /_test/*
local.env      all CA_* values for local runs and tests (tests/conftest.py loads it, never real endpoints)
tests/         unit: foundations, vertex, cli, canary, judge_rules, parse, pii, sessions, reporting_units;
               emulator: bq, docs, assessor_e2e, assessor_paths (failures, time budget, late/erased turns, leaks),
               monitor, suite_run. test_suite: oracle judge over all suite cases (distance 0).
               conftest: rows() reader, wipe(), _fresh_emulator restarts a slow emulator per module
aiel-content-indexers/src/common/doc_index/  chunking, embedding (Vertex EU + Fake = analyzer's), bigquery REST, writer
```

### How to run without make

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
| Refusing a duplicate `CREATE TABLE IF NOT EXISTS` takes ~5 s | `create_all` lists tables and creates only missing ones; emulator staging tables `_stg_<table>` are created there, not per write |
| Slows down as its job history grows (`SELECT 1`: 0.3 s → 2+ s) | `make test` / `make coverage` start with `make db-reset`; batch statements into one multi-statement script (`wipe()`, MERGE + empty staging) |

### Make targets planned

`help, up, down, db-init, db-reset, seed, demo, run-assessor, run-monitor, run-daily, run-weekly, record,
alert-lookup, suite, suite-coverage, suite-restore, suite-live, pii-eval, index-local (FULL=1), test, test-unit,
coverage, lint, fmt, build`.

---

## M0. Scaffolding

- [x] Branch + submodule on `AIENGLAB-782`
- [x] `pyproject.toml` (uv), package skeleton, ruff (SIM108 ignored), pytest, pytest-cov `fail_under = 90`
- [x] `docker-compose.yml`: BigQuery emulator, fake GCS, stub servers (Slack, GitHub, Cloud Run executions)
- [x] Verify emulator capabilities; gaps recorded in **Emulator quirks**
- [x] `Dockerfile` (one image, spaCy models), `Makefile`, `CLAUDE.md`, `.gitignore`

## M1. Foundations (§12.16 milestone 1)

- [x] Settings in one place (§12.14) — `config/settings.yaml`
- [x] Closed lists with a version (§6.4, §6.7, §7.4, §7.7) — `vocab.py`
- [x] Logging wrapper; test that planted text never appears in logs (§12.13)
- [x] Sentry: error class only (§12.13)
- [x] Leak guard + planted-PII test (§6.10) — unit tests + e2e `test_no_text_is_stored`
- [x] Keys (§12.5)
- [x] BigQuery DDL for all tables of §12.10 + authorized-view SQL + `aiel_evals` contract + emulator copies
- [x] `ca db-init`; MERGE writer keyed by table key (§12.6)
- [x] CLI: job modules for monitor, daily, weekly, judge-suite, record
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
- [x] Polish/English synthetic PII test set + recall measurement (`make pii-eval`) (§6.12) — `pii/eval_set.yaml`
  (82 planted values, 20 persons with inflected forms, a held-out part), `pii/evaluate.py`; 100 % recall
- [x] Judge client: `eu` only, temperature 0, structured output, 429 backoff, throttled count, tokens, daily limit
- [x] Stage 1 form + rubric en/pl + gating + deterministic codes + primary order + severity + topic (§6.4–§6.8)
- [x] Evidence kind, verifiable, people directory excluded (§6.2, §6.6)
- [x] Answer spans and span counts (§6.4)
- [x] Fingerprint; late-arriving earlier turn re-assesses later ones (§6.1)
- [x] Relation → previous turn's reaction (§5.3)
- [x] Feedback in window: thumbs + reason codes, comment never; dislike = late trigger
- [x] Feedback after window: fallback by session key + question index behind the setting (§12.5) — off by
  default; position = the log's `questionIndex` + 1 (to confirm with §12.17 before switching it on)
- [x] Work list incl. parallel run doubling, 5 % second-model sample, missed at 3h30 (§12.6)
- [x] Phase 1 concurrency + 7-minute stop (§12.6)
- [x] Retrieval counts per document and day (§12.6)
- [x] Run record in `quality_runs` (§12.10, §12.12) — plus `covered`, `search_cutoff`, `feedback_cutoff`
- [x] `quality-monitor`: pipeline health per run + hourly log gap check + pipeline-health alerts (§9.2, §12.8)
  — also HIGH cluster alerts with session grades, ✅ acknowledgements and the alert lookup (M6 items, done here)
- [x] Unit tests to > 90 % coverage

## M3. Documents and stage 2 (§12.16 milestone 3)

- [x] Indexer sink in the submodule (§12.7): `src/common/doc_index/` (chunking, embedding, bigquery REST, writer),
  hooked into `VertexAIDataStore` (`_buffer_content` → `add_part`, `finalize_content` → `finish`, `_cleanup_content`
  → `cleanup(keep)`) and `LocalStorageSink`; `BaseIndexer._DOC_INDEX = False` on `AssociatesIndexer`. Enabled by
  `-p doc_index.dataset=...` (+ `project_id`, `endpoint`, `embedder=vertex|fake`, `embedding_project`,
  `embedding_location`, `max_documents`). Prod inserts = one DML `INSERT ... FROM UNNEST(@rows)` per 200 rows (no
  streaming buffer, so the end-of-run DELETE works on hourly runs); emulator = insertAll. Unchanged text (same URL,
  text hash, model) is skipped; the delete removes rows whose `TO_HEX(SHA256(uri))` is not in the bucket keep-set and
  old rows of rewritten URLs; an empty keep-set deletes nothing.
- [x] Local indexer runs write vectors to the emulator (`make index-local` → submodule `quality-index-local`, docker,
  `host.docker.internal:9050`, 20 docs unless `FULL=1`, `EMBED=fake|vertex`) — run 2026-10-29 on biztech (476 pages
  read from gs://biztech-technical-wiki, 20 embedded): fake 62 chunks, vertex 53 chunks (`max_documents` takes the
  first 20 to finish, so the sets differ). The analyzer's `DocumentIndex` finds each indexed document first for its
  own text, 5 of 5 with both embedders; re-embedded URLs lost their old-model rows, searches filter by model.
- [x] Content bucket reader (Fernet, path rule, cap) — `docs/content.py`
- [x] Document index search (`VECTOR_SEARCH` / emulator cosine), top 10, people directory excluded
- [x] Evidence check (§6.9)
- [x] Flagging + late triggers, flagged at most once (§7.1)
- [x] Stage 2 (§7.2–§7.5), cause path by rule, document to fix, findings confirmed/dropped
- [x] Stage 2 kept beside stage 1 (§7.6)
- [x] Session grades: provisional / final / not gradable; re-grade at close (§7.7)
- [x] Phase 3 time budget, pending first, give up at 3h30 (§12.6)
- [x] Done when: index hit rate and flagged share are measured (daily job, M5) — `INDEX_HIT_RATE` in
  `quality_judge_quality`; `FLAGGED_SHARE` daily metric (flagged / assessed turns)

## M4. Judge trust (§12.16 milestone 4)

- [x] Suite case format (YAML in `suite_cases/`): fixed input incl. search results + expected forms, `reviewed`, `part`
  — `suite/cases.py`, `suite_cases/{suite,documents}.yaml` (21-document corpus)
- [x] Cases meeting every scenario minimum (§11.1); coverage checker — 264 cases, `ca quality-judge-suite --check`
- [x] Scoring (§11.2), 3 runs averaged, per case/field/scenario — `suite/scoring.py`, `suite/runner.py::summarize`
- [x] Keep rule (§11.3) → `quality_judge_suite_runs`; 70 % reliability → `experimental` — `runner.decide`,
  `label_recall`, read by `monitor.reliable_labels`
- [x] Live suite run on `gemini-3.8-flash` + `gemini-4-argon` (spend cap!) — v1 BASELINE (tuning 0.77, held-out
  1.47, 4 false / 6 missed HIGH); v2 (conflicting references are contradicted; OUT_OF_SCOPE also on a rightful
  refusal) KEEP: tuning 0.46, held-out 1.15, 4 false / 0 missed HIGH; every label reliable except REASONING_ERROR
  (20 %, experimental). Settings name v2 as current (pre-launch: no parallel run). One pass each, not 3, to stay
  within the spend cap; the job's default stays 3.
- [x] Canary assessed like real turns, `quality_canary_results` with question hash (§11.4) — agreement is daily (M5)
- [x] Planted errors (swapped number, dropped step, wrong name), with and without references (§11.4)
- [x] Index hit rate per canary question (expected doc in top 10) (§11.4)
- [x] Second-model check on 5 % → `quality_judge_checks` (§11.5)
- [x] Judge versions: hash, first use recorded; parallel run assesses with both (§6.11, §12.14)

## M5. Metrics (§12.16 milestone 5)

- [x] Authorized views SQL (§12.4)
- [x] Log completeness (§8.2) — `reporting/completeness.py`: the monitor checks the last hour, the daily job all 24
  hours of its day again; a channel with a gap hour makes the day incomplete (`incomplete`, `LOG_GAP_HOURS`)
- [x] Change events from 5 sources (§12.9) — `reporting/changes.py` (log view, GitHub commits per path with cluster
  IDs from the message, Cloud Run indexer executions, judge versions and parallel-run ends), `reporting/record.py`
- [x] Daily metrics (§8.1–§8.5), standardized AQR (§8.4), judge quality measures (§11.4, §11.5), recompute-not-add —
  `reporting/metrics.py`, `reporting/judge_quality.py`, `reporting/daily.py`

## M6. Alerts, clusters, digest (§12.16 milestone 6)

- [x] Anomaly check + alerts (§8.6, §8.7) — `reporting/anomaly.py` (jump, CUSUM drift, reference restart at the ✅,
  no new alert while one is open), alerts and retries in `daily.py`; ✅ read by the monitor
- [x] `HIGH` cluster alerts with session grades; alert lookup (§7.7, §9.2, §12.8) — `reporting/monitor.py`, `reporting/lookup.py`
- [x] Release impact (§10.3) — `reporting/release.py`
- [x] Weekly clusters, document stats, digest (§9) — `reporting/weekly.py`, `messages.digest`

## M7. Closed loop (§12.16 milestone 7)

- [x] `quality_eval_documents` (§10.1, §12.11); gate verdicts in digest; turns still in baseline top clusters (§9.3)

## Final

- [x] `CLAUDE.md` complete; `make help` lists every target (26, all described); `make coverage` green: 229 tests,
  98.37 % (session 5, after the sweep fixes)
- [x] Requirement sweep: re-read `design-doc.md` section by section against this plan (session 5, see Next steps)
- [x] `make build` (session 5, on the user's request): `conversation-analyzer:local`, 1.64 GB; offline in the
  container `ca --help`, `quality-judge-suite --check` and `pii.evaluate` (recall 1.0) work, and `quality-assessor`
  with `--network host` writes its run record on the emulator
- [ ] Push of `AIENGLAB-782_v2` waits for the user

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
| Fake judge | Scripted by `[[fake key=value]]` markers in synthetic text (see `judge/fake.py`); `fail=output|api fail_on=<Form>` makes a call fail. |
| HIGH cluster alerts | A turn is alerted once its stage 2 is no longer `PENDING` (done or given up), so a stage 1 HIGH that stage 2 drops never alerts. "New" = no earlier HIGH alert of the same cluster for the same session segment. Pace-marked and canary turns never alert. One alert per cluster with ≥ `alerts.high_alert_bar` new turns. |
| Experimental labels (§11.3) | A label is reliable when the latest full suite run of the metric judge version marks it so (`quality_judge_suite_runs.label_recall`); with no such run every label is experimental. A cluster with an experimental primary failure is never alerted and never ranked (`rank` NULL, `experimental` true); the digest lists such clusters apart under *Experimental labels*. `make demo` seeds a stand-in suite run with the v2 run's recall (`scenario.SUITE_RECALL`); `make suite-restore` loads the stored reports back after a reset. |
| Doc index per URL | The sink writes one content blob per URL (parts of one URL joined); the index does the same: rows keyed by URI, `doc_id` = normalized ID of the URL's first document. Confluence `:chunk:` documents are skipped like for the bucket. |
| Doc index tables | Created by the writer if missing (`CREATE TABLE IF NOT EXISTS`, schema = `CHUNK_COLS`); in production the indexer SA needs dataEditor on `bolek_quality_doc_index`. |
| Suite topic | §11.2 scores no topic, so the expected stage 1 form has none. |
| Suite stage 2 | Run only for cases with an expected stage 2; a case flagged by a late trigger gives `flag_reasons`. |
| Health alert periods | Same check fires again only in a new period: coverage and waiting once per hour, a failed run once per run, no run once per hour, log gap once per hour and channel, window and tokens once per day (deterministic alert IDs). |
| Log gap check | The last hour that ended ≥ 15 min ago, once (a `LOG_HOUR` row marks it checked). Usual = median of the same hour 1–4 weeks back, only weeks whose day has log data; needs ≥ 2 such weeks; gap when records < 30 % of usual and usual ≥ 5. |
| Run coverage | Per run: covered / eligible over the turns in the window that are eligible and younger than 3h30 (`quality_runs`). Daily coverage against the log's counts is the daily job's (§12.9). |
| Suite input | A case is judged like a live turn: PII scrubbed, references get the placeholders, a fixed `DocumentSource` returns the case's `documents` for every search. Stage 2 runs when the case expects one and stage 1 (or the case's `flag_reasons`, a late trigger) flags it; otherwise it counts as missed. The session grade gets fixed stage 1 labels (earlier turns' `stage1`, the current turn's expected stage 1), so only the judge changes between runs. |
| Suite scoring | A failed call scores as an empty form (every expected value missed) and is counted in `failed_calls`. Labels for reliability are the failure codes: a stage 1 code is found when stage 1 records it, a stage 2 primary when stage 2's failure types hold it. `false_high` is the total over passes; the keep rule compares it per pass. |
| Suite runs | `--limit`/`--part` runs are stored with `partial = true` and no decision; only full runs become a baseline or set label reliability. A run of the baseline's own judge version is a new BASELINE (re-measure), not a decision. Spend guard: `suite.max_usd_per_run` with price estimates in settings; the run stops with TOKEN_LIMIT. |
| Daily metrics | Rates per channel (and ALL) and slice (intent, topic, data store, stratum, families); small slices pooled into `MERGED_OTHER` per slice kind (`merged`); stratum rows always kept as the parts of standardized AQR. Stratum weights = verifiable-turn shares over the 4 weeks from `go_live_day` or the last AQR_REBASE, days before the computed day only (today's own mix while none exist); a small stratum takes its intent family's AQR, else the channel's. Volume, coverage, missed from the log's counts view; dislikes from the feedback view (web UI only); active users and retention from `ge_metrics` (latest 7 days rewritten). Extra metric `FLAGGED_SHARE` (M3 done-criterion). |
| Anomalies | Series = slice ALL per channel; days skipped when incomplete or under 100 turns; reference pooled over the last 28 such days of the same kind (≥ 14), restarted at the last acknowledgement; noise = max(chance for the day's denominator, stdev of the days); CUSUM rebuilt over up to 120 days; no new anomaly while one is open. Coverage checked from day 1, quality metrics after the baseline. Unsent alerts are retried by the next run. |
| Release impact | Releases = prompt, data store, document, model, engine, agent, connector events; confounded by another release, a judge change, a parallel-run end or a rebase in the 10 weekdays, or by a judge version change between the two sides. WAITING rows until 5 complete weekdays after exist. Indexer runs are recorded but neither measured nor confounding (hourly). |
| Change events | GitHub `paths` map a path to the change kind; cluster IDs (`cluster-<16 hex>`) parsed from commit messages. Indexer events = Cloud Run executions of `indexer-*` jobs finished on the day. |
| Weekly | Clusters from the week's assessed turns (per-day metric judge version); trend = turns / mean of the 4 weeks before; a fixed cluster is followed through weeks without turns and closes after 2 weeks under 25 % of its 4-week level before the fix week. Anchor set once per quarter (traffic = cited + retrieved; at least 20 per data store with traffic); focus set per active cluster with a document, a knowledge gap once a DOCUMENT fix names it. Digest = AQR trend, top clusters, best documents and topics, unusual items, release verdicts, gate verdicts (only change IDs that look like event IDs), turns still in the baseline's top clusters. |
| Feedback after window | Off by default; matches session key + position (`questionIndex` + 1) over 30 days and rewrites the stored turn row. |
| Suite cases | Drafted by Claude from hand-made facts of the corpus (drafting script not kept: the YAML is the source and is reviewed by hand). Stage 2 of a turn whose only evidence is an earlier turn's references starts at question 3 (no cited documents), so its cause is RETRIEVAL_MISS. Span `refs` are 0-based like the log; the judge sees reference numbers from 1 (fixed in `render_turn`). |
| Gate verdicts | `aiel_evals.gate_results.change_id` is expected to be our change event ID. quality-daily stores the latest `PASS`/`FAIL` per change in `quality_release_impact.gate_verdict` (the dashboard reads only `bolek_quality_metrics`); the digest lists the week's verdicts. Any other verdict value is ignored, so no evaluator text reaches Slack or the tables. |
| Anchor set rotation | Anchor rows are keyed by quarter (`period`); the old quarter's rows stay, so the evaluator can run old and new sets side by side for 2 weeks (§10.1). Question checks (answerable, no duplicate, no people directory) are the evaluator's. |
| Release impact slices | Measured on slice ALL per channel (web UI, Slack+MCP, all). The spec's "about 8 points for a data store with 15 % of the traffic" is read as a detection limit, not a per-data-store measurement. |

## Spend log (paid Vertex calls, cap 50 USD)

| Date | What | Model | Tokens in / out | Est. USD |
|---|---|---|---|---|
| 2026-10-29 | judge suite smoke run, 10 cases, 1 pass (`suite-006ae3928a747698`) | gemini-3.8-flash | 99,365 / 4,960 | 0.21 |
| 2026-10-29 | judge suite, all 264 cases, 1 pass (`suite-006ae392aee9aba9`, BASELINE) | gemini-3.8-flash | 2,098,509 / 220,991 | 5.29 |
| | | gemini-4-argon | 319,185 / 16,345 | 1.76 |
| 2026-10-29 | judge suite v2, all 264 cases, 1 pass (`suite-006ae3961f390f5f`, KEEP) | gemini-3.8-flash | 2,143,050 / 214,003 | 5.30 |
| | | gemini-4-argon | 354,282 / 17,330 | 1.94 |
| 2026-10-29 | `make index-local EMBED=vertex`: 20 biztech documents, 53 chunks (≤ 2,000 chars), plus 5 search queries | text-multilingual-embedding-002 | ≤ 110k chars | < 0.01 |
| | **Total so far** | | | **14.51** |

Prices: Vertex AI billing catalog, regional (eu) online text: flash 1.65 / 8.25 USD per M tokens in / out, argon 4.40
/ 22.00 (thinking tokens count as output). A full 1-pass suite run is about 7 USD and 35 minutes (argon is slow).
