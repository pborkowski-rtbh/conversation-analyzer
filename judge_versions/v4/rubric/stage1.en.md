# Stage 1 rubric (English)

You assess one turn of Bolek, our company assistant: the user's question and Bolek's answer. You fill in a fixed
form. Every field has a closed list of values; there is no free text.

## General rules

1. Judge only against what you are given: the question, the answer, the earlier turns and the evidence. You do not
   know what is true at the company.
2. A claim is wrong only when the evidence says something different. If the evidence says nothing about it, the
   claim is unsupported, not wrong.
3. Between two levels, choose the lower one only if you can name the concrete defect that rules out the higher one.
   Otherwise choose the higher one.
4. Score each field on its own. A clear answer can be wrong, and a correct one can be hard to read.
5. Leave out (null) fields that do not apply to the intent. Do not guess them.
6. Judge the content, not the language, unless the answer's language differs from the question's.

A **key claim** is one the user would act on: a number, name, date, rule, step, place or link.

## Intent

| Value | The question |
|---|---|
| `FACT_LOOKUP` | Asks for a fact of the company: a number, rule, date, owner of a process, a policy. |
| `HOW_TO` | Asks how to do something: steps, a procedure. |
| `TROUBLESHOOTING` | Describes a problem or error and asks how to fix it. |
| `PEOPLE_LOOKUP` | Asks about people: who someone is, who owns something, which team someone is in. |
| `DATA_QUESTION` | Asks about data: tables, fields, metrics, how to query them. |
| `GENERAL_TASK` | Asks for general work that needs no company knowledge: write, translate, summarize, code. |
| `CHITCHAT` | Greeting, thanks, small talk. |
| `OTHER` | Anything else, including questions too vague to classify. |

`FACT_LOOKUP`, `HOW_TO`, `TROUBLESHOOTING` and `DATA_QUESTION` are **knowledge intents**.

## Which fields apply to which intent

| Intent | Scores | Groundedness | Failure types |
|---|---|---|---|
| Knowledge intents | Relevance, completeness, clarity | Only when the turn has evidence (its own references or those of earlier turns) | All stage 1 codes |
| `PEOPLE_LOOKUP` | Relevance only | No | None of the judged codes |
| `GENERAL_TASK`, `CHITCHAT` | Relevance, completeness, clarity | No | `INCOMPLETE_ANSWER`, `MISUNDERSTOOD_QUERY`, `PRESENTATION_ISSUE`, `AMBIGUOUS_QUESTION`, `OUT_OF_SCOPE` |
| `OTHER` | Relevance, completeness, clarity | No | `AMBIGUOUS_QUESTION`, `OUT_OF_SCOPE` |

"Needs internal knowledge" is asked for knowledge intents only. Answer span counts are asked only for knowledge
turns with evidence whose answer the log splits into answer spans.

## Topic

The topic is the knowledge area of the turn. When the turn has references, the topic is the data store of the
references; when they come from several data stores, pick one of those. Choose freely only when there are no
references; use `OTHER` when nothing fits.

## Score levels

Two lines turn relevance and groundedness into decisions: 2 or lower flags the turn, and 4 or higher is needed for a
good answer. So the levels are sharpest at 2 and 4, and 3 means "neither".

| Level | Relevance: does it answer this question? | Completeness: does it cover every part? | Clarity: is it easy to read and use? | Groundedness: is it supported by its evidence? |
|---|---|---|---|---|
| 5 | Answers exactly the question asked, directly, at the start. | Covers every part, with what the user needs to act: steps, conditions, exceptions. | Easy to read and use at once. The answer comes first; structure and formatting fit the content. | Every claim is supported. |
| 4 | Answers the question, with a detour or material the user did not need. Also: a justified refusal of an out-of-scope question, or asking back when the question really is ambiguous. | Covers every part. A minor detail is missing that the user can do without. | Clear, but longer or less ordered than needed. | Every key claim is supported. Only side remarks or general knowledge lack support. |
| 3 | Partly on target: answers a broader or related question, and the user has to dig for the answer. | One part of a multi-part question is missing, or the main part lacks a condition or step the user needs. | Usable with effort: wordy, poorly ordered, or with unexplained jargon. | Most key claims are supported, at least one is not. Nothing is contradicted. |
| 2 | Mostly off target: about the topic, not the question. | Only a small part of the question is answered. | Hard to follow: confusing, mixing languages, or formatting that hides content. | Most key claims are unsupported, or one key claim is contradicted. |
| 1 | Does not answer: answers a different question, refuses without a reason, or is empty. | Nothing of substance is answered. | Unusable: unreadable, in the wrong language throughout, or broken. | Not backed by its evidence as a whole, or its main point is contradicted. |

- Completeness is about the question, not about the documents. Leaving out document content the user did not ask
  for is not a defect.
- For groundedness, the answer span counts guide the score, but there is no formula: one unsupported key claim
  weighs more than several unsupported side remarks. Check each answer span against the references it points to.
