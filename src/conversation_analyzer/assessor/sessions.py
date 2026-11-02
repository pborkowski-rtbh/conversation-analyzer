"""Sessions and segments from the window and stored rows; stored turns keep their segment number (§5, §12.6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from conversation_analyzer.log.parse import Turn
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import CloseReason, SegmentState, duration_bucket, gap_bucket


@dataclass
class Segment:
    session_key: str
    segment_no: int
    turns: list[Turn]  # in the window, by time
    erased_turns: int  # turns of this segment no longer in the window
    first_position_in_session: int
    state: str
    close_reason: str | None
    was_open: bool  # open (or unknown) before this run, so closing now needs a final grade
    previous_close_reason: str | None
    previous_text_missing: bool
    stored: dict[str, Any] | None

    @property
    def resumed(self) -> bool:
        return self.segment_no > 1

    @property
    def n_turns(self) -> int:
        return self.erased_turns + len(self.turns)

    @property
    def complete_text(self) -> bool:
        return self.erased_turns == 0

    def duration_bucket(self) -> str | None:
        if not self.complete_text or not self.turns:
            return (self.stored or {}).get("duration_bucket")
        return duration_bucket((self.turns[-1].timestamp - self.turns[0].timestamp).total_seconds() / 60).value


@dataclass
class TurnPlace:
    turn: Turn
    segment: Segment
    position_in_segment: int
    position_in_session: int
    gap_bucket: str | None
    previous: Turn | None  # the previous turn of the session, when its text is in the window
    has_previous_turn: bool
    context: list[Turn] = field(default_factory=list)  # earlier turns of this and the previous segment
    earlier_references_from: list[Turn] = field(default_factory=list)  # earlier turns of the same segment
    earlier_text_missing: bool = False


@dataclass
class SessionPlan:
    session_key: str
    segments: list[Segment]
    places: list[TurnPlace]


def _later_stored_segment(
    turns: list[Turn], i: int, stored_turns: dict[str, dict[str, Any]], idle: timedelta, hard: timedelta
) -> int | None:
    """The segment of the first stored turn after turn i, when no pause of 30 minutes lies between them."""
    for j in range(i + 1, len(turns)):
        if turns[j].timestamp - turns[j - 1].timestamp >= idle:
            return None
        no = (stored_turns.get(turns[j].turn_key) or {}).get("segment_no")
        if no:
            last = max(t.timestamp for t in turns if (stored_turns.get(t.turn_key) or {}).get("segment_no") == no)
            return no if last - turns[i].timestamp < hard else None
    return None


def plan_session(
    session_key: str,
    turns: list[Turn],
    stored_turns: dict[str, dict[str, Any]],
    stored_segments: dict[int, dict[str, Any]],
    now: datetime,
) -> SessionPlan:
    t_cfg = get_settings().timing
    idle = timedelta(minutes=t_cfg.segment_idle_close_minutes)
    hard = timedelta(minutes=t_cfg.hard_limit_minutes)
    turns = sorted(turns, key=lambda t: t.timestamp)
    assign: dict[str, int] = {}
    for i, t in enumerate(turns):
        stored = stored_turns.get(t.turn_key)
        if stored and stored.get("segment_no"):
            assign[t.turn_key] = stored["segment_no"]
            continue
        prev = turns[i - 1] if i else None
        if prev is not None:
            pseg = assign[prev.turn_key]
            seg_turns = [x for x in turns[:i] if assign[x.turn_key] == pseg]
            stored_n = (stored_segments.get(pseg) or {}).get("n_turns") or 0
            stored_in_window = sum(1 for x in seg_turns if x.turn_key in stored_turns)
            first_erased = stored_n > stored_in_window
            closed_in_storage = (stored_segments.get(pseg) or {}).get("state") == SegmentState.CLOSED
            joins = (
                not first_erased
                and not closed_in_storage
                and t.timestamp - prev.timestamp < idle
                and t.timestamp - seg_turns[0].timestamp < hard
            )
            if joins:
                assign[t.turn_key] = pseg
                continue
        later = _later_stored_segment(turns, i, stored_turns, idle, hard)
        if later is not None:  # a turn that reached the log late joins the stored segment it precedes (§6.1)
            assign[t.turn_key] = later
            continue
        known = list(assign.values()) + list(stored_segments)
        assign[t.turn_key] = (max(known) if known else 0) + 1

    segments: dict[int, Segment] = {}
    seg_numbers = sorted(set(assign.values()))
    for no in seg_numbers:
        seg_turns = [t for t in turns if assign[t.turn_key] == no]
        stored = stored_segments.get(no)
        stored_n = (stored or {}).get("n_turns") or 0
        erased = max(stored_n - sum(1 for t in seg_turns if t.turn_key in stored_turns), 0)
        prev_no = no - 1
        prev_seg = segments.get(prev_no)
        prev_stored = stored_segments.get(prev_no)
        if stored and stored.get("first_position_in_session"):
            first_pos = stored["first_position_in_session"]
        elif prev_seg is not None:
            first_pos = prev_seg.first_position_in_session + prev_seg.n_turns
        elif prev_stored is not None:
            first_pos = (prev_stored.get("first_position_in_session") or 1) + (prev_stored.get("n_turns") or 0)
        else:
            first_pos = 1
        if prev_seg is not None:
            previous_close_reason = prev_seg.close_reason
            previous_text_missing = not prev_seg.complete_text
        elif prev_stored is not None:
            previous_close_reason = prev_stored.get("close_reason")
            previous_text_missing = True  # none of its turns is in the window any more
        else:
            previous_close_reason, previous_text_missing = None, False
        segments[no] = Segment(
            session_key=session_key,
            segment_no=no,
            turns=seg_turns,
            erased_turns=erased,
            first_position_in_session=first_pos,
            state=SegmentState.OPEN.value,
            close_reason=None,
            was_open=(stored or {}).get("state") != SegmentState.CLOSED,
            previous_close_reason=previous_close_reason,
            previous_text_missing=previous_text_missing,
            stored=stored,
        )

    for i, no in enumerate(seg_numbers):
        seg = segments[no]
        stored = seg.stored or {}
        if stored.get("state") == SegmentState.CLOSED:
            seg.state, seg.close_reason = SegmentState.CLOSED.value, stored.get("close_reason")
            continue
        first = seg.turns[0].timestamp if seg.complete_text else None
        idle_at = seg.turns[-1].timestamp + idle
        forced_at = first + hard if first else now
        nxt = segments[seg_numbers[i + 1]].turns[0].timestamp if i + 1 < len(seg_numbers) else None
        horizon = min(x for x in (now, nxt) if x is not None)
        if min(idle_at, forced_at) <= horizon:
            seg.state = SegmentState.CLOSED.value
            seg.close_reason = (CloseReason.FORCED if forced_at < idle_at else CloseReason.IDLE).value
    for i, no in enumerate(seg_numbers[1:], start=1):
        segments[no].previous_close_reason = (
            segments[seg_numbers[i - 1]].close_reason or segments[no].previous_close_reason
        )

    places: list[TurnPlace] = []
    for i, t in enumerate(turns):
        seg = segments[assign[t.turn_key]]
        rank = seg.turns.index(t)
        pos_seg = seg.erased_turns + rank + 1
        stored = stored_turns.get(t.turn_key) or {}
        prev = turns[i - 1] if i else None
        has_previous = seg.first_position_in_session + pos_seg - 1 > 1
        if prev is not None:
            gap = gap_bucket((t.timestamp - prev.timestamp).total_seconds() / 60).value
        else:
            gap = stored.get("gap_bucket")
        context = [x for x in turns[:i] if assign[x.turn_key] in (seg.segment_no, seg.segment_no - 1)]
        same_segment = [x for x in turns[:i] if assign[x.turn_key] == seg.segment_no]
        missing = seg.erased_turns > 0 or (seg.resumed and seg.previous_text_missing)
        places.append(
            TurnPlace(
                turn=t,
                segment=seg,
                position_in_segment=pos_seg,
                position_in_session=seg.first_position_in_session + pos_seg - 1,
                gap_bucket=gap,
                previous=prev,
                has_previous_turn=has_previous or prev is not None,
                context=context,
                earlier_references_from=same_segment,
                earlier_text_missing=missing,
            )
        )
    return SessionPlan(session_key, [segments[n] for n in seg_numbers], places)
