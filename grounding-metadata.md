# Missing grounding metadata on web UI answers (Q1)

| | |
|---|---|
| Ticket | AIENGLAB-795 (epic AIENGLAB-543), `design.md` Q1 |
| Status | Findings, 2026-10-21 |
| Data | `audit_logs` 4h window, Wed 2026-10-21 ~08:30-12:30 UTC, prod engine: 533 web UI turns, 143 API turns. No evaluator traffic in the window. Read-only. Only key paths and aggregate counts were output; no question, answer or snippet text was read. |

## 1. Summary

1. **`answer.replies` in the export holds only the grounding part of the answer, never the reply text.** Every `replies` entry contains only `groundedContent.textGroundingMetadata` (`references`, `segments`). The answer text is always in `serviceTextReply`, and it has the same length whether or not `replies` is present (median ~2,100 characters). So a missing `replies` means "this answer came with no citations". The answer itself is not missing or truncated.
2. **Most answers without metadata did no full retrieval.** Among web UI turns that can be attributed cleanly (no other turn by the same user within ±10 min):
   - grounded answers had `Search` calls in 99% of cases (75/76), 5 or more per turn in 89% (68/76);
   - answers without metadata had none in 29% of cases (16/56), exactly 1 call in 39% (22/56), and several calls in the rest (18/56).
3. **Grounding drops with turn position** (from AIENGLAB-787): 62% of first turns, 11% from the 5th turn on. Follow-ups are mostly answered from the conversation context without new retrieval.
4. **Conclusion: the missing metadata mostly reflects real answer behavior (answers without citations), not a logging artifact.** One residual doubt remains: do 1-call and multi-call turns without metadata show citations in the UI? A 15-minute synthetic UI test settles it (§5).
5. **Impact on the design: "not verifiable" (D10) can shrink from ~64% to ~39% of web turns.**
   - 48% of follow-ups without metadata (130/269) come after an earlier grounded turn in the same session. They can be judged against that turn's references (session-level grounding, §4).
   - 25% of answers without metadata have URLs in their text, which can be extracted deterministically as fallback citations.

## 2. Structure of `response`

Key paths of `response` on `StreamAssist`, prod engine, in the window:

| Client | `replies` present | Turns | Keys under `answer` |
|---|---|---|---|
| Web UI | no | 337 | `name`, `state` |
| Web UI | yes | 186 | `name`, `state`, `replies[].groundedContent.textGroundingMetadata.{references[].{content, documentMetadata.{document, domain, mimeType, pageIdentifier, title, uri}}, segments[].{text, startIndex, endIndex, referenceIndices}}` |
| API (Slack, MCP) | no | 20 | `name`, `state` |
| API | yes | 126 | same as web |

- `replies` never has more than 1 element. It never contains `content.text`, so the reply text is not in `response`.
- `answer.state` = `SUCCEEDED` on 100% of turns, with or without `replies`.
- API answers are grounded far more often (86%) than web UI answers (36%). API sessions are almost all single-turn, so most API turns are first turns. API callers also send longer questions (median 212 vs 82 characters).

## 3. Retrieval behind answers with and without metadata

### 3.1 When `Search` happens relative to the turn

For isolated web UI turns, `Search` rows of the same user fall 0-60 s **before** the `StreamAssist` timestamp:

| Search offset vs turn | Grounded turns | Not grounded |
|---|---|---|
| -120..-60 s | 44 | 2 |
| -60..-30 s | 74 | 8 |
| -30..0 s | 505 | 96 |
| 0..+30 s | 12 | 15 |

So the `StreamAssist` timestamp is the end of the answer, and retrieval happens before it. The window in `design.md` §8.4 (−30 s..+180 s) misses most of the calls and catches calls of the next turn. **Use −120 s..+30 s.** Input for AIENGLAB-797.

### 3.2 Calls per turn (isolated web UI turns, window −120 s..+30 s)

| `Search` calls in the window | Grounded (76) | Not grounded (56) |
|---|---|---|
| 0 | 1 | 16 |
| 1 | 2 | 22 |
| 2-4 | 5 | 7 |
| 5+ | 68 | 11 |

The distribution is bimodal. A grounded answer comes with a full retrieval round (most often 5 calls, often 9-13). Most answers without metadata come with no retrieval or with one call. A single call is probably a check-and-skip (the assistant decides not to search further), which is consistent with an answer without citations.

### 3.3 Answers without metadata are real answers

| Web UI | Turns | Median answer length | Answers with a URL in the text |
|---|---|---|---|
| First turn, no metadata | 71 | 2,434 | 13 (18%) |
| First turn, grounded | 116 | 2,090 | 36 (31%) |
| Later turn, no metadata | 269 | 2,103 | 68 (25%) |
| Later turn, grounded | 77 | 2,276 | 28 (36%) |

## 4. What this changes in the design

| Area | Change |
|---|---|
| D10 "not verifiable" | Split it in three. (a) **Grounded**: metadata on this turn. (b) **Context-grounded**: no metadata, but an earlier turn in the same session has references; groundedness is judged against those references. (c) **Not verifiable**: neither. On the sample, (a) 36%, (b) 24%, (c) 39% of web turns. (b) needs the session grouping from `session-analysis.md`, and the earlier turns must still be in the 4h window. |
| `UNGROUNDED_INTERNAL_ANSWER` | Deterministic inputs are now available: no metadata **and** no retrieval (0 `Search` calls) on a knowledge intent. This is a stronger signal than "no metadata" alone, which includes context-grounded follow-ups. |
| Fallback citations | URLs in `serviceTextReply` matching the data-store host allowlist (`design.md` §8.7) are extracted as `text_cited_uris`, deterministically and without storing text. Kept separate from `cited_doc_uris` (metadata). |
| New per-turn fields | `grounding_source` (`METADATA`, `CONTEXT`, `TEXT_URL`, `NONE`), `n_retrieval_calls` from the −120 s..+30 s window. |
| §8.4 retrieval linkage | Window −120 s..+30 s (§3.1). |
| §4.3 "~28% grounded" | The share depends on turn position and client (§2). Report it by position, not as one number. |
| Q1 | Answered: real behavior, not a logging artifact, pending the UI test (§5). |

## 5. Remaining check (synthetic, no real data)

An engineer runs ~10 synthetic conversations in the web UI with their own account, 3-5 turns each: first turns on indexed topics, follow-ups that refer back, and follow-ups on a new topic. For each turn they note whether the UI shows citations. Then they compare with `answer.replies` in `audit_logs` for their own turns, inside the 4h window.

- Citations in the UI and no `replies` in the log would mean the export drops metadata. That would bring back the logging artifact hypothesis.
- No citations in the UI would confirm that the metadata reflects the answer.

The same check tells whether the single `Search` call (§3.2) produces any visible source.

## 6. Open points

- Evaluator traffic was absent from the window, so the planned comparison with evaluator responses was not possible. It is covered by AIENGLAB-801 (canary feasibility).
- Custom agent turns: 11 in the sample, none grounded. Too few to conclude.
- The API principal is a service account with hundreds of `Search` calls per turn window, so principal-based retrieval linkage does not work for API clients (relevant for phase 4).
