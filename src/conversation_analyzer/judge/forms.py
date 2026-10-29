"""What the judge fills in. No free text in any stored form; only the stage 2 search phrasings are text, in memory."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from conversation_analyzer.vocab import (
    DocRole,
    FailureCode,
    FindingVerdict,
    Intent,
    Outcome,
    Recovered,
    Relation,
    Severity,
    topics,
)

IntentL = Literal[tuple(i.value for i in Intent)]
TopicL = Literal[tuple(topics())]
RelationL = Literal[tuple(r.value for r in Relation)]
SeverityL = Literal[tuple(s.value for s in Severity)]
JudgedCodeL = Literal[
    tuple(
        c.value
        for c in (
            FailureCode.CONTRADICTED_CLAIM,
            FailureCode.UNSUPPORTED_CLAIM,
            FailureCode.INCOMPLETE_ANSWER,
            FailureCode.MISUNDERSTOOD_QUERY,
            FailureCode.PRESENTATION_ISSUE,
            FailureCode.AMBIGUOUS_QUESTION,
            FailureCode.OUT_OF_SCOPE,
        )
    )
]
WhatL = Literal[
    tuple(c.value for c in (FailureCode.CONTRADICTED_CLAIM, FailureCode.UNSUPPORTED_CLAIM, FailureCode.REASONING_ERROR))
]
StageOneCodeL = Literal[tuple(c.value for c in FailureCode if c is not FailureCode.NONE)]
RoleL = Literal[tuple(r.value for r in DocRole)]
Score = Field(ge=1, le=5)


class Stage1Form(BaseModel):
    """The stage 1 form (§6.4); fields that do not apply to the intent are left null (§6.6)."""

    intent: IntentL
    topic: TopicL
    relation: RelationL
    relevance: int = Field(ge=1, le=5)
    completeness: int | None = Field(default=None, ge=1, le=5)
    clarity: int | None = Field(default=None, ge=1, le=5)
    groundedness: int | None = Field(default=None, ge=1, le=5)
    unsupported_spans: int | None = Field(default=None, ge=0)
    language_matches: bool
    refusal_or_empty: bool
    contradicts_earlier: bool
    needs_internal_knowledge: bool | None = None
    failure_types: list[JudgedCodeL] = Field(default_factory=list)
    severity: SeverityL | None = None
    confidence: float = Field(ge=0, le=1)


class EvidenceCheckForm(BaseModel):
    """The evidence check looks only for a specific contradiction; it gives no scores (§6.9)."""

    contradiction_found: bool
    contradicting_document: int | None = Field(default=None, ge=1)
    confidence: float = Field(ge=0, le=1)


class Stage2Phrasings(BaseModel):
    """Problem claims as search phrasings; used for the search only, never stored (§7.5, §12.7)."""

    claims: list[str] = Field(default_factory=list, max_length=3)


class DocumentRole(BaseModel):
    document: int = Field(ge=1)
    role: RoleL


class ClaimForm(BaseModel):
    """One problem claim, with the answers to the cause-path questions (§7.3, §7.5)."""

    span_index: int | None = Field(default=None, ge=0)
    what: WhatL
    snippets_support_claim: bool
    snippets_hold_right_content: bool
    in_cited_full_text: bool
    in_other_found_document: bool
    documents: list[DocumentRole] = Field(default_factory=list)


class FindingForm(BaseModel):
    code: StageOneCodeL
    verdict: Literal[tuple(v.value for v in FindingVerdict)]


class Stage2Form(BaseModel):
    """The stage 2 form (§7.4)."""

    cited_documents_outdated: list[int] = Field(default_factory=list)
    cited_documents_conflicting: list[int] = Field(default_factory=list)
    claims: list[ClaimForm] = Field(default_factory=list, max_length=3)
    groundedness: int | None = Field(default=None, ge=1, le=5)
    stage1_findings: list[FindingForm] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class SessionGradeForm(BaseModel):
    """The session grade (§7.7); the rephrase and correction count is counted, not judged."""

    outcome: Literal[tuple(o.value for o in Outcome)]
    first_bad_turn: int | None = Field(default=None, ge=1)
    recovered_after_correction: Literal[tuple(r.value for r in Recovered)]
    confidence: float = Field(ge=0, le=1)
