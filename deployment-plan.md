# Deployment plan: Conversation Analyzer to production

How the Conversation Analyzer moves from this private repository (`pborkowski-rtbh/conversation-analyzer`) to an
official repository and to GCP, **one verifiable piece at a time**. `design-doc.md` stays the spec, `plan.md` the record
of the build so far. This file is the deployment's own plan and progress log: tick a box only when its verification
passed, and write what was observed next to it.

To resume: read **Status**, then the first unchecked step.

## Status (2026-11-04)

- Plan written and its open questions answered (§9); nothing deployed. A2 done (ticket 07). PII scrubbing dropped (A3, ticket 08). A5 done (department, AIENGLAB-853). All code is in the private repo (M0–M7 done, 233 tests, 98.35 % coverage).
- Paid Vertex spend of the build so far: 14.51 of 50 USD (see `plan.md`). Deployment spend is logged below, separately.

---

## 1. Decisions (2026-11-02)

| Topic | Decision |
|---|---|
| Document retrieval (RAG) | **Dropped entirely.** No document index, no embeddings, no indexer sink. Stage 2 reads the full text of the cited documents and of the documents linked in the answer, from the content bucket, and runs no search. The evidence check keeps only the documents linked in the answer text. `RETRIEVAL_MISS` and `KNOWLEDGE_GAP` can no longer be told apart and become one code (A2). The submodule `aiel-content-indexers` is not migrated. |
| PII scrubbing | **Dropped.** Questions, answers, earlier turns, references and documents reach the judge as they are, on EU endpoints only, never stored. `pii/`, Presidio and the spaCy models are removed (A3). |
| Department in strata | The user's department comes from `base_function` in `rtb-house-hr-reporting-data.IT.bolek_associates_active`, read from the `email → base_function` map the associates indexer writes each hour to its state bucket (AIENGLAB-853), mapped to a closed list of department families. Stratum = intent family × data-store family × department family. |
| Official repository | A new repository `RTBHouse-OEET/aiel-conversation-analyzer`, CI/CD like `aiel-content-indexers` (GitHub Actions, Workload Identity, Artifact Registry). Code arrives by one reviewed PR per step, not by pushing this repo's history. |
| Environments | **Stage** = project `rtb-aiel-core-stage`, its own infrastructure, its own BigQuery datasets (`stage_bolek_quality_*`), reading the **prod** audit log. **Prod** = project `rtbhouse-agentspace`, datasets `bolek_quality_*` (§12.10). Every step goes to stage first, then the same image digest to prod. |
| Stage volume | Stage assesses full traffic, but only while it is switched on. It is paused by default and resumed for a fixed number of hours (§3, the run gate). |
| Grafana | Dashboards live in `RTBHouse-Platform-Engineering/infra-grafana-dashboards` (Central Grafana, Git Sync), folder `AI-Engineering-Lab/Conversation-Analyzer/`: `test/` reads stage, `prod/` reads prod. |
| Infrastructure as code | Terraform in `RTBHouse-OEET/infrastructure`: `terraform/rtb-aiel-core-stage/` and `terraform/rtbhouse-agentspace/`, one file `conversation_analyzer.tf` per project, mirroring how `cloud_run_indexers.tf` is kept in both. |

## 2. Target picture

| | Local | Stage | Prod |
|---|---|---|---|
| Where | docker compose (emulator, fake GCS, stubs) | `rtb-aiel-core-stage`, `europe-west4` | `rtbhouse-agentspace`, `europe-west4` |
| Reads the log | synthetic rows | prod `rtbhouse-agentspace.analytics.audit_logs` (table-level grant) | same |
| Writes | emulator | `stage_bolek_quality_turns`, `stage_bolek_quality_metrics`, `stage_bolek_quality_log_views` (EU) | `bolek_quality_turns`, `bolek_quality_metrics`, `bolek_quality_log_views` (EU) |
| Hash key (§12.5) | `local-hash-key` | own secret in stage | own secret in prod |
| Judge (Vertex, `eu`) | fake | project `rtb-aiel-core-stage` | project `rtbhouse-agentspace` |
| Content bucket | fake GCS | prod bucket, read only | prod bucket, read only |
| Image | `conversation-analyzer:local` | `europe-west4-docker.pkg.dev/rtb-aiel-core-stage/conversation-analyzer/stage@sha256:…` | `…/rtbhouse-agentspace/conversation-analyzer/prod@sha256:…` |
| Slack | stub | `#bolek-quality-stage` (one channel for every message) | `#bolek-quality`, `#aiel-alerts` |
| Grafana | — | Central Grafana **test** | Central Grafana **prod** |
| Schedules | by hand | always enabled; jobs exit at once while the run gate is closed | always enabled |

The two hash keys differ, so stage and prod rows can never be joined by session or turn key.

Jobs, per environment (§12.3): `quality-assessor`, `quality-monitor`, `quality-daily`, `quality-weekly` (scheduled),
`quality-judge-suite`, `quality-record`, `quality-db-init` (by hand). Service accounts (§12.4), prefixed `stage-` in
stage: `quality-assessor`, `quality-reporter`, `quality-judge-suite`, `quality-schema` (db-init only), and
`grafana-bolek-quality` (read-only on the metrics dataset). There is no `content-indexers` change any more.

