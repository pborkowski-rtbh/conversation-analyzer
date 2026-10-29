"""Our documents: the encrypted content bucket and the document index, on fake GCS and the emulator (§12.7)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from conversation_analyzer.devtools import scenario
from conversation_analyzer.devtools.synthetic import index_documents
from conversation_analyzer.docs import content, index
from conversation_analyzer.docs.content import ContentReader, content_path, derive_key, fernet, storage_client
from conversation_analyzer.docs.embedder import FakeEmbedder
from conversation_analyzer.docs.index import DocumentIndex, search_sql
from conversation_analyzer.judge.case import DocRef
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


def test_search_sql_uses_vector_search_in_bigquery(monkeypatch):
    monkeypatch.setattr(get_settings().env, "bq_endpoint", None)
    sql = search_sql([[0.1, 0.2]], top_chunks=50)
    assert "VECTOR_SEARCH(" in sql and "top_k => 50" in sql and "distance_type => 'COSINE'" in sql
    assert "quality_chunks_rtb_crj_confluence" in sql and "associates" not in sql
    assert "WHERE embedding_model = @model" in sql


@pytest.fixture(scope="module")
def indexed(emulator):
    index_documents(scenario.DOCUMENTS, NOW)
    return DocumentIndex(embedder=FakeEmbedder())


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


def test_search_finds_the_document_and_caches(indexed):
    found = indexed.search("How many days of on-demand leave per year?")
    assert found[0] == LEAVE and len(found) == len(set(found)) <= get_settings().sizes.search_top_k
    searches = indexed.searches
    assert indexed.search("How many days of on-demand leave per year?") == found
    indexed.prefetch(["How many days of on-demand leave per year?", "business trip approval", "business trip approval"])
    assert indexed.searches == searches + 1  # one search for the one new text
    assert indexed.search("business trip approval")[0].doc_id == scenario.TRIP.doc_id
    assert indexed.search_many([]) == []


def test_search_skips_chunks_of_another_embedding_model(indexed):
    class RealModel(FakeEmbedder):
        model = "text-multilingual-embedding-002"

    assert DocumentIndex(embedder=RealModel()).search("How many days of on-demand leave per year?") == []


def test_lookup_uri_and_data_stores(indexed):
    trip = DocRef(scenario.TRIP.doc_id, scenario.TRIP.data_store, scenario.TRIP.uri)
    assert indexed.lookup_uri(scenario.TRIP.uri) == trip
    assert indexed.lookup_uri("https://evil.example/x") is None
    assert indexed.lookup_uri("https://rtbhouseproduct.atlassian.net/wiki/spaces/HR/pages/999") is None
    assert indexed.data_stores_of([scenario.API.doc_id, "unknown"]) == {scenario.API.doc_id: scenario.API.data_store}
    assert indexed.data_stores_of([]) == {}


def test_session_view_gives_documents_the_sessions_placeholders(indexed):
    pii = PiiMap()
    pii.placeholder("PERSON", "Travel Tool")  # pretend a name, to see it replaced in the document
    view = indexed.view(pii)
    doc = view.read(DocRef(scenario.TRIP.doc_id, scenario.TRIP.data_store, scenario.TRIP.uri))
    assert "<PERSON_1>" in doc.text and "Travel Tool" not in doc.text
    assert view.search("business trip approval") == indexed.search("business trip approval")
    assert view.lookup_uri(scenario.TRIP.uri) is not None
    assert indexed.view(None).read(LEAVE).text == scenario.LEAVE.text
    assert view.read(DocRef("x", "rtb-crj-confluence", None)) is None


def test_no_index_tables_means_no_query(monkeypatch):
    monkeypatch.setattr(index, "indexed_tables", lambda: [])
    idx = DocumentIndex(embedder=FakeEmbedder())
    assert idx.search_many(["a"]) == [[]] and idx.lookup_uri(scenario.TRIP.uri) is None
    assert idx.data_stores_of(["a"]) == {}
