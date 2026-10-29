"""Slack messages from templates: counts, codes, IDs, allowlisted links, and no time finer than the hour (§12.8)."""

from __future__ import annotations

from datetime import date
from typing import Any

from conversation_analyzer.reporting.results import ClusterKey
from conversation_analyzer.vocab import CountBucket, GradeState, HealthCheck, Outcome

_OUTCOME = {
    Outcome.RESOLVED: "resolved",
    Outcome.PARTIALLY_RESOLVED: "partly resolved",
    Outcome.UNRESOLVED: "unresolved",
    Outcome.UNCLEAR: "unclear",
}
_COUNT = {CountBucket.ZERO: "never", CountBucket.ONE: "once", CountBucket.TWO_OR_MORE: "2 or more times"}


def when(day: date, hour: int) -> str:
    return f"{day.isoformat()} {hour:02d}:00 UTC"


def duration(minutes: float) -> str:
    return f"{int(minutes) // 60}h{int(minutes) % 60:02d}"


def session_line(grade: dict[str, Any] | None, n_turns: int) -> str:
    """For example: 5 turns, unresolved (provisional), went wrong at turn 2, rephrased or corrected 2 or more times."""
    if grade is None:
        return f"{n_turns} turns, no grade yet"
    if grade["grade_state"] == GradeState.NOT_GRADABLE:
        return f"{n_turns} turns, not gradable (earlier text already erased)"
    parts = [f"{n_turns} turns", f"{_OUTCOME[Outcome(grade['outcome'])]} ({grade['grade_state'].lower()})"]
    if grade.get("first_bad_turn"):
        parts.append(f"went wrong at turn {grade['first_bad_turn']}")
    parts.append(f"rephrased or corrected {_COUNT[CountBucket(grade['rephrases_corrections'])]}")
    if grade.get("recovered") == "YES":
        parts.append("recovered after the correction")
    return ", ".join(parts)


def high_cluster(
    alert_id: str,
    key: ClusterKey,
    by_channel: dict[str, int],
    owner: str,
    experimental: bool,
    sessions: list[str],
    day: date,
    hour: int,
) -> str:
    n = sum(by_channel.values())
    where = f"{key.data_store} document {key.doc_id}" if key.doc_id else f"topic {key.topic}"
    lines = [
        f":red_circle: *HIGH failures* `{key.primary_failure}`{' (experimental label)' if experimental else ''}",
        f"{where}" + (f" <{key.uri}|link>" if key.uri else ""),
        f"{n} new turns ({', '.join(f'{c} {k}' for k, c in sorted(by_channel.items()))}), {when(day, hour)}."
        f" Owner: {owner}.",
        "Sessions:",
        *[f"• {s}" for s in sessions],
        f"Alert `{alert_id}`; look up its sessions with `make alert-lookup ALERT={alert_id}`.",
    ]
    return "\n".join(lines)


def health(alert_id: str, check: HealthCheck, value: float | None, day: date, hour: int, **ctx: Any) -> str:
    v = value or 0.0
    text = {
        HealthCheck.COVERAGE: f"Coverage of assessment run `{ctx.get('run_id')}` was {v:.1%} "
        f"(target {ctx.get('target', 0):.0%}).",
        HealthCheck.WAITING_TOO_LONG: f"A turn has waited {duration(v)} for assessment "
        f"(limit {duration(ctx.get('limit', 0))}).",
        HealthCheck.NO_RUN: f"No assessment run for {duration(v)} (limit {duration(ctx.get('limit', 0))}).",
        HealthCheck.RUN_FAILED: f"Assessment run `{ctx.get('run_id')}` failed: `{ctx.get('error_class')}`.",
        HealthCheck.LOG_GAP: f"Log gap: {ctx.get('channel')} had {int(v)} records in the hour {ctx.get('checked')}, "
        f"usually {ctx.get('expected', 0):.0f}.",
        HealthCheck.WINDOW_SHORT: f"The log window is {duration(v)}, under {duration(ctx.get('limit', 0))}: "
        "turns may be erased before they are assessed.",
        HealthCheck.TOKEN_LIMIT: f"Judge tokens used today: {v / 1e6:.1f}M, over the daily limit of "
        f"{ctx.get('limit', 0) / 1e6:.1f}M.",
    }[check]
    return f":warning: *Conversation Analyzer pipeline* `{check.value}`, {when(day, hour)}\n{text}\nAlert `{alert_id}`."


def acknowledged(user: str, day: date) -> str:
    return f":white_check_mark: Acknowledged by <@{user}> on {day.isoformat()}; the reference period restarts that day."
