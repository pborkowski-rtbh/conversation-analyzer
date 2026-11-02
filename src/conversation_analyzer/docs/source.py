"""Our documents for one run: links resolved to documents and read from the content bucket; no search (§6.9, §12.7)."""

from __future__ import annotations

import hashlib

from conversation_analyzer.docs.content import ContentReader
from conversation_analyzer.judge.case import DocRef, DocText
from conversation_analyzer.leak_guard import is_people_directory, link_data_store
from conversation_analyzer.log.parse import Reference
from conversation_analyzer.pii.scrubber import PiiMap


def link_doc_id(uri: str) -> str:
    """The ID of a linked document that no reference in the window names: a hash of its link."""
    return "url-" + hashlib.sha256(uri.encode()).hexdigest()[:32]


class RunDocuments:
    """The documents a run can reach: those its turns cite, and those their answers link to."""

    def __init__(self, reader: ContentReader | None = None) -> None:
        self.reader = reader or ContentReader()
        self._by_uri: dict[str, DocRef] = {}
        self._store_of: dict[str, str] = {}

    def register(self, references: list[Reference]) -> None:
        """References seen in the window name the documents behind links and the data store of retrieved IDs."""
        for r in references:
            if is_people_directory(r.data_store, r.doc_id, r.uri):
                continue
            self._store_of.setdefault(r.doc_id, r.data_store)
            if r.uri:
                self._by_uri.setdefault(r.uri, DocRef(r.doc_id, r.data_store, r.uri))

    def lookup_uri(self, uri: str) -> DocRef | None:
        """A link in the answer text as a document: the window's ID for it, else a hash of the link."""
        if uri in self._by_uri:
            return self._by_uri[uri]
        data_store = link_data_store(uri)
        if data_store is None or is_people_directory(data_store, None, uri):
            return None
        return DocRef(link_doc_id(uri), data_store, uri)

    def data_stores_of(self, doc_ids: list[str]) -> dict[str, str]:
        """The data store of each document ID that a reference in the window names (§12.6 retrieval counts)."""
        return {d: self._store_of[d] for d in doc_ids if d in self._store_of}

    def view(self, pii: PiiMap | None) -> SessionDocuments:
        return SessionDocuments(self, pii)


class SessionDocuments:
    """The DocumentSource of one session: documents get that session's placeholders when read (§6.3)."""

    def __init__(self, docs: RunDocuments, pii: PiiMap | None) -> None:
        self.docs = docs
        self.pii = pii

    def lookup_uri(self, uri: str) -> DocRef | None:
        return self.docs.lookup_uri(uri)

    def read(self, ref: DocRef) -> DocText | None:
        doc = self.docs.reader.read(ref)
        if doc is None or self.pii is None:
            return doc
        return DocText(ref=doc.ref, title=self.pii.apply(doc.title), text=self.pii.apply(doc.text))
