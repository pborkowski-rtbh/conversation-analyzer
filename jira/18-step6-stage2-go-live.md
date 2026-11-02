# 18 · Step 6: evidence check, stage 2 and session grades, then go-live

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 18 |
| Depends on | 07, 09, 17 |
| Plan | `deployment-plan.md` Step 6 |

### User story

As a team member, when a turn is flagged, I want a diagnosis of why it failed from the documents it cited or linked so that problem clusters point at what to fix, and the baseline can start.

### Context

Moves: `judge/evidence.py`, `judge/stage2.py`, `judge/session.py`, `docs/content.py`, assessor phases 2-3, late triggers. The assessor reads the prod content bucket with the content secrets (stage cross-project). Prod promotion is go-live: the 4-week baseline starts.

### Acceptance criteria

* Infra: assessor accounts read the content bucket and `mcp-content-encryption-*` secrets
* Stage, one open working day: flagged share recorded (expected < 20 %); stage 2 done / pending / given up per run, given up ≈ 0
* Share of cited documents whose full text was found in the bucket recorded; evidence check `NO_DOCUMENTS` share recorded (if near 100 %, a follow-up to remove the check is proposed)
* Cause mix recorded: `CHUNKING_ISSUE`, `NOT_IN_CITED_SOURCES`, `OUTDATED_SOURCE`, `CONFLICTING_SOURCES`, answer errors
* `gemini-4-argon` tokens per flagged turn and USD per day recorded
* Session grades become final within 3h30; not gradable counted
* `leak-audit`: 0 findings
* Prod promoted; `metrics.go_live_day` set; the date recorded in `deployment-plan.md`
* Rollback tested on stage: `stage2.enabled: false` keeps stage 1 running

### If something is not clear

Look at `design-doc.md` first, starting with §6.9, §7, §8.6, §12.6, §12.7.
