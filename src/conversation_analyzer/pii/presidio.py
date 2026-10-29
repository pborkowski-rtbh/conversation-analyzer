"""Presidio with spaCy's English and Polish models, plus our own recognisers (§12.13). Runs inside the assessor."""

from __future__ import annotations

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import (
    CreditCardRecognizer,
    EmailRecognizer,
    IbanRecognizer,
    PhoneRecognizer,
    PlPeselRecognizer,
)

from conversation_analyzer.pii.scrubber import Entity
from conversation_analyzer.settings import get_settings

_PL_WORDS = frozenset(
    [
        "się",
        "nie",
        "jest",
        "czy",
        "jak",
        "dla",
        "oraz",
        "jestem",
        "mam",
        "mój",
        "moja",
        "jaki",
        "jaka",
        "gdzie",
        "kiedy",
        "ile",
        "który",
        "która",
        "proszę",
        "dzięki",
        "może",
        "można",
        "są",
        "też",
        "już",
        "tak",
        "żeby",
        "albo",
        "przez",
    ]
)
_EN_WORDS = frozenset(
    [
        "the",
        "is",
        "are",
        "what",
        "how",
        "where",
        "when",
        "which",
        "who",
        "can",
        "could",
        "please",
        "thanks",
        "my",
        "our",
        "for",
        "with",
        "does",
        "do",
        "and",
        "or",
        "not",
        "this",
        "that",
    ]
)
_HONORIFICS = frozenset(["pan", "pani", "panie", "panią", "państwo", "mr", "mrs", "ms", "dr", "prof"])

ENTITIES = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "PL_PESEL",
    "PL_NIP",
    "PL_ID_CARD",
    "EMPLOYEE_ID",
    "IBAN_CODE",
    "CREDIT_CARD",
]
LANGUAGES = ("en", "pl")


class PlNipRecognizer(PatternRecognizer):
    """Polish tax ID (NIP): 10 digits with a checksum."""

    def __init__(self, language: str) -> None:
        super().__init__(
            "PL_NIP",
            patterns=[Pattern("nip", r"\b\d{3}[- ]?\d{3}[- ]?\d{2}[- ]?\d{2}\b", 0.4)],
            context=["nip"],
            supported_language=language,
        )

    def validate_result(self, pattern_text: str) -> bool:
        d = [int(c) for c in pattern_text if c.isdigit()]
        weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
        return len(d) == 10 and sum(w * x for w, x in zip(weights, d, strict=False)) % 11 == d[9]


class PlIdCardRecognizer(PatternRecognizer):
    """Polish ID card number: three letters and six digits, with a check digit."""

    def __init__(self, language: str) -> None:
        super().__init__(
            "PL_ID_CARD",
            patterns=[Pattern("id", r"\b[A-Z]{3}\s?\d{6}\b", 0.5)],
            context=["dowód", "dowodu", "id card"],
            supported_language=language,
        )

    def validate_result(self, pattern_text: str) -> bool:
        v = pattern_text.replace(" ", "")
        values = [ord(c) - 55 for c in v[:3]] + [int(c) for c in v[3:]]
        weights = (7, 3, 1, 0, 7, 3, 1, 7, 3)
        return sum(w * x for w, x in zip(weights, values, strict=False)) % 10 == values[3]


def _recognizers(language: str) -> list:
    s = get_settings().pii
    domains = "|".join(d.split(".")[0] for d in s.company_email_domains)
    return [
        EmailRecognizer(supported_language=language),
        PatternRecognizer(
            "EMAIL_ADDRESS",
            supported_language=language,
            patterns=[Pattern("company_email", rf"\b[\w.+-]+@(?:{domains})(?:\.[a-z]{{2,}})?\b", 0.9)],
        ),
        PhoneRecognizer(supported_language=language, supported_regions=s.phone_regions),
        PatternRecognizer(
            "PHONE_NUMBER",
            supported_language=language,
            patterns=[Pattern("pl_phone", r"(?<!\d)(?:\+48[ -]?)?\d{3}[ -]\d{3}[ -]\d{3}(?!\d)", 0.6)],
        ),
        PlPeselRecognizer(supported_language=language),
        PlNipRecognizer(language),
        PlIdCardRecognizer(language),
        PatternRecognizer(
            "EMPLOYEE_ID",
            supported_language=language,
            patterns=[Pattern(f"emp{i}", p, 0.7) for i, p in enumerate(s.employee_id_patterns)],
        ),
        IbanRecognizer(supported_language=language),
        CreditCardRecognizer(supported_language=language),
    ]


