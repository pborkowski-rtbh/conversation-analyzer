# Linking retrieval (`Search`) calls to turns

| | |
|---|---|
| Ticket | AIENGLAB-797 (epic AIENGLAB-543), `design.md` §8.4 |
| Builds on | `grounding-metadata.md` §3.1 (timing), `document-mapping.md` §4 (cited IDs = Search result IDs) |
| Status | Findings, 2026-10-21 |
| Data | `audit_logs` 4h window, Wed 2026-10-21 ~09:00-13:00 UTC, prod engine, web UI: 533 turns (199 grounded, 945 citations), 2,356 `Search` calls by the same users. Read-only. Only aggregate counts were output. |

## 1. Summary

1. **There is no ID linking a `Search` call to a turn.**
   - `Search.response.attributionToken` never matches `serviceAttributionToken`: 0 matches.
   - `Search` has no session or turn field, and its results carry only `id`.
   - Linking stays a time rule per user.
2. **The rule in `design.md` §8.4 (−30 s..+180 s) is wrong.** Retrieval happens before the answer is logged (`grounding-metadata.md` §3.1). The window catches the next turn's calls: 643 calls were assigned to two turns. 6% of cited documents (57/945) are missing from the calls assigned to their turn.
3. **Proposed rule:** a call belongs to turn T when it is from the same user, after the previous turn of that user (+30 s), and in [T −120 s, T +30 s].
   - Each call goes to at most one turn: 0 double assignments.
   - **99.8% of cited documents (943/945) are found in the calls assigned to their turn.**
   - 198 of 199 grounded turns get at least one call.
4. **Coverage:** 73% of web turns (390/533) get at least one call. The rest are mostly answers without retrieval (`grounding-metadata.md` §3.2), so "no calls" is a real signal (`n_retrieval_calls = 0`), not a linkage failure.
   - 89% of the users' `Search` calls are assigned to a turn.
   - Of the unassigned calls, 224 of 262 have no turn of that user within ±1h. They are probably from the UI search box or other surfaces, so they are correctly left out.
5. **Using the session is not needed for the rule.** The boundary "after the previous turn of the same user" works across parallel sessions too. The session matters only to read the per-turn result into session-level fields.

## 2. Rules compared

| | `design.md` §8.4: −30 s..+180 s | Proposed: (prev turn +30 s, T +30 s] ∩ [T −120 s, T +30 s] |
|---|---|---|
| Turns with ≥ 1 call | 410 / 533 | 390 / 533 |
| Grounded turns with ≥ 1 call | 195 / 199 | 198 / 199 |
| Calls assigned | 1,914 | 2,094 |
| Calls assigned to two turns | 643 | 0 |
| Cited documents found in the turn's calls | 888 / 945 (94.0%) | 943 / 945 (99.8%) |

Citation recall is the check of correctness. The cited document ID must appear in the retrieval results of the same turn (`document-mapping.md` §4), so a missing citation means the calls were attributed to the wrong turn.

## 3. Rule (for the assessor)

```text
for each user u, turns T1 < T2 < ... ordered by timestamp (StreamAssist row = end of answer):
  window(Tk) = ( max(Tk - 120 s, T(k-1) + 30 s) , Tk + 30 s ]
  calls(Tk)  = Search rows of u with timestamp in window(Tk)
derived per turn:
  n_retrieval_calls       = |calls(Tk)|
  retrieved_ids           = distinct results[].id over calls(Tk)        (in memory only)
  n_retrieved_results     = |retrieved_ids|
  retrieved_store_mix     = shares by data store (via doc_catalog, document-mapping.md §5)
  cited_in_retrieved      = |cited_ids ∩ retrieved_ids| / |cited_ids|  (expected ~1.0; < 1 flags a linkage issue)
  retrieved_not_cited     = |retrieved_ids \ cited_ids|                (input for RETRIEVAL_MISS / CHUNKING_ISSUE in stage 2)
  linkage_ambiguous       = Tk - T(k-1) < 150 s   (the windows would overlap without the cut)
```

- Constraint: the assessor must read `Search` rows while the principal is still present, inside the 4h window. That is already the case in `design.md` §8.1.
- The −120 s bound: 99% of calls of grounded isolated turns fall within −90 s (`grounding-metadata.md` §3.1). Long agent turns may take longer. Track the share of grounded turns with `cited_in_retrieved < 1` as a health metric, and widen the bound if it rises.

## 4. What it gives for diagnosis

- **`cited_in_retrieved`** is deterministic and close to 1. It is mostly a health check of the linkage, not a quality signal.
- **`retrieved_not_cited`** feeds stage 2: documents that were retrieved but not used. If one of them holds the answer, that points to `RETRIEVAL_MISS` in ranking or to a generation failure. That's possible now, because content is mappable via `doc_catalog` and the bucket (`document-mapping.md`).
- **`n_retrieval_calls = 0`** on a knowledge intent is the deterministic input to `UNGROUNDED_INTERNAL_ANSWER` (`grounding-metadata.md` §4).
- **Per-store retrieval share** (`retrieved_store_mix`) becomes exact with `doc_catalog`. Without it, ID prefixes are ambiguous for `pages_*`, `posts_*` and `sites_google_*`.

## 5. Limits

- Evaluator traffic runs under the developer who starts it, with 10 concurrent questions, so the per-user time rule can't separate its calls. Bolek Slack and MCP also run under user principals (`population-filter.md`). For them the rule may work, but that was not measured. They are in scope from phase 1 (D5), so measure it in phase 0.
- Two turns of the same user very close together can still split calls imperfectly. In the AIENGLAB-787 sample, 62 of 342 same-session gaps were under 1 min; the share under 30 s was not measured. `linkage_ambiguous` marks such turns.
- Only one 4h weekday sample. Re-check the citation recall weekly as part of pipeline health.

## 6. Impact on the design (not applied)

- §8.4: replace the −30 s..+180 s window with the rule in §3. Add `cited_in_retrieved` as a health metric, and `retrieved_not_cited` and `linkage_ambiguous` as fields.
- §9 `turn_assessments`: add `retrieved_not_cited`, `linkage_ambiguous`.
- §11: add "citation recall of linkage ≥ 99%" to pipeline health checks.
