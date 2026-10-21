# Web UI population filter: humans vs automated callers

| | |
|---|---|
| Ticket | AIENGLAB-802 (epic AIENGLAB-543), `design.md` §4.3, §8.1 |
| Status | Findings, 2026-10-21 |
| Data | `StreamAssist` rows over 30 days (request structure, engines, counts). 4h window Wed 2026-10-21 ~10:00-14:00 UTC (principal domains and per-user volume as counts). Code: `airflow-dags/dags/user_activity_materialize.py`. Read-only. No text was read and no identities were output. |

## 1. Summary

1. **The web UI signature holds.** `request.agentsSpec` present means web UI. No row carries both `agentsSpec` and `query.text` (0 of 20,761 web UI rows).
2. **Four populations, with clear rules:**

   | Population | Rule | 30 days, prod | 30 days, dev |
   |---|---|---|---|
   | Web UI | `agentsSpec` present | 20,706 | 55 |
   | Evaluator | `query.text` present and `STARTS_WITH(LTRIM(query.text), 'Provide concise, focused answers')` | 8,813 | 8,195 |
   | Other API (Bolek Slack, MCP) | `query.text` present, not evaluator | 2,852 | 411 |
   | Unknown | neither: `query.parts[].text` without `agentsSpec` | 12 | 0 |

3. **No automated caller shows up inside the web UI population** in the window: 132 `@rtbhouse.com` and 3 `@adlook.com` principals. The busiest user had 26 turns in 4h, never more than 2 in one minute, and no two turns of the same user were less than 10 s apart (p1 = 19 s). This is human pace.
4. **The "unknown" rows** (12 in 30 days: 1 on 10-06, 7 on 10-08, 4 on 10-15) look like a UI surface or client that sends `query.parts` without an agent spec. They are too few to matter and are excluded and counted (§3).
5. **The existing residuum check in `user_activity_materialize` covers API attribution, not the web UI side.** It compares non-evaluator `query.text` rows with Slack + MCP telemetry once a day. It would catch a new API client, or the web UI starting to send `query.text`. It would not catch a script driving the web UI, or growth of the "unknown" shape. Two small checks close that (§3).

## 2. Evidence

| Check | Result |
|---|---|
| Rows with `agentsSpec` and `query.text` | 0 of 20,761 |
| Rows with neither | 12 in 30 days, all prod; `query.parts[0]` has only `text` |
| Web UI principal domains (window) | `rtbhouse.com` 523 turns / 132 users; `adlook.com` 9 turns / 3 users |
| Turns per web UI user in 4h | 1: 51 users; 2-3: 43; 4-10: 30; 11-20: 8; 21-40: 3 (max 26) |
| Max web UI turns per user in one minute | 2 |
| Gap between consecutive turns of a user | p1 19 s, p5 37 s, median 183 s; 0 of 397 gaps under 10 s |
| Sessions per user in 4h | max 6 |
| Evaluator detection | Prefix is preceded by a newline, so `LTRIM` is required (`canary-feasibility.md`). `user_activity_materialize.py:368-376` already does it right; `design.md` §8.1 does not. |
| API principal | API rows run under user principals (39 users in the window), because Bolek Slack and MCP call on behalf of the user |

## 3. Proposed rules for the assessor

```text
client =
  'web_ui'     if JSON_QUERY(request,'$.agentsSpec') IS NOT NULL
  'evaluator'  if STARTS_WITH(LTRIM(JSON_VALUE(request,'$.query.text')), 'Provide concise, focused answers')
  'api'        if JSON_VALUE(request,'$.query.text') IS NOT NULL
  'unknown'    otherwise
assessed population (phase 1) = client = 'web_ui' AND engine = prod
```

Added checks, run daily with the completeness checks in `data-completeness.md` §4:

| Check | Rule | Action |
|---|---|---|
| Unknown shape | `unknown` rows > 20 per day, or > 1% of web UI rows | Warning: a new client or UI surface. Look at request keys only. |
| Burst user | A web UI principal with > 10 turns in 10 min, or median gap < 15 s over ≥ 10 turns | Exclude that user's turns from metrics for the day, and count them as `excluded_burst`. The principal is not stored, only the count. |
| Signature overlap | Any row with both `agentsSpec` and `query.text` | Alert: Google changed the shape, so the population rule must be reviewed |
| Domain | Principal domain not in {`rtbhouse.com`, `adlook.com`} | Count only. It shows external or test accounts appearing. |

Per-user outlier rules use the principal only in memory inside the window, like the rest of the assessor (`design.md` D1).

## 4. Impact on the design (not applied)

- §4.3: four populations with counts. The evaluator share is ~41% of `StreamAssist` rows over 30 days, not "12,151 in 7 days" via `STARTS_WITH`.
- §8.1: use the `client` rule from §3; fix the evaluator filter (`LTRIM`).
- §11 / §15 "Web-UI signature changes": add the checks from §3. The `user_activity_materialize` residuum check stays as the API-side guard.
- Slack and MCP are in scope from phase 1 (D5). `api` rows run under user principals. Whether the `Search` linkage works for them is not measured yet (`retrieval-linkage.md` §5).
- `design.md` Q17: in today's window all 168 non-evaluator API turns on prod had a session ID in `response.answer.name`, but 165 of their 168 sessions had one turn (max 2). A Slack thread is not one Gemini Enterprise session, so session context for Slack has to come from elsewhere (e.g. the Slack bot's own `session_id`).

## 5. Open points

- What produces the `unknown` rows (`query.parts` without `agentsSpec`)? Candidates: NotebookLM or deep-research pages (`agentspacePageType` values in `WriteUserEvent`), or a client using the v1 API with parts. They are not worth chasing at 12 rows a month unless the check fires.
- `adlook.com` users: confirm they are an intended user group, and decide whether they belong in metrics. They are kept here.
