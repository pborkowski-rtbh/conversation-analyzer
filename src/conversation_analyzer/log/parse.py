"""Turn the log's records into in-memory turns, feedback and searches. Nothing here is ever stored as is."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from conversation_analyzer import keys
from conversation_analyzer.leak_guard import is_people_directory
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import Channel, FeedbackReason, Thumbs

_DOC_NAME = re.compile(r"/dataStores/(?P<ds>[^/]+)/branches/[^/]+/documents/(?P<doc>[^/]+)$")


@dataclass(frozen=True)
class Reference:
    doc_id: str
    data_store: str
    uri: str | None
    title: str
    snippet: str

    @property
    def people_directory(self) -> bool:
        return is_people_directory(self.data_store, self.doc_id, self.uri)

    def as_doc(self) -> dict[str, Any]:
        return {"doc_id": self.doc_id, "data_store": self.data_store, "uri": self.uri}


@dataclass(frozen=True)
class Span:
    """An answer span: a part of the answer the log links to the references it cites."""

    index: int
    start: int
    end: int
    text: str
    reference_indices: tuple[int, ...]


@dataclass
class Turn:
    """One answer call on the production engine, as read inside the window. Text lives only in memory."""

    turn_key: str
    session_key: str
    timestamp: datetime
    channel: Channel
    question: str
    answer: str
    references: list[Reference]
    spans: list[Span]
    answer_state: str
    is_canary: bool
    principal: str | None = field(repr=False, default=None)
    assist_token: str | None = field(repr=False, default=None)

    @property
    def evidence_references(self) -> list[Reference]:
        """References that may serve as evidence: never the people directory (§6.2)."""
        return [r for r in self.references if not r.people_directory]

    def size(self) -> int:
        """Question, answer and references together, for the too-large rule (§6.3)."""
        return len(self.question) + len(self.answer) + sum(len(r.snippet) + len(r.title) for r in self.references)


@dataclass(frozen=True)
class Feedback:
    assist_token: str | None
    session_key: str | None
    question_index: int | None
    thumbs: Thumbs | None
    reasons: tuple[FeedbackReason, ...]
    timestamp: datetime


@dataclass(frozen=True)
class Search:
    timestamp: datetime
    principal: str | None
    doc_ids: tuple[str, ...]


def _json(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return json.loads(value)


def channel_of(request: dict[str, Any]) -> Channel:
    if request.get("agentsSpec") is not None:
        return Channel.WEB_UI
    if (request.get("query") or {}).get("text") is not None:
        return Channel.SLACK_MCP
    return Channel.WEB_UI


def question_of(row: dict[str, Any], request: dict[str, Any]) -> str:
    if row.get("userQuery"):
        return row["userQuery"]
    query = request.get("query") or {}
    if query.get("text"):
        return query["text"]
    return "\n".join(p.get("text", "") for p in query.get("parts") or [] if isinstance(p, dict))


def is_canary(question: str, principal: str | None) -> bool:
    ev = get_settings().evaluator
    return question.lstrip().startswith(ev.prompt_prefix) or (principal is not None and principal in ev.accounts)


def parse_turn(row: dict[str, Any]) -> Turn | None:
    """A StreamAssist record still inside the window, or None when its answer is already erased."""
    response = _json(row.get("response"))
    request = _json(row.get("request"))
    answer = response.get("answer") or {}
    name = answer.get("name")
    parsed = keys.parse_answer_name(name) if name else None
    if parsed is None:
        return None
    engine, session_id = parsed
    grounding: dict[str, Any] = {}
    for reply in answer.get("replies") or []:
        meta = ((reply or {}).get("groundedContent") or {}).get("textGroundingMetadata")
        if meta:
            grounding = meta
            break
    references = []
    for ref in grounding.get("references") or []:
        meta = ref.get("documentMetadata") or {}
        m = _DOC_NAME.search(meta.get("document") or "")
        if not m:
            continue
        references.append(
            Reference(
                doc_id=m["doc"],
                data_store=m["ds"],
                uri=meta.get("uri"),
                title=meta.get("title") or "",
                snippet=ref.get("content") or "",
            )
        )
    spans = []
    for i, seg in enumerate(grounding.get("segments") or []):
        spans.append(
            Span(
                index=i,
                start=int(seg.get("startIndex") or 0),
                end=int(seg.get("endIndex") or 0),
                text=seg.get("text") or "",
                reference_indices=tuple(int(x) for x in seg.get("referenceIndices") or []),
            )
        )
    question = question_of(row, request)
    principal = row.get("userIamPrincipal")
    return Turn(
        turn_key=keys.turn_key(name),
        session_key=keys.session_key(engine, session_id),
        timestamp=row["timestamp"],
        channel=channel_of(request),
        question=question,
        answer=row.get("serviceTextReply") or "",
        references=references,
        spans=spans,
        answer_state=answer.get("state") or "",
        is_canary=is_canary(question, principal),
        principal=principal,
        assist_token=row.get("assistToken") or response.get("assistToken"),
    )


def parse_feedback(row: dict[str, Any]) -> Feedback:
    request = _json(row.get("request"))
    fb = (request.get("userEvent") or {}).get("feedback") or {}
    info = fb.get("conversationInfo") or {}
    session = keys.session_from_name(info.get("session") or "")
    thumbs = {"LIKE": Thumbs.UP, "DISLIKE": Thumbs.DOWN}.get(fb.get("feedbackType") or "")
    known = {r.value for r in FeedbackReason}
    reasons = tuple(
        FeedbackReason(r) if r in known else FeedbackReason.UNRECOGNIZED
        for r in fb.get("reasons") or []
        if isinstance(r, str)
    )
    q_index = info.get("questionIndex")
    return Feedback(
        assist_token=info.get("assistToken"),
        session_key=keys.session_key(*session) if session else None,
        question_index=int(q_index) if q_index is not None else None,
        thumbs=thumbs,
        reasons=reasons,
        timestamp=row["timestamp"],
    )


def parse_search(row: dict[str, Any]) -> Search:
    response = _json(row.get("response"))
    ids = tuple(r["id"] for r in response.get("results") or [] if isinstance(r, dict) and r.get("id"))
    return Search(timestamp=row["timestamp"], principal=row.get("userIamPrincipal"), doc_ids=ids)


_URL = re.compile(r"https://[^\s)\]>\"'`]+")


def linked_urls(answer: str) -> list[str]:
    """Links in the answer text, in order, without trailing punctuation (§6.9 step 1)."""
    seen: list[str] = []
    for m in _URL.finditer(answer):
        url = m.group(0).rstrip(".,;:!?")
        if url not in seen:
            seen.append(url)
    return seen
