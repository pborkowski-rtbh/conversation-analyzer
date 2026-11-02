# 13 · Step 1: foundations in the official repository, CI and the first image

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 13 |
| Depends on | 01, 11 |
| Plan | `deployment-plan.md` Step 1 |

### User story

As a Conversation Analyzer maintainer, when the first code moves, I want the foundations tested in CI and built into an image in both registries so that later steps only add modules.

### Context

Moves: `settings`, `vocab`, `safe_log`, `errors`, `secrets`, `keys`, `leak_guard`, `bq/` (schema, client, init), `cli` (`db-init` only), `config/`, Dockerfile, Makefile, docker-compose and their tests. No runtime in GCP yet. Images are referenced by digest, not `:latest`.

### Acceptance criteria

* The official repository holds the step-1 modules, `README.md`, `CLAUDE.md`, `design-doc.md` and `deployment-plan.md` (kept there from now on)
* `ci.yml` runs ruff, unit tests and emulator tests (docker compose in the job) with coverage ≥ 90 %; a deliberately broken test turns it red
* `cd-stage.yml` / `cd-prod.yml` build once on merge to `main` and push with the git SHA tag to both registries, printing the digest
* Infra PR (both stacks in `RTBHouse-OEET/infrastructure`): Artifact Registry repository `conversation-analyzer` and the CI writer binding
* `docker run <digest> --help` and `db-init --help` work; image size recorded
* Step 1 in `deployment-plan.md` ticked, digest in the deployment record

### If something is not clear

Look at `design-doc.md` first, starting with §12.14. If it is still not clear, ask Paweł Borkowski. Don't assume.
