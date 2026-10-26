# Bolek Quality Loop, explained simply

Start here if you are new. This is the big picture in plain words. For details and numbers see `design.md`; for the form the grader fills in see `categorizarion.md`.

Matches `design.md` Draft v5 (2026-10-21). Maintained: update this file whenever a decision changes the flow.

## The problem

Bolek is our company assistant. About 900 to 1,450 people-questions a day come through its web page, and about 115 more through Slack and MCP (other tools that call Bolek). Nobody knows which answers were good.

- People rarely click thumbs up or down (about 1 answer in 1,000). On Slack they can react with an emoji.
- Google erases the answers, and who asked, after about **4 hours**. The question text stays for 30 days.

So we can't learn from Bolek's mistakes, because the evidence disappears before anyone looks.

## The idea in one sentence

A robot grades every answer **while it still exists**, writes down only **numbers and labels** (never the text), and those numbers tell the team what to fix and whether the fixes worked.

The goal is one number going up: the **Answer Quality Rate** (the share of checkable answers that were good). Its target is set after the first 4 weeks of measuring, because today nobody knows its starting value.

## The flow, step by step

```
real question -> Bolek answers -> robot grades it (within ~3 hours)
   -> numbers saved, text forgotten -> daily and weekly summaries
   -> Slack tells the team -> team fixes something
   -> test the fix on made-up questions -> release -> check the numbers moved
```

### 1. Someone asks Bolek a question

On the web page, in Slack or through MCP: all three are graded from day one. Bolek answers. Google keeps a log of it. After 4 hours the answer, the chat's ID and the person's identity are erased from the log. We assume those 4 hours are all we will ever have.

### 2. A small program checks the log every 10 minutes

It picks up new answers that nobody has graded yet and grabs the previous 1 or 2 questions **from the same chat**, so it understands the conversation. Nobody reads any of this: it is all automatic.

How it knows which answers belong to one chat:

- Every chat has an ID hidden in the log, but only for those 4 hours. We save a scrambled version of it, so our numbers can be grouped by chat without pointing back to the real one.
- If nobody writes in a chat for 30 minutes, we treat that part of the chat as finished. A chat that goes on for hours is cut into parts, and a later part only gets the earlier part's grades as context (the text may be gone by then).
- An answer is graded again only if something it depends on changed, for example a thumbs down arrived. A fingerprint made of IDs (never text) makes sure the same situation is never graded twice.
- We record simple facts per chat (how many questions, how many "that's wrong" replies, how long it lasted).
- When an answer looks bad, the stronger grader (step 5) also grades the whole chat: did the person get what they needed, where did it go wrong, how many times did they have to ask again. This chat grade is only a hint for the team: it is shown next to alerts, but no number or ranking uses it. If part of the chat's text is already erased, the chat is marked "can't be graded" instead.

### 3. Private details are blacked out

Names, emails, phone numbers and similar details are replaced by labels like `<PERSON_1>`. The same person always gets the same label, so the grader can still follow the story.

### 4. The first grader looks at every answer (Gemini 3.8 flash, in the EU)

It fills in a fixed form, not an essay: what kind of question was it, was the answer relevant, complete, clear, was it backed by the sources Bolek showed, and did anything go wrong. The "what went wrong" answer comes from a fixed list.

Some rules for the form:

- **Only real, identified problems are reported.** If the grader is not sure, the answer is *not* marked as a failure. So our failure counts are "at least this many".
- **The grader doesn't know what is true at our company.** So an answer is "very wrong" only when one of our documents clearly says something different. If nothing is found, it is only "not backed by sources".
- **Sources from earlier in the chat count too.** Many follow-up answers show no sources because Bolek found them for the previous question. Those earlier sources are used.
- **Answers with no sources at all** (about 4 in 10 on the web page) get a quick extra check: the grader searches our documents itself and reads up to 3 of them, looking only for a clear contradiction. These answers are still called *not verifiable*: the check can catch a mistake but never prove the answer right. They are reported separately and never counted as "good".
- **Different questions get different forms.** Small talk or "write me an email" are not graded on source-backing.
- **Huge pasted texts are skipped** and counted as "too large", not half-graded.
- The grader also says how *confident* it is. That is just a hint for people. No rule or calculation uses it.
- The *topic* (for example HR or the API docs) comes from the sources the answer cited. The grader only guesses it when there are none.

### 5. A second, stronger grader looks at the doubtful ones (Gemini 4 argon, only if needed)

If the first grade is bad, the answer was very wrong, a user clicked thumbs down (or reacted badly on Slack), or the user's next message sounds like "that's wrong", the stronger grader also reads the full source documents (also blacked out) and searches our documents itself. It follows one path: was the answer in what Bolek cited, in the full document, somewhere else, or nowhere? Only it can say *why* things went wrong, for example "the right document exists but was not found" or "nobody wrote this down anywhere".

### 6. A checker stops anything unsafe

Before saving, a checker allows only numbers, picks from the fixed lists, and document links. Any free text is rejected, so nothing can quote a conversation.

