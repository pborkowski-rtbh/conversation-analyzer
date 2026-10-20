# Turn categorization (stage 1 form)

Source: `design.md` §5.2, §5.3, §8.6. Each web turn gets one filled-in form from the judge (`gemini-3.8-flash`, `eu` multi-region, temperature 0, structured output). All values are closed lists or numbers, no free text.

## Fields

| Field | Values |
|---|---|
| `intent` | `FACT_LOOKUP`, `HOW_TO`, `TROUBLESHOOTING`, `PEOPLE_LOOKUP`, `DATA_QUESTION`, `GENERAL_TASK`, `CHITCHAT`, `OTHER` |
| `topic` | One per data-store knowledge area (about Bolek, API docs, app hints, biztech, BQ docs, Confluence, helpdesk Q&A, HR House, InHouse, know-how, traffic wiki, Google Drive, people directory) plus `OTHER`. Versioned (`taxonomy_version`). |
| `relation_to_previous` | `FIRST`, `FOLLOW_UP`, `REPHRASE`, `CORRECTION`, `FRUSTRATION`, `NEW_TOPIC` |
| `relevance`, `completeness`, `clarity` | 1-5 |
| `groundedness` | 1-5, only if references exist; judged per segment against the snippets it cites |
| `unsupported_segment_count`, `total_segment_count` | Counts from `segments[]` |
| `answer_language_matches`, `is_refusal_or_empty`, `contradicts_previous_answer`, `needs_internal_knowledge` | Booleans |
| `failure_types[]`, `primary_failure` | Failure taxonomy below |
| `severity` | `LOW`, `MEDIUM`, `HIGH` (`HIGH` = concrete factual error on an internal knowledge question) |
| `confidence` | 0-1 |

## Failure taxonomy

| Family | Codes |
|---|---|
| Retrieval | `RETRIEVAL_MISS`, `CHUNKING_ISSUE` |
| Corpus | `KNOWLEDGE_GAP`, `OUTDATED_SOURCE`, `CONFLICTING_SOURCES` |
| Generation | `UNSUPPORTED_CLAIM`, `REASONING_ERROR`, `INCOMPLETE_ANSWER`, `MISUNDERSTOOD_QUERY`, `PRESENTATION_ISSUE`, `UNGROUNDED_INTERNAL_ANSWER` |
| Question | `AMBIGUOUS_QUESTION`, `OUT_OF_SCOPE` |
| System | `AGENT_OR_TOOL_ERROR` |
| none | `NONE` |

`UNGROUNDED_INTERNAL_ANSWER` is set when `needs_internal_knowledge` is true and there are no references.

## Stage 2 (flagged turns only)

`gemini-4-argon` (`eu` multi-region), only if necessary, with the cited full documents (scrubbed). Triggered by `relevance ≤ 2`, `groundedness ≤ 2`, `severity = HIGH`, a retrieval/corpus failure, a dislike, or a late trigger. Checks snippet vs answer, then full document vs snippet, and refines the failure types.

## Not defined yet

- The rubric prompt and the meaning of each 1-5 level.
- A formal JSON schema.
- The stage 2 output fields.
