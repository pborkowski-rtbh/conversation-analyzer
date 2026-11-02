"""Parsing audit-log records: turns, references, spans, channel, canary, feedback and searches (§12.2, §12.5)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from conversation_analyzer.log import parse
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import Channel, FeedbackReason, Thumbs

TS = datetime(2026, 10, 28, 12, tzinfo=UTC)
ENGINE = "projects/1/locations/eu/collections/default_collection/engines/eng"
NAME = f"{ENGINE}/sessions/s1/assistAnswers/a1"
DOC = "projects/1/locations/eu/collections/default_collection/dataStores/{ds}/branches/0/documents/{doc}"


def turn_row(**kw):
    response = {
        "assistToken": "tok-r",
        "answer": {
            "name": NAME,
            "state": "SUCCEEDED",
            "replies": [
                {"groundedContent": {}},
                {
                    "groundedContent": {
                        "textGroundingMetadata": {
                            "references": [
                                {
                                    "content": "snippet",
                                    "documentMetadata": {
                                        "document": DOC.format(ds="rtb-crj-confluence", doc="d1"),
                                        "uri": "https://x/d1",
                                        "title": "T",
                                    },
                                },
                                {"content": "no document name", "documentMetadata": {}},
                            ],
                            "segments": [
                                {"startIndex": 2, "endIndex": 9, "text": "an answer", "referenceIndices": [0]},
                                {},
                            ],
                        }
                    }
                },
            ],
        },
    }
    row = {
        "timestamp": TS,
        "request": json.dumps({"agentsSpec": {}}),
        "response": json.dumps(response),
        "userQuery": "the question",
        "serviceTextReply": "an answer",
        "userIamPrincipal": "user:a@rtbhouse.com",
    }
    row.update(kw)
    return row


def test_parse_turn_reads_references_spans_and_keys():
    t = parse.parse_turn(turn_row())
    assert t is not None and t.channel is Channel.WEB_UI and t.answer_state == "SUCCEEDED"
    assert [(r.doc_id, r.data_store, r.uri, r.title, r.snippet) for r in t.references] == [
        ("d1", "rtb-crj-confluence", "https://x/d1", "T", "snippet")
    ]
    assert t.spans[0].reference_indices == (0,) and t.spans[1].text == "" and t.spans[1].end == 0
    assert t.assist_token == "tok-r" and len(t.turn_key) == 32 and len(t.session_key) == 32
    assert t.size() == len("the question") + len("an answer") + len("snippet") + 1
    assert t.evidence_references == t.references


def test_parse_turn_without_answer_name_is_erased():
    assert parse.parse_turn(turn_row(response=None)) is None
    assert parse.parse_turn(turn_row(response={"answer": {"name": "not/a/name"}})) is None


def test_question_and_channel_from_request():
    req = {"query": {"text": "slack question"}}
    t = parse.parse_turn(turn_row(userQuery=None, request=req, serviceTextReply=None))
    assert t.channel is Channel.SLACK_MCP and t.question == "slack question" and t.answer == ""
    req = {"query": {"parts": [{"text": "part one"}, "junk", {"text": "part two"}]}}
    t = parse.parse_turn(turn_row(userQuery="", request=req))
    assert t.question == "part one\npart two" and t.channel is Channel.WEB_UI


def test_canary_by_prefix_or_account():
    ev = get_settings().evaluator
    assert parse.is_canary("  " + ev.prompt_prefix + " rest", None)
    assert not parse.is_canary("ordinary", None)
    accounts = list(ev.accounts)
    ev.accounts = ["user:evaluator@rtbhouse.com"]
    try:
        assert parse.is_canary("ordinary", "user:evaluator@rtbhouse.com")
    finally:
        ev.accounts = accounts


def test_parse_feedback():
    request = {
        "userEvent": {
            "eventType": "add-feedback",
            "feedback": {
                "feedbackType": "DISLIKE",
                "reasons": ["INACCURATE", "SOMETHING_NEW", 5],
                "comment": "free text",
                "conversationInfo": {"session": f"{ENGINE}/sessions/s1", "assistToken": "tok", "questionIndex": "2"},
            },
        }
    }
    fb = parse.parse_feedback({"timestamp": TS, "request": request})
    assert fb.thumbs is Thumbs.DOWN and fb.question_index == 2 and fb.assist_token == "tok"
    assert fb.reasons == (FeedbackReason.INACCURATE, FeedbackReason.UNRECOGNIZED)
    assert fb.session_key == parse.parse_turn(turn_row()).session_key
    empty = parse.parse_feedback({"timestamp": TS, "request": None})
    assert empty.thumbs is None and empty.session_key is None and empty.question_index is None and not empty.reasons


def test_parse_search():
    results = [{"id": "a"}, {"x": 1}, "junk", {"id": ""}]
    row = {"timestamp": TS, "userIamPrincipal": "p", "response": {"results": results}}
    assert parse.parse_search(row).doc_ids == ("a",)


def test_linked_urls():
    text = "See https://a.example/x. Then (https://b.example/y), https://a.example/x and `https://c.example/z`"
    assert parse.linked_urls(text) == ["https://a.example/x", "https://b.example/y", "https://c.example/z"]
    assert parse.linked_urls("http://insecure.example only") == []