## 3. Stage pause and resume: the run gate

Stage reads real traffic, so every hour it runs costs judge tokens. Proposal:

- **A control object** `gs://rtb-aiel-core-stage-quality-control/run-gate.json` = `{"open_until": "<UTC time>"}`. Every
  scheduled stage job reads it first. When `now > open_until`, the job writes a run record with status `PAUSED`
  (assessor) or nothing (others), logs `gate_closed`, and exits 0 within seconds. No Vertex call, no Slack message.
  A Cloud Run job execution that exits at once costs a fraction of a cent, so the schedulers can stay enabled.
- **Resume:** `make stage-resume HOURS=6` (or the GitHub Actions workflow `stage-gate.yml`, `workflow_dispatch` with
  `action=resume|pause`, `hours`) writes `open_until = now + hours`. **Pause:** `make stage-pause` writes a time in the
  past. The workflow is the official path: it leaves an audit trail of who opened stage and for how long.
- **It closes itself.** Forgetting to pause costs at most `HOURS` (capped at 24 by the workflow). A second guard: the
  stage daily token limit (`judge.daily_token_limit`) is set to about a tenth of prod's.
- **Prod has no gate** (`run_gate.uri` unset), so the code path cannot pause prod by mistake.
- **What a pause means for the numbers.** Turns that reach 3h30 while stage is paused are recorded as missed on the
  next open run; the stage monitor treats `PAUSED` run records as "no run expected" (no coverage, no-run or log-gap
  alerts while closed and for the first 3h30 after opening). The stage dashboard shades paused hours.
- **Manual runs** (`gcloud run jobs execute … --args=…,--ignore-gate`) work while the gate is closed, for one-off tests.

Why not pause the Cloud Scheduler jobs instead: it needs Terraform to ignore `paused`, scheduler admin rights in CI,
and it never closes itself.

## 4. How every step works

Each step below is one unit of migration. It is done when all of its checks are ticked.

1. **Code PR** into the official repo: only the modules the step needs, their tests, and the settings they read.
   CI must be green (lint, unit tests, emulator tests, coverage ≥ 90 % of the code present).
2. **Image** built by CD on merge, pushed to stage (and prod) Artifact Registry, referenced **by digest** in Terraform
   (not `:latest` as the indexers do): a deploy is a visible one-line change and a rollback is reverting it.
3. **Infra PR** into `RTBHouse-OEET/infrastructure`, stage stack first. Prod stack in a second PR, after stage passed.
4. **Verify on stage** with the step's checks (open the run gate for as long as the check needs, then close it).
5. **Promote to prod**: the same digest, the prod infra PR, the same checks on prod.
6. **Record** in this file: the date, digests, observed numbers, spend.

Rules that hold for every step:

- **Off by default.** A new job or feature ships disabled (no schedule, Slack off, gate closed) and is switched on by
  a separate one-line change after the deploy itself was verified.
- **Never drop or recreate** a dataset or a table. Schema changes are additive (`ca db-init` adds columns); a column
  that is no longer written stays.
- **Rollback** = revert the digest (or the infra PR). Stored rows are keyed (§12.6), so re-running a fixed version
  rewrites rather than duplicates.
- **No text anywhere** (§6.10, §12.13) is checked again in every environment, not assumed from local tests: every
  step that writes rows runs the leak audit (A6), every step that adds a job checks its Cloud Logging output.
- **Real BigQuery is touched only by deployed jobs, CI and Terraform**, never from a laptop (the hard rule of
  `CLAUDE.md` stays for local work). Checks that need a query on stage or prod are run by an engineer in the BigQuery
  console under their own account, read only, and their SQL is written in this file.

---

## 5. Phase A: changes in the private repo before migration

These change the design, so they are made and tested here first (emulator, fake judge, suite), and migrate with the
steps that need them. Each ends with `make coverage` green.

### A1. Spec update

- [x] (2026-11-02) `design-doc.md`: §6.9 (evidence check uses only links in the answer), §7.2–§7.5 (no search; cause path without
  question 3; the merged code), §8.4 and §8.9 (department as a third stratum dimension), §11.4 (no index hit rate, no
  `KNOWLEDGE_GAP` miss rate), §12.1–§12.4 and §12.7 (no document index, no indexer change), §12.10 (no
  `bolek_quality_doc_index`), §12.14 (environments, run gate, official repo), §12.16 (this plan replaces the build
  plan for deployment).
- [ ] `plan.md`: a pointer to this file; deviations table rows for the decisions of §1.

### A2. Drop the document index

- [x] Remove `docs/index.py`, `docs/embedder.py`, `devtools` chunk seeding, `make index-local`, the `embedding`
  settings, `CA_EMBEDDING_BACKEND`, the `bolek_quality_doc_index` dataset and `chunk_table()`.
