"""Read the window: the production engine's turns of the last 4h30, feedback and searches (§12.6)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from conversation_analyzer.bq.client import fq, query
from conversation_analyzer.bq.views import engine_filter, partition_filter
from conversation_analyzer.log.parse import Feedback, Search, Turn, parse_feedback, parse_search, parse_turn
from conversation_analyzer.settings import get_settings


@dataclass
class Window:
    turns: list[Turn]
    feedback: list[Feedback]
    searches: list[Search]
    oldest_answer_age_minutes: float | None  # how far back answers still exist: the measured window (§12.12)


def read_window(now: datetime, feedback_since: datetime, search_since: datetime, search_until: datetime) -> Window:
    s = get_settings()
    log = fq("log", s.log_table)
    start = now - timedelta(minutes=s.timing.window_read_minutes)
    turn_rows = query(
        f"""
SELECT timestamp, assistToken, userIamPrincipal, userQuery, serviceTextReply,
       TO_JSON_STRING(request) AS request, TO_JSON_STRING(response) AS response
FROM {log}
WHERE {partition_filter(1)} AND methodName = 'StreamAssist' AND timestamp >= @start AND timestamp <= @now
  AND {engine_filter()} AND response IS NOT NULL""",
        start=start,
        now=now,
    )
    feedback_rows = query(
        f"""
SELECT timestamp, TO_JSON_STRING(request) AS request
FROM {log}
WHERE {partition_filter(1)} AND methodName = 'WriteUserEvent' AND timestamp > @since AND timestamp <= @now
  AND JSON_VALUE(request, '$.userEvent.eventType') = 'add-feedback'
  AND {engine_filter("JSON_VALUE(request, '$.userEvent.engine')")}""",
        since=min(feedback_since, start),
        now=now,
    )
    search_rows = query(
        f"""
SELECT timestamp, userIamPrincipal, TO_JSON_STRING(response) AS response
FROM {log}
WHERE {partition_filter(1)} AND methodName = 'Search' AND timestamp >= @since AND timestamp < @until
  AND response IS NOT NULL""",
        since=search_since,
        until=search_until,
    )
    oldest = query(
        f"""
SELECT MIN(timestamp) AS t FROM {log}
WHERE {partition_filter(1)} AND methodName = 'StreamAssist' AND response IS NOT NULL
  AND timestamp >= TIMESTAMP_SUB(@now, INTERVAL 6 HOUR)""",
        now=now,
    )[0]["t"]
    turns = [t for t in (parse_turn(r) for r in turn_rows) if t is not None]
    return Window(
        turns=sorted(turns, key=lambda t: t.timestamp),
        feedback=[parse_feedback(r) for r in feedback_rows],
        searches=[parse_search(r) for r in search_rows],
        oldest_answer_age_minutes=(now - oldest).total_seconds() / 60 if oldest else None,
    )