- A contradicted key claim always means groundedness 2 or lower, `CONTRADICTED_CLAIM` and `HIGH`.
- A key claim is contradicted when any passage of the evidence says something specific and different on the same
  point, even if another reference supports the claim. Two references that disagree do not cancel each other out.
  This includes an answer that applies a rule to a case the passage excludes or drops the rule's condition, and an
  answer that puts something else in place of what the passage says (another item in a list of what something shows
  or contains, another time period, another scope).

## Relation to the previous turn

The previous turn is the turn before it in the same session, also when a pause started a new segment. If two values
fit, the first one in this order wins: `CORRECTION`, `FRUSTRATION`, `REPHRASE`, `FOLLOW_UP`, `NEW_TOPIC`.

| Value | The user's turn |
|---|---|
| `FIRST` | Has no previous turn, or the previous turn's text is already erased. |
| `CORRECTION` | Says or shows that the previous answer was wrong: "that's not true", "it's 4 days, not 6". |
| `FRUSTRATION` | Shows annoyance or gives up: "useless", "forget it". |
| `REPHRASE` | Asks the same thing again in other words, without saying the answer was wrong. |
| `FOLLOW_UP` | Builds on the previous answer: a next step, a detail, a related question. |
| `NEW_TOPIC` | Has nothing to do with the previous turn. |

## Yes / no checks

| Check | True when |
|---|---|
| Needs internal knowledge | A correct answer depends on something specific to our company: a rule, process, system, number, name or document. "How do I book a business trip?" is true; "How do I write a SQL join?" is false; "How do I query our campaign table?" is true. |
| Answer language matches | The answer is mainly in the language of the question. Code, names and quoted document text do not count. |
| Refusal or empty | The answer declines to answer, or has no content of substance. |
| Contradicts an earlier answer | A key claim differs from a key claim of an earlier answer in the same session. |

## Failure types you may record

Record a code only if you can point to the concrete thing below. If you can't, do not record it. When you record no
code, the turn has no identified problem.

| Code | Meaning | You must be able to point to |
|---|---|---|
| `CONTRADICTED_CLAIM` | A key claim contradicts the evidence: a different number, name, date, rule or step. | A key claim and a passage of the evidence that says something specific and different on the same point |
| `UNSUPPORTED_CLAIM` | A key claim is not supported by its evidence, and no evidence contradicts it. | A key claim that no evidence supports |
| `INCOMPLETE_ANSWER` | Parts of the question are not answered. | A part of the question the answer does not address |
| `MISUNDERSTOOD_QUERY` | A different question was answered. | The different question that was answered instead |
| `PRESENTATION_ISSUE` | Wrong language or broken formatting. | The wrong language, or the formatting that hides content |
| `AMBIGUOUS_QUESTION` | Too vague to answer well; Bolek should have asked back. | Two meanings of the question that need different answers, where Bolek picked one without asking |
| `OUT_OF_SCOPE` | Not something Bolek should or can answer. The code is about the question: record it also when Bolek rightly declines. | Why Bolek should not or cannot answer it, for example a request to do something Bolek cannot do, such as booking a trip |

Do not record causes such as a missed document or an outdated source: you cannot see them in stage 1.

## Severity

Set severity only when you record a code; with no code, leave it null.

| Level | Meaning |
|---|---|
| `HIGH` | A key claim on a knowledge intent is contradicted by the evidence (`CONTRADICTED_CLAIM`). Nothing else is `HIGH`. |
| `MEDIUM` | The answer fails its purpose without a contradiction: an unsupported key claim, a missing main part, a misunderstood question, a tool error, or an internal question answered with no evidence. |
| `LOW` | The user still gets what they need: a formatting or language problem, a minor gap. |

## Confidence

Your confidence in the whole form, from 0 to 1. It is informational only.

## Examples (the documents and numbers are made up)

| Turn | Intent | Relevance | Completeness | Clarity | Groundedness | Failure, severity |
|---|---|---|---|---|---|---|
| "How many days of on-demand leave do I have?" The reference says up to 4; the answer says 6. | `FACT_LOOKUP` | 5 | 5 | 5 | 1 | `CONTRADICTED_CLAIM`, `HIGH` |
| "How do I book a business trip, and who approves it?" The answer explains only the booking, which the reference supports. | `HOW_TO` | 5 | 3 | 5 | 5 | `INCOMPLETE_ANSWER`, `MEDIUM` |
| "What's the limit?", with no earlier turns. The answer explains meal expense limits at length. | `OTHER` | 2 | 2 | 4 | (not asked) | `AMBIGUOUS_QUESTION`, `MEDIUM` |
| "What does the monthly invoice list?" The reference says the net amount and the VAT per campaign; the answer says the net amount and the number of impressions. | `FACT_LOOKUP` | 5 | 5 | 5 | 1 | `CONTRADICTED_CLAIM`, `HIGH` |

In the first example relevance stays 5: the answer is on target, just wrong. In the second, the missing part lowers
completeness, not relevance. That is why every field is scored on its own. In the third, Bolek should have asked
which limit was meant; the guess missed the question, so the user did not get what they needed.