- [x] Remove the submodule `aiel-content-indexers` (its branch `AIENGLAB-782` stays unmerged). The note on that
  branch is still open (a commit in another repository).
- [x] Stage 2 (`judge/stage2.py`): documents = full text of the cited documents and of the documents linked in the
  answer text; no phrasings call (`Stage2Phrasings` goes, one judge call fewer per flagged turn).
- [x] Cause path (§7.3) without the search question: *not in the snippets → in the full text of a cited or linked
  document?* yes `CHUNKING_ISSUE`, no → **`NOT_IN_CITED_SOURCES`** (replaces `RETRIEVAL_MISS` and
  `KNOWLEDGE_GAP`; no document to fix, clustered by topic). `OUTDATED_SOURCE` and `CONFLICTING_SOURCES` are unchanged.
- [x] Evidence check: documents linked in the answer text only; if none, the check is skipped and counted as
  `NO_DOCUMENTS` in the run record, so its reach is measured on real traffic (step 6).
- [x] Retrieval counts (§12.6): a retrieved document ID takes its data store from the references seen in the
  window (agreed with the user); IDs no reference names are not counted. Linked documents take the window's ID for
  their URL, else `url-<32 hex>`.
- [x] Canary: drop index hit rate and the `KNOWLEDGE_GAP` miss rate (`INDEX_HIT_RATE` measure, digest line).
- [x] `vocab.py`: closed lists changed → new `closed_lists_version()`.
- [x] Verify: `make coverage` ≥ 90 %, `make demo` runs, `grep -ri "vector\|embed" src` finds nothing live.
  (2026-11-02: 222 tests, 98.26 %; demo end to end; grep clean.) Judge v3 drafted here, validated in A4.

### A3. No PII scrubbing

Decided 2026-11-02: conversations reach the judge as they are. Text still goes only to EU endpoints and is never
stored; the leak guard and `safe_log` are unchanged.

- [x] Remove `pii/` (scrubber, Presidio recognisers, `evaluate.py`, `eval_set.yaml`), the `pii` settings,
  `make pii-eval`, `tests/test_pii.py`, and the `presidio-analyzer`, `spacy`, `en-core-web-lg` and `pl-core-news-lg`
  dependencies.
- [x] Assessor, documents (`RunDocuments.view`), suite runner and case rendering work without a `PiiMap`: no
  placeholders in the conversation, the references or the documents.
- [x] Judge v3 (still a draft, A4 validates it): the stage 1 rubric (en, pl) loses the placeholder paragraph; the
  version ID changes by hash.
- [x] Suite runner reads the cases as they are (no case uses placeholders today); the oracle stays at distance 0.
- [x] Kept: the leak tests with planted personal data (stored rows, logs, Sentry) still fail if any of it appears.
- [x] `CLAUDE.md` (layout, `make install`, `make pii-eval`), Dockerfile and Makefile comments updated; image size
  without the spaCy models noted for step 1.
- [x] Verify: `make coverage` ≥ 90 %, `make demo` runs, `grep -ri "presidio\|spacy\|placeholder" src` finds
  nothing live.
  (2026-11-03: 207 tests, 98.31 %; demo end to end; grep clean. v3 ID `v3-22911c7119fd` → `v3-d3d21286d11e`.
  Local image 2.84 GB → 344 MB.)

### A4. Judge v3 and the suite

- [x] `judge_versions/v3` (copy of v2): stage 2 rubric and prompt without found documents; form schema with the new
  code. New version ID by hash.
- [x] Suite cases: rewrite expected stage 2 forms of every `RETRIEVAL_MISS` / `KNOWLEDGE_GAP` case; drop the
  `documents` that only search could reach; `make suite-coverage` still meets the §11.1 minimums (adjust the scenario
  minimums for the merged code). Suite version changes, so the next full run is a new BASELINE.
