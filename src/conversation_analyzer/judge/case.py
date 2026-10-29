"""What the judge sees for one turn, and how it is written into a prompt. The same shape comes from the live
assessor and from the judge test suite (§11.1), so between two suite runs only the judge changes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from conversation_analyzer.log.parse import Reference, Span
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import KNOWLEDGE_INTENTS, EvidenceKind


@dataclass(frozen=True)
class DocRef:
    doc_id: str
    data_store: str
    uri: str | None

    def as_doc(self) -> dict[str, Any]:
        return {"doc_id": self.doc_id, "data_store": self.data_store, "uri": self.uri}


@dataclass(frozen=True)
class DocText:
    ref: DocRef
    title: str
    text: str


class DocumentSource(Protocol):
    """Our documents: the document index and the content bucket live, fixed results in the suite."""

    def search(self, text: str) -> list[DocRef]: ...

    def read(self, ref: DocRef) -> DocText | None: ...

    def lookup_uri(self, uri: str) -> DocRef | None: ...


@dataclass
class EarlierTurn:
    """An earlier turn of the session: its text while it exists, otherwise its stored labels and scores (§5.3)."""

    position_in_session: int
    segment_no: int
    question: str | None
    answer: str | None
    labels: dict[str, Any] | None = None


@dataclass
class JudgeCase:
    question: str
    answer: str
    references: list[Reference]
    spans: list[Span]
    answer_state: str = "SUCCEEDED"
    earlier: list[EarlierTurn] = field(default_factory=list)
    earlier_references: list[Reference] = field(default_factory=list)
    has_previous_turn: bool = False
    previous_text_available: bool = False

    @property
    def own_evidence(self) -> list[Reference]:
        return [r for r in self.references if not r.people_directory]

    @property
    def earlier_evidence(self) -> list[Reference]:
        return [r for r in self.earlier_references if not r.people_directory]

    def evidence_kind(self) -> EvidenceKind:
        if self.own_evidence:
            return EvidenceKind.OWN_REFERENCES
        if self.earlier_evidence:
            return EvidenceKind.EARLIER_REFERENCES
        return EvidenceKind.NONE

    def evidence(self) -> list[Reference]:
        return self.own_evidence or self.earlier_evidence

    def answer_empty(self) -> bool:
        return not self.answer.strip() or (self.answer_state not in ("", "SUCCEEDED"))


def topic_of(data_store: str) -> str:
    ds = get_settings().data_store(data_store)
    return ds.topic if ds else "OTHER"


def _ref_line(i: int, r: Reference) -> str:
    return f"[{i}] data store {r.data_store} (topic {topic_of(r.data_store)}), title: {r.title}\n{r.snippet}"


def _context_block(case: JudgeCase) -> str:
    """Earlier turns as text, at most the context cap; when cut, the most recent are kept (§5.3)."""
    cap = get_settings().sizes.context_chars
    blocks: list[str] = []
    used = 0
    for t in reversed(case.earlier):
        if t.question is None:
            labels = ", ".join(f"{k} {v}" for k, v in (t.labels or {}).items() if v is not None)
            block = f"### Turn {t.position_in_session} (segment {t.segment_no}, text erased): {labels}"
        else:
            block = (
                f"### Turn {t.position_in_session} (segment {t.segment_no})\nQuestion: {t.question}\nAnswer: {t.answer}"
            )
        if used + len(block) > cap:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(reversed(blocks)) or "(none)"


def render_turn(case: JudgeCase, with_context: bool = True) -> str:
    """The turn in a fixed layout; the current turn is always under '## CURRENT TURN'."""
    parts = []
    if with_context:
        parts.append("## EARLIER TURNS OF THE SESSION\n" + _context_block(case))
        if case.earlier_evidence and not case.own_evidence:
            refs = "\n\n".join(_ref_line(i + 1, r) for i, r in enumerate(case.earlier_evidence))
            parts.append("## REFERENCES OF EARLIER TURNS (evidence for this turn)\n" + refs)
    prev = (
        "no previous turn"
        if not case.has_previous_turn
        else "previous turn text available"
        if case.previous_text_available
        else "previous turn text erased"
    )
    spans = "\n".join(f'[S{s.index}] "{s.text}" -> references {list(s.reference_indices)}' for s in case.spans)
    parts.append(
        "## CURRENT TURN\n"
        f"Relation context: {prev}\n"
        f"Evidence: {case.evidence_kind().value}\n"
        f"Answer spans in the log: {len(case.spans)}\n"
        f"### QUESTION\n{case.question}\n### ANSWER\n{case.answer}\n"
        + (f"### ANSWER SPANS\n{spans}\n" if case.spans else "")
    )
    refs = "\n\n".join(_ref_line(i + 1, r) for i, r in enumerate(case.own_evidence))
    parts.append("## REFERENCES OF THE CURRENT TURN\n" + (refs or "(none)"))
    return "\n\n".join(parts)


def render_documents(docs: list[DocText], heading: str = "DOCUMENTS") -> str:
    cap = get_settings().sizes.document_chars
    out = [f"## {heading}"]
    for i, d in enumerate(docs, start=1):
        out.append(f"[{i}] data store {d.ref.data_store}, title: {d.title}\n{d.text[:cap]}")
    return "\n\n".join(out) if docs else f"## {heading}\n(none)"


def is_knowledge(intent: str) -> bool:
    return intent in KNOWLEDGE_INTENTS
