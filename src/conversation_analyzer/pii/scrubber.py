"""PII scrubbing of conversations, and the conversation's placeholders applied to documents (§6.3, §12.13).

The mapping from values to placeholders exists only in memory during a run.
"""

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
_NAME_SEQ = re.compile(rf"{_WORD.pattern}(?:\s+{_WORD.pattern}){{0,2}}")


def stem(word: str) -> str:
    w = word.lower()
    for suffix in _SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[: -len(suffix)]
    return w


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
        self._exact: dict[str, str] = {}
        self._digits: dict[str, str] = {}

    def placeholder(self, entity_type: str, surface: str, lemma: str | None = None) -> str:
        if entity_type == "PERSON":
            key = name_key(lemma or surface)
            if key not in self._persons and len(key) == 1:
                # A surname alone gets the placeholder of the full name it belongs to.
                for full, ph in self._persons.items():
                    if len(full) > 1 and full[-1] == key[0]:
                        self._persons[key] = ph
                        break
            if key not in self._persons:
                self._persons[key] = self._new("PERSON")
                if len(key) > 1:  # a document that names only the surname gets the same placeholder
                    self._persons.setdefault(key[-1:], self._persons[key])
            return self._persons[key]
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
            pattern = r"\+?" + r"[\s-]?".join(re.escape(d) for d in digits)
            text = re.sub(pattern, ph, text)
            if digits.startswith("48") and len(digits) == 11:
                text = re.sub(r"[\s-]?".join(re.escape(d) for d in digits[2:]), ph, text)
        if self._persons:
            text = _NAME_SEQ.sub(lambda m: self._replace_names(m.group(0)), text)
        return text

    def _replace_names(self, seq: str) -> str:
        words = _WORD.findall(seq)
        stems = [stem(w) for w in words]
        # Longest known name inside this sequence of capitalized words wins.
        for size in range(len(words), 0, -1):
            for i in range(len(words) - size + 1):
                ph = self._persons.get(tuple(stems[i : i + size]))
                if ph:
                    before = " ".join(words[:i])
                    after = self._replace_names(" ".join(words[i + size :])) if i + size < len(words) else ""
                    return " ".join(x for x in (before, ph, after) if x)
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
    return "".join(out)


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
