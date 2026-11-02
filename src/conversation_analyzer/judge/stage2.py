"""Stage 2: why a flagged turn failed, with the full documents in front of the judge (§7.2-§7.6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from conversation_analyzer.judge.case import DocRef, DocText, DocumentSource, JudgeCase, render_documents, render_turn
from conversation_analyzer.judge.client import Judge, Usage, generate_validated
from conversation_analyzer.judge.evidence import linked_documents
from conversation_analyzer.judge.forms import ClaimForm, Stage2Form
from conversation_analyzer.judge.stage1 import Stage1Result, order_codes, severity_for
from conversation_analyzer.judge.version import JudgeVersion
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import (
    DETERMINISTIC_CODES,
    ClaimWhy,
    DocRole,
    FailureCode,
    FindingVerdict,
)

F = FailureCode
_WHAT_ORDER = {F.CONTRADICTED_CLAIM: 0, F.UNSUPPORTED_CLAIM: 1, F.REASONING_ERROR: 2}
# The document a fix starts from (§7.4): the cited or linked one that holds the content for CHUNKING_ISSUE.
_FIX_ROLES = {
    ClaimWhy.CHUNKING_ISSUE: (DocRole.CITED, DocRole.HOLDS_RIGHT_ANSWER),
    ClaimWhy.OUTDATED_SOURCE: (DocRole.OUTDATED,),
    ClaimWhy.CONFLICTING_SOURCES: (DocRole.CONFLICTING,),
}


@dataclass
class Claim:
    span_index: int | None
    what: str
    why: str
    documents: list[tuple[DocRef, str]]

    def row(self, position: int) -> dict[str, Any]:
        return {
            "position": position,
            "span_index": self.span_index,
            "what": self.what,
            "why": self.why,
            "documents": [{**d.as_doc(), "role": role} for d, role in self.documents],
        }


@dataclass
class Stage2Result:
    claims: list[Claim]
    groundedness: int | None
    failure_types: list[str]
    primary_failure: str
    severity: str | None
    stage1_findings: list[dict[str, str]]
    document_to_fix: DocRef | None
    confidence: float
    model: str
    found_docs: list[DocRef] = field(default_factory=list)

    def row(self) -> dict[str, Any]:
        return {
            "claims": [c.row(i + 1) for i, c in enumerate(self.claims)],
            "groundedness": self.groundedness,
            "failure_types": self.failure_types,
            "primary_failure": self.primary_failure,
            "severity": self.severity,
            "stage1_findings": self.stage1_findings,
            "document_to_fix": self.document_to_fix.as_doc() if self.document_to_fix else None,
            "confidence": self.confidence,
        }

    def changed_stage1(self, s1: Stage1Result) -> bool:
        return self.primary_failure != s1.primary_failure or any(
            f["verdict"] == FindingVerdict.DROPPED for f in self.stage1_findings
        )


def _stage1_summary(s1: Stage1Result, flag_reasons: list[str]) -> str:
    return (
        "## STAGE 1 RESULT\n"
        f"intent {s1.intent}, relevance {s1.relevance}, groundedness {s1.groundedness}, "
        f"failure types {', '.join(s1.failure_types)}, severity {s1.severity}\n"
        f"Flagged because: {', '.join(flag_reasons)}"
    )


def _cause(
    claim: ClaimForm, has_snippets: bool, has_documents: bool, outdated: bool, conflicting: bool
) -> ClaimWhy | None:
    """The cause path of §7.3; None means the claim is supported and the finding is dropped."""
    if has_snippets:
        if claim.snippets_support_claim:
            if outdated:
                return ClaimWhy.OUTDATED_SOURCE
            if conflicting:
                return ClaimWhy.CONFLICTING_SOURCES
            return None
        if claim.snippets_hold_right_content:
            return ClaimWhy.NONE
    if has_documents and claim.in_full_text:
        return ClaimWhy.CHUNKING_ISSUE
    return ClaimWhy.NOT_IN_CITED_SOURCES


def _documents(case: JudgeCase, s1: Stage1Result, docs: DocumentSource) -> tuple[list[DocText], list[DocText]]:
    """The full text of the cited documents, then of the documents linked in the answer; there is no search."""
    cited: list[DocText] = []
    seen: set[DocRef] = set()
    for r in case.own_evidence:
        ref = DocRef(r.doc_id, r.data_store, r.uri)
        if ref in seen:
            continue
        seen.add(ref)
        full = docs.read(ref)
        cited.append(full if full is not None else DocText(ref, r.title, r.snippet))
    linked_refs = [r for r in [*s1.found_docs, *linked_documents(case, docs)] if r not in seen]
    linked: list[DocText] = []
    for ref in dict.fromkeys(linked_refs):
        if len(linked) == get_settings().sizes.stage2_linked_documents:
            break
        text = docs.read(ref)
        if text is not None:
            linked.append(text)
    return cited, linked


def diagnose(
    case: JudgeCase,
    s1: Stage1Result,
    flag_reasons: list[str],
    version: JudgeVersion,
    judge: Judge,
    usage: Usage,
    docs: DocumentSource,
) -> Stage2Result:
    model = version.stage2_model
    base = render_turn(case) + "\n\n" + _stage1_summary(s1, flag_reasons)
    cited, linked = _documents(case, s1, docs)
    prompt = "\n\n".join(
        [base, render_documents(cited, "CITED DOCUMENTS (full text)"), _render_linked(linked, len(cited))]
    )
    form = generate_validated(judge, model, version.system("stage2", "stage2"), prompt, Stage2Form, usage)
    return apply_rules(form, case, s1, cited + linked, len(cited), model, [d.ref for d in linked])


def _render_linked(linked: list[DocText], offset: int) -> str:
    """Linked documents are numbered after the cited ones."""
    cap = get_settings().sizes.document_chars
    out = ["## DOCUMENTS LINKED IN THE ANSWER (full text)"]
    for i, d in enumerate(linked, start=offset + 1):
        out.append(f"[{i}] data store {d.ref.data_store}, title: {d.title}\n{d.text[:cap]}")
    return "\n\n".join(out) if linked else out[0] + "\n(none)"


def apply_rules(
    form: Stage2Form,
    case: JudgeCase,
    s1: Stage1Result,
    numbered: list[DocText],
    n_cited: int,
    model: str,
    found: list[DocRef],
) -> Stage2Result:
    has_cited = n_cited > 0
    outdated_set = {i for i in form.cited_documents_outdated if 1 <= i <= n_cited}
    conflicting_set = {i for i in form.cited_documents_conflicting if 1 <= i <= n_cited}
    claims: list[Claim] = []
    for c in form.claims[: get_settings().sizes.stage2_max_claims]:
        doc_idx = {d.document for d in c.documents}
        roles = {d.role for d in c.documents}
        outdated = bool(outdated_set & doc_idx) or DocRole.OUTDATED in roles
        conflicting = bool(conflicting_set & doc_idx) or DocRole.CONFLICTING in roles
        why = _cause(c, has_cited, bool(numbered), outdated, conflicting)
        if why is None:
            continue
        what = c.what
        if why is ClaimWhy.NONE and what == F.UNSUPPORTED_CLAIM:
            what = F.REASONING_ERROR.value  # the snippets hold the right facts: the answer misread them
        documents = [(numbered[d.document - 1].ref, d.role) for d in c.documents if 1 <= d.document <= len(numbered)]
        claims.append(Claim(c.span_index, what, why.value, documents))
    claims.sort(key=lambda c: _WHAT_ORDER[F(c.what)])

    verdicts = {f.code: f.verdict for f in form.stage1_findings}
    findings = []
    kept: set[FailureCode] = set()
    for code in s1.failure_types:
        if code == F.NONE:
            continue
        verdict = verdicts.get(code, FindingVerdict.CONFIRMED.value)
        if F(code) in DETERMINISTIC_CODES:
            verdict = FindingVerdict.CONFIRMED.value  # they follow from the data
        findings.append({"code": code, "verdict": verdict})
        if verdict == FindingVerdict.CONFIRMED:
            kept.add(F(code))
    codes = kept | {F(c.what) for c in claims} | {F(c.why) for c in claims if c.why != ClaimWhy.NONE}
    failure_types, primary = order_codes(codes)
    if claims:
        first = claims[0]
        primary = first.why if first.why != ClaimWhy.NONE else first.what
        failure_types = [primary] + [c for c in failure_types if c != primary]

    groundedness = form.groundedness if s1.knowledge_turn and s1.verifiable else None
    if F.CONTRADICTED_CLAIM in codes and groundedness is not None:
        groundedness = min(groundedness, 2)
    # A dropped HIGH gets its severity set again by the stage 1 rules (§7.5).
    severity = severity_for(codes, s1.intent, s1.severity if s1.severity != "HIGH" else None)

    doc_to_fix = None
    if claims and claims[0].why in _FIX_ROLES:
        why = ClaimWhy(claims[0].why)
        doc_to_fix = next((d for d, role in claims[0].documents if role in _FIX_ROLES[why]), None)
        if doc_to_fix is None and why is ClaimWhy.CHUNKING_ISSUE and numbered:
            doc_to_fix = numbered[0].ref

    return Stage2Result(
        claims=claims,
        groundedness=groundedness,
        failure_types=failure_types,
        primary_failure=primary,
        severity=severity,
        stage1_findings=findings,
        document_to_fix=doc_to_fix,
        confidence=float(form.confidence),
        model=model,
        found_docs=found,
    )
