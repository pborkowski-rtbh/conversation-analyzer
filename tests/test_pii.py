"""PII scrubbing: placeholders, inflected Polish names, the conversation's placeholders in documents (§6.3, §6.12)."""

from __future__ import annotations

import pytest

from conversation_analyzer.pii import presidio
from conversation_analyzer.pii.scrubber import Entity, PiiMap, default_analyzer, name_key, scrub, stem


def test_stem_and_name_key_join_inflected_forms():
    assert stem("Kowalskiego") == stem("Kowalski") == stem("Kowalskim") == "kowalsk"
    assert stem("Ola") == "ola"  # too short to cut
    assert name_key("Janem Kowalskim") == name_key("Jan Kowalski")
    assert name_key("x-1") == ("x-1",)


def test_placeholders_are_consistent_per_value():
    pii = PiiMap()
    full = pii.placeholder("PERSON", "Jana Kowalskiego", "Jan Kowalski")
    assert full == "<PERSON_1>"
    assert pii.placeholder("PERSON", "Kowalskim") == full  # the surname alone
    assert pii.placeholder("PERSON", "Anna Nowak") == "<PERSON_2>"
    assert pii.placeholder("PHONE_NUMBER", "+48 601 234 567") == pii.placeholder("PHONE_NUMBER", "601-234-567")
    assert pii.placeholder("EMAIL_ADDRESS", "A@x.com") == pii.placeholder("EMAIL_ADDRESS", " a@x.com ")
    assert pii.placeholder("PL_PESEL", "44051401359") == "<PL_PESEL_1>"
    assert pii.placeholder("PHONE_NUMBER", "123") == "<PHONE_NUMBER_2>"  # too few digits: kept as typed
    assert len(pii) == 6


def test_apply_gives_documents_the_same_placeholders():
    pii = PiiMap()
    assert pii.apply("nothing to do") == "nothing to do"
    person = pii.placeholder("PERSON", "Jan Kowalski")
    email = pii.placeholder("EMAIL_ADDRESS", "jan.kowalski@rtbhouse.com")
    phone = pii.placeholder("PHONE_NUMBER", "+48 601 234 567")
    doc = (
        "Contact Jan Kowalski (JAN.KOWALSKI@rtbhouse.com, 601 234 567 or +48601234567). "
        "Ask Pan Kowalski or Dział Kadr Jana Kowalskiego Nowaka."
    )
    out = pii.apply(doc)
    assert f"Contact {person} ({email}, {phone} or {phone})" in out
    assert f"Ask Pan {person}" in out and f"Kadr {person} Nowaka" in out
    assert "Kowalsk" not in out and pii.apply("") == ""


class FixedAnalyzer:
    def __init__(self, entities):
        self.entities = entities

    def analyze(self, text):
        return self.entities


def test_scrub_uses_the_longest_of_overlapping_entities():
    text = "Call Jan Kowalski now"
    entities = [Entity(5, 8, "PERSON", 0.9), Entity(5, 17, "PERSON", 0.8, "Jan Kowalski")]
    assert scrub(text, PiiMap(), FixedAnalyzer(entities)) == "Call <PERSON_1> now"
    assert scrub("", PiiMap(), FixedAnalyzer([])) == ""


def test_polish_recognizer_checksums():
    nip = presidio.PlNipRecognizer("pl")
    assert nip.validate_result("526-025-02-74") and not nip.validate_result("526-025-02-75")
    card = presidio.PlIdCardRecognizer("pl")
    assert card.validate_result("ABA 300000") and not card.validate_result("ABA300001")


def test_main_language_and_name_shapes():
    assert presidio.main_language("Jak mogę zgłosić urlop?") == "pl"
    assert presidio.main_language("How do I request leave?") == "en"
    assert presidio._name_like("Kowalski") and presidio._name_like("O'Neil")
    assert not presidio._name_like("CHUNKING_ISSUE") and not presidio._name_like("HTTP")


@pytest.fixture(scope="module")
def analyzer():
    return default_analyzer()


@pytest.mark.parametrize(
    ("text", "planted"),
    [
        (
            "Cześć, tu Jan Kowalski, mój numer to +48 601 234 567, a mail jan.kowalski@rtbhouse.com.",
            ["Jan Kowalski", "601 234 567", "jan.kowalski@rtbhouse.com"],
        ),
        (
            "Rozmawiałem z Janem Kowalskim o PESEL 44051401359 i NIP 526-025-02-74.",
            ["Janem Kowalskim", "44051401359", "526-025-02-74"],
        ),
        (
            "Hi, I'm Sarah Connor, my card is 4111 1111 1111 1111 and IBAN PL61109010140000071219812874.",
            ["Sarah Connor", "4111 1111 1111 1111", "PL61109010140000071219812874"],
        ),
        ("Mój dowód ABA 300000, numer pracownika RTB-123456.", ["ABA 300000", "RTB-123456"]),
    ],
)
def test_real_analyzer_scrubs_planted_details(analyzer, text, planted):
    out = scrub(text, PiiMap(), analyzer)
    for value in planted:
        assert value not in out


def test_real_analyzer_keeps_content(analyzer):
    text = "Ask Bolek about CHUNKING_ISSUE in BigQuery for RTB House."
    assert scrub(text, PiiMap(), analyzer) == text
    pii = PiiMap()
    out = scrub("Pan Marek Nowak pisał do Marka Nowaka.", pii, analyzer)
    assert out.count("<PERSON_1>") == 2 and "Pan <PERSON_1>" in out
