# Mapping cited and retrieved documents to their content (Q2)

| | |
|---|---|
| Ticket | AIENGLAB-796 (epic AIENGLAB-543), `design.md` Q2 |
| Status | Findings, 2026-10-21 |
| Data | Code in `aiel-content-indexers` (branch `associates-indexer`) and `aiel-interfaces` (MCP server). GCS `mcp-document-content`: object names only. `audit_logs` 4h window, prod engine: reference resource names, URI hosts and ID patterns. No document content was read and nothing was decrypted. |

## 1. Summary

1. **A cited document maps to its content with one deterministic rule:** `gs://mcp-document-content/<data_store_id>/<sha256(uri)>.enc`.
   - `data_store_id` comes from `references[].documentMetadata.document` (`.../dataStores/<id>/branches/0/documents/<doc_id>`).
   - `uri` is `references[].documentMetadata.uri`.
   - Verified on the window: **100% of distinct cited documents of the indexer data stores** (1,075 of 1,075) have an object at that path.
2. **The data stores without content are:**
   - Google Drive (a native connector, 76 distinct cited documents, ~6% of citations);
   - `rtb-bq-documentation-v2` (no `content_sink`);
   - the people directory (`rtb-associates`, excluded on purpose).
   - Overall, ~94% of prod citations can be mapped to full content.
3. **The MCP server already reads these objects.** `aiel-interfaces/mcp_server/document_content.py` resolves URI to data store, then to `sha256(uri)`, and decrypts with Fernet. The stage-2 assessor can reuse that code and its read-only service account pattern instead of writing a new reader.
4. **Retrieved documents (`Search` results) are keyed by the same document ID as citations.** 100% of cited document IDs appear in the same user's `Search` results right before the turn. But `Search` results carry only `id`, with no URI and no data store, and some ID prefixes are shared by several data stores. Mapping retrieved-but-not-cited documents needs a **document catalog** (`doc_id → data_store, uri_sha256`) exported by the indexers (§5).
5. **People-directory documents can be excluded reliably** by data store (`rtb-associates`, `people-connections_*`), by the `associate-` ID prefix, or by a `mailto:` URI.

## 2. Path from indexer to data store and bucket

One sink writes both: `aiel-content-indexers/src/common/sinks/vertex_ai_sink.py`.

| Step | Detail | Code |
|---|---|---|
| Document ID | `_normalize_document_id`: strips `http(s)://`, replaces characters outside `[A-Za-z0-9-_]` with `_`, collapses repeats. IDs over 128 characters are cut to 119 + `_` + md5[:8]. | `vertex_ai_sink.py:358-386` |
| Data store fields | `structData`: `id`, `title`, `uri` = source URL, `mime_type`, `relevant_for_team` | `vertex_ai_sink.py:515-570` |
| Content object | `<data_store_id>/<sha256(url)>.enc`; optional raw HTML at `<data_store_id>/raw/<sha256(url)>.enc`. Parts with the same URL are joined; `:chunk:` parts are skipped (the main document holds the full text). | `vertex_ai_sink.py:201-275`, hash in `common/utils/fingerprint_delta.py:24-26` |
| Format | Fernet token over JSON `{title, url, content, chunk_count}` | same |
| Encryption | Fernet key from PBKDF2-HMAC-SHA256 over two Secret Manager secrets (`mcp-content-encryption-key`, `mcp-content-encryption-salt`, indexers project). No KMS. | `vertex_ai_sink.py:178-199` |
| Write identity | `mcp-content-rw@rtb-ai-engineering-indexers` (impersonated) | `vertex_ai_sink.py:129-142` |
| Cleanup | Objects whose hash is not in the current run are deleted | `vertex_ai_sink.py:297-329` |
| Reader | MCP: search the engine with `uri: ANY("<url>")`, take the data store from `document.name`, read `<ds>/<sha256(url)>.enc` | `aiel-interfaces/mcp_server/document_content.py:34-138`, `tools/bolek.py:327-520` |

## 3. Data stores, ID formats and content availability

Distinct cited documents in the window, prod engine. "In bucket" means `sha256(uri)` was found among the object names of that data store folder.

