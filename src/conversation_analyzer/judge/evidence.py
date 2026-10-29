"""The evidence check: for knowledge turns without evidence, our own documents may show a contradiction (§6.9)."""

from __future__ import annotations

from conversation_analyzer.judge.case import DocRef, DocText, DocumentSource, JudgeCase, render_documents, render_turn
from conversation_analyzer.judge.client import Judge, Usage, generate_validated
from conversation_analyzer.judge.forms import EvidenceCheckForm
from conversation_analyzer.judge.stage1 import Stage1Result
from conversation_analyzer.judge.version import JudgeVersion
from conversation_analyzer.leak_guard import is_people_directory
from conversation_analyzer.log.parse import linked_urls
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import EvidenceKind, FailureCode


def needed(result: Stage1Result) -> bool:
    return result.knowledge_turn and result.evidence_kind == EvidenceKind.NONE


def candidates(case: JudgeCase, docs: DocumentSource) -> list[DocRef]:
    """Documents linked in the answer text first, then the index's top results for the scrubbed question."""
    found: list[DocRef] = []
    for url in linked_urls(case.answer):
        ref = docs.lookup_uri(url)
        if ref and ref not in found:
            found.append(ref)
    for ref in docs.search(case.question)[: get_settings().sizes.search_top_k]:
        if ref not in found:
            found.append(ref)
    return [r for r in found if not is_people_directory(r.data_store, r.doc_id, r.uri)]


def read_up_to(refs: list[DocRef], docs: DocumentSource, n: int) -> list[DocText]:
    read: list[DocText] = []
    for ref in refs:
        if len(read) == n:
            break
        text = docs.read(ref)
        if text is not None:
            read.append(text)
    return read


def check(
    case: JudgeCase, result: Stage1Result, version: JudgeVersion, judge: Judge, usage: Usage, docs: DocumentSource
) -> None:
    """Record CONTRADICTED_CLAIM and HIGH when a document contradicts the answer; the turn stays not verifiable."""
    result.evidence_check_ran = True
    read = read_up_to(candidates(case, docs), docs, get_settings().sizes.evidence_check_documents)
    result.found_docs = [d.ref for d in read]
    if not read:
        return
    prompt = render_turn(case, with_context=False) + "\n\n" + render_documents(read)
    form = generate_validated(
        judge, version.stage1_model, version.system("evidence_check", "stage1"), prompt, EvidenceCheckForm, usage
    )
    if form.contradiction_found:
        result.evidence_check_contradiction = True
        result.add_code(FailureCode.CONTRADICTED_CLAIM)
