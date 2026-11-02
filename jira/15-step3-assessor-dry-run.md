# 15 · Step 3: assessor dry run on the real log in stage and prod

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 15 |
| Depends on | 14 |
| Plan | `deployment-plan.md` Step 3 |

### User story

As a Conversation Analyzer maintainer, before any judge call, I want the assessor to read the real log and write run records only so that the window read, keys and BigQuery writes are proven without any text leaving memory.

### Context

Moves: `log/`, `assessor/sessions.py`, `assessor/state.py`, `assessor/run.py` (dry-run path), `bq/external.py`, `devtools/`. Stage reads prod `analytics.audit_logs` with a table-level grant. The run gate keeps stage closed by default.

### Acceptance criteria

* Infra: job `quality-assessor` (4 GiB, 2 CPU, 9 min, no retries, `--dry-run`), schedule every 10 min UTC, run-gate bucket and object (closed), table-level read on `audit_logs`, `jobUser`, Sentry DSN secret
* Stage, gate open 2 h: 12 run records `OK` with `turns_read` > 0 on weekday hours, then `PAUSED` after closing
* The oldest answer's age is ≥ 3h45 in every run
* Turns read per hour match an engineer's count from `analytics.audit_logs_public` for the same hours, or the difference is explained
* A manual re-run with the same `CA_NOW` leaves one run record (MERGE works on real BigQuery); bytes billed per run noted
* Cloud Logging of the job holds only `safe_log` events (no `@rtbhouse.com`, no question fragment); a forced failure reaches Sentry as an error class only
* `leak-audit` on the run records: 0 findings
* Prod: same checks over 24 h, still `--dry-run`
* Step 3 in `deployment-plan.md` ticked, digest recorded

### If something is not clear

Look at `design-doc.md` first, starting with §12.5, §12.6, §12.12, §12.13.
