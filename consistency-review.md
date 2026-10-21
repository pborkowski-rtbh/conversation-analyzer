# Consistency review: analysis notes vs `design.md` v4 and `design-doc.md`

| | |
|---|---|
| Date | 2026-10-21 |
| Compared | `main` at `d665478` (`design.md` Draft v4, `design-doc.md` §1-4, `notes.md`, `eli5.md`) against the analysis notes of AIENGLAB-787 and 795-803 (merged on branch `analysis-bundle`) |
| Scope | Facts and proposals that contradict each other. `design.md` and `design-doc.md` were **not edited**; the items in §1 are for their owner. |

## 1. Items in `design.md` / `design-doc.md` that the new findings contradict

Ordered by impact.

| # | Where | Now says | Finding | Suggested change | Source |
|---|---|---|---|---|---|
| 1 | `design.md` §8.1 (eligibility SQL) | `NOT STARTS_WITH(JSON_VALUE(request,'$.query.text'), 'Provide concise, focused answers that:')` excludes the evaluator | The evaluator prompt starts with a newline, so this matches 0 rows. Every evaluator turn (~41% of `StreamAssist` rows in 30 days; ~650 today) would be assessed as Slack/MCP traffic. | `NOT STARTS_WITH(LTRIM(JSON_VALUE(request,'$.query.text')), 'Provide concise, focused answers')`, as `user_activity_materialize.py:368-376` does. Same fix in §8.13 ("`query.text` plus the evaluator prefix") and wherever the canary is selected. | `canary-feasibility.md` §1, `population-filter.md` §2 |
| 2 | `design.md` §7.1, §8.4 | `Search` rows of the same principal between −30 s and +180 s | `Search` happens before the `StreamAssist` timestamp, which is the end of the answer. The window assigns 643 calls to two turns and misses 6% of citations. | Window (previous turn + 30 s, T + 30 s] ∩ [T − 120 s, T + 30 s]. Each call is assigned once, and 99.8% of cited documents are found in the turn's calls. Add `cited_in_retrieved` as a health metric. | `retrieval-linkage.md` §2-3 |
| 3 | `design.md` §8.4 | `retrieved_store_mix` "shares by ID prefix → data store" | Prefixes are ambiguous: `pages_*` and `posts_*` belong to both traffic wiki and InHouse, `sites_google_*` to both helpdesk QA and HR House. `Search` results carry only `id`. | Use a `doc_catalog` table from the indexers (`doc_id → data_store, uri_sha256`), or accept the ambiguity for those prefixes | `document-mapping.md` §4-5 |
| 4 | `design.md` §4.3, §15, Q1; `design-doc.md` §3.2 | ~28% of web answers have reference info; "the cause is not yet known" | Answered. `answer.replies` holds only grounding metadata, and its absence means "no citations". Most of those answers did no full retrieval (0 calls in 29%, 1 call in 39%). Real behavior, not a logging artifact; one synthetic UI check remains. The share falls with turn position: 62% on first turns, 11% from turn 5. | Replace "cause unknown" with the finding. Consider "context-grounded" follow-ups (an earlier turn of the same session has references, 24% of web turns) as a third grounding class next to D10. | `grounding-metadata.md` §1, §4 |
| 5 | `design.md` §8.3 / D17 | A turn after 30 min idle starts segment n+1 whose context is the previous segment's **derived** labels, "since the earlier text may be past 4h" | In the daytime samples, 6-9% of same-session continuations come after more than 30 min, and 19-29% of multi-turn sessions have such a gap. Most of those gaps are 30-120 min, so the earlier text is usually **still in the window**. Within-session gap p95 is 66 min and p98 is 100 min (midday sample). | Keep D17's segments, but give a resumed segment the **text** of the earlier segment when it is still in the window, and fall back to derived labels only when it is past 4h. D19 should then mark `NOT_GRADABLE` only when text is really gone, not on every resume. "Recalibrate to the p98 of within-session gaps" would give ~100 min, so segments would close late and session grades would wait for most of the window. Recalibrate on the share of resumes whose earlier text is gone instead. | `conversation-heuristics.md` §2, §4 |
| 6 | `design.md` §4.3 | Evening sample: 51 of 52 same-session gaps under 30 min; old rule wrong on 3 of 56 transitions | The daytime sample is larger: the old principal + 30 min rule is wrong on 46 of 392 transitions (12%), and same-session gaps of 30 min or more are 22 of 342. | Update the numbers. The conclusion (use `session_key`) only gets stronger. | `conversation-heuristics.md` §1-2 |
| 7 | `design.md` §8.3, Q17 | Slack and MCP session ID "to be verified" | In today's window, all 168 non-evaluator API turns on prod had a session ID in `response.answer.name`, but 165 of their 168 sessions had a single turn. A Slack thread is not one Gemini Enterprise session. | Answer Q17. Session facts and session grades will be near-empty for Slack/MCP unless another key is used (the Slack bot's own `session_id`, which sits in `agent_usage_analytics_*`; see item 11). | `population-filter.md` §4 |
| 8 | `design.md` §4.4, §16 Q10 | Data gap 09-30..10-04, "other methods not checked"; cause open | Only `StreamAssist` was missing, from 09-29 22:01 to 10-05 15:10 UTC. Most likely cause: the export started sending `assistToken` before the column existed. It can recur on any export schema change. | Answer Q10. Add a per-method silence alert to §7.3 / §11, and the risk "export schema change drops a method" to §15. | `data-completeness.md` |
| 9 | `design.md` §12, Q3 | ~15M stage-1 input tokens per weekday; quota to be checked | Measured input: ~3.6k characters per web turn, snippets short (p90 1.2k). Stage 1 is ~6-9M input tokens per weekday (~$7-9 per weekday now, about double from 2027). There is no per-project `eu` quota for these models (shared capacity), so retry with backoff is enough. | Replace the estimate; answer Q3. The session grade (D19) cost is still unknown, because `gemini-4-argon` has no public price. | `cost-quota.md` |
| 10 | `design.md` Q2, §7.1 stage 2 | Mapping URI/ID to `mcp-document-content` open | Answered: `gs://mcp-document-content/<data_store_id>/<sha256(uri)>.enc`, Fernet, key derived from two Secret Manager secrets (no KMS). Verified for 100% of distinct cited documents of indexer data stores. Drive (~6% of citations), BQ docs and people directory have no content. | Answer Q2. In §10.2, "reads `mcp-document-content` and its key" means read access to the bucket and the two secrets; reuse `aiel-interfaces/mcp_server/document_content.py`. | `document-mapping.md` |
| 11 | `design.md` §10.3, Q8, Q16 | SECOPS findings: `daily_user_activity` emails, GCS 7-year retention | Bigger: `agent_usage_analytics_*` (Slack) keeps `user_email`, `user_query` and some `agent_response`, with no expiry, since 2026-03-25. Q16 (Slack emoji source) may point there. Also `mcp_usage_analytics_*` and `web_channel_backfill_audit` keep emails without expiry. | Add these to §10.3. Note on Q16 that reading `agent_usage_analytics_*` would extend the analyzer onto data that breaks the 4h rule. | `secops-identity-data.md` |
| 12 | `design.md` §8.3 | Context for stage 1: up to 2 prior turns | Not a contradiction but a trade-off. The full session as context costs ~$2 per weekday more and helps `relation_to_previous` and contradiction checks on long sessions (p90 session ~20k characters). | Owner's choice; `cost-quota.md` §5 recommends full context with a 60k-character cap | `cost-quota.md` §5 |
| 13 | `design.md` §8.13; `design-doc.md` "Canary" | Evaluator turns are graded "each run" | The evaluator is run by hand: 11 of 19 weekdays had traffic. It sends single-turn questions only, in English, with a concise-answer prompt. Session-level labels and `relation_to_previous` can't be calibrated on it. | Depend on a scheduled run (AIENGLAB-524). Add a multi-turn canary set. Store `answer.name`/`assistToken` in the evaluator DB for an exact join. | `canary-feasibility.md` §4 |
| 14 | `design.md` §11 | Web UI signature check reuses the `user_activity_materialize` residuum | That check guards the API side only. It wouldn't catch a script in the web UI or growth of the "neither" shape (12 rows in 30 days with `query.parts` and no `agentsSpec`). | Add the unknown-shape, burst-user and signature-overlap checks | `population-filter.md` §3 |

