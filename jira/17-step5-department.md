# 17 · Step 5: department family on real traffic

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 17 |
| Depends on | 03, 10, 16 |
| Plan | `deployment-plan.md` Step 5 |

### User story

As a team member, before the baseline starts, I want every real turn to carry its department family so that the baseline weights include departments.

### Context

Moves: `people/directory.py` and the stratum code. Must be live in prod before go-live (ticket 18), because the strata freeze with the baseline.

### Acceptance criteria

* Infra: read on `directory/` of the indexers' state bucket for both assessor accounts (prefix-conditioned `objectViewer`)
* Stage, gate open 2 h: `UNKNOWN` share < 5 % of non-canary turns, else the principal format is checked and fixed
* No family below the privacy floor appears; no email in any row (`leak-audit`, schema)
* Run records show `DIRECTORY_UNAVAILABLE` = 0
* The same checks pass in prod
* Step 5 in `deployment-plan.md` ticked

### If something is not clear

Look at `design-doc.md` first, starting with §8.4.
