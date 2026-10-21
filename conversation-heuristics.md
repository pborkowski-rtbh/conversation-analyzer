# Conversation details heuristics

| | |
|---|---|
| Ticket | AIENGLAB-787 (epic AIENGLAB-543) |
| Builds on | `session-analysis.md` (session ID, close rules), `design.md` v3 (D14: verdict and reaction are separate) |
| Status | Findings, 2026-10-21 |
| Data | `audit_logs` 4h window, Wed 2026-10-21 ~08:15-12:15 UTC: web UI, prod engine, 180 sessions, 525 turns. Read-only. Only aggregate counts were output; no question or answer text was read. |

## 1. Summary

1. **Group by `session_id`, not by principal + idle gap.** On the daytime sample, the principal + 30 min rule gets 46 of 392 consecutive-turn transitions wrong (12%). It splits 22 real sessions and merges 24 pairs of different sessions.
2. **Conversations are longer than the evening sample suggested.**
   - 57% of sessions have more than one turn, and they hold 85% of turns.
   - 10% of sessions last over 1h (26% of turns).
   - 19% of multi-turn sessions have a pause of 30 min or more.
3. **A 30 min idle close is not a session end.** It is a point at which to assess what is there so far. Session-level results must be updatable when the user comes back (§4).
4. **Cheap text heuristics carry no usable signal:**
   - word overlap for rephrase detection;
   - keyword lists for correction and frustration;
   - phrase matching for "no answer".

   Rephrase, correction and frustration need the LLM's `relation_to_previous`, as `design.md` already plans. Keep only deterministic, structural details.
5. **Side finding for AIENGLAB-795 (Q1):** grounding metadata is present exactly when `answer.replies` is present.
   - It is on 62% of first turns and only 21% of later turns, falling to 11% from the 5th turn on.
   - This points to a logging property of follow-up turns rather than ungrounded answers.

## 2. Gaps: same session vs new session

Gap to the same user's previous turn (web UI):

| Gap | Same session | New session |
|---|---|---|
| < 1 min | 62 | 1 |
| 1-5 min | 187 | 6 |
| 5-15 min | 50 | 8 |
| 15-30 min | 21 | 9 |
| 30-60 min | 11 | 7 |
| > 60 min | 11 | 19 |

- No gap threshold separates the two columns. Half of the new sessions start within 30 min of the previous one (the user clicked "new chat"). 6.4% of same-session continuations come after 30 min or more.
- Users opening a new session is the most common observed end: 44 of 180 sessions (24%) ended because the same user started another one. 119 went idle for 30 min or more, and 17 were still open.

## 3. Conversation shape

| Turns per session | Sessions | Turns |
|---|---|---|
| 1 | 77 | 77 |
| 2 | 47 | 94 |
| 3-5 | 32 | 119 |
| 6-10 | 17 | 129 |
| 11-26 | 7 | 106 |

| Duration (first to last turn) | Sessions | Turns |
|---|---|---|
| < 5 min | 112 | 156 |
| 5-30 min | 40 | 165 |
| 30-60 min | 10 | 69 |
| 1-2h | 12 | 82 |
| 2-3h30 | 6 | 53 |

- The window caps what we can see at 4h, so the long tail is underestimated. 43 sessions had their first visible turn in the first 30 min of the window, so some of them probably started earlier (left-censored). The session map from `session-analysis.md` §5.3 removes both limits.
- Questions get shorter in a conversation. Median length is 50 characters on the first turn and 41 on later turns; 29% of follow-ups are under half the previous question's length. That is typical follow-up behavior, not a quality signal.
- Custom agents: 10 turns in 2 sessions. Too few to say anything.

## 4. Proposed handling of session end

`session-analysis.md` §4 proposed: close after 30 min idle, force at 3h30, analyze in segments. The daytime data keeps the rules but changes what "close" means:

- **Per-turn verdicts don't wait for the session (D14).** A turn is assessed as soon as it lands, with the previous turns of the same session as context.
- **The session-level assessment runs at the first close** (30 min idle, or the user started another session) and writes a row keyed by `session_key`.
- **If the user comes back while earlier turns are still in the window**, the session-level row is recomputed over all turns (MERGE, same key). It is not a new segment. A new segment is created only when earlier turns are already past 4h. It then gets the previous turns' derived labels as context.
- **Final state:** the session-level row is final once the oldest turn leaves the window, or at the 3h30 hard limit. A flag `still_open_at_finalization` marks sessions cut by the window.

Why 30 min and not longer: a longer threshold only delays the first result. It does not avoid segments: 3.2% of continuations come after more than 1h anyway. With recomputation, a short threshold costs one extra LLM call for ~20% of multi-turn sessions and gives results sooner.

