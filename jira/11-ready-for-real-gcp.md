# 11 · Environment settings, run gate and operational commands for real GCP

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 11 |
| Depends on | — |
| Plan | `deployment-plan.md` A6 |

### User story

As a Conversation Analyzer maintainer, when the jobs first run against real GCP, I want per-environment settings, a stage on/off switch and commands to check schema and stored rows so that every deployment step can be verified safely.

### Context

Stage (`rtb-aiel-core-stage`, datasets `bolek_quality_*` like prod's) reads the prod log and must not cost anything while paused. So far the code has only run on the emulator, so the real-BigQuery paths (load job + MERGE, partition expiry, authorized views across projects) are untested. Work happens in the private repository.

### Acceptance criteria

* Stage and prod run the same code and `config/settings.yaml`: `CA_PROJECT` (required) is the job's own project; our datasets, the hash-key secret, the Vertex project and the department map follow from it; the log and `aiel_evals` are read from prod's project; no environment switch
* Dataset names are built in one place and are the same in both projects (no prefix)
* Run gate: `CA_RUN_GATE_URI` (stage jobs only); a closed gate writes a `PAUSED` run record (assessor) or nothing (others) and exits 0; `--ignore-gate`; the monitor treats paused periods and the first 3h30 after opening as no run expected; tested on fake GCS
* `ca run-gate resume --hours n` (max 24), `pause` and `status` write and read the control object (fake GCS)
* `ca quality-assessor --dry-run` reads the window and writes only the run record (no Vertex)
* `ca db-init --check` compares live tables, columns, partitioning and views with `bq/schema.py` and exits non-zero on a difference
* `ca leak-audit --since <day>` re-runs the leak guard and a string-length check over stored rows and prints counts only
* Kill switches `stage2.enabled` and `evidence_check.enabled` (default true)
* `CA_CODE_VERSION` set from the git SHA at image build
* `CLAUDE.md`: only what a local run with the emulator and mocks can verify lives in this repo
* `make coverage` ≥ 90 %

Moved to the migration (2026-11-05: this repo holds only what runs locally): the `CLAUDE.md` rule for real BigQuery
goes to step 1; `make stage-resume`/`stage-pause` and the `stage-gate.yml`
workflow go to step 3 (`deployment-plan.md`).

### If something is not clear

Look at `design-doc.md` first, starting with §12.3, §12.10, §12.12, §12.14.
