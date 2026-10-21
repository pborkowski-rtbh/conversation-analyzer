# Turn categorization (stage 1 form)

Source: `design.md` §3.1 (D8-D22), §5.2, §5.3, §8.3, §8.6. Each turn (web UI, Slack Bolek, MCP; D5) gets one filled-in form from the judge (`gemini-3.8-flash`, `eu` multi-region, temperature 0, structured output). All values are closed lists or numbers, no free text.

## Rules

- **Only identified problems are reported (D9).** A failure code is recorded only when it is deterministic or confirmed against the sources; otherwise `NONE`. Stage 1 never guesses retrieval or corpus codes. Failure rates are lower bounds.
- **Not verifiable (D10).** Knowledge answers without citation metadata: `groundedness` NULL, only deterministic codes, reported separately, never counted as good.
- **Gated by intent (D11).** Fields that do not apply to an intent are NULL and not asked of the judge (table below).
- **Rubric (D12).** Written meaning of each score level plus synthetic few-shot examples from canary and evaluator turns, versioned and tuned on the canary.
- **Oversized turns (D13).** Above the size cap: not graded, recorded as `SKIPPED_TOO_LARGE`, counted in coverage.
- **Verdict vs reaction (D14).** The quality verdict uses only the judge's findings. The user's reaction (next turn's `relation_to_previous`) is a separate metric; the last turn of a conversation has none.
- **Confidence (D15).** Informational only, no logic uses it.
- **Topic (D16).** From the cited data stores when there are citations, by the judge otherwise; `topic_source` records which.

## Fields

| Field | Values |
|---|---|
| `intent` | `FACT_LOOKUP`, `HOW_TO`, `TROUBLESHOOTING`, `PEOPLE_LOOKUP`, `DATA_QUESTION`, `GENERAL_TASK`, `CHITCHAT`, `OTHER`. Knowledge intents: `FACT_LOOKUP`, `HOW_TO`, `TROUBLESHOOTING`, `DATA_QUESTION`. |
| `topic`, `topic_source` | One per data-store knowledge area (about Bolek, API docs, app hints, biztech, BQ docs, Confluence, helpdesk Q&A, HR House, InHouse, know-how, traffic wiki, Google Drive, people directory) plus `OTHER`; versioned (`taxonomy_version`). `topic_source`: `CITATION` or `JUDGE`. |
| `relation_to_previous` | `FIRST`, `FOLLOW_UP`, `REPHRASE`, `CORRECTION`, `FRUSTRATION`, `NEW_TOPIC`, against the previous turn of the same session |
| `relevance`, `completeness`, `clarity` | 1-5, per intent table |
| `groundedness` | 1-5, knowledge intents with references only; judged per segment against the snippets it cites |
| `unsupported_segment_count`, `total_segment_count` | Counts from `segments[]` |
| `answer_language_matches`, `is_refusal_or_empty`, `contradicts_previous_answer`, `needs_internal_knowledge` | Booleans |
| `failure_types[]`, `primary_failure` | Stage-1 codes from the taxonomy below |
| `severity` | `LOW`, `MEDIUM`, `HIGH` (`HIGH` = concrete factual error on an internal knowledge question) |
| `confidence` | 0-1, informational only |

## Fields by intent

| Intent | `relevance` | `completeness`, `clarity` | `groundedness`, segment counts | `needs_internal_knowledge` | Failure codes |
|---|---|---|---|---|---|
| Knowledge | yes | yes | yes, if citations exist; otherwise NULL and not verifiable | yes | all; not verifiable → deterministic only |
| `PEOPLE_LOOKUP` | yes | no | no | no | `AGENT_OR_TOOL_ERROR` only |
| `GENERAL_TASK`, `CHITCHAT` | yes | yes | no | no | generation codes except `UNSUPPORTED_CLAIM`, `REASONING_ERROR`, `UNGROUNDED_INTERNAL_ANSWER`; question and system codes |
| `OTHER` | yes | yes | no | no | question and system codes |

Initial table, finalized with the rubric.

## Failure taxonomy

| Family | Code | Assigned by |
|---|---|---|
| Retrieval | `RETRIEVAL_MISS`, `CHUNKING_ISSUE` | Stage 2 only |
| Corpus | `KNOWLEDGE_GAP`, `OUTDATED_SOURCE`, `CONFLICTING_SOURCES` | Stage 2 only |
| Generation | `UNSUPPORTED_CLAIM` | Stage 1 (per segment, grounded turns only), stage 2 |
| Generation | `REASONING_ERROR` | Stage 2 only |
| Generation | `INCOMPLETE_ANSWER`, `MISUNDERSTOOD_QUERY`, `PRESENTATION_ISSUE` | Stage 1 |
| Generation | `UNGROUNDED_INTERNAL_ANSWER` | Stage 1, deterministic |
| Question | `AMBIGUOUS_QUESTION`, `OUT_OF_SCOPE` | Stage 1 |
| System | `AGENT_OR_TOOL_ERROR` | Stage 1, deterministic |
| none | `NONE` | no identified failure |

`UNGROUNDED_INTERNAL_ANSWER` is set when `needs_internal_knowledge` is true and there are no references.

## Stage 2 (flagged turns only)

`gemini-4-argon` (`eu` multi-region), only if necessary, with the cited full documents (scrubbed). Triggered by `relevance ≤ 2`, `groundedness ≤ 2`, `severity = HIGH`, a dislike, or a late trigger (next turn `REPHRASE`/`CORRECTION`). Checks snippet vs answer, then full document vs snippet, and assigns the stage-2 codes with evidence.

## Sessions (D17-D22)

- **Only the 4h window exists.** Turns are grouped by `session_key` = HMAC(engine, `session_id` from `response.answer.name`).
- **Stage 1 stays per turn**, with up to 2 prior turns of the same session as context. A turn is assessed again only when its `input_fingerprint` (IDs and versions, no text) is new: a late context row, a late trigger, or a new rubric.
- **Segments**: closed after 30 min idle (provisional) or forced at 3h30. A turn in a closed session starts segment n+1 (`resumed`), with the previous segment's derived labels as context.
- **Session facts.** `session_facts` per segment holds facts only: turn count, reaction counts, duration bucket.
- **Session grade (D19), informational only.** When a turn is flagged for stage 2, `gemini-4-argon` grades its whole segment so far: `outcome` (`RESOLVED`, `PARTIALLY_RESOLVED`, `UNRESOLVED`, `UNCLEAR`), `first_bad_turn_index`, `rephrase_bucket`, `recovered_after_correction`, `confidence`. `grade_state`: `PROVISIONAL` while open, `FINAL` after a re-grade at close, `NOT_GRADABLE` if part of the text is gone. No metric uses it; it is attached to Slack alerts, each grade reachable by `alert_id`.
- No session map is stored; the anonymizer stays separate and unchanged.
- Open (`design.md` Q14): does a chat reopened from history keep its `session_id`; the right idle threshold.

## Not defined yet

- The rubric text: level definitions and few-shot examples (approach decided, D12).
- Size cap for `SKIPPED_TOO_LARGE` (Q11).
- Exact bar for "identified" on non-deterministic stage-1 codes (Q12).
- Topic rule when an answer cites several data stores (Q13).
- A formal JSON schema.
- The stage 2 output fields.
- The session-grade rubric (level meanings of `outcome`, `rephrase_bucket` boundaries).
