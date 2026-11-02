# 09 · Judge v3 and the judge test suite without search

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 09 |
| Depends on | 07, 08 |
| Plan | `deployment-plan.md` A4 |

### User story

As a Conversation Analyzer maintainer, when stage 2 no longer searches, I want a judge version and suite cases that match the new cause path so that the judge is trusted on what it actually does.

### Context

Judge v2 (current) was kept by the suite on 2026-10-29 with search results in its inputs. Removing search changes the stage 2 rubric, prompt and form, so it is a new judge version (`judge_versions/v3`), and the suite cases change, so the next full run is a new BASELINE. Paid Vertex spend so far: 14.51 of 50 USD; one full pass is about 7 USD and 35 minutes.

### Acceptance criteria

* `judge_versions/v3` exists (copy of v2) with the stage 2 rubric and prompt without found documents and the form with `NOT_IN_CITED_SOURCES`
* Every suite case expecting `RETRIEVAL_MISS` or `KNOWLEDGE_GAP` is rewritten; documents only a search could reach are removed; `make suite-coverage` meets the §11.1 minimums (adjusted for the merged code)
* `tests/test_suite.py` (oracle judge) stays at distance 0
* `make suite-live JUDGE_VERSION=v3`, one pass, gives: missed HIGH = 0, false HIGH ≤ 4, held-out distance ≤ 1.15, no label under 70 % recall except `REASONING_ERROR`; otherwise a tuned v4 meets them (tuning part only)
* Each paid run is logged in the spend log of `plan.md`
* `judge.current_version` names the kept version

### If something is not clear

Look at `design-doc.md` first, starting with §7.3-§7.5, §11.1-§11.3.
