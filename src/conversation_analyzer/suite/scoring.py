"""Distance of a judge's forms from the expected ones (§11.2); field weights come with the suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from conversation_analyzer.vocab import FormField, Severity

F = FormField
_NULLABLE = ("completeness", "clarity", "groundedness", "unsupported_spans", "needs_internal_knowledge", "severity")
_CHECKS = {
    "relation": F.RELATION,
    "needs_internal_knowledge": F.NEEDS_INTERNAL_KNOWLEDGE,
    "language_matches": F.LANGUAGE_MATCHES,
    "refusal_or_empty": F.REFUSAL_OR_EMPTY,
    "contradicts_earlier": F.CONTRADICTS_EARLIER,
}
_SCORES = {
    "relevance": F.RELEVANCE,
    "completeness": F.COMPLETENESS,
    "clarity": F.CLARITY,
    "groundedness": F.GROUNDEDNESS,
}
_DECISION_LINES = ("relevance", "groundedness")


@dataclass
class Distance:
    """Weighted distance parts per field, and the counts the keep rule needs."""

    parts: dict[str, float] = field(default_factory=dict)
    false_high: int = 0
    missed_high: int = 0

    def add(self, f: FormField, value: float, weight: float) -> None:
        if value:
            self.parts[f.value] = self.parts.get(f.value, 0.0) + value * weight

    @property
    def total(self) -> float:
        return sum(self.parts.values())


def _side(score: int) -> int:
    """-1 flags the turn (2 or lower), 1 counts as good (4 or higher), 0 between (§11.2)."""
    return -1 if score <= 2 else 1 if score >= 4 else 0


def score_distance(field_name: str, expected: int, actual: int) -> float:
    d = abs(expected - actual) / 4
    if field_name in _DECISION_LINES and _side(expected) != _side(actual):
        d += 1
    return d


def severity_distance(expected: str | None, actual: str | None) -> tuple[float, bool, bool]:
    """The severity part, and whether it is a false or a missed HIGH."""
    if actual == Severity.HIGH and expected != Severity.HIGH:
        return 5.0, True, False
    if expected == Severity.HIGH and actual != Severity.HIGH:
        return 3.0, False, True
    if {expected, actual} == {Severity.LOW, Severity.MEDIUM}:
        return 1.0, False, False
    return 0.0, False, False


def stage1_distance(expected: dict[str, Any], actual: dict[str, Any], weights: dict[str, float]) -> Distance:
    w = weights
    d = Distance()
    d.add(F.INTENT, float(expected["intent"] != actual["intent"]), w["intent"])
    for name in _NULLABLE:
        if (expected.get(name) is None) != (actual.get(name) is None):
            d.add(F.FILLED_FIELDS, 1.0, w["filled_fields"])
    for name, f in _CHECKS.items():
        e, a = expected.get(name), actual.get(name)
        if e is not None and a is not None:
            d.add(f, float(e != a), w["check"])
    for name, f in _SCORES.items():
        e, a = expected.get(name), actual.get(name)
        if e is not None and a is not None:
            d.add(f, score_distance(name, e, a), w["score"])
    total = actual.get("total_spans")
    e_spans, a_spans = expected.get("unsupported_spans"), actual.get("unsupported_spans")
    if total and e_spans is not None and a_spans is not None:
        d.add(F.SPAN_COUNTS, min(abs(e_spans - a_spans) / total, 1.0), w["span_counts"])
    e_codes, a_codes = set(expected["failure_types"]), set(actual["failure_types"])
    union = e_codes | a_codes
    d.add(F.FAILURE_TYPES, len(e_codes ^ a_codes) / len(union) if union else 0.0, w["failure_types"])
    d.add(F.PRIMARY_FAILURE, float(expected["primary_failure"] != actual["primary_failure"]), w["primary_failure"])
    if expected.get("severity") is not None or actual.get("severity") is not None:
        value, false_high, missed_high = severity_distance(expected.get("severity"), actual.get("severity"))
        d.add(F.SEVERITY, value, w["severity"])
        d.false_high += false_high
        d.missed_high += missed_high
    return d


def add_evidence(d: Distance, expected: dict[str, Any] | None, actual: bool | None, weights: dict[str, float]) -> None:
    if expected is None:
        return
    d.add(F.EVIDENCE_CHECK, float(bool(actual) != expected["contradiction_found"]), weights["check"])


def add_stage2(
    d: Distance, expected: dict[str, Any] | None, actual: dict[str, Any] | None, weights: dict[str, float]
) -> None:
    if expected is None:
        return
    if actual is None:  # stage 2 failed: every expected value is missed
        d.add(F.STAGE2_CAUSE, 1.0, weights["stage2_cause"])
        d.add(F.DOCUMENT_TO_FIX, float(expected.get("document_to_fix") is not None), weights["document_to_fix"])
        return
    d.add(F.STAGE2_CAUSE, float(expected["primary_failure"] != actual["primary_failure"]), weights["stage2_cause"])
    d.add(
        F.DOCUMENT_TO_FIX,
        float(expected.get("document_to_fix") != actual.get("document_to_fix")),
        weights["document_to_fix"],
    )


def add_session(
    d: Distance, expected: dict[str, Any] | None, actual: dict[str, Any] | None, weights: dict[str, float]
) -> None:
    if expected is None:
        return
    actual = actual or {}
    d.add(F.SESSION_OUTCOME, float(expected["outcome"] != actual.get("outcome")), weights["session_outcome"])
    e_bad, a_bad = expected.get("first_bad_turn"), actual.get("first_bad_turn")
    if e_bad is None or a_bad is None:
        bad = float((e_bad is None) != (a_bad is None))
    else:
        bad = min(abs(e_bad - a_bad), 1)
    d.add(F.FIRST_BAD_TURN, bad, weights["first_bad_turn"])
    d.add(F.RECOVERED, float(expected["recovered"] != actual.get("recovered")), weights["recovered"])
