"""Slack messages from templates: counts, codes, IDs, allowlisted links, and no time finer than the hour (§12.8)."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from conversation_analyzer.reporting.results import ClusterKey
from conversation_analyzer.settings import get_settings
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


_PERCENT = ("AQR", "SHARE", "RATE", "COVERAGE", "RESUMED")
_KIND = {"JUMP": "sudden jump", "DRIFT": "slow drift"}
_EVENT_ID = re.compile(r"^evt-[0-9a-f]{8,64}$")


def value(metric: str, v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:.1%}" if any(p in metric for p in _PERCENT) else f"{v:.1f}"


def anomaly(a: dict[str, Any]) -> str:
    m = a["metric"]
    events = a.get("change_events") or []
    cause = (
        "Change events in the 48 hours before, likely caused by: " + ", ".join(f"`{e}`" for e in events)
        if events
        else "No change event in the 48 hours before: unexplained."
    )
    return "\n".join(
        [
            f":chart_with_downwards_trend: *Anomaly* `{m}` on {a['channel']}, {a['day'].isoformat()} "
            f"({_KIND[a['kind']]})",
            f"Value {value(m, a['value'])}, reference {value(m, a['reference_value'])} "
            f"(band {value(m, a['band_low'])} to {value(m, a['band_high'])}).",
            cause,
            f"React with :{get_settings().alerts.ack_emoji}: to acknowledge. Alert `{a['alert_id']}`.",
        ]
    )


def _change(change_id: str | None) -> str:
    return f"`{change_id}`" if change_id and _EVENT_ID.match(change_id) else "a change"


def digest(
    week: date,
    trend: dict[str, dict[str, float | None]],
    clusters: list[dict[str, Any]],
    best_docs: list[dict[str, Any]],
    best_topics: list[dict[str, Any]],
    unusual: list[str],
    releases: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    baseline_top_turns: int | None,
) -> str:
    """The Monday digest (§9.2): derived values only, documents by ID and allowlisted link."""
    lines = [f":bar_chart: *Bolek quality digest*, week of {week.isoformat()}", "*AQR (standardized)*"]
    for channel in sorted(trend):
        t = trend[channel]
        lines.append(f"• {channel}: {value('AQR', t.get('now'))} (4 weeks before: {value('AQR', t.get('before'))})")
    lines.append("*Top problem clusters* (turns this week; trend against the 4 weeks before; owner)")
    for c in clusters:
        where = f"{c['data_store']} document {c['doc_id']}" if c["doc_id"] else f"topic {c['topic']}"
        link = f" <{c['uri']}|link>" if c.get("uri") else ""
        trend_text = f"x{c['trend']:.1f}" if c.get("trend") else "new"
        label = " (experimental label)" if c["experimental"] else ""
        lines.append(
            f"{c['rank']}. `{c['primary_failure']}`{label} {where}{link}: {c['n_turns']} turns ({c['n_high']} HIGH), "
            f"{trend_text}, owner {c['owner']}, `{c['cluster_id']}`"
        )
    if not clusters:
        lines.append("none")
    lines.append("*Best documents*")
    lines += [
        f"• {d['data_store']} document {d['doc_id']}"
        + (f" <{d['uri']}|link>" if d.get("uri") else "")
        + f": AQR {value('AQR', d['aqr'])} over {d['n_verifiable']} turns"
        for d in best_docs
    ] or ["none with enough turns"]
    lines.append("*Best topics*")
    lines += [f"• {t['topic']}: AQR {value('AQR', t['aqr'])} over {t['n']} turns" for t in best_topics] or ["none"]
    lines.append("*Unusual*")
    lines += [f"• {u}" for u in unusual] or ["nothing"]
    lines.append("*Release results* (standardized AQR, all channels)")
    lines += [
        f"• {_change(r['event_id'])}: {r['verdict'].lower().replace('_', ' ')}"
        + (f" ({r['diff'] * 100:+.1f} points)" if r.get("diff") is not None else "")
        for r in releases
    ] or ["none this week"]
    lines.append("*Release gate verdicts*")
    lines += [f"• {_change(g['change_id'])}: {g['verdict']}" for g in gates] or ["none this week"]
    if baseline_top_turns is not None:
        lines.append(f"*Turns still in the baseline's top clusters*: {baseline_top_turns}")
    return "\n".join(lines)
