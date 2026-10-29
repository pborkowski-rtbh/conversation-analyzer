"""Stage 1: the form every eligible turn gets, with the rules that follow from the data (§6.4-§6.8)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from conversation_analyzer.judge.case import DocRef, JudgeCase, render_turn, topic_of
from conversation_analyzer.judge.client import Judge, Usage, generate_validated
from conversation_analyzer.judge.forms import Stage1Form
from conversation_analyzer.judge.version import JudgeVersion
from conversation_analyzer.vocab import (
    DETERMINISTIC_CODES,
    KNOWLEDGE_INTENTS,
    STAGE1_PRIMARY_ORDER,
    EvidenceKind,
    FailureCode,
    FlagReason,
    Intent,
    Relation,
    Severity,
    TopicSource,
)

F = FailureCode
_NON_SOURCE_GENERATION = {F.INCOMPLETE_ANSWER, F.MISUNDERSTOOD_QUERY, F.PRESENTATION_ISSUE}
_QUESTION = {F.AMBIGUOUS_QUESTION, F.OUT_OF_SCOPE}
_JUDGED = {F.CONTRADICTED_CLAIM, F.UNSUPPORTED_CLAIM} | _NON_SOURCE_GENERATION | _QUESTION
# Codes the judge may give per intent (§6.6); deterministic codes are added by rule, not by the judge.
ALLOWED_JUDGED = {
    Intent.PEOPLE_LOOKUP: set(),
    Intent.GENERAL_TASK: _NON_SOURCE_GENERATION | _QUESTION,
    Intent.CHITCHAT: _NON_SOURCE_GENERATION | _QUESTION,
    Intent.OTHER: set(_QUESTION),
}
_DEFAULT_SEVERITY = {
    F.UNSUPPORTED_CLAIM: Severity.MEDIUM,
    F.UNGROUNDED_INTERNAL_ANSWER: Severity.MEDIUM,
    F.MISUNDERSTOOD_QUERY: Severity.MEDIUM,
    F.AGENT_OR_TOOL_ERROR: Severity.MEDIUM,
    F.INCOMPLETE_ANSWER: Severity.MEDIUM,
    F.AMBIGUOUS_QUESTION: Severity.MEDIUM,
    F.OUT_OF_SCOPE: Severity.LOW,
    F.PRESENTATION_ISSUE: Severity.LOW,
}
_ORDER = {c: i for i, c in enumerate(STAGE1_PRIMARY_ORDER)}


@dataclass
class Stage1Result:
    intent: str
    topic: str
    topic_source: str
    relation: str
    relevance: int
    completeness: int | None
    clarity: int | None
    groundedness: int | None
    unsupported_spans: int | None
    total_spans: int | None
    language_matches: bool
    refusal_or_empty: bool
    contradicts_earlier: bool
    needs_internal_knowledge: bool | None
    failure_types: list[str]
    primary_failure: str
    severity: str | None
    confidence: float
    knowledge_turn: bool
    verifiable: bool
    evidence_kind: str
    model: str
    evidence_check_ran: bool = False
    evidence_check_contradiction: bool = False
    found_docs: list[DocRef] = field(default_factory=list)

    def flag_reasons(self) -> list[str]:
        reasons = []
        if self.relevance <= 2:
            reasons.append(FlagReason.LOW_RELEVANCE.value)
        if self.groundedness is not None and self.groundedness <= 2:
            reasons.append(FlagReason.LOW_GROUNDEDNESS.value)
        if self.severity == Severity.HIGH:
            reasons.append(FlagReason.HIGH_SEVERITY.value)
        return reasons

    def add_code(self, code: FailureCode) -> None:
        codes = {FailureCode(c) for c in self.failure_types if c != F.NONE} | {code}
        self.failure_types, self.primary_failure = order_codes(codes)
        self.severity = severity_for(codes, self.intent, None)
        if code is F.CONTRADICTED_CLAIM and self.groundedness is not None:
            self.groundedness = min(self.groundedness, 2)

    def row(self) -> dict[str, Any]:
        keys = (
            "intent",
            "topic",
            "topic_source",
            "relation",
            "relevance",
            "completeness",
            "clarity",
            "groundedness",
            "unsupported_spans",
            "total_spans",
            "language_matches",
            "refusal_or_empty",
            "contradicts_earlier",
            "needs_internal_knowledge",
            "failure_types",
            "primary_failure",
            "severity",
            "confidence",
            "knowledge_turn",
            "verifiable",
            "evidence_kind",
            "evidence_check_ran",
            "evidence_check_contradiction",
        )
        return {k: getattr(self, k) for k in keys}

    def labels(self) -> dict[str, Any]:
        """What a later turn sees of this turn once its text is erased (§5.3)."""
        return {
            "intent": self.intent,
            "topic": self.topic,
            "relevance": self.relevance,
            "groundedness": self.groundedness,
            "primary_failure": self.primary_failure,
            "severity": self.severity,
        }


def order_codes(codes: set[FailureCode]) -> tuple[list[str], str]:
    """Codes in the fixed order; the first is the primary failure (§6.8)."""
    ordered = sorted(codes, key=lambda c: _ORDER.get(c, len(_ORDER)))
    if not ordered:
        return [F.NONE.value], F.NONE.value
    return [c.value for c in ordered], ordered[0].value


def severity_for(codes: set[FailureCode], intent: str, judged: str | None) -> str | None:
    """HIGH only for a contradicted claim on a knowledge intent; nothing else is HIGH (§6.8)."""
    if not codes:
        return None
    if F.CONTRADICTED_CLAIM in codes and intent in KNOWLEDGE_INTENTS:
        return Severity.HIGH.value
    candidates = [_DEFAULT_SEVERITY.get(c, Severity.MEDIUM) for c in codes if c is not F.CONTRADICTED_CLAIM]
    floor = Severity.MEDIUM if codes & DETERMINISTIC_CODES else Severity.LOW
    if judged in (Severity.LOW, Severity.MEDIUM):
        chosen = Severity(judged)
    else:
        chosen = Severity.MEDIUM if (judged == Severity.HIGH or Severity.MEDIUM in candidates) else Severity.LOW
    return Severity.MEDIUM.value if floor is Severity.MEDIUM or chosen is Severity.MEDIUM else Severity.LOW.value


def topic_for(case: JudgeCase, judged: str) -> tuple[str, str]:
    """From the references' data stores; the judge picks among them, or freely when there are none (§6.4)."""
    topics = [topic_of(r.data_store) for r in case.own_evidence]
    if not topics:
        return judged, TopicSource.JUDGE.value
    counts = Counter(topics)
    if judged in counts:
        return judged, TopicSource.REFERENCES.value
    return counts.most_common(1)[0][0], TopicSource.REFERENCES.value