## 5. Conversation details to store per session

All are deterministic, computed in the window from structure only, and stored as derived values (D1):

| Field | Definition | Source |
|---|---|---|
| `session_key` | HMAC of `session_id` | `response.answer.name` |
| `n_turns`, `turn_index` (per turn) | count / order by `timestamp` | `audit_logs` |
| `duration_bucket` | `<5m`, `5-30m`, `30-60m`, `1-2h`, `2-3h30`, `>=3h30` | first to last turn |
| `max_gap_bucket`, `gap_to_previous_bucket` (per turn) | `<1m`, `1-5m`, `5-15m`, `15-30m`, `30-60m`, `>60m` | consecutive turns |
| `end_reason` | `NEW_SESSION`, `IDLE`, `WINDOW_LIMIT`, `OPEN` | §2 |
| `n_segments`, `resumed` | segments created by resume after 4h | §4 |
| `left_censored` | first turn in the first 30 min of the window and no session map entry for earlier turns | §3 |
| `grounded_turn_share` | turns with grounding metadata / turns | `answer.replies` |
| `uses_custom_agent` | any turn with `agentsSpec.agentSpecs` | request |
| `feedback_count`, `feedback_types` | joined by session | `conversationInfo.session` |
| `question_length_bucket` (per turn) | length buckets, not text | `userQuery` |

From the LLM (stage 1), once per turn and summarized per session:
- `relation_to_previous` per turn;
- per session: counts of `REPHRASE`, `CORRECTION` and `FRUSTRATION`, and `first_negative_turn_index`;
- `session_outcome` (`RESOLVED`, `ABANDONED_AFTER_FAILURE`, `UNRESOLVED`, `SINGLE_TURN`).

The last two need rubric definitions (`categorizarion.md`, "Not defined yet").

## 6. Text heuristics tested and rejected

These were computed in BigQuery inside the window. Only counts left the query.

| Heuristic | Result | Why rejected |
|---|---|---|
| Rephrase = word overlap (Jaccard of 3+ character words) with the previous question ≥ 0.3 | 8 of 345 follow-ups (2.3%) | Far below any plausible rephrase rate. Polish inflection breaks word matching, and a rephrase uses different words by definition. |
| Correction keywords (PL/EN: "nie o to", "źle", "wrong", ...) | 7.2% of first turns, 4.6% of later turns | Matches more often on first turns, where a correction is impossible, so it measures vocabulary, not corrections. |
| Frustration keywords ("??", "znowu", "again", ...) | 3 of 525 | Too rare to be a signal. |
| "No answer" phrases in the answer ("nie znalazłem", "couldn't find", ...) | 3 of 525 | Too rare. Missed refusals can't be checked without reading text, which is not allowed. |
| Fast re-ask (gap < 2 min) | 153 of 345 follow-ups | Normal conversation pace (already found in `monitoring.md`). |

The LLM labels (`relation_to_previous`, `is_refusal_or_empty`) remain the only way to get these signals. Their quality is checked on the canary stream (AIENGLAB-801), not with keyword proxies.

## 7. Grounding by position (input to AIENGLAB-795)

| Turn index in session | Turns with grounding / turns |
|---|---|
| 1 | 111 / 180 (62%) |
| 2 | 39 / 103 (38%) |
| 3-4 | 18 / 96 (19%) |
| 5+ | 16 / 146 (11%) |

- Grounding metadata and `answer.replies` are present on exactly the same turns.
- Overall share 35% (184/525), close to the ~28% in `design.md`.
- Strongest hypothesis: the export doesn't log `replies` for most follow-up turns. A model that stops retrieving would more likely still log replies without references.
- To verify in AIENGLAB-795 with evaluator multi-turn traffic and `Search` calls per turn.

## 8. Impact on other documents (not applied)

- `design.md` §8.3: replace principal + 30 min grouping with `session_key` (also `session-analysis.md` §7). Add recomputation on resume (§4 here). §9 `turn_assessments`: add `gap_to_previous_bucket` with the finer buckets from §5.
- `design.md` Q14 and the TODO in `categorizarion.md`: answered by `session-analysis.md` §4 and §4 here, pending team review.
- `design.md` §4.3, "~28% grounded": add that the share depends strongly on turn position (§7).

## 9. Open points

- Weekday afternoon sample to confirm the distributions (part of AIENGLAB-798).
- `session_outcome` definitions in the rubric.
- Whether a chat resumed from history days later keeps the same `session_id`; this needs the session map (`session-analysis.md` S4).
