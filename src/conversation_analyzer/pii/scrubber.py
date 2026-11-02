"""PII scrubbing of conversations, and their placeholders applied to documents; the mapping lives only in memory."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

# Polish declension endings, longest first, so inflected forms of a name share one key (§6.12).
_SUFFIXES = (
    "iego",
    "iemu",
    "owie",
    "ymi",
    "imi",
    "ami",
    "ach",
    "iem",
    "ego",
    "emu",
    "owi",
    "iej",
    "ów",
    "om",
    "em",
    "im",
    "ym",
    "ie",
    "ą",
    "ę",
    "a",
    "u",
    "y",
    "i",
    "o",
    "e",
)
_WORD = re.compile(r"[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:-[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?")
_NAME_SEQ = re.compile(rf"{_WORD.pattern}(?:\s+{_WORD.pattern})*")
_FLEETING_E = re.compile(r"(?<=[^aeiouyąęó])e([kłlc])$")


def stem(word: str) -> str:
    """Strip a Polish ending, and the fleeting e of Marek/Marka or Paweł/Pawła, so all forms share one stem."""
    w = word.lower()
    for suffix in _SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= 2:  # Ewa, Ewy, Ewie, Ewą: "ew"
            w = w[: -len(suffix)]
            break
    return _FLEETING_E.sub(r"\1", w) if len(w) >= 4 else w


def name_key(text: str) -> tuple[str, ...]:
    return tuple(stem(w) for w in _WORD.findall(text)) or (text.lower().strip(),)


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


@dataclass(frozen=True)
class Entity:
    start: int
    end: int
    entity_type: str
    score: float
    lemma: str | None = None  # base form of a name, so inflected forms share a placeholder


class Analyzer(Protocol):
    """The scrubbing engine behind one interface: Presidio today, replaceable by Cloud DLP (§12.13)."""

    def analyze(self, text: str) -> list[Entity]: ...


class PiiMap:
    """Values to placeholders for one session; the same value always gets the same placeholder."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, tuple[str, ...]], str] = {}
        self._counters: Counter[str] = Counter()
        self._persons: dict[tuple[str, ...], str] = {}
        self._aliases: dict[tuple[str, ...], str | None] = {}  # None: a first name or surname two persons share
        self._exact: dict[str, str] = {}
        self._digits: dict[str, str] = {}

    def _person(self, key: tuple[str, ...]) -> str | None:
        return self._persons.get(key) or (self._aliases.get(key) if len(key) == 1 else None)

    def placeholder(self, entity_type: str, surface: str, lemma: str | None = None) -> str:
        if entity_type == "PERSON":
            key = name_key(lemma or surface)
            ph = self._person(key)
            if ph is None:
                ph = self._persons[key] = self._new("PERSON")
                # The first name or the surname alone, later or in a document, gets the same placeholder.
                for part in {key[:1], key[-1:]} if len(key) > 1 else ():
                    self._aliases[part] = ph if self._aliases.get(part, ph) == ph else None
            return ph
        digits = _digits(surface)
        if entity_type == "PHONE_NUMBER" and len(digits) == 11 and digits.startswith("48"):
            digits = digits[2:]  # +48 601 234 567 and 601-234-567 are the same number
        if entity_type in ("PHONE_NUMBER", "PL_PESEL", "PL_NIP", "CREDIT_CARD", "IBAN_CODE") and len(digits) >= 6:
            if digits not in self._digits:
                self._digits[digits] = self._new(entity_type)
            return self._digits[digits]
        norm = surface.lower().strip()
        if norm not in self._exact:
            self._exact[norm] = self._new(entity_type)
        return self._exact[norm]

    def _new(self, entity_type: str) -> str:
        self._counters[entity_type] += 1
        return f"<{entity_type}_{self._counters[entity_type]}>"

    def __len__(self) -> int:
        return len(set(self._persons.values()) | set(self._exact.values()) | set(self._digits.values()))

    def apply(self, text: str) -> str:
        """Give a document the conversation's placeholders; the document is not scrubbed otherwise (§6.3)."""
        if not len(self) or not text:
            return text
        for value, ph in sorted(self._exact.items(), key=lambda kv: -len(kv[0])):
            text = re.sub(re.escape(value), ph, text, flags=re.IGNORECASE)
        for digits, ph in self._digits.items():
            # Phones are keyed without the Polish country code, which a document may or may not write.
            prefix = r"(?:\+?48[\s-]?)?" if ph.startswith("<PHONE_NUMBER_") else ""
            text = re.sub(r"(?<!\d)" + prefix + r"[\s-]?".join(re.escape(d) for d in digits) + r"(?!\d)", ph, text)
        if self._persons:
            text = _NAME_SEQ.sub(lambda m: self._replace_names(m.group(0)), text)
        return text

    def _replace_names(self, seq: str) -> str:
        words = list(_WORD.finditer(seq))
        stems = [stem(m.group(0)) for m in words]
        # Longest known name inside this sequence of capitalized words wins; the text around it is kept as it is.
        for size in range(len(words), 0, -1):
            for i in range(len(words) - size + 1):
                ph = self._person(tuple(stems[i : i + size]))
                if ph:
                    start, end = words[i].start(), words[i + size - 1].end()
                    return self._replace_names(seq[:start]) + ph + self._replace_names(seq[end:])
        return seq


def scrub(text: str, pii: PiiMap, analyzer: Analyzer | None = None) -> str:
    """Replace every personal detail in a conversation text with its placeholder."""
    if not text:
        return text
    entities = (analyzer or default_analyzer()).analyze(text)
    out, pos = [], 0
    for e in _non_overlapping(entities):
        out.append(text[pos : e.start])
        out.append(pii.placeholder(e.entity_type, text[e.start : e.end], e.lemma))
        pos = e.end
    out.append(text[pos:])
    # Values already known in the session are replaced also where the analyzer missed them (a surname alone).
    return pii.apply("".join(out))


def _non_overlapping(entities: list[Entity]) -> list[Entity]:
    chosen: list[Entity] = []
    for e in sorted(entities, key=lambda x: (-(x.end - x.start), -x.score, x.start)):
        if all(e.end <= c.start or e.start >= c.end for c in chosen):
            chosen.append(e)
    return sorted(chosen, key=lambda x: x.start)


@lru_cache(maxsize=1)
def default_analyzer() -> Analyzer:
    from conversation_analyzer.pii.presidio import PresidioAnalyzer

    return PresidioAnalyzer()
