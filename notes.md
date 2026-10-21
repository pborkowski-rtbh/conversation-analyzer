# AIENGLAB-543: Bolek RAG - Conversation Analyzer (notes)

Current design: `design.md`. Decision IDs below match its §3.1.

## Framing
- Real problem: the learning loop is open. Users ask, nobody knows which answers were good. The analyzer is one tool for closing it.
- Failure types: retrieval, corpus, generation, question. One symptom (thumbs down) can come from any of them: cheap signals say *that* something failed, deeper analysis says *why*.
- Possible shape: funnel. Cheap implicit signals flag suspect conversations, deeper analysis (LLM/human) diagnoses only flagged ones, confirmed failures become evals or corpus fixes.
- Scope now: web (Gemini Enterprise / Agentspace). Slack later (emoji reactions as feedback).
- SECOPS: parked.

## Decisions
- **Models (D3, D8, 2026-10-20)**: `eu` multi-region is an accepted EU endpoint, never `global`. Stage 1 `gemini-3.8-flash` on every turn; stage 2 `gemini-4-argon` on flagged turns, only if necessary. Gemini 2.5 not used.
- **Stage 1 form (2026-10-21)**:
  - D9: only identified problems are reported (deterministic or confirmed against sources). Stage 1 never guesses retrieval/corpus codes; stage 2 assigns them with evidence.
  - D10: knowledge answers without citation metadata are "not verifiable": groundedness NULL, deterministic codes only, reported separately, never counted as good.
  - D11: fields gated by intent.
  - D12: rubric = level definitions + synthetic few-shot examples from canary/evaluator turns, versioned, tuned on the canary.
  - D13: oversized turns skipped as `SKIPPED_TOO_LARGE`, counted in coverage.
  - D14: quality verdict and user reaction are separate metrics.
  - D15: `confidence` informational only, no logic uses it.
  - D16: topic from cited data stores first, judge only without citations.
- TODO: detect a finished conversation; decide on sessions over 4h (`design.md` Q14).

## Data (project `rtbhouse-agentspace`, dataset `analytics`)
- Web interactions: `audit_logs` (`Search`, `StreamAssist`, `WriteUserEvent`), data from 2026-09-17.
- As of 2026-10-16: eval traffic ~35% of `StreamAssist` (12,151 of ~35,000 over 25 days), identified by the evaluator's prompt prefix "Provide concise, focused answers that:". Non-eval: ~22,800 calls in 25 days. Upper bound on human traffic. **Unresolved**: `design.md` §4.3 quotes the same 12,151 evaluator rows for 7 days (as of 2026-10-19); one of the two periods is wrong, to re-check.
- Web feedback: 37 events (27 dislike, 10 like) as of 2026-10-16; 33 (24 dislike, 9 like) as of 2026-10-19 (rolling 30-day retention). ~0.1-0.15% of real traffic. Carries `conversationInfo` (`assistToken`, `session`, `questionIndex`) and `userPseudoId`. Joins to the answer by `serviceAttributionToken` (26 of 33).
- Slack Bolek (`bolek_slack` in `agent_usage_analytics_*`): query, email, session, no answer text.

## Anonymization
- Composer DAG `audit_logs_annonymizer` (project `rtb-ai-engineering-indexers`, every 15 min) NULLs `response`, `serviceTextReply`, `userIamPrincipal` for rows older than 4 hours.
- DAG `audit_logs_cleanup` deletes rows older than 30 days.
- Kept: `userQuery`, tokens, full `request` JSON (incl. feedback).
- So answers, sources and identity exist for ~4 hours only. By design.

## Idea: the "analyzer" may be several systems
Split by the question each answers and the data it needs:
- **Monitoring** ("did something get worse?"): population-level, works on metadata only (re-ask rate, usage by department). Errors and latency are not available: no such fields in `audit_logs` (`monitoring.md` v2).
- **Steering** ("where to put effort?"): metadata only (retrieval share by data store, hot-but-stale / never-retrieved docs, eval coverage vs real usage).
- **Diagnosis** ("what went wrong in this answer?"): the only part that needs text, so the only part under the 4h / no-human / no-fragile-data constraints.
- **Building evals**: needs question text (and golden answers), a separate data problem from diagnosis.

Metadata-only monitoring was later verified as insufficient and is kept as the health layer (`design.md` §14).

## Open questions (early; status as of 2026-10-21)
1. Does the GCS sink `audit-logs-rtbhouse-agentspace` still hold raw un-anonymized logs? Answered: it keeps principal emails, 7-year unlocked retention (`design.md` §10.3).
2. Where to hook the analyzer? Answered: in-window `turn-assessor` writing derived rows (`design.md` §7.1).
3. Thumbs reasons as the failure taxonomy, or our own? Answered: own closed taxonomy (`design.md` §5.2).
4. Collect more feedback, or use the feedback as a calibration set? Answered: direction check only, too few events (`design.md` §8.13).
5. Do implicit signals predict "bad"? Replaced: user reaction is a separate metric from `relation_to_previous` (D14).
