# Bolek Quality Loop: Design Document

| | |
|---|---|
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer), task AIENGLAB-782 |
| Owner | Paweł Borkowski |
| Status | Draft, 2026-10-21. Sections 1-4 written; further sections to follow. |

## 1. Goal

**Raise Bolek's Answer Quality Rate (AQR) on real traffic, and prove every improvement with numbers.**

AQR is the share of verifiable turns whose answer was judged good, standardized to a fixed mix of question types so that a change in what people ask does not look like a change in quality. To raise it, we close Bolek's learning loop: assess every turn, find what to fix, and verify that the fix worked.

### 1.1 Why now

- Bolek answers about 900 to 1,450 questions per weekday on the web UI, and about 115 per day through Slack Bolek and MCP. Nobody knows which answers were good.
- Users give feedback on about 1 answer in 1,000, which is too little to steer by.
- Google erases the answer text, the session ID and the user's identity from the log after about 4 hours. The evidence is gone before anyone could review it.

### 1.2 What we build

An automated assessment of every turn on every channel, done inside the window, that stores **derived values only**: scores, labels from closed lists, and the document IDs of references. From these we compute AQR and the other quality metrics, ranked problem clusters, alerts, and a way to verify releases. Feedback is attached to the assessed turns. When a turn is flagged, its session segment also gets a session grade, shown in alerts as extra context for the team; no metric uses it.

### 1.3 Success criteria

Numeric targets, including the AQR increase, are set after a 4-week baseline period that starts when assessment goes live. No baseline exists today.

| # | Criterion | How we know | Target |
|---|---|---|---|
| 1 | AQR goes up | AQR per day, per channel and for all channels together | Set after the baseline |
| 2 | Every eligible turn is assessed before its answer is erased | Assessed within 3 hours; coverage, the too-large share and the not-verifiable share reported daily | Set after the baseline |
| 3 | No question or answer text is ever stored | Only derived values pass the leak guard; no person reads questions or answers | Always |
| 4 | The team knows what to fix | The weekly digest ranks problem clusters | Weekly |
| 5 | Regressions are noticed quickly | Daily anomaly alerts on the quality metrics | Set after the baseline |
| 6 | A fix can be proven | The release gate before release, then the release impact on the live numbers | Every production change |

### 1.4 Out of scope

- Reading, copying or re-asking real user questions.
- Keeping data longer than the existing 4-hour rule.
- Fixing the problems found. The loop shows the team where to look, and the team owns the fixes.

## 2. Dictionary

Terms used in this document. Each term has exactly one meaning.

- A **turn** is the unit we assess; the **answer** is the text Bolek produced in it.
- An **assessment** grades one turn; a **session grade** grades one session segment.
- A **segment** is always a part of a session; a part of an answer's text is an **answer span**.

### 2.1 Traffic and data

| Term | Definition |
|---|---|
| **Channel** | Where a question comes from: the Gemini Enterprise **web UI**, **Slack Bolek**, or **MCP** (other tools calling Bolek). Evaluator traffic is not a channel. All metrics exist per channel and for all channels together. |
| **Turn** | One user question and Bolek's answer to it: one answer call on the production engine, as recorded in Google's activity log. |
| **Answer** | The text Bolek produced in a turn, with its references. |
| **Session** | A sequence of turns that share the same session ID. The session ID exists only inside the window; we keep only a keyed hash of it, the **session key**, which cannot be turned back into the ID. |
| **Session segment** | A part of a session. A segment closes after **30 minutes without a new turn** (provisional) or is **forced closed** when its oldest turn is 3h30 old. A turn arriving after its session's segment closed starts the next segment, marked **resumed**. For most sessions, one segment is the whole session. |
| **Window** | The roughly **4 hours** after a turn during which its answer text, session ID and the user's identity exist in the log. The question text stays for 30 days. Everything we assess must be read inside the window. |
| **Anonymizer** | The existing job, running every 15 minutes, that erases answer text, session ID and identity from turns older than 4 hours. Because of its schedule, data can last up to about 4h22m. It is not changed by this project. |
| **Feedback** | A user's explicit reaction to an answer. In the web UI: a thumbs up or down, optionally with reason codes from Google's closed list and a free-text comment. In Slack: an emoji reaction. The comment is text, so it is never stored by this system; only the thumbs and the reason codes are. |
| **Reference** | A source snippet Bolek attached to an answer, with the ID and link of its document. |
| **Answer span** | A part of an answer's text that the log links to the references supporting it. Used to count unsupported claims. |
| **Data store** | A collection of documents Bolek searches, such as HR House or the API docs. Each reference belongs to one data store. |
| **Canary** | Synthetic questions from the evaluator that pass through the same log as real traffic. Unlike real turns, engineers may read them, so they are used to test and calibrate the judge. |
| **Derived value** | Anything this system stores: a number, a label from a closed list, a document ID or link, a version. Never question or answer text, summaries, or identity. |

