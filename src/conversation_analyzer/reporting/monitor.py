"""quality-monitor: pipeline health per run, the hourly log check, HIGH cluster alerts, ✅ acknowledgements (§12.8)."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from conversation_analyzer import safe_log
from conversation_analyzer.bq.client import query, tbl, write
from conversation_analyzer.bq.schema import (
    ACKNOWLEDGEMENTS,
    ALERT_SESSIONS,
    ALERTS,
    ANOMALIES,
    PIPELINE_HEALTH,
    RUNS,
    SESSION_GRADES,
    SUITE_RUNS,
)
from conversation_analyzer.judge.version import metric_version
from conversation_analyzer.reporting import messages, slack
from conversation_analyzer.reporting.completeness import check_hours
from conversation_analyzer.reporting.results import ClusterKey, cluster_key, results
from conversation_analyzer.settings import get_settings
from conversation_analyzer.settings import now as utc_now
from conversation_analyzer.vocab import (
    AlertKind,
    AnomalyState,
    HealthCheck,
    HealthKind,
    RunStatus,
    Severity,
    Stage2State,
    owner_of,
)


def alert_id(*parts: Any) -> str:
    """Deterministic, so a check that fires again in the same period maps to the alert already sent."""
    return "alert-" + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def floor_hour(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0)


def reliable_labels(judge_version: str) -> set[str]:
    """Labels the latest suite run of this judge version found reliably; all others are experimental (§11.3)."""
    rows = query(
        f"""
SELECT l.label FROM (
  SELECT label_recall FROM {tbl(SUITE_RUNS)} WHERE judge_version = @v AND NOT partial
  ORDER BY day DESC, suite_run_id DESC LIMIT 1
) r, UNNEST(r.label_recall) l WHERE l.reliable""",
        v=judge_version,
    )
    return {r["label"] for r in rows}


class Monitor:
    def __init__(self, now: datetime) -> None:
        self.s = get_settings()
        self.now = now
        self.today = now.date()
        self.hour = now.hour
        self.health: list[dict[str, Any]] = []
        self.alerts: list[dict[str, Any]] = []
        self.alert_sessions: list[dict[str, Any]] = []
        self.acks: list[dict[str, Any]] = []
        since = self.today - timedelta(days=2)
        self.sent = {r["alert_id"] for r in query(f"SELECT alert_id FROM {tbl(ALERTS)} WHERE day >= @d", d=since)}

    # ------------------------------------------------------------------ alerts

    def send_health(self, aid: str, check: HealthCheck, value: float | None, **ctx: Any) -> None:
        if aid in self.sent:
            return
        text = messages.health(aid, check, value, self.today, self.hour, **ctx)
        channel, ts = slack.post(self.s.alerts.alerts_channel, text)
        self.sent.add(aid)
        self.alerts.append(
            {
                "alert_id": aid,
                "kind": AlertKind.PIPELINE_HEALTH.value,
                "day": self.today,
                "hour": self.hour,
                "slack_channel": channel,
                "slack_ts": ts,
                "check": check.value,
                "channel": ctx.get("channel"),
                "run_id": ctx.get("run_id"),
                "value": value,
                "experimental": False,
            }
        )

    # ------------------------------------------------------------------ per run

    def check_runs(self) -> int:
        """One health row per assessment run, and an alert for each check it fails (§9.2, §12.12)."""
        since = self.today - timedelta(days=1)
        runs = query(
            f"""
SELECT run_id, run_day, started_at, status, error_class, eligible, covered, assessed, too_large, missed, failed,
       oldest_waiting_minutes, window_margin_minutes
FROM {tbl(RUNS)} WHERE run_day >= @d""",
            d=since,
        )
        tokens = {
            r["run_id"]: r["n"] or 0
            for r in query(
                f"""SELECT r.run_id, SUM(t.input_tokens + t.output_tokens) AS n