class PresidioAnalyzer:
    def __init__(self) -> None:
        s = get_settings().pii
        provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": lang, "model_name": s.spacy_models[lang]} for lang in LANGUAGES],
                "ner_model_configuration": {
                    "model_to_presidio_entity_mapping": {"PERSON": "PERSON", "PER": "PERSON", "persName": "PERSON"},
                    "low_confidence_score_multiplier": 0.4,
                    "low_score_entity_names": [],
                    # Company names, places and dates are content the judge needs, not personal details.
                    "labels_to_ignore": [
                        "CARDINAL",
                        "DATE",
                        "EVENT",
                        "FAC",
                        "GPE",
                        "LANGUAGE",
                        "LAW",
                        "LOC",
                        "MONEY",
                        "NORP",
                        "ORDINAL",
                        "ORG",
                        "PERCENT",
                        "PRODUCT",
                        "QUANTITY",
                        "TIME",
                        "WORK_OF_ART",
                        "orgName",
                        "placeName",
                        "geogName",
                        "date",
                        "time",
                    ],
                },
            }
        )
        nlp_engine = provider.create_engine()
        registry = RecognizerRegistry(supported_languages=list(LANGUAGES))
        registry.load_predefined_recognizers(languages=list(LANGUAGES), nlp_engine=nlp_engine)
        for language in LANGUAGES:
            for recognizer in _recognizers(language):
                registry.add_recognizer(recognizer)
        self.engine = AnalyzerEngine(nlp_engine=nlp_engine, registry=registry, supported_languages=list(LANGUAGES))
        self.allow_list = s.allow_list
        self.threshold = s.score_threshold

    def analyze(self, text: str) -> list[Entity]:
        """Patterns from both languages; names only from the model of the text's main language."""
        main = main_language(text)
        found: list[Entity] = []
        for language in LANGUAGES:
            artifacts = self.engine.nlp_engine.process_text(text, language)
            results = self.engine.analyze(
                text,
                language=language,
                entities=ENTITIES,
                nlp_artifacts=artifacts,
                score_threshold=self.threshold,
                allow_list=self.allow_list,
            )
            for r in results:
                if r.entity_type != "PERSON":
                    found.append(Entity(r.start, r.end, r.entity_type, r.score))
                elif language == main:
                    person = _trimmed_person(artifacts.tokens, r.start, r.end, r.score)
                    if person is not None:
                        found.append(person)
        return found


def main_language(text: str) -> str:
    words = text.lower().split()
    pl = sum(w.strip(".,?!:;") in _PL_WORDS for w in words) * 2 + sum(c in "ąćęłńóśźż" for c in text.lower())
    en = sum(w.strip(".,?!:;") in _EN_WORDS for w in words) * 2
    return "pl" if pl > en else "en"


def _name_like(word: str) -> bool:
    """Names are words: identifiers such as CHUNKING_ISSUE or table_v2 are content, not people."""
    letters = word.replace("-", "").replace("'", "").replace(".", "")
    return letters.isalpha() and not (len(letters) > 3 and letters.isupper())


def _trimmed_person(doc, start: int, end: int, score: float) -> Entity | None:
    """Drop honorifics and lowercase words at the edges of a name; a name keeps at least one capitalized word."""
    span = doc.char_span(start, end, alignment_mode="expand")
    if span is None:
        return None
    tokens = [t for t in span]
    while tokens and (tokens[0].text.lower() in _HONORIFICS or not tokens[0].text[:1].isupper()):
        tokens.pop(0)
    while tokens and not tokens[-1].text[:1].isupper():
        tokens.pop()
    if not tokens or not all(_name_like(t.text) for t in tokens):
        return None
    lemma = " ".join(t.lemma_ for t in tokens)
    return Entity(tokens[0].idx, tokens[-1].idx + len(tokens[-1].text), "PERSON", score, lemma)
