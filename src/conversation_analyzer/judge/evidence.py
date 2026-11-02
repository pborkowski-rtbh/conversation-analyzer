"""The evidence check: for knowledge turns without evidence, the documents the answer links may contradict it (§6.9)."""

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


def linked_documents(case: JudgeCase, docs: DocumentSource) -> list[DocRef]:
    """Documents linked in the answer text, in order, without the people directory; there is no search."""
    found: list[DocRef] = []
    for url in linked_urls(case.answer):
        ref = docs.lookup_uri(url)
        if ref and ref not in found and not is_people_directory(ref.data_store, ref.doc_id, ref.uri):
            found.append(ref)
    return found


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
) -> bool:
    """Record CONTRADICTED_CLAIM and HIGH when a linked document contradicts the answer; False when none is readable."""
    read = read_up_to(linked_documents(case, docs), docs, get_settings().sizes.evidence_check_documents)
    if not read:
        return False
    result.evidence_check_ran = True
    result.found_docs = [d.ref for d in read]
    prompt = render_turn(case, with_context=False) + "\n\n" + render_documents(read)
    form = generate_validated(
        judge, version.stage1_model, version.system("evidence_check", "stage1"), prompt, EvidenceCheckForm, usage
    )
    if form.contradiction_found:
        result.evidence_check_contradiction = True
        result.add_code(FailureCode.CONTRADICTED_CLAIM)
    return True
