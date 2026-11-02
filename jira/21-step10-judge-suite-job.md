# 21 · Step 10: judge test suite as a Cloud Run job

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 21 |
| Depends on | 15 |
| Plan | `deployment-plan.md` Step 10 |

### User story

As a Conversation Analyzer maintainer, when the judge changes, I want the suite to run as a job in each environment so that label reliability is known there and HIGH alerts can use it.

### Context

Moves: `suite/`, `suite_cases/`. Without a full suite run in an environment every label is experimental, so no HIGH cluster alert is sent (§11.3). Must come before HIGH alerts in ticket 22. One full pass is about 7 USD.

### Acceptance criteria

* Infra: job `quality-judge-suite` (by hand, 60 min), account with Vertex and write on `quality_judge_suite_runs` only
* One full run per environment stores a BASELINE row with label reliability
* Distances are within noise of the local run of ticket 08
* Spend logged; step 10 ticked

### If something is not clear

Look at `design-doc.md` first, starting with §11.1-§11.3, §12.3. If it is still not clear, ask Paweł Borkowski. Don't assume.
