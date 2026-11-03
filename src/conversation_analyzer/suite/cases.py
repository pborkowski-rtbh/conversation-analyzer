"""Judge test suite cases: a fixed input, its cited and linked documents from the corpus, the expected forms (§11.1)."""

from __future__ import annotations

import hashlib
import json
from functools import cached_property
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from conversation_analyzer.judge.case import DocRef, DocText, EarlierTurn, JudgeCase
from conversation_analyzer.log.parse import Reference, Span
from conversation_analyzer.settings import REPO_ROOT
from conversation_analyzer.vocab import (
    ClaimWhy,
    EvidenceKind,
    FailureCode,
    Intent,
    Outcome,
    Recovered,
    Relation,
    Severity,
    SuitePart,
)

CASES_DIR = REPO_ROOT / "suite_cases"
EDGE_TAGS = ("refusal", "wrong_language", "people_lookup", "private_details", "long_context")


class SuiteDocument(BaseModel):
    """A document of the suite's small corpus: what a case cites or links and what the bucket holds."""

    doc_id: str
    data_store: str
    uri: str | None
    title: str
    text: str

    @property
    def ref(self) -> DocRef:
        return DocRef(self.doc_id, self.data_store, self.uri)


class CaseReference(BaseModel):
    doc: str  # key in documents.yaml
    snippet: str


class CaseSpan(BaseModel):
    text: str
    refs: list[int] = Field(default_factory=list)  # 0-based indices into the turn's references, as in the log


class Stage1Labels(BaseModel):
    """What the session grade sees of an earlier turn: its stage 1 result (fixed input, not judged again)."""

    relation: Literal[tuple(r.value for r in Relation)] = "FIRST"
    relevance: int = Field(default=4, ge=1, le=5)
    primary_failure: Literal[tuple(c.value for c in FailureCode)] = "NONE"
    severity: Literal[tuple(s.value for s in Severity)] | None = None


class CaseTurn(BaseModel):
    question: str
    answer: str
    state: str = "SUCCEEDED"
    references: list[CaseReference] = Field(default_factory=list)
    spans: list[CaseSpan] = Field(default_factory=list)
    stage1: Stage1Labels | None = None  # earlier turns only


class ExpectedStage1(BaseModel):
    """The stage 1 form after the rules (§6.6-§6.8): what a perfect judge ends up with."""

    intent: Literal[tuple(i.value for i in Intent)]
    relation: Literal[tuple(r.value for r in Relation)]
    relevance: int = Field(ge=1, le=5)
    completeness: int | None = Field(default=None, ge=1, le=5)
    clarity: int | None = Field(default=None, ge=1, le=5)
    groundedness: int | None = Field(default=None, ge=1, le=5)
    unsupported_spans: int | None = Field(default=None, ge=0)
    language_matches: bool = True
    refusal_or_empty: bool = False
    contradicts_earlier: bool = False
    needs_internal_knowledge: bool | None = None
    failure_types: list[Literal[tuple(c.value for c in FailureCode)]] = Field(default_factory=lambda: ["NONE"])
    primary_failure: Literal[tuple(c.value for c in FailureCode)] = "NONE"
    severity: Literal[tuple(s.value for s in Severity)] | None = None

    @model_validator(mode="after")
    def _primary_is_listed(self) -> ExpectedStage1:
        if self.primary_failure not in self.failure_types:
            raise ValueError("primary_failure must be one of failure_types")
        return self


class ExpectedEvidence(BaseModel):
    contradiction_found: bool


class ExpectedStage2(BaseModel):
    primary_failure: Literal[tuple(c.value for c in FailureCode)]
    cause: Literal[tuple(w.value for w in ClaimWhy)] | None = None  # the first claim's why; None: no claim left
    document_to_fix: str | list[str] | None = None  # key(s) in documents.yaml; a list accepts any of them

    def fix_options(self) -> list[str | None]:
        d = self.document_to_fix
        return list(d) if isinstance(d, list) else [d]


class ExpectedSession(BaseModel):
    outcome: Literal[tuple(o.value for o in Outcome)]
    first_bad_turn: int | None = None
    recovered: Literal[tuple(r.value for r in Recovered)]


class Expected(BaseModel):
    stage1: ExpectedStage1
    evidence_check: ExpectedEvidence | None = None
    stage2: ExpectedStage2 | None = None
    session: ExpectedSession | None = None


