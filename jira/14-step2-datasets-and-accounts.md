# 14 · Step 2: datasets, service accounts and tables in stage and prod

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 14 |
| Depends on | 13 |
| Plan | `deployment-plan.md` Step 2 |

### User story

As a Conversation Analyzer maintainer, before any job runs, I want every dataset, table and service account to exist with the right access so that the jobs start from a checked, empty state.

### Context

Terraform creates datasets, service accounts, IAM and the `quality-db-init` job; the tables come from `bq/schema.py` through `quality-db-init`. Stage uses the same dataset names and `stage-` accounts in `rtb-aiel-core-stage`. Datasets are never dropped.

### Acceptance criteria

* Stage: datasets `bolek_quality_turns`, `bolek_quality_metrics`, `bolek_quality_log_views` in `rtb-aiel-core-stage` (location `EU`, 365-day partition expiry on turns), service accounts `stage-quality-assessor`, `stage-quality-reporter`, `stage-quality-judge-suite`, `stage-quality-schema`, dataset IAM per §12.4, job `quality-db-init`, hash-key secret (value set by hand)
* `quality-db-init` run once; `quality-db-init --check` exits 0; a second run changes nothing
* An engineer's read-only IAM review shows every account has exactly the §12.4 access; nobody but the assessor reads `audit_logs` or the hash key
* The same in prod (`bolek_quality_*`, accounts without prefix), with its own hash key
* Step 2 in `deployment-plan.md` ticked

### If something is not clear

Look at `design-doc.md` first, starting with §12.4, §12.10.