- [x] `tests/test_suite.py` (oracle judge) at distance 0.
- [x] **Paid:** `make suite-live JUDGE_VERSION=v3`, one pass (~7 USD, ~35 min). Accept v3 when: missed HIGH = 0, false
  HIGH ≤ 4, held-out distance ≤ 1.15 (v2's), no label below 70 % recall other than `REASONING_ERROR`. Otherwise tune
  (v4…) on the tuning part only. Log the spend.
  (2026-11-03, two passes of v3, 13.4 USD, total 27.92: false HIGH 4, held-out 1.05 / 1.10, only `REASONING_ERROR`
  below 70 % recall; **missed HIGH 1** both times (`budget_tab-contradicted`: a different time window judged
  unsupported, not contradicted). Open: a v4 stage 1 rubric clarification, tuned on the tuning part only, then one pass.
  First pass also showed `OUTDATED_SOURCE` recall 0: the outdated cases cited no newer document; fixed in the cases.)
  (2026-11-03, v4 kept, 6.79 USD, total 34.71: the 4 misapplied-rule cases expect contradicted/HIGH at stage 1 and
  `REASONING_ERROR` at stage 2, as the v3 judge already read them; v4 rubric: a rule applied to an excluded case or
  something else named in place of what the passage lists is contradicted; at stage 2 `REASONING_ERROR` wins over
  contradicted when the snippets held the right rule. Run `suite-006ae9c5dbc7572ac5b`: missed HIGH 0, false HIGH 2,
  held-out 0.815, every label ≥ 70 % recall.)
- [x] Settings: `judge.current_version: v4` (pre-launch: no parallel run).

### A5. Department

- [x] **Input:** the distinct `base_function` values and their associate counts, read from the stage associates
  indexer's map (2026-11-04: 1536 associates, 45 values; no HR-table query needed). Four families in `settings.yaml`
  (`strata.department_families`): `ENGINEERING` 314, `CAMPAIGNS` 443, `COMMERCIAL` 514, `CORPORATE` 258; the rest
  (7) `OTHER`; users not in the map `UNKNOWN`.
- [x] Privacy floor for families: a family with fewer than `strata.department_min_associates` (30) active associates
  in the run's map is stored as `OTHER`. The `base_function` itself has no floor (decision 2026-11-04).
- [x] `vocab.DepartmentFamily` (closed list; the mapping is part of `closed_lists_version()`), `SliceKind.DEPARTMENT`.
- [x] `people/directory.py`: reads the department map (`CA_DEPARTMENT_MAP_URI`, default
  `gs://rtbhouse-agentspace-indexers-state/directory/associates-departments.json`) once per assessor run, in memory;
  missing, malformed or older than `people_directory.max_age_hours` → `None`, and the run uses `UNKNOWN` for everyone
  and records `directory_unavailable` (the monitor alerts `DIRECTORY_UNAVAILABLE` once a day). The map is written by
  the associates indexer (RTBHouse-OEET/aiel-content-indexers#187, RTBHouse-OEET/infrastructure#1176), so the assessor
  needs no HR-table grant. Users not found (service accounts, externals) → `UNKNOWN`. Canary accounts are excluded
  anyway.
- [x] Assessor: `department` column (leak-guard kind `department`: family codes only) on `quality_turns` and
  `quality_segments`, set in memory from `userIamPrincipal` during the window; the principal is never stored (as
  today). A family once stored is kept; `UNKNOWN` is replaced while the identity is in the log.
- [x] Metrics: stratum = `intent__datastore__department`; department slice; small strata fall back to intent family
  (existing rule). Data-store families collapse to 3 (`ENGINEERING`, `COMPANY`, `NONE` incl. Drive), so there are at
  most 4 × 3 × 6 = 72 strata, most of them pooled; the final list freezes with the baseline (§8.9).
- [x] Emulator: the department map in fake GCS (`scenario.DEPARTMENTS`, `store_department_map`); synthetic turns carry principals that map to every family.
- [x] `base_function` as is (kind `base_function`: any value listed in `strata.department_families`, every current
  value is, under its family or `OTHER`; a new HR value is stored as `OTHER` until listed) and `user_key` (HMAC of the
  email, kind `hash`) on turns and segments.
- [x] Tests: leak guard rejects anything but a family code in `department` and a listed value in `base_function`; e2e
  department rows, strata and user keys, no email stored; a family below the floor is folded; a missing, then found,
  then stale map.

### A6. Ready for real GCP

- [ ] **Per-environment settings:** `config/settings.yaml` (common) + `config/env/{local,stage,prod}.yaml` overlays
  selected by `CA_ENV`: projects, dataset prefix (`stage_`), Vertex project, Slack channels, token limit, run gate.
  `local.env` sets `CA_ENV=local`.
- [ ] **Dataset prefix** applied everywhere a dataset name is built (tables, views, external tables).
- [ ] **Run gate** (§3): `run_gate.uri` setting, read at job start, `--ignore-gate`, `PAUSED` run status (closed
  list), monitor rules for paused periods; fake GCS test.
- [ ] **Dry run:** `ca quality-assessor --dry-run`: reads the window, builds sessions and the work list, writes only
  the run record (no Vertex). The first thing run against real data.
- [ ] **Schema check:** `ca db-init --check`: compares live datasets, tables, columns, partitioning and views with
  `bq/schema.py`; exits non-zero on a difference. Used after every deploy.
- [ ] **Kill switches:** `stage2.enabled` and `evidence_check.enabled` settings (default true), so stage 1 can keep
  running when stage 2 misbehaves.
- [ ] **Leak audit:** `ca leak-audit --since <day>`: reads stored rows of every table back and runs `leak_guard`
  on them again, plus a length check on every string column; prints counts only. Run after every step that writes.
- [ ] **Real-BigQuery paths** that the emulator never exercised are listed and covered by the first stage steps:
  load job + `MERGE` in `bq/client.write`, partition expiry, authorized views across projects, `INFORMATION_SCHEMA`
  reads, query cost. Each gets a check in step 3.
- [ ] Dockerfile: `CA_CODE_VERSION` from the git SHA (build arg), so every run record names its code.
- [ ] `CLAUDE.md`: hard rules updated for environments (real BigQuery only through deployed jobs).

### A7. Dashboard queries testable locally

- [ ] `make dashboard-check DASHBOARD=<path to a dashboard JSON>`: extracts every panel's SQL from a Grafana
  dashboard file, replaces the Grafana macros (`$__timeFilter`, variables) with fixed values, and runs it on the
  emulator after `make demo`. Fails on any error or empty required panel. The dashboard's source stays in
  `infra-grafana-dashboards`; this repo only tests it.

---

## 6. External gates

They don't block early steps, but each blocks the step named. Start them now; record the answer and its date here.

| # | Gate | Who | Blocks | Status |
|---|---|---|---|---|
| G1 | SECOPS: stage service accounts read prod conversation text (assessor) and prod content bucket; the judge gets conversation text without PII scrubbing; audit-log content check of Vertex/Secret Manager/GCS calls (§12.13); exclusion of our SAs from the 7-year log copy if needed | SECOPS | step 4 (stage assessor with judge) | [ ] |
| G2 | HR/SECOPS: department family, `base_function` as is (no floor: small departments name their people) and a keyed hash of the user's email stored per turn, read from the associates indexer's `email → base_function` map (no assessor access to the HR table) | HR data owner, SECOPS | step 5 | [ ] |
| G3 | Slack app (post, `reactions.read`) in the workspace; channels `#bolek-quality-stage`, `#bolek-quality`, `#aiel-alerts`; bot token in Secret Manager per project | Slack admins | step 9 | [ ] |
| G4 | Central Grafana: a BigQuery datasource per instance (test → stage SA, prod → prod SA), plugin installed, folder `AI-Engineering-Lab/Conversation-Analyzer` | Platform Engineering | step 8 | [ ] |
| G5 | Evaluator (AIENGLAB-519): daily canary on the prod engine, `aiel_evals` contract (`bq/external.py`), gate results naming our change IDs | evaluator owner | step 11, step 13 | [ ] |
| G6 | New repository `RTBHouse-OEET/aiel-conversation-analyzer`, CODEOWNERS, branch protection, WIF provider + SA for CI in both projects (as `GCP_RESTRICTED_*` for the indexers) | OEET admins, infra owners | step 1 | [ ] |
| G7 | Feedback numbering check (§12.17) on synthetic chats, before `feedback_after_window_fallback` is switched on | us | optional, after step 7 | [ ] |

---

## 7. Phase B: the migration steps

Module map: which private-repo code moves in which step.

| Step | Moves | New in official repo |
|---|---|---|
| 1 | `settings`, `vocab`, `safe_log`, `errors`, `secrets`, `keys`, `leak_guard`, `bq/` (schema, client, init), `cli` (only `db-init`), `config/`, Dockerfile, Makefile, docker-compose, tests of these | CI/CD workflows, `config/env/*` |
| 2 | — (infra only) | |
| 3 | `log/`, `assessor/sessions.py`, `assessor/state.py`, `assessor/run.py` (dry run path), `bq/external.py`, `devtools/` | `--dry-run`, run gate, `leak-audit` |
| 4 | `judge/` (forms, version, case, client, fake, stage1), `judge_versions/v3`, assessor phase 1 | |
| 5 | department (`people/directory.py`, stratum code) | |
| 6 | `judge/evidence.py`, `judge/stage2.py`, `judge/session.py`, `docs/content.py`, assessor phases 2–3, late triggers | |
| 7 | `reporting/monitor.py`, `reporting/completeness.py`, `reporting/messages.py` (health only), `reporting/slack.py` (posting off) | |
| 8 | `reporting/daily.py`, `metrics.py`, `changes.py`, `judge_quality.py`, `results.py`, `bq/views.py` (authorized views) | Grafana dashboard (other repo) |
| 9 | Slack on; `reporting/lookup.py`, HIGH cluster alerts, ✅ acknowledgements | |
| 10 | `suite/`, `suite_cases/`, `quality-judge-suite` job | |
| 11 | `assessor/canary.py`, second-model check | |
| 12 | `reporting/weekly.py`, `anomaly.py`, `release.py`, `record.py`, digest | |
| 13 | eval documents, gate verdicts (§12.11) | |

### Step 1. Repository, CI, image

Goal: the official repo builds and tests the foundations and pushes an image. Nothing runs in GCP.

- [ ] G6 done; repo created from the step-1 module set; `README.md`, `CLAUDE.md`, `design-doc.md` (A1 version),
  `deployment-plan.md` (this file moves with it and is kept there from now on).
- [ ] `ci.yml`: ruff, unit tests, emulator tests (docker compose as a service in the job), coverage ≥ 90 %.
- [ ] `cd-stage.yml` / `cd-prod.yml`: on merge to `main`, build once, push to both Artifact Registry repos with the
  git SHA tag; print the digest.
- [ ] Infra PR (both stacks): Artifact Registry repo `conversation-analyzer`, the CI writer binding.
- Verify:
  - [ ] CI green on the PR; a deliberately broken test makes it red.
  - [ ] Image digest in both registries; `docker run <digest> --help` lists the step-1 commands; `docker run <digest>
    db-init --help`.
  - [ ] Image size recorded (no spaCy models since A3; local build 344 MB, was 2.84 GB).
- Rollback: none needed (no runtime).

### Step 2. Datasets, service accounts, tables (stage, then prod)

Goal: every dataset and table exists, empty, with the right access.

- [ ] Infra PR stage: datasets `stage_bolek_quality_turns`, `stage_bolek_quality_metrics`,
  `stage_bolek_quality_log_views` (location `EU`, labels, default partition expiry 365 days on the turns dataset);
  SAs `stage-quality-assessor`, `stage-quality-reporter`, `stage-quality-judge-suite`, `stage-quality-schema`; dataset
  IAM per §12.4; Cloud Run job `quality-db-init` (SA `stage-quality-schema`, no schedule); hash-key secret (value set by
  hand, never in Terraform state).
- [ ] Run `quality-db-init` once by hand.
- Verify:
  - [ ] `quality-db-init --check` exits 0 (every table, column, partitioning as in `bq/schema.py`).
  - [ ] Running `quality-db-init` a second time changes nothing (idempotent) and `--check` stays 0.
  - [ ] IAM matrix check by an engineer (read-only `get-iam-policy` on each dataset): every SA has exactly the rows
    of §12.4; the reporter can't write the turns dataset; nobody but the assessor can read `analytics.audit_logs`
    or the hash-key secret.
- [ ] Same for prod (`bolek_quality_*`, SAs without prefix).
- Rollback: datasets stay (empty); revert IAM only.

### Step 3. Assessor dry run on real data (stage, then prod)

Goal: the window read, keys, sessions and the run record work on the real log. No text leaves memory, no Vertex call.

- [ ] Infra PR stage: job `quality-assessor` (4 GiB, 2 CPU, 9 min timeout, `max_retries = 0`, args `--dry-run`),
  scheduler every 10 min (UTC), run-gate bucket and object (closed), table-level `roles/bigquery.dataViewer` on
  `rtbhouse-agentspace.analytics.audit_logs` for `stage-quality-assessor` (not the dataset: §12.4), `jobUser` in stage,
  Sentry DSN secret.
- [ ] `make stage-resume HOURS=2`.
- Verify (stage):
  - [ ] 12 run records with status `OK`, `turns_read` > 0 on weekday hours; one more after closing the gate with
    status `PAUSED`.
  - [ ] Window margin: the oldest answer's age ≥ 3h45 in every run (§12.12).
  - [ ] Cross-check: turns read per hour vs an engineer's count from `analytics.audit_logs_public` for the same hour
    (within the eligible rules); difference explained or zero.
  - [ ] Real-BigQuery paths: the `MERGE` via load job wrote exactly one run record per run (no duplicate after a manual
    re-run of the same `CA_NOW`); bytes billed per run (from `INFORMATION_SCHEMA.JOBS`) noted for the §12.15 estimate.
  - [ ] Cloud Logging of the job: only `safe_log` events; search the job's logs for `@rtbhouse.com`, a question
    fragment, `"text"` → no hit.
  - [ ] Sentry: force one failure (`--ignore-gate` with a bad setting) → the event carries the error class only.
  - [ ] `leak-audit` on the run records: 0 findings.
- [ ] Promote to prod (gate absent → runs every 10 min, still `--dry-run`). Same checks over 24 h.
- Rollback: pause or revert the job.

### Step 4. Stage 1 in shadow (stage, then prod)

Goal: every turn gets its stage 1 form; coverage ≥ 98 %. No Slack.

- [ ] G1 done.
- [ ] Infra PR: Vertex `aiplatform.user` for the assessor SA (judge in the same project, location `eu`); drop
  `--dry-run`; stage token limit ~6M/day.
- Verify (stage, gate open one weekday working day, ~8 h, and one overnight period):
  - [ ] Coverage ≥ 98 % over the open period, excluding the first 3h30 after opening; missed = turns older than 3h30
    at the opening only.
  - [ ] Oldest waiting turn < 3 h; no run over 9 min; 429 count per run noted.
  - [ ] Tokens per run and USD per hour vs §12.15 (≈ 200 USD/month on full traffic for stage 1); extrapolation noted.
  - [ ] Stage 1 distributions look sane: intent mix, verifiable share, `HIGH` share; compared with the suite's
    scenario mix (no hard threshold, read by an engineer).
  - [ ] `leak-audit` over all rows written: 0 findings. Spot check: 20 random `quality_stage1_results` rows contain
    only codes, numbers and IDs.
  - [ ] Content: Vertex request logging confirmed off in the project; the §12.13 audit-log check on the job's calls (G1).
  - [ ] Close the gate; the next runs are `PAUSED`, cost stops (billing check next day).
- [ ] Promote to prod. Exit: **coverage ≥ 98 % for 5 weekdays** (M2 criterion), daily cost within estimate.
- Rollback: back to `--dry-run` (one arg) or the previous digest.

### Step 5. Department (stage, then prod)

Goal: every turn carries its department family. It comes before stage 2 because go-live (step 6) starts the
baseline, and the strata, department included, freeze with it.

- [ ] G2 done; A5 merged.
- [ ] Infra PR: `roles/storage.objectViewer` on the indexers' state bucket, conditioned on
  `resource.name.startsWith("projects/_/buckets/<project>-indexers-state/objects/directory/")`, for `stage-quality-assessor`
  (stage bucket) and `quality-assessor` (prod bucket); `CA_DEPARTMENT_MAP_URI` on the stage job.
- Verify (stage, 2 open hours):
  - [ ] `department` distribution per day: `UNKNOWN` share < 5 % of non-canary turns (else check principals format).
  - [ ] No family below the privacy floor appears; no email in any row (`leak-audit` + schema).
  - [ ] Run records: `DIRECTORY_UNAVAILABLE` = 0.
- [ ] Promote to prod.

### Step 6. Evidence check, stage 2, session grades (stage, then prod) — go-live

Goal: flagged turns get a diagnosis from cited and linked documents, without search.

- [ ] Infra PR: assessor SA reads the prod content bucket and the content secrets (`mcp-content-encryption-*`) —
  cross-project grants for the stage SA (G1 covers it).
- Verify (stage, one open working day):
  - [ ] Flagged share (expect < 20 %, §7.1); stage 2 done / pending / given up per run; given up ≈ 0 on a normal day.
  - [ ] Documents read: share of cited documents whose full text was found in the bucket (Drive and people directory
    excluded by design); `NO_DOCUMENTS` share of the evidence check (A2) — if near 100 %, propose removing the evidence
    check in a follow-up.
  - [ ] Cause mix: `CHUNKING_ISSUE`, `NOT_IN_CITED_SOURCES`, `OUTDATED_SOURCE`, `CONFLICTING_SOURCES`, answer errors.
  - [ ] argon tokens per flagged turn and USD per day.
  - [ ] Session grades: provisional → final within 3h30 of the segment's first turn; not gradable counted.
  - [ ] `leak-audit`: 0 findings (stage 2 claims and document IDs pass the data-store allowlist).
- [ ] Promote to prod. This is **go-live**: set `metrics.go_live_day` in prod; the 4-week baseline starts (§8.6).
- Rollback: setting `stage2.enabled: false` (new flag in A6) keeps stage 1 running.

### Step 7. Monitor without Slack (stage, then prod)

Goal: pipeline health per run and per log hour is computed and stored; alerts are stored but not posted.

- [ ] Infra PR: job `quality-monitor` (SA reporter, every 10 min at +5 min), `slack.enabled: false`.
- [ ] Authorized views (`stage_bolek_quality_log_views` over prod `analytics.audit_logs`): the views are created by
  `db-init`; the infra PR adds them as authorized views on prod `analytics` (`google_bigquery_dataset_access`).
- Verify:
  - [ ] `quality_pipeline_health` has a row per run and per log hour; stage marks paused periods as such.
  - [ ] Reporter SA can query the views but gets *access denied* on `analytics.audit_logs` directly.
  - [ ] Force a health condition on stage (open the gate, kill a run by setting a 1-minute timeout on one manual
    execution) → an alert row with the deterministic alert ID; no duplicate on the next run.
- [ ] Promote to prod.

### Step 8. Daily metrics and the Grafana dashboard (stage, then prod)

Goal: daily aggregates exist and the team can read them in Grafana.

- [ ] Infra PR: job `quality-daily` (05:00 UTC), reader access to `ge_metrics`, Cloud Run executions list (indexer
  change events), GitHub token secret (read only).
- [ ] G4 done: SA `grafana-bolek-quality` (stage and prod) with `dataViewer` on the metrics dataset only + `jobUser`;
  datasource UIDs recorded here.
- [ ] Dashboard in `infra-grafana-dashboards/test/AI-Engineering-Lab/Conversation-Analyzer/` (`_folder.json`,
  `README.md`, `bolek-quality.json`, `dashboard.grafana.app/v1beta1`), layout of §8.8 rows 1–6, a department filter
  next to channel. Row 7 (clusters, release impact) waits for step 12; its panels show "no data yet".
- Verify:
  - [ ] `make dashboard-check DASHBOARD=…/bolek-quality.json` green on the emulator (A7).
  - [ ] `quality-daily --day <d>` twice → identical rows (recompute, not add).
  - [ ] Volume metric for a day vs the log view's count: equal.
  - [ ] Every panel renders on the test instance; no panel shows a slice under 20 turns; incomplete and paused days
    are marked.
  - [ ] Grafana SA gets *access denied* on the turns dataset.
- [ ] Promote: `prod/AI-Engineering-Lab/Conversation-Analyzer/` with the prod datasource UID; the team's first
  morning read (M5 exit: "the team reads the dashboard every morning").

### Step 9. Slack: health alerts, HIGH cluster alerts, acknowledgements (stage, then prod)

- [ ] G3 done; Slack token secret per project; `slack.enabled: true` on stage only, all messages to
  `#bolek-quality-stage`.
- [ ] Step 10 done first for HIGH alerts: without a full suite run in the environment every label is experimental and
  nothing is alerted (§11.3). Health alerts don't need it.
- Verify:
  - [ ] A forced health condition (as in step 7) posts one message; the next run doesn't repeat it.
  - [ ] A HIGH cluster alert on stage: the message carries only codes, counts, hours and the alert ID;
    `ca quality-alert-lookup --alert <id>` (as the team, read only) shows the segments' grades.
  - [ ] ✅ on the alert → the monitor records the acknowledgement and replies in the thread.
- [ ] Promote to prod (`#aiel-alerts` for health, `#bolek-quality` for HIGH).

### Step 10. Judge suite as a job (stage, then prod)

- [ ] Infra PR: job `quality-judge-suite` (by hand, 60 min), SA with Vertex and write on `quality_judge_suite_runs` only.
- Verify: one full run per environment (~7 USD each, logged) → a BASELINE row with label reliability; numbers within
  noise of A4's local run.

### Step 11. Canary and second-model check

- [ ] G5 done (or at least the daily canary on the prod engine and the evaluator accounts in `evaluator.accounts`).
- Verify: canary turns recognized (count per day = the evaluator's question count), never in metrics; planted copies
  assessed; `quality_judge_quality` has canary agreement and planted-caught rates; second-model disagreement rows on
  ~5 % of turns.

### Step 12. Weekly, anomalies, release impact, `quality-record`

- [ ] Infra PR: job `quality-weekly` (Monday 06:00 UTC), job `quality-record` (by hand).
- Verify: a weekly run twice → identical clusters; the first digest in `#bolek-quality-stage`, then in prod after an
  engineer reads it; `quality-record --kind DOCUMENT …` creates one change event; anomaly checks stay silent until
  the baseline ends (§8.6) — confirm the job logs `baseline_running`.
- [ ] Dashboard row 7 filled.

### Step 13. Closed loop

- [ ] G5 complete: gate verdicts in `aiel_evals.gate_results` name our change event IDs.
- Verify: `quality_eval_documents` filled weekly; a known change shows its gate verdict in the digest and in
  `quality_release_impact`.

### Step 14. Hand-over and close of the private repo

- [ ] Everything of `plan.md` that still matters (emulator quirks, deviations) moved into the official repo's docs.
- [ ] Private repo archived (read only) with a pointer to the official one; `aiel-content-indexers` branch
  `AIENGLAB-782` closed with a note (index dropped).

---

## 8. Timeline sketch

| Weeks from start | Work |
|---|---|
| 1 | A1–A6 (A4 includes one paid suite run); gates G1–G6 requested |
| 2 | Steps 1–3 (stage and prod) |
| 3 | Step 4 stage; A7; step 4 prod starts its 5 weekdays |
| 4 | Steps 5–6 stage; step 7 |
| 5 | Steps 5–6 prod → **go-live** (step 6), baseline weeks 1–4 begin; step 8 |
| 6–9 | Steps 9–12 during the baseline; anomaly alerts start after week 9 |
| later | Step 13 (evaluator), step 14 |

## 9. Risks and open points

| Risk | Effect | Mitigation |
|---|---|---|
| Without search, stage 2 can't tell retrieval misses from knowledge gaps | Fewer actionable "document to fix" findings | Merged code clustered by topic; revisit adding search later as its own step (the A2 commit can be reverted in the private history) |
| Evidence check with answer links only rarely runs | Turns without references stay unchecked for contradictions | Measured in step 6 (`NO_DOCUMENTS` share); remove it if it never runs |
| 72 strata with department | Many small strata pooled; standardized AQR noisier | Fewer data-store and department families (A5); freeze after week 1 of the baseline |
| Department is a quasi-identifier | `base_function` + `user_key` point at a person in `bolek_quality_turns` for small departments | Hashed email only, hash key readable by the assessor alone, 365-day expiry, explicit G2 sign-off |
| Stage reads prod text | Two places see conversations | Same SA rules as prod, gate closed by default, G1 sign-off |
| Real BigQuery behaves differently from the emulator | Write or view failures on first deploy | Dry run (step 3) and `db-init --check` before any judge call |
| Central Grafana has no BigQuery datasource | No dashboard | G4 early; fallback: a Looker Studio report over the metrics dataset until it exists |
| Evaluator late | No canary, no gate verdicts | Steps 11 and 13 are last and optional for go-live |

Resolved with the user (2026-11-02):

1. The merged stage 2 code is `NOT_IN_CITED_SOURCES` (A2).
2. Department: 3–5 families from `base_function`, privacy floor 30 associates, data-store families cut to 3
   (`ENGINEERING`, `COMPANY`, `NONE`). The mapping was filled from the stage department map on 2026-11-04 (A5).
3. The official repository is `RTBHouse-OEET/aiel-conversation-analyzer` (G6).

## 10. Deployment spend log

| Date | Environment | What | Est. USD |
|---|---|---|---|
| | | | |

## 11. Deployment record

| Step | Env | Date | Image digest | Observed | By |
|---|---|---|---|---|---|
| | | | | | |