### 2.2 Assessment

| Term | Definition |
|---|---|
| **Assessment** | The form the judge fills in for one turn: closed-list labels and scores only, no free text. |
| **Judge** | The language model filling in a form, always on an EU endpoint: `gemini-3.8-flash` for stage 1, `gemini-4-argon` for stage 2 and session grades. |
| **Stage 1** | The assessment every eligible turn gets, within about 5 to 15 minutes. |
| **Stage 2** | A deeper diagnosis of flagged turns only. The judge also reads the full source documents and is the only stage that may say *why* something failed, for example that the right document exists but was not found. |
| **Flagged turn** | A turn that goes to stage 2: relevance or groundedness 2 or lower, `HIGH` severity, a dislike, or a late trigger. |
| **Late trigger** | A signal that arrives after the turn was first assessed but while it is still in the window: a dislike, or a next turn that rephrases the question or says the answer was wrong. |
| **Rubric** | The written meaning of each score level plus synthetic example turns, given to the judge. Versioned; results from different versions are only compared through a parallel run. |
| **Intent** | The type of question: `FACT_LOOKUP`, `HOW_TO`, `TROUBLESHOOTING`, `PEOPLE_LOOKUP`, `DATA_QUESTION`, `GENERAL_TASK`, `CHITCHAT`, `OTHER`. `FACT_LOOKUP`, `HOW_TO`, `TROUBLESHOOTING` and `DATA_QUESTION` are **knowledge intents**: questions that need internal knowledge. Which fields are assessed depends on the intent. |
| **Topic** | The knowledge area of a turn (one per data store, plus `OTHER`). Taken from the data stores of its references; the judge decides it only when there are no references. |
| **Failure type** | A code from a closed list, in five families: retrieval, corpus, generation, question, system. A turn can have several; one is its **primary failure**. Retrieval and corpus codes are assigned only in stage 2. |
| **Identified problem** | A failure that is either deterministic (follows from the data, e.g. no references on a knowledge question) or confirmed against the sources. Only identified problems are recorded, so failure rates are lower bounds. |
| **Verifiable turn** | A turn whose answer can be checked against sources: any non-knowledge turn, or a knowledge turn with at least one reference. Knowledge turns without references are **not verifiable**: they are reported separately and never counted as good. |
| **Severity** | `LOW`, `MEDIUM` or `HIGH`. `HIGH` means a concrete factual error on an internal knowledge question. |
| **Reaction** | How the user's next turn in the same session relates to this one: a follow-up, a rephrase, a correction ("that's wrong"), frustration, or a new topic. A separate metric, never part of the turn's assessment. The last turn of a session has none. |
| **Fingerprint** | A hash of the IDs and versions an assessment depended on (the turn, its context turns, triggers, rubric, model). Never built from text. A turn is assessed again only when its fingerprint changes, so the same input is never assessed twice. |
| **Session facts** | Counts per session segment: number of turns, of rephrases, corrections and frustrations, the duration bucket, whether it was resumed or forced closed. Facts only. |
| **Session grade** | The judge's grade of a whole session segment, made when one of its turns is flagged: outcome (`RESOLVED`, `PARTIALLY_RESOLVED`, `UNRESOLVED`, `UNCLEAR`), the turn where it first went wrong, how often the user had to rephrase, whether the answers recovered after a correction. **Provisional** while the segment is open, **final** after a re-grade at close, **not gradable** when part of the segment's text is already erased. Informational only: no metric or ranking uses it; it is shown in alerts. |
| **PII scrubbing** | Replacing names, emails, phone numbers and similar details with placeholders such as `<PERSON_1>` before any text reaches the judge. The same value gets the same placeholder within a turn and its context. |
| **Leak guard** | The final check before anything is stored or sent: only numbers, closed-list values and allowlisted document links pass. Any free text is rejected. |

### 2.3 Measurement and action

