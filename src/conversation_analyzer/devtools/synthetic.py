"""Synthetic log records and documents for local runs and tests; only ever written to the emulator and fake GCS."""

from __future__ import annotations

import contextlib
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from conversation_analyzer.bq.client import client
from conversation_analyzer.bq.schema import chunk_table_name
from conversation_analyzer.docs.content import content_path, fernet, storage_client
from conversation_analyzer.docs.embedder import FakeEmbedder
from conversation_analyzer.settings import get_settings

PROJECT_PATH = "projects/181861149279/locations/eu/collections/default_collection"


def _engine(engine: str | None = None) -> str:
    return f"{PROJECT_PATH}/engines/{engine or get_settings().production_engine}"


@dataclass
class Ref:
    data_store: str
    doc_id: str
    uri: str
    title: str
    snippet: str


@dataclass
class SynthTurn:
    session_id: str
    minutes_ago: float
    question: str
    answer: str
    channel: str = "web"  # web, api or canary
    principal: str = "user:anna.test@rtbhouse.com"
    refs: list[Ref] = field(default_factory=list)
    spans: list[tuple[str, list[int]]] = field(default_factory=list)  # (text in the answer, reference indices)
    feedback: str | None = None  # LIKE or DISLIKE
    feedback_minutes_ago: float | None = None
    state: str = "SUCCEEDED"
    erased: bool = False  # past the anonymizer: answer, session ID and identity are gone
    engine: str | None = None
    answer_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    assist_token: str = field(default_factory=lambda: uuid.uuid4().hex)


def turn_rows(t: SynthTurn, now: datetime) -> list[dict[str, Any]]:
    ts = now - timedelta(minutes=t.minutes_ago)
    engine = _engine(t.engine)
    if t.channel == "web":
        request = {
            "name": f"{engine}/assistants/default_assistant",
            "query": {"parts": [{"text": t.question}]},
            "agentsSpec": {"agentSpecs": [{"agentId": "default"}]},
        }
        question = t.question
    else:
        text = t.question
        if t.channel == "canary":
            ev = get_settings().evaluator
            text = f"\n{ev.prompt_prefix} that: are grounded.{ev.question_marker}{t.question}"
        request = {"name": f"{engine}/assistants/default_assistant", "query": {"text": text}}
        question = text
    references = [
        {
            "content": r.snippet,
            "documentMetadata": {
                "document": f"{PROJECT_PATH}/dataStores/{r.data_store}/branches/0/documents/{r.doc_id}",
                "uri": r.uri,
                "title": r.title,
            },
        }
        for r in t.refs
    ]
    segments = []
    for text, idx in t.spans:
        start = t.answer.find(text)
        segments.append(
            {"text": text, "startIndex": max(start, 0), "endIndex": max(start, 0) + len(text), "referenceIndices": idx}
        )
    answer: dict[str, Any] = {"name": f"{engine}/sessions/{t.session_id}/assistAnswers/{t.answer_id}", "state": t.state}
    if references:
        answer["replies"] = [
            {"groundedContent": {"textGroundingMetadata": {"references": references, "segments": segments}}}
        ]
    row = {
        "timestamp": ts.isoformat(),
        "methodName": "StreamAssist",
        "serviceAttributionToken": uuid.uuid4().hex,
        "assistToken": t.assist_token,
        "request": request,
        "response": None if t.erased else {"assistToken": t.assist_token, "answer": answer},
        "userIamPrincipal": None if t.erased else t.principal,
        "userQuery": question,
        "serviceTextReply": None if t.erased else t.answer,
        "serviceLabel": None,
        "serviceName": "discoveryengine",
    }
    rows = [row]
    if t.feedback:
        fb_ts = now - timedelta(
            minutes=t.feedback_minutes_ago if t.feedback_minutes_ago is not None else max(t.minutes_ago - 2, 0)
        )
        rows.append(
            {
                "timestamp": fb_ts.isoformat(),
                "methodName": "WriteUserEvent",
                "serviceAttributionToken": uuid.uuid4().hex,
                "assistToken": None,
                "request": {
                    "userEvent": {
                        "eventType": "add-feedback",
                        "engine": engine,
                        "userPseudoId": uuid.uuid4().hex,
                        "feedback": {
                            "feedbackType": t.feedback,
                            "reasons": ["INACCURATE", "SOMETHING_NEW"],
                            "comment": "This comment is free text and must never be stored anywhere at all",
                            "conversationInfo": {
                                "session": f"{engine}/sessions/{t.session_id}",
                                "assistToken": t.assist_token,
                                "questionIndex": 0,
                            },
                        },
                    }
                },
                "response": None,
                "userIamPrincipal": None,
                "userQuery": None,
                "serviceTextReply": None,
                "serviceLabel": None,
                "serviceName": "discoveryengine",
            }
        )
    return rows