### 7. Save the form, forget everything else

What is kept looks like: "Tuesday, HR topic, relevance 4, one unsupported claim, cited document X". The question and answer are never saved, and neither are summaries.

### 8. Turn grades into numbers

Every day, the grades are added up:

- **Answer Quality Rate (AQR)**: the share of checkable answers that were good. This is the number that should go up.
- **How often each kind of problem happens.**
- **User reaction**, tracked separately: how often the next message is "ask again", "that's wrong" or "this is useless".
- **Alarms** if something suddenly gets worse, or slowly drifts worse.

All numbers exist per channel (web, Slack, MCP) and for all channels together. AQR is also corrected for what people ask: a week with many easy questions must not look like a better Bolek. Groups with fewer than 20 answers on a day are not shown alone, because one bad answer would swing them too much (20 is a setting).

### 9. Turn numbers into a to-do list

Every week, the problems are grouped by document, data store and kind of failure, and ranked. For example: "Document X caused 12 unsupported answers this week, fix owner: the document owner."

### 10. Slack tells the team, the dashboard shows the trend

Slack gets only messages made from numbers: alerts for serious clusters, daily alarms, and a weekly summary with the worst and the best.

A Grafana dashboard is checked every morning, top to bottom: is the pipeline working, is anything unusual, is AQR going up, what kind of problem grew and where, how users react, and did the last fix help. It shows only daily and weekly totals.

An alert about a group of bad answers also shows how their chats went (for example "3 unresolved, 1 resolved, worst one went wrong at question 2"). Every chat grade behind an alert can be looked up.

### 11. The team fixes something

It could be a prompt, a data source, the indexer, a document, or the model.

### 12. Test the fix on made-up questions

We never re-ask real questions. We generate test questions from the documents that real traffic uses or that caused problems. A fix must not make the general test set worse and must improve the problem area. This is the release gate.

### 13. Release, then check the numbers

After release, we compare the real numbers for 5 weekdays before and after. The comparison can only see fairly big changes (around 2 to 3 percentage points), so small fixes are judged mostly by the made-up test.

## The rules that shape everything

1. **Store only derived values.** Scores, labels, document links, counts. Never question or answer text, summaries, or identity. We also never store a list linking log entries to chats, so chats can't be rebuilt after 4 hours.
2. **No person reads conversations.** Everything is automatic, and debugging uses synthetic test traffic.
3. **Only EU Gemini endpoints** (the `eu` multi-region), and only after blacking out private details.
4. **Notifications go only to Slack.** There is also one Grafana dashboard the team checks every morning. It shows only daily and weekly totals, never a single conversation.
5. **Real questions are never re-asked or copied** into tests.

## How we know the grader is any good

Nobody may read real conversations, so we check the grader on material that is allowed to be read.

- **A test suite for the grader**, like unit tests: a few hundred made-up cases covering every situation (every kind of question, every kind of mistake, whole chats), each with the grade a perfect grader would give. We measure how far the grader's answers are from those, and a change to the grader is kept only if that distance goes down. A fifth of the cases is kept hidden while tuning, to catch a grader that just learned the test.
- **Our own test traffic** (the evaluator's questions go through Bolek and the same logs), to check the whole path, and to plant known mistakes in answers and see whether the grader catches them.
- **A second model** on a small sample of real grades, to see whether the two agree.

Labels that are not trustworthy enough are shown as "experimental".

## What is not decided yet

- The grading guide: a first draft is written (what each score means, in English and Polish), but it is not yet tuned on the grader's test suite, which has to be written first.
- Whether 30 minutes is the right "chat is idle" time. We start with 30 and watch on the dashboard how often a returning user's earlier messages are already erased.
- Exactly how sure a grade must be to count as an "identified" problem.
- Whether the grader's own searches end up in the log (if they don't, it may search with words from the answer too, which finds better documents).
- Which topic to use when an answer cites several data stores.
- Why about 7 in 10 answers show no sources in the log (a spike is planned first, because it decides how useful the grader can be).
- For Slack and MCP: how to tell the two apart in the log. Slack emoji reactions are optional: used only if we find a way to collect them.
- Whether the security team accepts the `eu` multi-region, and whether our quota is enough. (The Gemini 4 argon model itself is accepted.)

## Where to read more

| File | What it has |
|---|---|
| `design.md` | The full design: decisions, facts, algorithms, data model, risks |
| `categorizarion.md` | The form the first grader fills in, the failure list, which fields apply to which question type |
| `rubric.md` | What each score level means (English and Polish), with example turns: the grading guide, first draft |
| `data-access.md` | Why the grader searches our documents itself, and when an answer counts as "very wrong" |
| `notes.md` | Decisions and early thinking |
| `session-analysis.md` | How chats (sessions) are found in the log; partly adopted, see its review table |
| `monitoring.md` | Early idea for metadata-only monitoring, now kept as the health layer |
| `funnel.md` | The first list of problem types |
