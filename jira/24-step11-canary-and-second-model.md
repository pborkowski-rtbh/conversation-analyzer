# 24 · Step 11: canary and second-model check on real traffic

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 24 |
| Depends on | 06, 18 |
| Plan | `deployment-plan.md` Step 11 |

### User story

As a Conversation Analyzer maintainer, when the evaluator asks its daily canary questions, I want them assessed and compared so that the judge is checked on the real path every day.

### Context

Moves: `assessor/canary.py` and the second-model check. Canary turns are recognized by the evaluator's prompt prefix and accounts and never count in metrics.

### Acceptance criteria

* Canary turns per day equal the evaluator's question count, and none appear in the metrics
* Planted-error copies are assessed; `quality_judge_quality` has canary agreement and planted-caught rates
* Second-model disagreement rows cover about 5 % of turns
* The same in prod; step 11 ticked

### If something is not clear

Look at `design-doc.md` first, starting with §11.4, §11.5, §12.11. If it is still not clear, ask Paweł Borkowski. Don't assume.
