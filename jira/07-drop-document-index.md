# 07 · Drop the document index and search from the assessor

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 07 |
| Depends on | — |
| Plan | `deployment-plan.md` A2 |

### User story

As a Conversation Analyzer maintainer, when we deploy without our own document search, I want the code to read only cited and linked documents so that no indexer change, embedding model or vector search has to ship.

### Context

The design now has no document index (`design-doc.md`, revised 2026-11-02). Stage 2 and the evidence check read the full text of cited documents and of documents linked in the answer, from the content bucket. `RETRIEVAL_MISS` and `KNOWLEDGE_GAP` are replaced by `NOT_IN_CITED_SOURCES`. Work happens in the private repository before migration.

### Acceptance criteria

* `docs/index.py`, `docs/embedder.py`, chunk seeding in `devtools`, `make index-local`, the `embedding` settings, `CA_EMBEDDING_BACKEND`, the `bolek_quality_doc_index` dataset and `chunk_table()` are removed
* The `aiel-content-indexers` submodule is removed; a note on its branch `AIENGLAB-782` says the sink is not used
* Stage 2 reads cited and linked documents only; the `Stage2Phrasings` call is gone
* The cause path ends in `CHUNKING_ISSUE` (content in a cited or linked document's full text) or `NOT_IN_CITED_SOURCES` (no document to fix, clustered by topic)
* The evidence check uses only documents linked in the answer; skipped turns are counted as `NO_DOCUMENTS` in the run record
* Retrieval counts resolve the data store and people-directory exclusion from document IDs and settings, not from the index
* The canary index hit rate, `INDEX_HIT_RATE` and the knowledge-gap miss rate are removed; `closed_lists_version()` changes
* `make coverage` ≥ 90 % and `make demo` runs end to end

### If something is not clear

Look at `design-doc.md` first, starting with §6.7, §6.9, §7.2-§7.5, §11.4, §12.7.