| Data store | Document ID format | URI | Cited docs | In bucket |
|---|---|---|---|---|
| `rtb-confluence-v2` | `confluence_<SPACE>_<pageId>_v<ver>` (chunks add `_chunk_<i>`) | `rtbhouseproduct.atlassian.net/wiki/...` | 401 | 401 |
| `rtb-knowhow-v2` | `know_how_<postId>` | `knowhow.rtbhouse.com/posts/...` | 250 | 250 |
| `rtb-biztech-v2` | DokuWiki ID, normalized (`tech_...`, `landed_click...`, `bid_rejection...`) | `biztech.rtbhouse.com/dokuwiki/doku.php?id=...` | 159 | 159 |
| `rtb-traffic-wiki-v2` | `docs_<n>`, `pages_<n>`, `posts_<n>` | `traffic-wiki.rtbhouse.biz/...` | 140 | 140 |
| `rtb-inhouse-v2` | `pages_<n>`, `posts_<n>` | `inhouse.rtbhouse.net/?page_id=...` | 76 | 76 |
| `rtb-helpdesk-qa-v2` | normalized page URL (`sites_google_com_rtbhouse_com_hdqa_...`) | `sites.google.com/rtbhouse.com/hdqa/...` | 21 | 21 |
| `rtb-hr-house-v2` | normalized page URL (`sites_google_com_rtbhouse_com_hr-house-...`) | `sites.google.com/rtbhouse.com/hr-house...` | 12 | 12 |
| `rtb-app-hints-v2` | normalized hint URL (`api_apps-tools_rtbhouse_biz_helps_edit_...`) | `api.apps-tools.rtbhouse.biz/helps/edit/...` | 8 | 8 |
| `rtb-about-bolek-v2` | `bolek-website_<blob>` | `about.bolek.rtbhouse.net/...` | 5 | 5 |
| `rtb-api-docs-v2` | `<api>_endpoint_...`, `..._model_...`, `parser_api...`, `web_api...` | spec or page URL | 3 | 3 |
| `gdrive_collection_22062025_google_drive` | Drive file ID | `drive.google.com/...` | 76 | 0 (native connector, no content sink) |
| `rtb-bq-documentation-v2` | `bq-doc-<event_type>[--<field>]` | BigQuery console URL | 2 | 0 (no content sink) |
| `rtb-associates` | `associate-<sha256(email)[:32]>` | `mailto:<email>` | 5 | 0 (excluded by design) |

Not seen in citations in the window, but present:
- `rtb-doc-repo-v2` is in the bucket, but the MCP marks it disabled.
- `rtb-otrs-v2_dev` exists only as a dev folder.
- Calendar and `people-connections_*` are native connectors.
- Hints split into several parts get `:chunk:` IDs, so they probably have no object. That is inferred from code (`hints_indexer.py:316`), not observed: all 8 cited hints were found.

The prod engine cites only prod data stores. `_dev` data stores are cited only by the dev engine.

## 4. Retrieved vs cited

| Check | Result |
|---|---|
| Cited document ID found in the same user's `Search` results, −10 min..+1 min | 100% for every data store (909 of 909 non-empty references) |
| Fields on a `Search` result | `id` only (no `uri`, no data store, no score) |
| ID prefixes shared by several data stores | `pages_*`, `posts_*` (traffic wiki and InHouse), `sites_google_*` (helpdesk QA and HR House) |

Consequences:
- **Cited documents:** the data store and the URI come with the reference, so the content path is computable at once (§1).
- **Retrieved but not cited:** only the ID is known. The data store is ambiguous for some prefixes, and the URI is unknown. `cited_in_retrieved` in `design.md` §8.4 is fully deterministic, because the IDs are identical. The opposite direction (what was retrieved but not used) needs a catalog.

## 5. Proposal: document catalog

The indexers already compute everything at write time. Add one small BigQuery table, written by the sink in the same run:

```text
indexers.doc_catalog(
  data_store_id STRING, doc_id STRING, uri_sha256 STRING, host STRING,
  mime_type STRING, has_content BOOL, indexed_at TIMESTAMP, is_people_directory BOOL)
```

- No titles, no content, no raw URIs (only the hash and the host). That keeps it non-fragile.
- It enables:
  - mapping every `Search` result to a data store and its content object;
  - `retrieved_store_mix` without guessing from prefixes;
  - `doc_stats_weekly.retrieval_hits` per document;
  - the eval-builder picking documents by traffic;
  - "never-retrieved" documents for steering (`notes.md`).
- Size: ~7.7k objects in the prod bucket folders, plus Drive and BQ docs entries without content.
- Alternative without indexer changes: resolve IDs with the Discovery Engine `documents.get` API per data store at assessment time. That is slower, and for shared prefixes it needs several calls. Prefer the catalog.

## 6. Impact on the design (not applied)

| Area | Change |
|---|---|
| §7.1 stage 2, §8.6 | Content fetch = `<data_store_id>/<sha256(uri)>.enc`, decrypted with the existing Fernet scheme. Reuse `aiel-interfaces/mcp_server/document_content.py`. The assessor service account needs read access to the bucket and the two secrets. That is broader than "KMS key" in §10.2, so the wording should be corrected. |
| §8.4 | `cited_in_retrieved`: exact match on document ID (no mapping needed). |
| §8.5, §8.7 people-directory exclusion | Rule: data store `rtb-associates` or `people-connections_*`, or `associate-` ID prefix, or `mailto:` URI. Apply before the LLM call and before any write. |
| §9 `cited_doc_uris` | Store `data_store_id` + `doc_id` (or `uri_sha256`) instead of raw URIs. URIs can contain names (Drive titles in query strings, `mailto:`). |
| Q2 | Answered. |
| New dependency | `doc_catalog` from the indexers (owner: indexers). |

## 7. Open points

- Content for Drive documents: the stage-2 pass can't fetch them (6% of citations). Accept the gap, or fetch via the Drive API with a scoped service account (a SECOPS question).
- Bucket freshness: the cleanup deletes objects of removed documents. A cited document deleted between the answer and stage 2 (minutes) is rare but possible; the assessor should then record `content_missing`.
- Who owns `doc_catalog` and when it is added to the sink.
