# 16 · Step 4: stage 1 in shadow on real traffic

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 16 |
| Depends on | 02, 09, 15 |
| Plan | `deployment-plan.md` Step 4 |

### User story

As a Conversation Analyzer maintainer, when stage 1 runs on real traffic, I want coverage, cost and leak checks proven in stage and then prod so that the first judged results are trustworthy and affordable.

### Context

Moves: `judge/` (forms, version, case, client, fake, stage1), the kept judge version, assessor phase 1. Judge calls go to Vertex in the job's own project, location `eu`. No Slack yet. Stage token limit is about a tenth of prod's.

### Acceptance criteria

* Infra: `aiplatform.user` for the assessor account, `--dry-run` removed, stage daily token limit ~6M
* Stage, gate open one weekday working day (~8 h) plus one overnight period: coverage ≥ 98 % excluding the first 3h30 after opening
* Oldest waiting turn < 3 h; no run over 9 min; 429 count per run noted
* Tokens per run and USD per hour recorded and extrapolated to a month (§12.15 expects ~200 USD/month for stage 1)
* Intent mix, verifiable share and `HIGH` share reviewed by an engineer
* `leak-audit` over all rows written: 0 findings; Vertex request logging confirmed off; the §12.13 audit-log content check done (ticket 02)
* After closing the gate, runs are `PAUSED` and next-day billing shows no judge cost
* Prod: coverage ≥ 98 % for 5 weekdays, daily cost within the estimate
* Spend in the deployment spend log; step 4 ticked

### If something is not clear

Look at `design-doc.md` first, starting with §6, §8.3 (pipeline health), §12.6, §12.12, §12.13, §12.15.