## 2. Analysis notes that conflicted with decisions D17-D22, D5 (fixed in `analysis-bundle`)

| Note | Conflict | Fix |
|---|---|---|
| `conversation-heuristics.md` §4 | Proposed recomputing the session row instead of a new segment on resume (vs D17/D18) | Status line marks it as superseded by `design.md`. The useful part is kept as item 5 above (text context while it exists). |
| `conversation-heuristics.md` §5, §9 | `left_censored` and the resume check relied on a session map (rejected, D21) | Redefined as a "possibly truncated" flag; open point reworded |
| `data-completeness.md` §4 | Placed the completeness check in the combined window job (rejected, D20) | A separate job or the daily aggregation |
| `cost-quota.md` | Assumed a session pass on `gemini-3.8-flash` for every session, and web traffic only | Session grade on `gemini-4-argon` for flagged turns (D19), Slack/MCP added (D5); monthly total corrected to ~$200 now (~$400 from 2027) |
| `secops-identity-data.md` §3, §6 | Mentioned the session map as a proposal, and Slack as phase 4 | Session map noted as rejected (D21); Slack in scope from phase 1 (D5), with the Q16 risk |
| `population-filter.md`, `retrieval-linkage.md`, `grounding-metadata.md` | Said "phase 4" for Slack/MCP | In scope from phase 1 (D5); `Search` linkage for them to be measured in phase 0 |

## 3. Consistent, no change needed

- Session ID in `response.answer.name`, `assistToken` per turn, HMAC `session_key` (D17): all notes agree.
- Window up to ~4h22m (4h + max 22 min between anonymizer runs): matches the measured cadence.
- Feedback join by `assistToken` (12/12 since 10-06): matches.
- Derived values only, people-directory exclusion: `document-mapping.md` gives the exact rule (data store, `associate-` prefix, `mailto:`), which fits §8.5 / §8.7.
- `design-doc.md` must be standalone (no references to other `.md` files), per `notes.md`. The findings above have to be restated in it, not linked.

## 4. Still open

- AIENGLAB-798: the afternoon weekday sample (running) will firm up item 5 and the idle threshold.
- `gemini-4-argon` price and terms (Q4), which set the cost of stage 2 and of session grades.