def search_row(principal: str, minutes_ago: float, doc_ids: list[str], now: datetime) -> dict[str, Any]:
    return {
        "timestamp": (now - timedelta(minutes=minutes_ago)).isoformat(),
        "methodName": "Search",
        "serviceAttributionToken": uuid.uuid4().hex,
        "assistToken": None,
        "request": {"query": "synthetic search", "userInfo": {"userAgent": "x"}},
        "response": {"results": [{"id": d} for d in doc_ids], "attributionToken": uuid.uuid4().hex},
        "userIamPrincipal": principal,
        "userQuery": None,
        "serviceTextReply": None,
        "serviceLabel": None,
        "serviceName": "discoveryengine",
    }


def change_row(method: str, minutes_ago: float, now: datetime, data_store: str | None = None) -> dict[str, Any]:
    name = f"{PROJECT_PATH}/dataStores/{data_store}" if data_store else _engine()
    return {
        "timestamp": (now - timedelta(minutes=minutes_ago)).isoformat(),
        "methodName": method,
        "serviceAttributionToken": uuid.uuid4().hex,
        "assistToken": None,
        "request": {"name": name},
        "response": None,
        "userIamPrincipal": None,
        "userQuery": None,
        "serviceTextReply": None,
        "serviceLabel": None,
        "serviceName": "discoveryengine",
    }


def insert_log(rows: list[dict[str, Any]]) -> None:
    s = get_settings()
    table = f"{s.env.bq_project}.{s.datasets.log}.{s.log_table}"
    for i in range(0, len(rows), 200):
        errors = client().insert_rows_json(table, rows[i : i + 200])
        if errors:
            raise RuntimeError(f"insert failed: {errors[:1]}")


@dataclass
class SynthDoc:
    data_store: str
    doc_id: str
    uri: str
    title: str
    text: str


def ensure_bucket(name: str) -> None:
    from google.api_core.exceptions import Conflict

    with contextlib.suppress(Conflict):
        storage_client().create_bucket(name)


def index_documents(docs: list[SynthDoc], now: datetime) -> None:
    """What the indexers' sink does for real (§12.7): text to the bucket, vectors to the document index."""
    s = get_settings()
    embedder = FakeEmbedder()
    rows_by_table: dict[str, list[dict[str, Any]]] = {}
    for d in docs:
        bucket = s.bucket_for(d.data_store)
        ensure_bucket(bucket)
        payload = json.dumps({"title": d.title, "url": d.uri, "content": d.text, "chunk_count": 1}).encode()
        storage_client().bucket(bucket).blob(content_path(d.data_store, d.uri)).upload_from_string(
            fernet().encrypt(payload)
        )
        chunks = [d.title + "\n" + part for part in d.text.split("\n\n") if part.strip()] or [d.title]
        vectors = embedder.embed(chunks, "RETRIEVAL_DOCUMENT")
        text_hash = hashlib.sha256(d.text.encode()).hexdigest()
        for i, vec in enumerate(vectors):
            rows_by_table.setdefault(chunk_table_name(d.data_store), []).append(
                {
                    "doc_id": d.doc_id,
                    "uri": d.uri,
                    "data_store": d.data_store,
                    "chunk_no": i,
                    "embedding": vec,
                    "text_hash": text_hash,
                    "embedding_model": embedder.model,
                    "indexed_at": now.isoformat(),
                }
            )
    for table, rows in rows_by_table.items():
        errors = client().insert_rows_json(f"{s.env.bq_project}.{s.datasets.doc_index}.{table}", rows)
        if errors:
            raise RuntimeError("index insert failed")