class SuiteCase(BaseModel):
    id: str
    part: Literal["TUNING", "HELD_OUT"] = SuitePart.TUNING.value
    reviewed: bool = False
    language: Literal["en", "pl"] = "en"
    tags: list[Literal[EDGE_TAGS]] = Field(default_factory=list)
    earlier: list[CaseTurn] = Field(default_factory=list)  # earlier turns of the segment, oldest first
    previous_text_available: bool = True
    turn: CaseTurn
    flag_reasons: list[str] | None = None  # a late trigger (e.g. DISLIKE) when stage 1 alone would not flag it
    expected: Expected

    def references(self, corpus: dict[str, SuiteDocument], turn: CaseTurn) -> list[Reference]:
        out = []
        for r in turn.references:
            d = corpus[r.doc]
            out.append(Reference(d.doc_id, d.data_store, d.uri, d.title, r.snippet))
        return out

    def judge_case(self, corpus: dict[str, SuiteDocument]) -> JudgeCase:
        spans = []
        for i, s in enumerate(self.turn.spans):
            start = max(self.turn.answer.find(s.text), 0)
            spans.append(Span(i, start, start + len(s.text), s.text, tuple(s.refs)))
        if self.previous_text_available:
            earlier = [EarlierTurn(i + 1, 1, t.question, t.answer) for i, t in enumerate(self.earlier)]
            earlier_refs = [r for t in self.earlier for r in self.references(corpus, t)]
        else:  # an earlier segment whose text is erased: the judge sees only its labels (§5.3)
            labels = [(t.stage1 or Stage1Labels()).model_dump() for t in self.earlier]
            earlier = [EarlierTurn(i + 1, 1, None, None, labels[i]) for i in range(len(self.earlier))]
            earlier_refs = []
        return JudgeCase(
            question=self.turn.question,
            answer=self.turn.answer,
            references=self.references(corpus, self.turn),
            spans=spans,
            answer_state=self.turn.state,
            earlier=earlier,
            earlier_references=earlier_refs,
            has_previous_turn=bool(self.earlier),
            previous_text_available=bool(self.earlier) and self.previous_text_available,
        )

    def evidence_kind(self, corpus: dict[str, SuiteDocument]) -> EvidenceKind:
        return self.judge_case(corpus).evidence_kind()

    def scenarios(self, corpus: dict[str, SuiteDocument]) -> list[str]:
        """The scenario values this case tests, for the minimums of §11.1."""
        s1 = self.expected.stage1
        out = [f"intent:{s1.intent}", f"evidence:{self.evidence_kind(corpus).value}", f"relation:{s1.relation}"]
        out += [f"failure:{c}" for c in s1.failure_types]
        if s1.severity:
            out.append(f"severity:{s1.severity}")
        if s1.severity == Severity.MEDIUM and s1.primary_failure == FailureCode.UNSUPPORTED_CLAIM:
            out.append("severity:NEAR_MISS")
        if self.expected.stage2:
            out.append(f"failure:{self.expected.stage2.primary_failure}")
            cause = self.expected.stage2.cause
            out.append(f"cause:{'ANSWER' if cause in (None, ClaimWhy.NONE) else cause}")
        if self.expected.session and 3 <= len(self.earlier) + 1 <= 5:
            out.append(f"outcome:{self.expected.session.outcome}")
        out += [f"edge:{t}" for t in self.tags]
        return out


class Suite(BaseModel):
    """The cases, their documents, the field weights and the scenario minimums, versioned together."""

    weights: dict[str, float]
    minimums: dict[str, int]
    documents: dict[str, SuiteDocument]
    cases: list[SuiteCase]
    raw: str = Field(repr=False)

    @cached_property
    def version(self) -> str:
        return "suite-" + hashlib.sha256(self.raw.encode()).hexdigest()[:12]

    def doc_texts(self) -> dict[DocRef, DocText]:
        return {d.ref: DocText(d.ref, d.title, d.text) for d in self.documents.values()}

    def coverage(self) -> dict[str, tuple[int, int]]:
        """Scenario value to (cases that test it, minimum)."""
        counts: dict[str, int] = {}
        for c in self.cases:
            for s in set(c.scenarios(self.documents)):
                counts[s] = counts.get(s, 0) + 1
        return {k: (counts.get(k, 0), v) for k, v in sorted(self.minimums.items())}

    def short(self) -> dict[str, tuple[int, int]]:
        return {k: v for k, v in self.coverage().items() if v[0] < v[1]}


def load_suite(directory: Path = CASES_DIR) -> Suite:
    meta = yaml.safe_load((directory / "suite.yaml").read_text())
    docs_raw = yaml.safe_load((directory / "documents.yaml").read_text())
    documents = {k: SuiteDocument(**v) for k, v in docs_raw.items()}
    cases: list[SuiteCase] = []
    texts = [(directory / "suite.yaml").read_text(), (directory / "documents.yaml").read_text()]
    for path in sorted((directory / "cases").glob("*.yaml")):
        text = path.read_text()
        texts.append(text)
        cases.extend(SuiteCase(**c) for c in yaml.safe_load(text) or [])
    ids = [c.id for c in cases]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate case ids: {sorted(duplicates)}")
    for c in cases:
        for t in [*c.earlier, c.turn]:
            for r in t.references:
                if r.doc not in documents:
                    raise ValueError(f"{c.id}: unknown document {r.doc}")
        for d in c.expected.stage2.fix_options() if c.expected.stage2 else []:
            if d is not None and d not in documents:
                raise ValueError(f"{c.id}: unknown document {d}")
    return Suite(
        weights=meta["weights"],
        minimums=meta["minimums"],
        documents=documents,
        cases=cases,
        raw=json.dumps(texts),
    )