def apply_rules(form: Stage1Form, case: JudgeCase, model: str) -> Stage1Result:
    intent = form.intent
    knowledge = intent in KNOWLEDGE_INTENTS
    evidence = case.evidence_kind()
    verifiable = not knowledge or evidence is not EvidenceKind.NONE
    topic, topic_source = topic_for(case, form.topic)

    relation = form.relation
    if not case.has_previous_turn or not case.previous_text_available:
        relation = Relation.FIRST.value
    elif relation == Relation.FIRST:
        relation = Relation.NEW_TOPIC.value

    people = intent == Intent.PEOPLE_LOOKUP
    completeness = None if people else form.completeness
    clarity = None if people else form.clarity
    groundedness = form.groundedness if knowledge and verifiable else None
    with_spans = knowledge and evidence is EvidenceKind.OWN_REFERENCES and bool(case.spans)
    total_spans = len(case.spans) if with_spans else None
    unsupported = min(max(form.unsupported_spans or 0, 0), total_spans) if with_spans else None
    needs_internal = form.needs_internal_knowledge if knowledge else None

    if knowledge:
        allowed = _JUDGED if verifiable else set()
    else:
        allowed = ALLOWED_JUDGED.get(Intent(intent), set())
    codes = {F(c) for c in form.failure_types} & allowed
    if case.answer_empty():
        codes.add(F.AGENT_OR_TOOL_ERROR)
    if knowledge and needs_internal and evidence is EvidenceKind.NONE:
        codes.add(F.UNGROUNDED_INTERNAL_ANSWER)
    if F.CONTRADICTED_CLAIM in codes and groundedness is not None:
        groundedness = min(groundedness, 2)
    failure_types, primary = order_codes(codes)

    return Stage1Result(
        intent=intent,
        topic=topic,
        topic_source=topic_source,
        relation=relation,
        relevance=form.relevance,
        completeness=completeness,
        clarity=clarity,
        groundedness=groundedness,
        unsupported_spans=unsupported,
        total_spans=total_spans,
        language_matches=form.language_matches,
        refusal_or_empty=form.refusal_or_empty,
        contradicts_earlier=form.contradicts_earlier,
        needs_internal_knowledge=needs_internal,
        failure_types=failure_types,
        primary_failure=primary,
        severity=severity_for(codes, intent, form.severity),
        confidence=float(form.confidence),
        knowledge_turn=knowledge,
        verifiable=verifiable,
        evidence_kind=evidence.value,
        model=model,
    )


def assess(
    case: JudgeCase, version: JudgeVersion, judge: Judge, usage: Usage, model: str | None = None
) -> Stage1Result:
    """Fill in the form for one turn. `model` overrides the stage 1 model for the second-model check (§11.5)."""
    model = model or version.stage1_model
    form = generate_validated(judge, model, version.system("stage1", "stage1"), render_turn(case), Stage1Form, usage)
    return apply_rules(form, case, model)
