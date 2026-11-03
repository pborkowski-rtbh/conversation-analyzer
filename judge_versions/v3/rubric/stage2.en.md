# Stage 2 rubric (English)

Stage 1 said **what** went wrong with an answer. You find out **why**, with the full text of the cited documents
and of the documents linked in the answer text in front of you. There is no search: you see no other documents.
Use the stage 1 rubric for groundedness and severity.

## What is wrong with a claim

At most 3 problem claims, most important first: contradicted before unsupported before reasoning errors, key claims
before side remarks. When a claim fits more than one row, `CONTRADICTED_CLAIM` wins, and `REASONING_ERROR` wins over
`UNSUPPORTED_CLAIM`.

| Code | When |
|---|---|
| `CONTRADICTED_CLAIM` | A document you read says something specific and different on the same point: a different number, name, date, rule or step. |
| `UNSUPPORTED_CLAIM` | No document you read states the claim, and none says something different. |
| `REASONING_ERROR` | The cited snippets hold the right facts, but the answer combined them wrongly, drew a conclusion they don't support, or applied a rule to the wrong case. |

## Checks on the cited documents

Run them first, on the cited documents. Report the numbers of the documents.

| Check | When |
|---|---|
| Outdated | A cited document is contradicted on the same point by a document with a later date, or says itself that it is replaced or out of date. |
| Conflicting | Two cited documents give different specific values on the same point, and neither is clearly newer. |

## The cause path, question by question

For each claim answer these questions; the cause follows from your answers.

| Question | Rule |
|---|---|
| 1. Do the cited snippets support the claim? | "Support" means the snippet states it, or it follows directly without extra assumptions. |
| 1b. If not: do the snippets hold the right content, which the answer misread? | Then the cause is the answer itself. |
| 2. Is the right content in the full text of a cited or linked document? | It is in a document the answer cited or linked, but not in the snippet Bolek got. |

If the answer to question 2 is no, the right content is in none of the documents you read, and the cause is
`NOT_IN_CITED_SOURCES`. A turn with no references starts at question 2, on the documents linked in its answer.

For every document behind a claim, give its number and its role: `CITED`, `HOLDS_RIGHT_ANSWER`,
`CONTRADICTS_CLAIM`, `OUTDATED` or `CONFLICTING`.

## Confirming or dropping stage 1 findings

For each stage 1 code: **dropped** only if you can point to a passage that supports the claim in a document that
passed both checks, or to a passage that shows the contradiction is about a different case (another country, year or
product). Otherwise **confirmed**.

## Examples (the documents and numbers are made up)

| Situation | What | Why | Document to fix |
|---|---|---|---|
| The answer says 6 days of on-demand leave. The cited snippet is about sick leave; the full text of the same document says 4. | `CONTRADICTED_CLAIM` | `CHUNKING_ISSUE` | The cited leave policy |
| Same answer, no references; it links the leave policy, whose full text says 4. | `CONTRADICTED_CLAIM` | `CHUNKING_ISSUE` | The linked leave policy |
| Same answer, no references and no links. No document you read says anything about on-demand leave. | `UNSUPPORTED_CLAIM` | `NOT_IN_CITED_SOURCES` | (none) |
| The answer says 6 days, as the cited 2024 leave policy does. The 2026 policy, also cited, says 4. | `CONTRADICTED_CLAIM` | `OUTDATED_SOURCE` | The 2024 leave policy |
| The snippet says trips outside Europe need finance approval; the answer says all trips do. | `REASONING_ERROR` | (none) | (none) |
