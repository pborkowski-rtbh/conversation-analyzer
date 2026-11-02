"""The whole assessment path on the emulator, with the fake judge and synthetic records."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from conversation_analyzer.assessor.run import run
from conversation_analyzer.bq.schema import (
    CANARY_RESULTS,
    JUDGE_CHECKS,
    JUDGE_VERSIONS,
    QUALITY_TURNS,
    RETRIEVAL_COUNTS,
    RUNS,
    SEGMENTS,
    SESSION_GRADES,
    STAGE1_RESULTS,
    STAGE2_RESULTS,
    TABLES,
)
from conversation_analyzer.devtools import scenario
from conversation_analyzer.docs.source import RunDocuments, link_doc_id
from conversation_analyzer.judge.fake import FakeJudge
from conversation_analyzer.settings import get_settings
from tests.conftest import rows, wipe

pytestmark = pytest.mark.emulator

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def first_run(emulator):
    wipe()
    s = get_settings()
    accounts = list(s.evaluator.accounts)
    share = s.judge.second_model_share
    s.evaluator.accounts = ["user:evaluator@rtbhouse.com"]
    s.judge.second_model_share = 1.0
    s.canary.planted_share = 1.0
    scenario.seed(NOW)
    judge = FakeJudge()
    record = run(now=NOW, judge=judge, docs=RunDocuments())
    yield record, judge
    s.evaluator.accounts = accounts
    s.judge.second_model_share = share
    s.canary.planted_share = 0.25


def by_status():
    out = {}
    for r in rows(QUALITY_TURNS):
        out.setdefault(r["status"], []).append(r)
    return out


def test_run_record(first_run):
    record, _ = first_run
    assert record["status"] == "OK"
    assert record["turns_read"] == 22  # the erased turn is invisible
    assert record["too_large"] == 1 and record["missed"] == 1
    assert record["canary_assessed"] == 1
    assert record["covered"] == record["eligible"]
    assert record["oldest_waiting_minutes"] == 0.0
    assert record["stage2_done"] >= 3 and record["session_grades"] >= 3
    assert record["evidence_checks"] >= 1 and record["pace_marked"] == 12
    stored = rows(RUNS)
    assert len(stored) == 1 and stored[0]["tokens"][0]["input_tokens"] > 0


def test_statuses_and_positions(first_run):
    statuses = by_status()
    assert len(statuses["TOO_LARGE"]) == 1 and len(statuses["MISSED"]) == 1
    assert "FAILED" not in statuses
    turns = rows(QUALITY_TURNS, "NOT pace_excluded")
    resumed = [r for r in turns if r["resumed"]]
    assert len(resumed) == 1 and resumed[0]["segment_no"] == 2 and resumed[0]["position_in_session"] == 2
    assert resumed[0]["gap_bucket"] == "30_60_MIN" and resumed[0]["position_in_segment"] == 1
    assert len(rows(QUALITY_TURNS, "pace_excluded")) == 12
    channels = {r["channel"] for r in rows(QUALITY_TURNS)}
    assert channels == {"WEB_UI", "SLACK_MCP"}


def test_contradiction_flags_stage2_and_reaction(first_run):
    t = [
        r
        for r in rows(QUALITY_TURNS)
        if r["flagged"] and "HIGH_SEVERITY" in r["flag_reasons"] and r["evidence_kind"] == "OWN_REFERENCES"
    ][0]
    assert t["stage2_state"] == "DONE" and t["reaction"] == "CORRECTION"
    assert "NEXT_CORRECTION" in t["flag_reasons"]
    s1 = rows(STAGE1_RESULTS, f"turn_key = '{t['turn_key']}'")[0]
    assert s1["severity"] == "HIGH" and s1["groundedness"] == 1 and s1["primary_failure"] == "CONTRADICTED_CLAIM"
    assert s1["total_spans"] == 1 and s1["topic"] == "HR_HOUSE" and s1["topic_source"] == "REFERENCES"
    s2 = rows(STAGE2_RESULTS, f"turn_key = '{t['turn_key']}'")[0]
    assert s2["primary_failure"] == "CHUNKING_ISSUE" and s2["document_to_fix"]["data_store"] == "rtb-crj-hr-house"
    assert s2["claims"][0]["why"] == "CHUNKING_ISSUE" and "searched_phrasings" not in s2
    grade = rows(SESSION_GRADES, f"session_key = '{t['session_key']}'")[0]
    assert grade["outcome"] == "RESOLVED" and grade["recovered"] == "YES" and grade["rephrases_corrections"] == "1"


def test_evidence_check_finds_contradiction(first_run):
    t = [
        r
        for r in rows(QUALITY_TURNS)
        if r["evidence_kind"] == "NONE" and r["flagged"] and "HIGH_SEVERITY" in r["flag_reasons"]
    ][0]
    s1 = rows(STAGE1_RESULTS, f"turn_key = '{t['turn_key']}'")[0]
    assert s1["verifiable"] is False and s1["evidence_check_contradiction"] is True
    assert set(s1["failure_types"]) == {"CONTRADICTED_CLAIM", "UNGROUNDED_INTERNAL_ANSWER"}
    # The answer links the trips page and no reference in the window names it: its ID is a hash of the link.
    assert t["found_docs"] == [
        {"doc_id": link_doc_id(scenario.TRIP.uri), "data_store": "rtb-crj-confluence", "uri": scenario.TRIP.uri}
    ]
    s2 = rows(STAGE2_RESULTS, f"turn_key = '{t['turn_key']}'")[0]
    assert s2["primary_failure"] == "CHUNKING_ISSUE"  # no references: the path starts at question 2, the linked page
    assert s2["document_to_fix"]["doc_id"] == link_doc_id(scenario.TRIP.uri)


def test_dislike_and_feedback(first_run):
    t = [r for r in rows(QUALITY_TURNS) if r["channel"] == "SLACK_MCP" and not r["is_canary"]][0]
    assert t["feedback_thumbs"] == "DOWN" and "DISLIKE" in t["flag_reasons"]
    assert t["feedback_reasons"] == ["INACCURATE", "UNRECOGNIZED"]
    s1 = rows(STAGE1_RESULTS, f"turn_key = '{t['turn_key']}'")[0]
    assert s1["groundedness"] is None and s1["needs_internal_knowledge"] is None and s1["verifiable"] is True
    s2 = rows(STAGE2_RESULTS, f"turn_key = '{t['turn_key']}'")[0]
    assert s2["primary_failure"] == "NOT_IN_CITED_SOURCES"  # no references and no links: nothing to read (§7.3)


def test_segments(first_run):
    segs = rows(SEGMENTS)
    resumed = [s for s in segs if s["resumed"]]
    assert len(resumed) == 1 and resumed[0]["previous_close_reason"] == "IDLE"
    assert resumed[0]["earlier_text_missing"] is False and resumed[0]["first_turn_relation"] == "FOLLOW_UP"
    two = [s for s in segs if s["n_turns"] == 2]
    assert two and two[0]["n_corrections"] == 1


def test_canary_and_planted(first_run):
    canary = rows(CANARY_RESULTS)
    original = [c for c in canary if c["planted_error"] == "NONE"][0]
    assert "index_found_expected" not in original and "expected_doc_id" not in original
    planted = {(c["planted_error"], c["with_references"]) for c in canary if c["planted_error"] != "NONE"}
    assert ("SWAPPED_NUMBER", True) in planted and ("SWAPPED_NUMBER", False) in planted
    assert rows(QUALITY_TURNS, "is_canary")[0]["status"] == "ASSESSED"


def test_second_model_retrieval_versions(first_run):
    checks = {r["field"]: r for r in rows(JUDGE_CHECKS)}
    assert checks["INTENT"]["n_compared"] > 0
    counts = rows(RETRIEVAL_COUNTS)
    assert counts == [
        {"day": NOW.date(), "doc_id": scenario.LEAVE.doc_id, "data_store": "rtb-crj-hr-house", "n_returned": 2}
    ]
    assert len(rows(JUDGE_VERSIONS)) == 1


def test_no_text_is_stored(first_run):
    """§6.10: no piece of the input longer than 20 characters appears in any stored result."""
    dump = json.dumps([rows(t) for t in TABLES], default=str)
    inputs = [t.question for t in scenario.turns()] + [t.answer for t in scenario.turns()]
    inputs += [d.text for d in scenario.DOCUMENTS] + list(scenario.PLANTED_PII)
    inputs.append("This comment is free text and must never be stored anywhere at all")
    allowed = {d.uri for d in scenario.DOCUMENTS}
    for text in inputs:
        for i in range(0, max(len(text) - 20, 1)):
            piece = text[i : i + 21]
            if len(piece) == 21 and piece in dump and not any(piece in a for a in allowed):
                pytest.fail("stored text found")
    for pii in scenario.PLANTED_PII:
        assert pii not in dump


def test_second_run_is_idempotent(first_run):
    _, judge = first_run
    calls = len(judge.calls)
    record = run(now=NOW + timedelta(minutes=10), judge=judge, docs=RunDocuments())
    assert record["assessed"] == 1  # only the turn that just became eligible
    new_calls = [c for c in judge.calls[calls:] if c[1] == "Stage1Form"]
    assert len(new_calls) == 2  # the new turn, and its second-model check
    assert len(rows(QUALITY_TURNS, "status = 'ASSESSED'")) == len(by_status()["ASSESSED"])
    assert len(rows(RUNS)) == 2
