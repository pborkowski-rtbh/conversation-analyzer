# 08 · Drop PII scrubbing from the assessor

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 08 |
| Depends on | — |
| Plan | `deployment-plan.md` A3 |

### User story

As a Conversation Analyzer maintainer, when PII scrubbing is no longer required, I want the assessor to send conversations to the judge as they are so that the scrubber, its language models and its placeholders don't have to ship or be maintained.

### Context

Decided on 2026-11-02: PII scrubbing is not necessary (`design-doc.md`, revised 2026-11-02, §3.1, §6.3). Today the assessor runs a Presidio scrubber with spaCy's English and Polish models (`pii/`, about 1 GB of models and 2-3 GB of memory) and gives the references and documents the conversation's placeholders. The other rules stay: text goes only to EU endpoints, nothing the judge reads is stored, and logs carry no text. Judge v3 is still a draft, so its rubric can change here before ticket 09's paid suite run. Work happens in the private repository before migration.

### Acceptance criteria

* `pii/` (scrubber, Presidio recognisers, `evaluate.py`, `eval_set.yaml`), the `pii` settings, `make pii-eval` and `tests/test_pii.py` are removed
* The `presidio-analyzer`, `spacy`, `en-core-web-lg` and `pl-core-news-lg` dependencies are removed from `pyproject.toml` and the lock file
* The assessor, `RunDocuments.view`, the suite runner and case rendering work without a `PiiMap`; no placeholders are applied to the conversation, references or documents
* The stage 1 rubric of `judge_versions/v3` (en, pl) no longer mentions placeholders; the v3 version ID changes by hash
* The leak tests with planted personal data (stored rows, logs, Sentry) still pass and still fail if any of it appears
* `tests/test_suite.py` (oracle judge) stays at distance 0
* `CLAUDE.md`, the Makefile and the Dockerfile no longer mention the scrubber or the spaCy models; the new image size is noted in `deployment-plan.md`
* `grep -ri "presidio\|spacy\|placeholder" src` finds nothing live
* `make coverage` ≥ 90 % and `make demo` runs end to end
* A3 in `deployment-plan.md` is ticked in the same PR

### If something is not clear

Look at `design-doc.md` first, starting with §3.1, §6.3, §6.10, §12.12, §12.13. If it is still not clear, ask Paweł Borkowski. Don't assume.
