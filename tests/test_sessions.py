"""Sessions and segments without the emulator: joins, closes, sticky stored numbers, late and erased turns (§5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from conversation_analyzer.assessor.sessions import plan_session
from conversation_analyzer.log.parse import Turn
from conversation_analyzer.vocab import Channel

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


def turn(key: str, minutes_ago: float) -> Turn:
    return Turn(key, "s", NOW - timedelta(minutes=minutes_ago), Channel.WEB_UI, "q", "a", [], [], "SUCCEEDED", False)


def plan(turns, stored_turns=None, stored_segments=None):
    return plan_session("s", turns, stored_turns or {}, stored_segments or {}, NOW)


def test_pause_of_30_minutes_starts_a_new_segment_and_idle_closes():
    p = plan([turn("a", 100), turn("b", 90), turn("c", 50)])
    first, second = p.segments
    assert [t.turn_key for t in first.turns] == ["a", "b"] and first.state == "CLOSED" and first.close_reason == "IDLE"
    assert second.resumed and second.previous_close_reason == "IDLE" and second.state == "CLOSED"
    places = {pl.turn.turn_key: pl for pl in p.places}
    assert places["c"].position_in_session == 3 and places["c"].position_in_segment == 1
    assert places["c"].gap_bucket == "30_60_MIN" and [t.turn_key for t in places["c"].context] == ["a", "b"]
    assert places["c"].earlier_references_from == [] and places["a"].gap_bucket is None
    assert first.duration_bucket() == "5_30_MIN"


def test_open_segment_stays_open():
    p = plan([turn("a", 20), turn("b", 10)])
    assert p.segments[0].state == "OPEN" and p.segments[0].close_reason is None


def test_three_and_a_half_hours_force_a_close():
    turns = [turn(str(i), 230 - i * 20) for i in range(12)]  # every 20 minutes, 3h40 in all
    p = plan(turns)
    first = p.segments[0]
    assert first.close_reason == "FORCED" and len(first.turns) == 11 and len(p.segments) == 2


def test_stored_numbers_are_sticky_and_erased_turns_shift_positions():
    stored_turns = {"c": {"segment_no": 2, "position_in_session": 4}}
    stored_segments = {
        1: {"n_turns": 2, "state": "CLOSED", "close_reason": "IDLE", "first_position_in_session": 1},
        2: {"n_turns": 2, "state": "OPEN", "first_position_in_session": 3, "duration_bucket": "1_5_MIN"},
    }
    p = plan([turn("c", 20), turn("d", 15)], stored_turns, stored_segments)
    seg = p.segments[0]
    assert seg.segment_no == 2 and seg.erased_turns == 1 and not seg.complete_text
    assert seg.previous_close_reason == "IDLE" and seg.previous_text_missing
    assert seg.duration_bucket() == "1_5_MIN"  # from storage: the first turn's text is gone
    places = {pl.turn.turn_key: pl for pl in p.places}
    # "d" can't join: the segment's first turn is erased, so its time limit can't be checked
    assert places["c"].position_in_session == 4 and places["c"].earlier_text_missing
    assert places["d"].segment.segment_no == 3


def test_closed_stored_segment_takes_no_new_turn():
    stored_turns = {"a": {"segment_no": 1}}
    stored_segments = {1: {"n_turns": 1, "state": "CLOSED", "close_reason": "FORCED", "first_position_in_session": 1}}
    p = plan([turn("a", 20), turn("b", 15)], stored_turns, stored_segments)
    assert [s.segment_no for s in p.segments] == [1, 2]
    assert p.segments[0].state == "CLOSED" and p.segments[1].previous_close_reason == "FORCED"


def test_late_turn_joins_the_stored_segment_it_precedes():
    stored_turns = {"b": {"segment_no": 1, "position_in_session": 1}}
    stored_segments = {1: {"n_turns": 1, "state": "OPEN", "first_position_in_session": 1}}
    p = plan([turn("late", 35), turn("b", 30)], stored_turns, stored_segments)
    (seg,) = p.segments
    places = {pl.turn.turn_key: pl for pl in p.places}
    assert places["late"].position_in_session == 1 and places["b"].position_in_session == 2
    assert [t.turn_key for t in places["b"].context] == ["late"]


def test_late_turn_after_a_long_pause_gets_its_own_segment():
    stored_turns = {"b": {"segment_no": 1}}
    stored_segments = {1: {"n_turns": 1, "state": "OPEN", "first_position_in_session": 1}}
    p = plan([turn("late", 100), turn("b", 30)], stored_turns, stored_segments)
    assert {pl.turn.turn_key: pl.segment.segment_no for pl in p.places} == {"late": 2, "b": 1}


def test_late_turn_never_stretches_a_segment_past_the_hard_limit():
    stored_turns = {k: {"segment_no": 1} for k in ("b", "c")}
    stored_segments = {1: {"n_turns": 2, "state": "OPEN", "first_position_in_session": 1}}
    turns = [turn("late", 215)] + [turn(str(i), 200 - i * 20) for i in range(10)] + [turn("b", 5), turn("c", 1)]
    for t in turns[1:-2]:
        stored_turns[t.turn_key] = {"segment_no": 1}
    p = plan(turns, stored_turns, stored_segments)
    assert {pl.turn.turn_key: pl.segment.segment_no for pl in p.places}["late"] == 2
