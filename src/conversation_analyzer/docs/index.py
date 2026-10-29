"""Search over the document index: VECTOR_SEARCH in BigQuery, grouped by document, top 10 (§12.7)."""

from __future__ import annotations

import threading
from typing import Any

from conversation_analyzer.bq.client import fq, query
from conversation_analyzer.bq.schema import chunk_table_name
from conversation_analyzer.docs.content import ContentReader
from conversation_analyzer.docs.embedder import Embedder, default_embedder
from conversation_analyzer.judge.case import DocRef, DocText
from conversation_analyzer.leak_guard import allowed_link, is_people_directory
from conversation_analyzer.pii.scrubber import PiiMap
from conversation_analyzer.settings import get_settings


def indexed_tables() -> list[str]:
    """One table per data store with text; the people directory never has one."""
    return [chunk_table_name(d.id) for d in get_settings().data_stores if d.has_content]


def _chunks_union() -> str:
    cols = "doc_id, uri, data_store, chunk_no, embedding"
    return " UNION ALL ".join(f"SELECT {cols} FROM {fq('doc_index', t)}" for t in indexed_tables())


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


def search_sql(vectors: list[list[float]], top_chunks: int) -> str:
    """One search for many queries at once (§12.6 phase 2): VECTOR_SEARCH in BigQuery, plain cosine on the emulator."""
    queries = " UNION ALL ".join(f"SELECT {i} AS qid, {_vector_literal(v)} AS embedding" for i, v in enumerate(vectors))
    if get_settings().env.emulator:
        return f"""
WITH q AS ({queries}), c AS ({_chunks_union()})
SELECT q.qid, c.doc_id, c.uri, c.data_store, COSINE_DISTANCE(c.embedding, q.embedding) AS distance
FROM q CROSS JOIN c
QUALIFY ROW_NUMBER() OVER (PARTITION BY q.qid ORDER BY distance) <= {top_chunks}"""
    return f"""
SELECT query.qid AS qid, base.doc_id AS doc_id, base.uri AS uri, base.data_store AS data_store, distance
FROM VECTOR_SEARCH(({_chunks_union()}), 'embedding', ({queries}), 'embedding',
                   top_k => {top_chunks}, distance_type => 'COSINE')"""


class DocumentIndex:
    """Our index and our bucket. Searches are cached, so phase 2 can run one search for all turns (§12.6)."""

    def __init__(self, embedder: Embedder | None = None, reader: ContentReader | None = None) -> None:
        self.embedder = embedder or default_embedder()
        self.reader = reader or ContentReader()
        self._cache: dict[str, list[DocRef]] = {}
        self._lock = threading.Lock()
        self.searches = 0

    def view(self, pii: PiiMap | None) -> SessionDocuments:
        return SessionDocuments(self, pii)

    def prefetch(self, texts: list[str]) -> None:
        todo = [t for t in dict.fromkeys(texts) if t not in self._cache]
        for text, refs in zip(todo, self.search_many(todo), strict=True):
            with self._lock:
                self._cache[text] = refs

    def search_many(self, texts: list[str]) -> list[list[DocRef]]:
        if not texts or not indexed_tables():
            return [[] for _ in texts]
        self.searches += 1
        k = get_settings().sizes.search_top_k
        rows = query(search_sql(self.embedder.embed(texts), top_chunks=k * 5))
        by_query: dict[int, list[dict[str, Any]]] = {}
        for r in sorted(rows, key=lambda r: (r["qid"], r["distance"])):
            by_query.setdefault(r["qid"], []).append(r)
        out = []
        for i in range(len(texts)):
            docs: list[DocRef] = []
            for r in by_query.get(i, []):
                ref = DocRef(r["doc_id"], r["data_store"], r["uri"])
                if ref not in docs and not is_people_directory(ref.data_store, ref.doc_id, ref.uri):
                    docs.append(ref)
            out.append(docs[:k])
        return out

    def search(self, text: str) -> list[DocRef]:
        if text not in self._cache:
            self.prefetch([text])
        return self._cache[text]

    def lookup_uri(self, uri: str) -> DocRef | None:
        """A link in the answer text, mapped to its document when the link belongs to an allowlisted data store."""
        if not allowed_link(uri, None) or not indexed_tables():
            return None
        union = " UNION ALL ".join(
            f"SELECT doc_id, uri, data_store FROM {fq('doc_index', t)} WHERE uri = @uri" for t in indexed_tables()
        )
        rows = query(f"SELECT DISTINCT doc_id, uri, data_store FROM ({union}) LIMIT 1", uri=uri)
        return DocRef(rows[0]["doc_id"], rows[0]["data_store"], rows[0]["uri"]) if rows else None

    def data_stores_of(self, doc_ids: list[str]) -> dict[str, str]:
        """The data store of each retrieved document, for retrieval counts (§12.6)."""
        if not doc_ids or not indexed_tables():
            return {}
        union = " UNION ALL ".join(
            f"SELECT doc_id, data_store FROM {fq('doc_index', t)} WHERE doc_id IN UNNEST(@ids)"
            for t in indexed_tables()
        )
        return {
            r["doc_id"]: r["data_store"]
            for r in query(f"SELECT DISTINCT doc_id, data_store FROM ({union})", ids=doc_ids)
        }


class SessionDocuments:
    """The DocumentSource of one session: documents get that session's placeholders when read (§6.3)."""

    def __init__(self, index: DocumentIndex, pii: PiiMap | None) -> None:
        self.index = index
        self.pii = pii

    def search(self, text: str) -> list[DocRef]:
        return self.index.search(text)

    def lookup_uri(self, uri: str) -> DocRef | None:
        return self.index.lookup_uri(uri)

    def read(self, ref: DocRef) -> DocText | None:
        doc = self.index.reader.read(ref)
        if doc is None or self.pii is None:
            return doc
        return DocText(ref=doc.ref, title=self.pii.apply(doc.title), text=self.pii.apply(doc.text))
