"""Alert lookup: the segments an alert reported, with the grade it showed and the latest grade (§7.7, §12.10)."""

from __future__ import annotations

from typing import Any

from conversation_analyzer.bq.client import query, tbl
from conversation_analyzer.bq.schema import ALERT_SESSIONS, ALERTS, SESSION_GRADES


def lookup(alert_id: str) -> dict[str, Any] | None:
    alerts = query(
        f"""SELECT alert_id, kind, day, hour, check, channel, primary_failure, data_store, doc_id, uri, topic, n_turns,
       run_id, value, experimental FROM {tbl(ALERTS)} WHERE alert_id = @a""",
        a=alert_id,
    )
    if not alerts:
        return None
    sessions = query(
        f"""
SELECT s.session_key, s.segment_no, s.grade_state_shown, s.outcome_shown,
       g.grade_state, g.outcome, g.first_bad_turn, g.rephrases_corrections, g.recovered, g.graded_turns
FROM {tbl(ALERT_SESSIONS)} s
LEFT JOIN {tbl(SESSION_GRADES)} g ON g.session_key = s.session_key AND g.segment_no = s.segment_no
WHERE s.alert_id = @a
ORDER BY s.session_key, s.segment_no""",
        a=alert_id,
    )
    return {"alert": alerts[0], "sessions": sessions}