FROM {tbl(RUNS)} r, UNNEST(r.tokens) t WHERE r.run_day >= @d GROUP BY r.run_id""",
                d=since,
            )
        }
        done = {
            r["run_id"]
            for r in query(
                f"SELECT run_id FROM {tbl(PIPELINE_HEALTH)} WHERE day >= @d AND kind = 'RUN' AND run_id IS NOT NULL",
                d=since,
            )
        }
        t = self.s.timing
        used: Counter[date] = Counter()
        for r in sorted(runs, key=lambda r: r["started_at"]):
            used[r["run_day"]] += tokens.get(r["run_id"], 0)
            if r["run_id"] in done:
                continue
            eligible = r["eligible"] or 0
            coverage = (r["covered"] or 0) / eligible if eligible else 1.0
            checks: list[HealthCheck] = []
            hour = r["started_at"].hour
            if coverage < self.s.metrics.coverage_target:
                checks.append(HealthCheck.COVERAGE)
                self.send_health(
                    alert_id("COVERAGE", r["run_day"], hour),
                    HealthCheck.COVERAGE,
                    coverage,
                    run_id=r["run_id"],
                    target=self.s.metrics.coverage_target,
                )
            if (r["oldest_waiting_minutes"] or 0) > t.assessment_target_minutes:
                checks.append(HealthCheck.WAITING_TOO_LONG)
                self.send_health(
                    alert_id("WAITING", r["run_day"], hour),
                    HealthCheck.WAITING_TOO_LONG,
                    r["oldest_waiting_minutes"],
                    limit=t.assessment_target_minutes,
                )
            if r["status"] != RunStatus.OK:
                checks.append(HealthCheck.RUN_FAILED)
                self.send_health(
                    alert_id("RUN_FAILED", r["run_id"]),
                    HealthCheck.RUN_FAILED,
                    None,
                    run_id=r["run_id"],
                    error_class=r["error_class"],
                )
            margin = r["window_margin_minutes"]
            if margin is not None and margin < t.window_alert_minutes:
                checks.append(HealthCheck.WINDOW_SHORT)
                self.send_health(
                    alert_id("WINDOW", r["run_day"]), HealthCheck.WINDOW_SHORT, margin, limit=t.window_alert_minutes
                )
            if used[r["run_day"]] > self.s.judge.daily_token_limit:
                checks.append(HealthCheck.TOKEN_LIMIT)
                self.send_health(
                    alert_id("TOKENS", r["run_day"]),
                    HealthCheck.TOKEN_LIMIT,
                    float(used[r["run_day"]]),
                    limit=self.s.judge.daily_token_limit,
                )
            self.health.append(
                {
                    "day": r["run_day"],
                    "kind": HealthKind.RUN.value,
                    "run_id": r["run_id"],
                    "hour": hour,
                    "channel": None,
                    "run_status": r["status"],
                    "coverage": coverage,
                    "eligible": eligible,
                    "assessed": r["assessed"],
                    "too_large": r["too_large"],
                    "missed": r["missed"],
                    "failed": r["failed"],
                    "oldest_waiting_minutes": r["oldest_waiting_minutes"],
                    "window_margin_minutes": margin,
                    "checks_fired": [c.value for c in checks],
                }
            )
        last = max((r["started_at"] for r in runs), default=None)
        silent = (self.now - last).total_seconds() / 60 if last else None
        if silent is None or silent > t.no_run_alert_minutes:
            minutes = silent if silent is not None else float(24 * 60)
            self.send_health(
                alert_id("NO_RUN", self.today, self.hour), HealthCheck.NO_RUN, minutes, limit=t.no_run_alert_minutes
            )
            self.health.append(
                {
                    "day": self.today,
                    "kind": HealthKind.RUN.value,
                    "run_id": None,
                    "hour": self.hour,
                    "channel": None,
                    "oldest_waiting_minutes": None,
                    "checks_fired": [HealthCheck.NO_RUN.value],
                }
            )
        return len(runs)

    # ------------------------------------------------------------------ the log

    def check_log_hour(self) -> datetime | None:
        """Once an hour: the records of the last complete hour against the usual for that hour and weekday (§8.2)."""
        hour = floor_hour(self.now - timedelta(minutes=75))
        checked = query(
            f"SELECT COUNT(*) AS n FROM {tbl(PIPELINE_HEALTH)} WHERE day = @d AND kind = 'LOG_HOUR' AND hour = @h",
            d=hour.date(),
            h=hour.hour,
        )
        if checked and checked[0]["n"]:
            return None
        for c in check_hours([hour]):
            if c.gap:
                self.send_health(
                    alert_id("LOG_GAP", hour.isoformat(), c.channel),
                    HealthCheck.LOG_GAP,
                    float(c.records),
                    channel=c.channel,
                    expected=c.expected,
                    checked=messages.when(hour.date(), hour.hour),
                )
            self.health.append(
                {
                    "day": hour.date(),
                    "kind": HealthKind.LOG_HOUR.value,
                    "run_id": None,
                    "hour": hour.hour,
                    "channel": c.channel,
                    "log_records": c.records,
                    "log_expected": c.expected,
                    "log_gap": c.gap,
                    "checks_fired": [HealthCheck.LOG_GAP.value] if c.gap else [],
                }
            )
        return hour

    # ------------------------------------------------------------------ HIGH clusters

    def high_cluster_alerts(self) -> int:
        """New HIGH failures, grouped like problem clusters; stage 1 HIGHs wait until stage 2 has had its say."""
        since = self.today - timedelta(days=1)
        version = metric_version(self.today)
        rows = results(
            "t.day >= @d AND NOT t.is_canary AND NOT IFNULL(t.pace_excluded, FALSE) AND t.stage2_state != @pending",
            version.version_id,
            d=since,
            pending=Stage2State.PENDING.value,
        )
        high = [r for r in rows if r["severity"] == Severity.HIGH]
        if not high:
            return 0
        alerted = query(
            f"""
