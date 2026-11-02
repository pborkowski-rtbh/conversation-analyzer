# 10 · Environment settings, run gate and operational commands for real GCP

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 10 |
| Depends on | — |
| Plan | `deployment-plan.md` A5 |

### User story

As a Conversation Analyzer maintainer, when the jobs first run against real GCP, I want per-environment settings, a stage on/off switch and commands to check schema and stored rows so that every deployment step can be verified safely.

### Context

Stage (`rtb-aiel-core-stage`, datasets `stage_bolek_quality_*`) reads the prod log and must not cost anything while paused. So far the code has only run on the emulator, so the real-BigQuery paths (load job + MERGE, partition expiry, authorized views across projects) are untested. Work happens in the private repository.

### Acceptance criteria

* `config/settings.yaml` plus `config/env/{local,stage,prod}.yaml`, selected by `CA_ENV`; `local.env` sets `CA_ENV=local`
* A dataset prefix (`stage_`) is applied wherever a dataset name is built
* Run gate: `run_gate.uri`; a closed gate writes a `PAUSED` run record (assessor) or nothing (others) and exits 0; `--ignore-gate`; the monitor treats paused periods and the first 3h30 after opening as no run expected; tested on fake GCS
* `make stage-resume HOURS=n` (max 24) and `make stage-pause`, plus a `stage-gate.yml` workflow (`workflow_dispatch`) that writes the control object
* `ca quality-assessor --dry-run` reads the window and writes only the run record (no PII scrubbing, no Vertex)
* `ca db-init --check` compares live tables, columns, partitioning and views with `bq/schema.py` and exits non-zero on a difference
* `ca leak-audit --since <day>` re-runs the leak guard and a string-length check over stored rows and prints counts only
* Kill switches `stage2.enabled` and `evidence_check.enabled` (default true)
* `CA_CODE_VERSION` set from the git SHA at image build
* `CLAUDE.md` hard rules updated: real BigQuery only through deployed jobs, CI and Terraform
* `make coverage` ≥ 90 %

### If something is not clear

Look at `design-doc.md` first, starting with §12.3, §12.10, §12.12, §12.14. If it is still not clear, ask Paweł Borkowski. Don't assume.
