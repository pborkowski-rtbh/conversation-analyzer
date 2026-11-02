# 26 · Step 14: hand-over and archive of the private repository

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 26 |
| Depends on | 25 |
| Plan | `deployment-plan.md` Step 14 |

### User story

As a Conversation Analyzer maintainer, when everything runs from the official repository, I want the private repository archived and its knowledge moved so that there is one source of truth.

### Context

`plan.md` in the private repository still holds the emulator quirks and the deviations table. The `aiel-content-indexers` branch `AIENGLAB-782` holds the unused doc-index sink.

### Acceptance criteria

* Emulator quirks and still-relevant deviations from `plan.md` are in the official repository's docs
* The private repository is archived (read only) with a pointer to the official one
* `aiel-content-indexers` branch `AIENGLAB-782` is closed with a note that the index was dropped
* Step 14 in `deployment-plan.md` ticked

### If something is not clear

Look at `design-doc.md` first. If it is still not clear, ask Paweł Borkowski. Don't assume.