SELECT a.primary_failure, a.data_store, a.doc_id, a.uri, a.topic, s.session_key, s.segment_no
FROM {tbl(ALERTS)} a JOIN {tbl(ALERT_SESSIONS)} s ON s.alert_id = a.alert_id
WHERE a.kind = @k AND a.day >= @d""",
            k=AlertKind.HIGH_CLUSTER.value,
            d=since - timedelta(days=1),
        )
        seen = {
            (
                ClusterKey(a["primary_failure"], a["data_store"], a["doc_id"], a["uri"], a["topic"]).cluster_id,
                a["session_key"],
                a["segment_no"],
            )
            for a in alerted
        }
        by_cluster: dict[ClusterKey, list[dict[str, Any]]] = defaultdict(list)
        for r in high:
            key = cluster_key(r)
            if (key.cluster_id, r["session_key"], r["segment_no"]) not in seen:
                by_cluster[key].append(r)
        bar = self.s.alerts.high_alert_bar
        todo = {k: v for k, v in by_cluster.items() if len(v) >= bar}
        if not todo:
            return 0
        reliable = reliable_labels(version.version_id)
        segments = sorted({(r["session_key"], r["segment_no"]) for turns in todo.values() for r in turns})
        grades = {
            (g["session_key"], g["segment_no"]): g
            for g in query(
                f"""SELECT session_key, segment_no, grade_state, outcome, first_bad_turn, rephrases_corrections,
       recovered, graded_turns FROM {tbl(SESSION_GRADES)} WHERE session_key IN UNNEST(@k)""",
                k=sorted({s for s, _ in segments}),
            )
        }
        sent = 0
        for key, turns in sorted(todo.items(), key=lambda kv: (-len(kv[1]), kv[0].cluster_id)):
            aid = alert_id("HIGH", key.cluster_id, *sorted(r["turn_key"] for r in turns))
            if aid in self.sent:
                continue
            segs = sorted({(r["session_key"], r["segment_no"]) for r in turns})
            lines = []
            for seg in segs:
                g = grades.get(seg)
                lines.append(messages.session_line(g, (g or {}).get("graded_turns") or 0))
            experimental = key.primary_failure not in reliable
            by_channel = Counter(r["channel"] for r in turns)
            text = messages.high_cluster(
                aid,
                key,
                dict(by_channel),
                owner_of(key.primary_failure).value,
                experimental,
                lines,
                self.today,
                self.hour,
            )
            channel, ts = slack.post(self.s.alerts.quality_channel, text)
            self.sent.add(aid)
            sent += 1
            self.alerts.append(
                {
                    "alert_id": aid,
                    "kind": AlertKind.HIGH_CLUSTER.value,
                    "day": self.today,
                    "hour": self.hour,
                    "slack_channel": channel,
                    "slack_ts": ts,
                    "primary_failure": key.primary_failure,
                    "data_store": key.data_store,
                    "doc_id": key.doc_id,
                    "uri": key.uri,
                    "topic": key.topic,
                    "n_turns": len(turns),
                    "experimental": experimental,
                }
            )
            for session_key, segment_no in segs:
                g = grades.get((session_key, segment_no)) or {}
                self.alert_sessions.append(
                    {
                        "alert_id": aid,
                        "session_key": session_key,
                        "segment_no": segment_no,
                        "day": self.today,
                        "grade_state_shown": g.get("grade_state"),
                        "outcome_shown": g.get("outcome"),
                    }
                )
        return sent

    # ------------------------------------------------------------------ acknowledgements

    def acknowledgements(self) -> int:
        """A ✅ on an open anomaly's alert acknowledges it; the daily job restarts its reference period (§12.8)."""
        open_ = query(
            f"""
SELECT a.anomaly_id, a.slack_channel, a.slack_ts FROM {tbl(ANOMALIES)} a
LEFT JOIN {tbl(ACKNOWLEDGEMENTS)} k ON k.anomaly_id = a.anomaly_id
WHERE a.state = @open AND a.slack_ts IS NOT NULL AND k.anomaly_id IS NULL""",
            open=AnomalyState.OPEN.value,
        )
        emoji = self.s.alerts.ack_emoji
        for a in open_:
            users = slack.reactions(a["slack_channel"], a["slack_ts"]).get(emoji) or []
            if not users:
                continue
            slack.post(a["slack_channel"], messages.acknowledged(users[0], self.today), thread_ts=a["slack_ts"])
            self.acks.append(
                {
                    "anomaly_id": a["anomaly_id"],
                    "acknowledged_by": users[0],
                    "ack_day": self.today,
                    "ack_hour": self.hour,
                    "replied": True,
                }
            )
        return len(self.acks)

    # ------------------------------------------------------------------ the run

    def execute(self) -> dict[str, Any]:
        runs = self.check_runs()
        log_hour = self.check_log_hour()
        high = self.high_cluster_alerts()
        acks = self.acknowledgements()
        write(ALERTS, self.alerts)
        write(ALERT_SESSIONS, self.alert_sessions)
        write(PIPELINE_HEALTH, self.health)
        write(ACKNOWLEDGEMENTS, self.acks)
        summary = {
            "runs_seen": runs,
            "health_rows": len(self.health),
            "log_hour_checked": log_hour is not None,
            "high_alerts": high,
            "health_alerts": sum(a["kind"] == AlertKind.PIPELINE_HEALTH for a in self.alerts),
            "acknowledged": acks,
        }
        safe_log.log("monitor_run", **summary)
        return summary


def run(now: datetime | None = None) -> dict[str, Any]:
    return Monitor(now or utc_now()).execute()
