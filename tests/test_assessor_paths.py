"""Assessor paths the demo scenario doesn't take: judge failures, the time budget, late and erased turns, leaks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from conversation_analyzer import keys
from conversation_analyzer.assessor import run as run_mod
from conversation_analyzer.assessor.run import run
from conversation_analyzer.bq.external import AUDIT_LOGS
from conversation_analyzer.bq.schema import QUALITY_TURNS, RUNS, SEGMENTS, SESSION_GRADES, STAGE1_RESULTS
from conversation_analyzer.devtools import scenario
from conversation_analyzer.devtools.synthetic import SynthTurn, insert_log, store_department_map, turn_rows
from conversation_analyzer.docs.content import storage_client
from conversation_analyzer.docs.source import RunDocuments
from conversation_analyzer.judge import stage1
from conversation_analyzer.judge.fake import FakeJudge
from conversation_analyzer.people.directory import split_uri
from conversation_analyzer.settings import get_settings
from tests.conftest import rows, wipe

pytestmark = pytest.mark.emulator

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
HIGH = "[[fake codes=CONTRADICTED_CLAIM severity=HIGH groundedness=1"
LEAVE_REF = scenario.ref(scenario.LEAVE, "Employees have up to 4 days of on-demand leave per year.")


class Capturing(FakeJudge):
    """The fake judge, keeping every prompt."""

    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[tuple[str, str]] = []

    def generate(self, model, system, prompt, form, usage):
        self.prompts.append((form.__name__, prompt))
        return super().generate(model, system, prompt, form, usage)


@pytest.fixture
def clean(emulator):
    wipe()
    share = get_settings().judge.second_model_share
    get_settings().judge.second_model_share = 0.0
    yield
    get_settings().judge.second_model_share = share


def seed(turns: list[SynthTurn], now: datetime = NOW) -> None:
    insert_log([r for t in turns for r in turn_rows(t, now)])


def assess(now: datetime = NOW, judge: FakeJudge | None = None) -> dict:
    return run(now=now, judge=judge or FakeJudge(), docs=RunDocuments())


def statuses() -> dict[str, dict]:
    return {r["turn_key"]: r for r in rows(QUALITY_TURNS)}


def test_invalid_judge_output_fails_the_turn_once(clean):
    seed([SynthTurn("F1", 20, "How many leave days?", "Four. [[fake fail=output]]")])
    record = assess()
    assert record["failed"] == 1 and record["assessed"] == 0
    (turn,) = statuses().values()
    assert turn["status"] == "FAILED" and turn["error_class"] == "JUDGE_INVALID_OUTPUT"
    assert assess(NOW + timedelta(minutes=10))["failed"] == 0  # counted in the run that failed it only


def test_api_error_leaves_the_turn_waiting(clean):
    seed([SynthTurn("A1", 20, "How many leave days?", "Four. [[fake fail=api]]")])
    record = assess()
    assert record["assessed"] == 0 and record["failed"] == 0 and not statuses()
    assert record["covered"] == 0 and record["eligible"] == 1 and record["oldest_waiting_minutes"] == 20.0


def test_stage2_failure_stays_pending_then_gives_up(clean):
    seed([SynthTurn("P1", 20, "How many leave days?", f"Six. {HIGH} fail=api fail_on=Stage2Form]]", refs=[LEAVE_REF])])
    record = assess()
    assert record["stage2_pending"] == 1 and record["stage2_done"] == 0
    (turn,) = statuses().values()
    assert turn["stage2_state"] == "PENDING" and turn["flagged"]
    record = assess(NOW + timedelta(minutes=200))  # past 3h30 since the turn
    assert record["stage2_gave_up"] == 1
    assert next(iter(statuses().values()))["stage2_state"] == "GAVE_UP"


def test_session_grade_failure_writes_no_grade(clean):
    seed(
        [
            SynthTurn(
                "G1", 20, "How many leave days?", f"Six. {HIGH} fail=api fail_on=SessionGradeForm]]", refs=[LEAVE_REF]
            )
        ]
    )
    record = assess()
    assert record["stage2_done"] == 1 and record["session_grades"] == 0 and not rows(SESSION_GRADES)


def test_no_time_left_starts_no_judge_call(clean, monkeypatch):
    monkeypatch.setattr(get_settings().timing, "stop_new_calls_after_seconds", 0)
    seed([SynthTurn("T1", 20, "How many leave days?", "Four.")])
    judge = FakeJudge()
    record = assess(judge=judge)
    assert record["assessed"] == 0 and not judge.calls and record["eligible"] == 1


def test_erased_earlier_segment_reaches_the_judge_as_labels(clean):
    first = SynthTurn("E1", 300, "How many leave days?", "Four. [[fake intent=FACT_LOOKUP]]", refs=[LEAVE_REF])
    seed([first])
    assess(NOW - timedelta(minutes=290))  # the first turn is assessed while its text exists
    seed([SynthTurn("E1", 20, "And sick leave? [[fake relation=FOLLOW_UP]]", "Needs a certificate.")])
    judge = Capturing()
    assess(judge=judge)
    prompt = next(p for f, p in judge.prompts if f == "Stage1Form")
    assert "### Turn 1 (segment 1, text erased): intent FACT_LOOKUP" in prompt
    assert "previous turn text erased" in prompt
    seg2 = [s for s in rows(SEGMENTS) if s["segment_no"] == 2][0]
    assert seg2["resumed"] and seg2["earlier_text_missing"] and seg2["first_position_in_session"] == 2


def test_late_earlier_turn_reassesses_the_later_one(clean):
    later = SynthTurn("L1", 30, "And how do I book it? [[fake relation=FOLLOW_UP]]", "In the Travel Tool.")
    seed([later])
    first = assess()
    assert first["assessed"] == 1
    seed([SynthTurn("L1", 35, "How do business trips work?", "Ask your manager.")])  # arrives late
    judge = FakeJudge()
    second = assess(NOW + timedelta(minutes=10), judge=judge)
    assert second["assessed"] == 2 and [f for _, f in judge.calls].count("Stage1Form") == 2
    positions = sorted(r["position_in_session"] for r in rows(QUALITY_TURNS))
    assert positions == [1, 2]
    s1 = {r["turn_key"]: r for r in rows(STAGE1_RESULTS)}
    assert sorted(r["relation"] for r in s1.values()) == ["FIRST", "FOLLOW_UP"]


def test_leak_guard_failure_marks_the_turn_failed(clean, monkeypatch):
    original = stage1.Stage1Result.row

    def leaky(self):
        row = original(self)
        if self.intent == "HOW_TO":
            row["topic"] = "free text that must never be stored"
        return row

    monkeypatch.setattr(stage1.Stage1Result, "row", leaky)
    seed(
        [
            SynthTurn("K1", 20, "How do I book a trip?", "In the tool. [[fake intent=HOW_TO]]"),
            SynthTurn("K2", 20, "How many leave days?", "Four.", principal="user:b@rtbhouse.com"),
        ]
    )
    record = assess()
    assert record["failed_by_class"] == [{"error_class": "LEAK_GUARD", "n": 1}] and record["failed"] == 1
    by_status = sorted((r["status"], r["error_class"]) for r in statuses().values())
    assert by_status == [("ASSESSED", None), ("FAILED", "LEAK_GUARD")]
    assert len(rows(STAGE1_RESULTS)) == 1
    assert "free text" not in str(rows(QUALITY_TURNS))


def test_failed_run_writes_a_failed_record(clean, monkeypatch):
    def boom(self, states, stored):
        raise RuntimeError("bad")

    monkeypatch.setattr(run_mod.AssessmentRun, "phase1", boom)
    seed([SynthTurn("X1", 20, "How many leave days?", "Four.")])
    with pytest.raises(RuntimeError):
        assess()
    (record,) = rows(RUNS)
    assert record["status"] == "FAILED" and record["error_class"] == "UNEXPECTED"


def test_feedback_for_a_turn_outside_the_window_is_counted(clean):
    seed(
        [
            SynthTurn("W1", 300, "Old question", "Old answer", erased=True, feedback="LIKE", feedback_minutes_ago=5),
            SynthTurn("W2", 20, "How many leave days?", "Four.", feedback="DISLIKE"),
        ]
    )
    record = assess()
    assert record["feedback_after_window"] == 1 and record["feedback_matched"] == 1


def test_feedback_after_the_window_reaches_its_turn_when_switched_on(clean, monkeypatch):
    seed([SynthTurn("W3", 20, "How many leave days?", "Four."), SynthTurn("W3", 15, "And sick days?", "Ask HR.")])
    assess()
    stored = {r["position_in_session"]: r for r in rows(QUALITY_TURNS)}
    assert stored[2]["feedback_thumbs"] is None
    later = NOW + timedelta(hours=5)  # both turns erased; the user dislikes the second answer

    def dislike(at: datetime) -> None:
        turn = SynthTurn(
            "W3",
            300,
            "And sick days?",
            "Ask HR.",
            erased=True,
            feedback="DISLIKE",
            feedback_minutes_ago=2,
            question_index=1,
        )
        insert_log([r for r in turn_rows(turn, at) if r["methodName"] != "StreamAssist"])

    wipe(AUDIT_LOGS)
    dislike(later)
    monkeypatch.setattr(get_settings().timing, "feedback_after_window_fallback", False)
    assert assess(now=later)["feedback_after_window"] == 1  # only counted
    assert {r["position_in_session"]: r["feedback_thumbs"] for r in rows(QUALITY_TURNS)} == {1: None, 2: None}
    monkeypatch.setattr(get_settings().timing, "feedback_after_window_fallback", True)
    dislike(later + timedelta(minutes=10))  # each run reads only the feedback that arrived since the last one
    assess(now=later + timedelta(minutes=10))
    after = {r["position_in_session"]: r for r in rows(QUALITY_TURNS)}
    assert after[2]["feedback_thumbs"] == "DOWN" and after[2]["feedback_reasons"] == ["INACCURATE", "UNRECOGNIZED"]
    assert after[1]["feedback_thumbs"] is None and after[2]["status"] == stored[2]["status"]


def _drop_department_map() -> None:
    bucket, path = split_uri(get_settings().department_map_uri)
    blob = storage_client().bucket(bucket).blob(path)
    if blob.exists():
        blob.delete()


def test_department_map_missing_then_found_then_stale(clean):
    seed([SynthTurn("D1", 20, "How many leave days?", "Four.", principal="user:ola@rtbhouse.com")])
    _drop_department_map()
    record = assess()
    assert record["directory_unavailable"] is True and rows(RUNS)[0]["directory_unavailable"] is True
    assert [t["department"] for t in statuses().values()] == ["UNKNOWN"]
    assert [s["department"] for s in rows(SEGMENTS)] == ["UNKNOWN"]
    # The map is back: the user's identity is still in the log, so the turn gets its family.
    store_department_map(scenario.DEPARTMENTS, NOW)
    assert assess(NOW + timedelta(minutes=10))["directory_unavailable"] is False
    assert [t["department"] for t in statuses().values()] == ["COMMERCIAL"]
    assert [s["department"] for s in rows(SEGMENTS)] == ["COMMERCIAL"]
    assert [(t["base_function"], t["user_key"]) for t in statuses().values()] == [
        ("Sales", keys.user_key("ola@rtbhouse.com"))
    ]
    # A stale map is not used, and a family once stored is kept.
    record = assess(NOW + timedelta(hours=get_settings().people_directory.max_age_hours, minutes=1))
    assert record["directory_unavailable"] is True
    assert [(t["department"], t["base_function"]) for t in statuses().values()] == [("COMMERCIAL", "Sales")]
