# Evaluator traffic as the canary stream for judge calibration

| | |
|---|---|
| Ticket | AIENGLAB-801 (epic AIENGLAB-543), `design.md` §8.13 |
| Status | Findings, 2026-10-21 |
| Data | `audit_logs` 30 days of `StreamAssist` (counts, engines, times). In-window structure of evaluator turns (counts only). Code in `aiel-agentspace-evaluator` (read-only; no DB connection). |

## 1. Summary

1. **The canary is feasible for per-turn labels, but not on a reliable schedule, and not for multi-turn behavior.**
2. **Evaluator traffic does pass through the window with the same structure as web turns.** It carries a session ID, `serviceTextReply`, and grounding metadata on 66-69% of turns (today: 213 of 324 on prod, 224 of 327 on dev).
3. **The evaluator prefix filter in `design.md` §8.1 and §4.3 misses everything.** The prompt starts with a newline, so `STARTS_WITH(..., 'Provide concise, focused answers that:')` matches 0 rows.
   - Use `STARTS_WITH(LTRIM(JSON_VALUE(request,'$.query.text')), 'Provide concise, focused answers')`, as `user_activity_materialize.py:368-376` already does, or `STRPOS(...) > 0`.
   - The same mistake hid evaluator traffic in the first version of `grounding-metadata.md` (corrected).
4. **Runs are manual and irregular.**
   - Evaluator traffic appeared on 11 of the 19 weekdays with data (2026-09-22..10-21, excluding the 09-30..10-02 export gap), from ~400 to ~4,600 turns a day, at changing hours (05:58 to 21:30 UTC).
   - Nothing schedules it: no cron, DAG or Cloud Scheduler job; the `daily_agentspace` preset is run by hand.
   - A canary that must run every day needs the scheduled run from **AIENGLAB-524**.
5. **Evaluator turns can be joined to golden answers, but only by text and time.**
   - The evaluator stores no API ID (session, answer, `assistToken`) and no per-question request time.
   - Join key: question text after stripping the prefix and `\n\nQuestion: `, the engine, and the audit timestamp within the run's `started_at..completed_at`. Retries (up to 5) can create several audit rows for one result.
   - A small evaluator change (store `answer.name` / `assistToken` per result) makes the join exact (§4).
6. **The canary distribution differs from web traffic**:
   - every evaluator call is a single-turn session;
   - questions are English-only (`languageCode=en`);
   - web grounding is off;
   - the concise-answer prompt changes answer length (median ~1,100 characters vs ~2,200 on web).

   So `relation_to_previous`, contradiction and session outcome cannot be calibrated on it at all, and answer-level agreement on the canary is an optimistic estimate for web traffic.

## 2. Evaluator traffic over 30 days

| Day | Prod engine | Dev engine | Time (UTC) |
|---|---|---|---|
| Fri 09-25 | 653 | 655 | 06:32-09:20 |
| Tue 09-29 | 205 | 204 | 12:54-13:25 |
| Tue 10-06 | 523 | 319 | 11:15-19:45 |
| Mon 10-12 | 249 | 259 | 20:42-21:30 |
| Tue 10-13 | 927 | 714 | 07:08-15:47 |
| Wed 10-14 | 719 | 501 | 12:46-19:38 |
| Thu 10-15 | 2,289 | 2,288 | 09:08-16:44 |
| Fri 10-16 | 1,630 | 1,631 | 07:35-15:51 |
| Mon 10-19 | 726 | 726 | 06:59-13:52 |
| Tue 10-20 | 568 | 571 | 05:58-08:44 |
| Wed 10-21 | 324 | 327 | 12:00-13:14 |

- No runs on 8 weekdays (09-22..24, 09-28, 10-05, 10-07..09). The 09-30..10-04 export gap is excluded (`data-completeness.md`).
- In the window today: 2 principals (developer accounts via ADC, not a service account), one session per call.
- Total over 30 days: 17,008 evaluator rows (8,813 prod, 8,195 dev). That is ~41% of all `StreamAssist` rows (41,044), so the exclusion filter matters for every volume metric.

## 3. How the evaluator calls the engine (code)

