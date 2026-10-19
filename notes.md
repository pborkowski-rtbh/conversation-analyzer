# AIENGLAB-543: Bolek RAG - Conversation Analyzer (notes)

## Framing
- Real problem: the learning loop is open. Users ask, nobody knows which answers were good. The analyzer is one tool for closing it.
- Failure types: retrieval, corpus, generation, question. One symptom (thumbs down) can come from any of them: cheap signals say *that* something failed, deeper analysis says *why*.
- Possible shape: funnel. Cheap implicit signals flag suspect conversations, deeper analysis (LLM/human) diagnoses only flagged ones, confirmed failures become evals or corpus fixes.
- Scope now: web (Gemini Enterprise / Agentspace). Slack later (emoji reactions as feedback).
- SECOPS: parked.

## Data (project `rtbhouse-agentspace`, dataset `analytics`)
- Web interactions: `audit_logs` (`Search`, `StreamAssist`, `WriteUserEvent`), data from 2026-09-17.
- Eval traffic is ~35% of `StreamAssist` (12,151 of ~35,000). Identified by the evaluator's prompt prefix "Provide concise, focused answers that:" (from `agentspace-evaluator`). Non-eval: ~22,800 calls in 25 days (~1,000-1,600 per weekday). Upper bound on human traffic, other automated callers would not match the prefix.
- Web feedback: 37 events (27 dislike, 10 like), ~0.15% of real traffic. Each has reasons, 2 have comments. Carries `conversationInfo` (`assistToken`, `session`, `questionIndex`) and `userPseudoId`. `assistToken` is probably a better join key than the one in existing views (untested).
- Slack Bolek (`bolek_slack` in `agent_usage_analytics_*`): query, email, session, no answer text.

## Anonymization
- Composer DAG `audit_logs_annonymizer` (project `rtb-ai-engineering-indexers`, every 15 min) NULLs `response`, `serviceTextReply`, `userIamPrincipal` for rows older than 4 hours.
- DAG `audit_logs_cleanup` deletes rows older than 30 days.
- Kept: `userQuery`, tokens, full `request` JSON (incl. feedback).
- So answers, sources and identity exist for ~4 hours only. By design.

## Idea: the "analyzer" may be several systems
Split by the question each answers and the data it needs:
- **Monitoring** ("did something get worse?"): population-level, works on metadata only (re-ask rate, errors, latency, usage by department).
- **Steering** ("where to put effort?"): metadata only (retrieval share by data store, hot-but-stale / never-retrieved docs, eval coverage vs real usage).
- **Diagnosis** ("what went wrong in this answer?"): the only part that needs text, so the only part under the 4h / no-human / no-fragile-data constraints.
- **Building evals**: needs question text (and golden answers), a separate data problem from diagnosis.

If it holds, the hard requirements apply to a smaller part than the epic implies. Risk: at ~1,000-1,600 non-eval calls per weekday, metadata-only monitoring may be too noisy to catch small regressions.

## Open questions
1. Does the GCS sink `audit-logs-rtbhouse-agentspace` (empty filter, not touched by the DAGs) still hold raw un-anonymized logs? Not checked.
2. Where to hook the analyzer? Natural spot: before the 4h cutoff, write derived features to a new table. Not designed.
3. Thumbs reasons as the failure taxonomy, or our own?
4. Collect more feedback, or use the 37 as a calibration set?
5. Do implicit signals (rephrasing, abandonment, length) predict "bad"? Validate against the thumbs.
