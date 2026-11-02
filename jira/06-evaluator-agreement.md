# 06 · Agreement with the evaluator (AIENGLAB-519) on canary runs and the aiel_evals contract

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 06 |
| Depends on | — |
| Plan | `deployment-plan.md` G5 |

### User story

As the Conversation Analyzer owner, before the canary and gate verdicts go live, I want the evaluator's owner to confirm what the evaluator delivers so that our side reads real data instead of assumptions.

### Context

The evaluator is being rebuilt in AIENGLAB-519 and writes to the BigQuery dataset `aiel_evals`. Our expected contract is in `bq/external.py` (`aiel_evals.results`, `aiel_evals.gate_results`). With the document index dropped, we no longer need the expected document of each question. Question generation from `quality_eval_documents` is not in 519's current phase.

### Acceptance criteria

* The evaluator's owner confirms a daily canary run on the production engine and its time (UTC)
* The evaluator's accounts and prompt prefix are confirmed for `evaluator.accounts` / `evaluator.prompt_prefix` in settings
* `aiel_evals.results` and `aiel_evals.gate_results` match `bq/external.py`, or the differences are listed in the ticket
* Gate results carry our change event IDs (`quality_change_events`), confirmed
* Generation of questions from `quality_eval_documents` has a phase or date, or is marked not planned
* G5 in `deployment-plan.md` is ticked with the date

### If something is not clear

Look at `design-doc.md` first, starting with §10.2, §11.4, §12.11. If it is still not clear, ask Paweł Borkowski. Don't assume.