| Term | Definition |
|---|---|
| **Eligible turn** | A turn on any channel, with an answer, between 5 minutes and 3h30 old. |
| **Coverage** | The share of eligible turns that were assessed or skipped as too large. A pipeline health measure, not quality. |
| **Too large** | A turn above the size limit (to be set). It is skipped, not partly assessed, and counted in coverage. |
| **Good answer** | A verifiable turn with relevance 4 or higher, groundedness 4 or higher (knowledge intents only), and no identified `HIGH` severity failure. The user's reaction is not used. |
| **AQR (Answer Quality Rate)** | Good answers divided by assessed verifiable turns, **standardized**: computed per stratum (intent family × data-store family) and weighted by each stratum's share in the baseline, so a change in what people ask does not look like a change in quality. Also reported raw. |
| **Failure rate** | For one failure type: turns with it as the identified primary failure, divided by assessed turns. A lower bound. |
| **Baseline** | The first 4 weeks after assessment goes live. All numeric targets and the AQR weights are set from it. |
| **Problem cluster** | Identified failures grouped by primary failure, data store and document (or by failure and topic when there is no document), ranked weekly by volume and severity. |
| **Alert** | A Slack message sent when something needs attention now: a severe problem cluster after an assessment run, a daily anomaly, or a pipeline health issue. A cluster alert carries the session grades of its turns, and each one can be looked up by the alert's ID. |
| **Digest** | The weekly Slack summary: AQR trend, top problem clusters with owners, best documents and topics, unusual items, release results. |
| **Release gate** | The check every change must pass before release: a paired offline evaluation of the candidate against the current version on synthetic questions. |
| **Anchor set** | About 300 to 500 synthetic questions, fixed per quarter, generated from documents in proportion to how much real traffic uses each data store. Must not get worse at the gate. |
| **Focus set** | 10 to 20 synthetic questions per active problem cluster, generated from its document. Must improve at the gate. |
| **Release impact** | After a release, the live numbers of the 5 weekdays before compared with the 5 weekdays after. It detects only changes of about 2 to 3 percentage points; smaller effects are judged by the gate. |
| **Change event** | A recorded change that can affect quality: a prompt, data store, model, engine or indexer change. Used to annotate alerts and to measure release impact. |

## 3. Principles and constraints

The design follows from a few rules and from what the log lets us see. Everything after this section is built on them.

### 3.1 Rules

| Rule | What it means | Why |
|---|---|---|
| **Derived values only** | The system stores scores, closed-list labels, document IDs, counts and versions. It never stores question text, answer text, summaries, feedback comments or identity. | Questions and answers can contain personal and confidential data. The anonymizer already erases the answers after 4 hours, and we must not rebuild what it removes. |
| **Synthetic questions only** | Tests use questions generated from the documents that real traffic retrieves or cites. Real questions are never re-asked or copied into a test set. | Same reason: real questions stay out of anything we keep. |
| **EU endpoints only** | Text reaches a model only on an EU endpoint (an EU region or the `eu` multi-region, never `global`), and only after PII scrubbing. | Question and answer text must not leave the EU, and personal details must not reach the model. Whether the security team accepts the `eu` multi-region is still open. |
| **Notifications only on Slack** | Alerts and the digest are sent only to Slack, in messages built from derived values. There are no per-session tickets. A dashboard may be added later; it is not part of this design yet. | One place for the team to be notified, and no path for text to leave the system. |
| **Fully automated** | No person reads questions or answers. The judge is tested on canary turns, which may be read. | Requirement of the project. Debugging and calibration use the canary, so there is never a need to look at a real turn. |
| **Only identified problems are reported** | A failure is recorded only when it follows from the data or is confirmed against the sources. When the judge is unsure, the turn is recorded as having no failure. | A false alarm costs the team's trust. The price is that failure rates are lower bounds. |
| **Not verifiable is not good** | A knowledge turn without references cannot be checked against sources. It is reported separately, never counted as good and left out of AQR. | Counting it as good would inflate AQR, and counting it as bad would invent failures. |
| **Assessment and reaction stay separate** | The assessment uses only the judge's findings. How the user reacted in the next turn is its own metric. | A rephrase may mean a bad answer or a new thought. Mixing them hides which one it was. |
| **Informational fields drive nothing** | The judge's confidence and the session grade are shown to people but used by no metric, ranking or trigger. | They are hints for the team, not checked results: confidence is the judge's own estimate, and a session grade is often provisional or missing because part of the session is already erased. |
| **All channels, one set of rules** | Web UI, Slack Bolek and MCP are assessed the same way, and every metric exists per channel and combined. | The same Bolek answers all three, so quality has to be comparable between them. |
| **The anonymizer is not touched** | It keeps its 4-hour rule and runs separately from the assessment. We store no list linking turns to sessions. | Changing retention needs a security decision, and such a list would let sessions be rebuilt after the window. |

### 3.2 What the log lets us see

| Fact | Value |
|---|---|
| Window | Answer text, session ID and identity exist for about 4 hours, up to about 4h22m because the anonymizer runs every 15 minutes. |
| Question text | Kept for 30 days. |
| Volume | About 900 to 1,450 web UI turns per weekday, 20 to 140 on a weekend day, and about 115 other API turns per day (810 in one 7-day window), which are Slack Bolek and MCP; the split between the two is not known yet. |
| Feedback | About 0.1 to 0.15% of web UI answers. |
| References | Only about 28-36% of web UI answers carry reference information in the log. This mostly reflects the answers themselves: an answer without references usually came without citations and often without any document search. Follow-up questions are the main case: 62% of first questions in a chat have references, but only 11% from the fifth question on. |
| Session ID | Present in the answer, so it is lost with the answer. Each turn has its own token, so tokens cannot group turns into a session. Slack Bolek and MCP turns have a session ID too, but almost every one of them is its own session, so a Slack thread is not one session. |
| Evaluator traffic | Passes through the same log and is told apart by its prompt prefix, which follows a leading line break. It is about 40% of all answer calls in the log, so it must be filtered out reliably. It is used as the canary, never as real traffic. It is started by hand on about half of the weekdays and sends single questions only. |

