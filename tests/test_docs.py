"""Our documents: the encrypted content bucket on fake GCS, and links resolved to documents without a search (§12.7)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from conversation_analyzer.devtools import scenario
from conversation_analyzer.devtools.synthetic import store_documents
from conversation_analyzer.docs import content
from conversation_analyzer.docs.content import ContentReader, content_path, derive_key, fernet, storage_client
from conversation_analyzer.docs.source import RunDocuments, link_doc_id
from conversation_analyzer.judge.case import DocRef
from conversation_analyzer.log.parse import Reference
from conversation_analyzer.pii.scrubber import PiiMap
from conversation_analyzer.settings import get_settings

pytestmark = pytest.mark.emulator

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
LEAVE = DocRef(scenario.LEAVE.doc_id, scenario.LEAVE.data_store, scenario.LEAVE.uri)


def test_key_derivation_matches_the_indexers_sink():
    # Same derivation as aiel-content-indexers' vertex_ai_sink: PBKDF2-HMAC-SHA256, 1.2M iterations, 32 bytes.
    key = derive_key("secret", "salt")
    assert key == derive_key("secret", "salt") and key != derive_key("secret", "pepper") and len(key) == 44
    assert content.KDF_ITERATIONS == 1_200_000
    assert content_path("rtb-crj-confluence", "https://x/1").startswith("rtb-crj-confluence/")
    assert content_path("rtb-crj-confluence", "https://x/1").endswith(".enc")


@pytest.fixture(scope="module")
def indexed(emulator):
    store_documents(scenario.DOCUMENTS)
    docs = RunDocuments()
    docs.register([Reference(scenario.TRIP.doc_id, scenario.TRIP.data_store, scenario.TRIP.uri, "Trips", "snippet")])
    return docs


def test_content_reader_decrypts_and_caps(indexed, monkeypatch):
    monkeypatch.setattr(get_settings().sizes, "document_chars", 20)
    reader = ContentReader()
    doc = reader.read(LEAVE)
    assert doc.title == scenario.LEAVE.title and doc.text == scenario.LEAVE.text[:20]


def test_content_reader_returns_none_without_content(indexed):
    reader = ContentReader()
    assert reader.read(DocRef("x", "gdrive_collection_22062025_google_drive", "https://drive/x")) is None
    assert reader.read(DocRef("associate-1", "rtb-crj-associates", "https://x")) is None
    assert reader.read(DocRef("x", "unknown-store", "https://x")) is None
    assert reader.read(DocRef("x", "rtb-crj-confluence", None)) is None
    assert reader.missing == 0
    assert reader.read(DocRef("x", "rtb-crj-confluence", "https://not/stored")) is None
    assert reader.missing == 1


def test_content_reader_counts_undecryptable_as_missing(indexed):
    s = get_settings()
    uri = "https://rtbhouseproduct.atlassian.net/wiki/broken"
    bucket = storage_client().bucket(s.bucket_for("rtb-crj-confluence"))
    bucket.blob(content_path("rtb-crj-confluence", uri)).upload_from_string(b"not a fernet token")
    bucket.blob(content_path("rtb-crj-confluence", uri + "2")).upload_from_string(fernet().encrypt(b"not json"))
    reader = ContentReader()
    assert reader.read(DocRef("b", "rtb-crj-confluence", uri)) is None
    assert reader.read(DocRef("b", "rtb-crj-confluence", uri + "2")) is None
    assert reader.missing == 2
    assert json.loads(fernet().decrypt(fernet().encrypt(b'{"a": 1}'))) == {"a": 1}


def test_links_resolve_to_window_ids_else_a_hash_of_the_link(indexed):
    trip = DocRef(scenario.TRIP.doc_id, scenario.TRIP.data_store, scenario.TRIP.uri)
    assert indexed.lookup_uri(scenario.TRIP.uri) == trip  # a reference in the window names it
    other = "https://rtbhouseproduct.atlassian.net/wiki/spaces/HR/pages/999"
    linked = indexed.lookup_uri(other)
    assert linked == DocRef(link_doc_id(other), "rtb-crj-confluence", other) and linked.doc_id.startswith("url-")
    assert len(linked.doc_id) == 36 and indexed.lookup_uri(other) == linked  # stable across lookups
    assert indexed.lookup_uri("https://evil.example/x") is None  # not an allowlisted data store
    assert indexed.lookup_uri("mailto:anna@rtbhouse.com") is None


def test_retrieved_ids_take_their_data_store_from_window_references():
    docs = RunDocuments()
    docs.register(
        [
            Reference("a1", "rtb-crj-api-docs", None, "t", "s"),
            Reference("a1", "rtb-crj-biztech", None, "t", "s"),  # the first one seen wins
            Reference("associate-1", "rtb-crj-associates", "mailto:x@rtbhouse.com", "t", "s"),
        ]
    )
    assert docs.data_stores_of(["a1", "associate-1", "unknown"]) == {"a1": "rtb-crj-api-docs"}
    assert docs.data_stores_of([]) == {}


def test_session_view_gives_documents_the_sessions_placeholders(indexed):
    pii = PiiMap()
    pii.placeholder("PERSON", "Travel Tool")  # pretend a name, to see it replaced in the document
    view = indexed.view(pii)
    doc = view.read(DocRef(scenario.TRIP.doc_id, scenario.TRIP.data_store, scenario.TRIP.uri))
    assert "<PERSON_1>" in doc.text and "Travel Tool" not in doc.text
    assert view.lookup_uri(scenario.TRIP.uri) is not None
    assert indexed.view(None).read(LEAVE).text == scenario.LEAVE.text
    assert view.read(DocRef("x", "rtb-crj-confluence", None)) is None
