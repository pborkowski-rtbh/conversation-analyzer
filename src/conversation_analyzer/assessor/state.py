"""What earlier runs stored for the sessions in the window: fingerprints, flags, segments, grades (§12.6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from conversation_analyzer.bq.client import query, tbl
from conversation_analyzer.bq.schema import (
    JUDGE_VERSIONS,
    QUALITY_TURNS,
    RUNS,
    SEGMENTS,
    SESSION_GRADES,
    STAGE1_RESULTS,
    STAGE2_RESULTS,
)
from conversation_analyzer.judge.case import DocRef
from conversation_analyzer.judge.stage1 import Stage1Result

LOOKBACK_DAYS = 7


@dataclass
class Stored:
    turns: dict[str, dict[str, Any]] = field(default_factory=dict)
    segments: dict[str, dict[int, dict[str, Any]]] = field(default_factory=dict)
    stage1: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    stage2: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    grades: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    versions: set[str] = field(default_factory=set)
    last_run: dict[str, Any] | None = None
    tokens_today: int = 0

    def session_turns(self, session_key: str) -> dict[str, dict[str, Any]]:
        return {k: v for k, v in self.turns.items() if v["session_key"] == session_key}


def load(session_keys: list[str], today: date) -> Stored:
    since = today - timedelta(days=LOOKBACK_DAYS)
    out = Stored()
    if session_keys:
        for row in query(
            f"SELECT * FROM {tbl(QUALITY_TURNS)} WHERE day >= @since AND session_key IN UNNEST(@keys)",
            since=since,
            keys=session_keys,
        ):
            out.turns[row["turn_key"]] = row
        for row in query(f"SELECT * FROM {tbl(SEGMENTS)} WHERE session_key IN UNNEST(@keys)", keys=session_keys):
            out.segments.setdefault(row["session_key"], {})[row["segment_no"]] = row
        for row in query(f"SELECT * FROM {tbl(SESSION_GRADES)} WHERE session_key IN UNNEST(@keys)", keys=session_keys):
            out.grades[(row["session_key"], row["segment_no"])] = row
    turn_keys = list(out.turns)
    if turn_keys:
        # Only the stage 2 columns needed: nested repeated fields don't round-trip through the emulator.
        for table, target, cols in (
            (STAGE1_RESULTS, out.stage1, "*"),
            (STAGE2_RESULTS, out.stage2, "turn_key, judge_version, primary_failure, severity"),
        ):
            for row in query(
                f"SELECT {cols} FROM {tbl(table)} WHERE day >= @since AND turn_key IN UNNEST(@keys)",
                since=since,
                keys=turn_keys,
            ):
                target[(row["turn_key"], row["judge_version"])] = row
    out.versions = {r["judge_version"] for r in query(f"SELECT judge_version FROM {tbl(JUDGE_VERSIONS)}")}
    runs = query(
        f"""SELECT search_cutoff, feedback_cutoff FROM {tbl(RUNS)}
WHERE run_day >= @since AND search_cutoff IS NOT NULL ORDER BY started_at DESC LIMIT 1""",
        since=today - timedelta(1),
    )
    out.last_run = runs[0] if runs else None
    tokens = query(
        f"""SELECT SUM(t.input_tokens + t.output_tokens) AS n FROM {tbl(RUNS)} r, UNNEST(r.tokens) t
WHERE r.run_day = @today""",
        today=today,
    )
    out.tokens_today = int(tokens[0]["n"] or 0) if tokens else 0
    return out


def stage1_from_row(row: dict[str, Any], found_docs: list[dict[str, Any]] | None = None) -> Stage1Result:
    """A stored stage 1 result back in memory, for a late trigger or a session grade in a later run."""
    keys = (
        "intent",
        "topic",
        "topic_source",
        "relation",
        "relevance",
        "completeness",
        "clarity",
        "groundedness",
        "unsupported_spans",
        "total_spans",
        "language_matches",
        "refusal_or_empty",
        "contradicts_earlier",
        "needs_internal_knowledge",
        "failure_types",
        "primary_failure",
        "severity",
        "confidence",
        "knowledge_turn",
        "verifiable",
        "evidence_kind",
        "evidence_check_ran",
        "evidence_check_contradiction",
    )
    values = {k: row.get(k) for k in keys}
    values["failure_types"] = list(values["failure_types"] or [])
    values["evidence_check_ran"] = bool(values["evidence_check_ran"])
    values["evidence_check_contradiction"] = bool(values["evidence_check_contradiction"])
    return Stage1Result(
        **values,
        model=row.get("judge_model") or "",
        found_docs=[DocRef(d["doc_id"], d["data_store"], d.get("uri")) for d in found_docs or []],
    )


def hour_floor(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0)


def search_until(now: datetime) -> datetime:
    """Searches are counted in whole hours ending at least 15 minutes ago, so a re-run recounts the same hours."""
    return hour_floor(now - timedelta(minutes=15))


def window_cutoffs(stored: Stored, now: datetime, window_minutes: int) -> tuple[datetime, datetime]:
    """Where the last run stopped reading searches and feedback, so each record is counted once."""
    floor = now - timedelta(minutes=window_minutes)
    first_whole_hour = hour_floor(floor) + (timedelta(hours=1) if floor != hour_floor(floor) else timedelta())
    if not stored.last_run:
        return first_whole_hour, floor
    return (
        max(stored.last_run["search_cutoff"] or first_whole_hour, first_whole_hour),
        max(stored.last_run["feedback_cutoff"] or floor, floor),
    )