### 3.3 What follows from this

| Because | We |
|---|---|
| The evidence disappears after 4 hours | Assess inside the window, with a target of 3 hours and a hard limit of 3h30. |
| Text may not be stored | Keep derived values, and check every write with the leak guard. |
| Feedback is too rare to measure quality | Assess every turn with a judge instead of waiting for feedback. |
| Most web UI answers have no references | Treat knowledge turns without references as not verifiable: only deterministic failures are recorded for them, and they are reported separately. Whether a follow-up can be checked against the references of earlier turns in the same chat is still open. |
| Nobody may read real questions or answers | Calibrate the judge on the canary, on injected faults and by comparing it with a second model. |
| Session IDs vanish with the answer | Group turns by a keyed hash of the session ID while it exists, and keep no map. |

## 4. High-level flow

The system is one loop: assess every turn, turn the results into numbers, tell the team, fix, test, release, and check that the numbers moved.

### 4.1 The loop

```mermaid
flowchart TB
    A["1. Users ask Bolek"] --> B["2. Assess every turn<br/>inside the window"]
    B --> C["3. Keep derived values only"]
    C --> D["4. Compute metrics and<br/>rank problem clusters"]
    D --> E["5. Tell the team on Slack"]
    E --> F["6. Team fixes"]
    F --> G["7. Test on synthetic questions,<br/>release, check live numbers"]
    G --> A
```

| # | Step | In one sentence |
|---|---|---|
| 1 | Users ask Bolek | Turns arrive on the web UI, Slack Bolek and MCP; Google logs them, and the window starts. |
| 2 | Assess every turn | Every 10 minutes, new turns are scrubbed of PII and assessed by the judge, before the anonymizer erases the answers. |
| 3 | Keep derived values only | Scores, labels and document IDs are stored; all text is dropped. |
| 4 | Compute metrics and rank problem clusters | Daily metrics (AQR, failure rates, coverage, anomalies) and a weekly ranked list of problem clusters. |
| 5 | Tell the team on Slack | Alerts and a weekly digest, built only from derived values. |
| 6 | Team fixes | The team changes a prompt, a data store, the indexer, a document or the model. |
| 7 | Test, release, check | The release gate tests the change on synthetic questions; after release, release impact compares the live numbers before and after. |

### 4.2 Step 2 in detail: assessment

```mermaid
flowchart LR
    A["Eligible turn<br/>+ earlier turns<br/>of its session"] --> B["PII scrubbing"]
    B --> C["Stage 1<br/>assessment"]
    C --> D{"Flagged?"}
    D -->|"no"| F["Leak guard"]
    D -->|"yes"| E["Stage 2<br/>+ session grade"]
    E --> F
    F --> G[("Derived values")]
```

Feedback joins the same turn. A dislike that arrives while the turn is still in the window is a late trigger and flags it.

### 4.3 Step 7 in detail: verification

```mermaid
flowchart LR
    A["Candidate change"] --> B{"Release gate<br/>anchor set: not worse<br/>focus set: better"}
    B -->|"fail"| C["Back to the team"]
    B -->|"pass"| D["Release"]
    D --> E["Release impact<br/>5 weekdays before vs after"]
```

### 4.4 The life of one turn

Everything about a turn must be read before the anonymizer erases its answer.

| Time after the turn | What happens |
|---|---|
| 5 minutes | The turn becomes eligible for assessment. |
| 5 to 15 minutes | Stage 1 assessment, normally. |
| up to 3 hours | Assessment target. |
| up to 3h30 | Hard limit. Late triggers can still start stage 2 and a session grade. A turn not assessed by then is recorded as missed and cannot be recovered. |
| 4 hours (up to 4h22m) | The anonymizer erases the answer, the session ID and the user's identity. |
| 30 days | The question text is deleted. |

### 4.5 Where each guarantee is enforced

| Guarantee | Where |
|---|---|
| No text is stored | Leak guard before every write; the output has no free-text fields. |
| Text goes only to EU endpoints | PII scrubbing, then the judge on the `eu` multi-region. |
| No person reads questions or answers | Every step is automatic; the judge is tested on the canary, not on real turns. |
| Real questions are never re-asked | Verification uses synthetic questions generated from documents. |
| Notifications go only to Slack | Step 5; messages are built from derived values. |
