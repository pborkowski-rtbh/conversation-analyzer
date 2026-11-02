# 25 · Step 12: weekly clusters, digest, anomalies, release impact and quality-record

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 25 |
| Depends on | 21, 23 |
| Plan | `deployment-plan.md` Step 12 |

### User story

As a team member, every Monday, I want a ranked list of problem clusters and the release results in a digest so that we know what to fix next and whether the last fix helped.

### Context

Moves: `reporting/weekly.py`, `anomaly.py`, `release.py`, `record.py`, the digest. Anomaly alerts stay silent until the baseline ends (§8.6).

### Acceptance criteria

* Infra: job `quality-weekly` (Monday 06:00 UTC) and job `quality-record` (by hand)
* A weekly run twice gives identical clusters
* The first digest appears in `#bolek-quality-stage`, then in prod after an engineer reads it
* `quality-record --kind DOCUMENT ...` creates exactly one change event
* The daily job logs `baseline_running` and raises no anomaly during the baseline
* Dashboard row 7 (clusters, release impact) is filled; step 12 ticked

### If something is not clear

Look at `design-doc.md` first, starting with §8.6, §8.7, §9, §10.3, §12.9.