| Aspect | Value | Code |
|---|---|---|
| Endpoint | `...engines/{engine}/assistants/default_assistant:streamAssist` (EU) | `rag_clients/agentspace_api.py:75-80, 186-191` |
| Engines | prod `gemini-enterprise-rtbh-pro_1760602066633`, dev `gemini-enterprise-rtbh-dev_1761661360554` | `agentspace_api.py:60-63` |
| Query | `query.text = "\nProvide concise, focused answers that: ...\n\nQuestion: {question}"` | `agentspace_api.py:214-217`, `rag_clients/constants.py:1-8` |
| Other request settings | `languageCode=en`, web/Google grounding off, `assistSkippingMode=REQUEST_ASSIST`, optional data store spec and model ID | `agentspace_api.py:216-233` |
| Sessions | none sent, none read: one stateless call per question | same |
| Identity | `google.auth.default()`: whoever runs the CLI | `agentspace_api.py:120-133` |
| Stored per result | `answer_text`, `sources` (cited URIs), scores (LLM judge, BERTScore, grounding), `passed`, `response_time_ms`, `created_at` (batch save time) | `sqls/003_create_run_tables.sql:62-90`, `repository/results.py:46-75` |
| Stored per question | `question_text` (without the prefix), `golden_answer`, `expected_grounding` | `sqls/002_create_base_tables.sql:33-48` |
| Not stored | session name, answer name, `assistToken`, per-request timestamp | `agentspace_api.py:315-351`, `evaluator/runner.py:291` |

## 4. What is needed to make the canary work

| # | Change | Owner | Why |
|---|---|---|---|
| 1 | Fix the evaluator filter to `LTRIM` + prefix, in the design (§4.3, §8.1) and in every analysis query | AIEL (this project) | Today the canary would be empty and evaluator turns would count as API traffic |
| 2 | **Scheduled daily evaluator run** on prod, e.g. 150-300 questions at a fixed time inside working hours (AIENGLAB-524) | Evaluator | A canary sample every weekday. It also feeds the release gate's noise floor (`design.md` §8.12). |
| 3 | Store `answer.name` (contains the session ID) and `assistToken` per result, plus the request timestamp | Evaluator (small change in `agentspace_api.py` parser and the results table) | Exact join from an audit row to its golden answer and scores, instead of text + time matching |
| 4 | A **multi-turn canary set**: 20-50 synthetic conversations of 3-5 turns, sent in one session (Gemini Enterprise sessions; the evaluator would need to pass `session`), with scripted follow-ups, rephrases and corrections | Evaluator + AIEL | The only way to calibrate `relation_to_previous`, `contradicts_previous_answer` and `session_outcome` without reading real conversations. Also needed for the context-grounded follow-ups in `grounding-metadata.md` §4. |
| 5 | Optionally a canary variant without the concise prompt and with `languageCode` unset, plus a Polish subset | Evaluator | Brings answer length and language closer to web traffic, so agreement measured on the canary transfers better |

Until #2 exists, use what's there. The assessor grades evaluator turns whenever a run passes through the window and reports agreement per run. Calibration thresholds (`design.md` §8.13, kappa ≥ 0.6) are evaluated over the accumulated runs, not per day.

## 5. Join procedure until #3 exists

```text
audit row  : methodName = 'StreamAssist', STRPOS(query.text, 'Provide concise, focused answers') > 0, in window
question   : text after the last "\n\nQuestion: " in query.text
engine     : from request.name  →  rag_systems (agentspace / ge_prod / ge_dev)
run        : evaluation_runs where audit timestamp BETWEEN started_at AND completed_at and rag system matches
result     : evaluation_results JOIN questions on run_id and exact question_text
duplicates : retries → several audit rows; keep the last one before completed_at
```

The DB has a private IP (`design.md` §4.1), so the assessor needs network access to it (Cloud SQL connector from the Cloud Run job) and read-only credentials. All of it is synthetic data, so engineers may inspect it.

## 6. Impact on the design (not applied)

- §4.3 and §8.1: correct the evaluator filter (#1). Update the eval share: ~41% of `StreamAssist` rows over 30 days.
- §8.13: canary availability depends on AIENGLAB-524; add the multi-turn canary (#4). Mark session-level labels "experimental" until #4 exists.
- §11 "Canary as health check": canary absence is common today (8 of 19 weekdays without a run), not an exception.
- §16: add "evaluator stores no API IDs" as a dependency, with change #3.
