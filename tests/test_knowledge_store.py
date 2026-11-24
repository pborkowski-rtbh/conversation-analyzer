"""RTB Knowledge (AIENGLAB-1004): a shared-store document counts under its source's own data store."""

from __future__ import annotations

from conversation_analyzer.docs.content import content_locations, content_path
from conversation_analyzer.settings import get_settings


def test_a_knowledge_document_is_attributed_to_its_source():
    s = get_settings()
    assert s.attribute("rtb-knowledge", "confluence__page_1") == ("rtb-crj-confluence", "page_1")


def test_other_documents_are_left_as_they_are():
    s = get_settings()
    assert s.attribute("rtb-crj-confluence", "confluence__page_1") == ("rtb-crj-confluence", "confluence__page_1")
    assert s.attribute("rtb-knowledge", "unknown-source__x") == ("rtb-knowledge", "unknown-source__x")
    assert s.attribute("rtb-knowledge", "no_prefix") == ("rtb-knowledge", "no_prefix")


def test_every_content_store_names_its_source_and_drive_does_not():
    s = get_settings()
    assert s.knowledge_data_store == "rtb-knowledge"
    for ds in s.data_stores:
        assert (ds.source is not None) == ds.has_content


def test_text_is_read_from_the_shared_store_first_then_the_own_store():
    s = get_settings()
    uri = "https://example.com/page?id=1"
    digest = "e0f7689666053925ffd23e999d8b4f13babf900438f049e22498f8d78117edc3"

    assert content_path("rtb-knowledge", uri, "confluence") == f"rtb-knowledge/sources/confluence/{digest}.enc"
    assert content_locations("rtb-crj-confluence", uri) == [
        (s.bucket_for("rtb-knowledge"), f"rtb-knowledge/sources/confluence/{digest}.enc"),
        (s.bucket_for("rtb-crj-confluence"), f"rtb-crj-confluence/{digest}.enc"),
    ]
    drive = "gdrive_collection_22062025_google_drive"
    assert content_locations(drive, uri) == [(s.bucket_for(drive), f"{drive}/{digest}.enc")]
