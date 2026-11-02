"""quality-daily (§12.9): change events, incomplete days, the day's metrics, anomalies, release impact and alerts."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from conversation_analyzer import safe_log
from conversation_analyzer.bq.client import query, tbl, write
from conversation_analyzer.bq.schema import ANOMALIES, CHANGE_EVENTS, JUDGE_QUALITY, METRICS_DAILY, RELEASE_IMPACT
from conversation_analyzer.errors import AnalyzerError, report
from conversation_analyzer.judge.version import metric_version
from conversation_analyzer.reporting import changes, judge_quality, messages, release, slack
from conversation_analyzer.reporting.anomaly import AnomalyCheck
from conversation_analyzer.reporting.completeness import check_hours
from conversation_analyzer.reporting.metrics import CHANNELS, DayMetrics
from conversation_analyzer.settings import get_settings, now
from conversation_analyzer.vocab import ALL, AnomalyState


class Daily:
    def __init__(self, day: date, at: datetime) -> None:
        self.day = day
        self.today = at.date()
        self.s = get_settings()
        self.version = metric_version(day).version_id

    def completeness(self) -> tuple[dict[str, bool], dict[str, int]]:
        """Every hour of the day checked again (§8.2); a channel with a gap hour makes its day incomplete."""
        start = datetime.combine(self.day, time(), UTC)
        checks = check_hours([start + timedelta(hours=h) for h in range(24)])
        gaps = {ch: 0 for ch in CHANNELS}
        for c in checks:
            gaps[c.channel] += c.gap
        gaps[ALL] = len({c.hour for c in checks if c.gap})
        return {ch: gaps[ch] > 0 for ch in CHANNELS}, gaps

    def change_events_near(self, anomaly_day: date) -> list[str]:
        """Change events of the 48 hours before the end of the anomaly's day, by the hour (§8.7)."""
        hours = self.s.metrics.anomaly.change_event_lookback_hours
        end = datetime.combine(anomaly_day + timedelta(days=1), time(), UTC)
        events = changes.events_between(anomaly_day - timedelta(days=hours // 24 + 1), anomaly_day)
        out = []
        for e in events:
            at = datetime.combine(e["day"], time(e["hour"] or 0), UTC)
            if end - timedelta(hours=hours) <= at < end:
                out.append(e["event_id"])
        return out

    def alert(self, a: dict[str, Any]) -> None:
        """Post the anomaly; a failed post is retried by the next run, the anomaly stays stored either way."""
        a["change_events"] = a["change_events"] or self.change_events_near(a["day"])
        a["explained"] = bool(a["change_events"])
        try:
            channel, ts = slack.post(self.s.alerts.quality_channel, messages.anomaly(a))
        except AnalyzerError as exc:
            report(exc)
            return
        a.update(slack_channel=channel, slack_ts=ts)

    def unsent(self) -> list[dict[str, Any]]:
        rows = query(
            f"SELECT * EXCEPT(change_events), ARRAY_TO_STRING(change_events, ',') AS events FROM {tbl(ANOMALIES)} "
            "WHERE state = @open AND slack_ts IS NULL",
            open=AnomalyState.OPEN.value,
        )
        for r in rows:
            r["change_events"] = [e for e in (r.pop("events") or "").split(",") if e]
        return rows

    def alerts(self, rows: list[dict[str, Any]], new: list[dict[str, Any]]) -> int:
        """Alert new anomalies and retry earlier unsent ones, then store them all; returns the alerts sent."""
        retry = [a for a in self.unsent() if a["anomaly_id"] not in {n["anomaly_id"] for n in new}]
        for a in [*new, *retry]:
            self.alert(a)
        write(ANOMALIES, rows + retry)
        return sum(1 for a in [*new, *retry] if a["slack_ts"])

    def execute(self) -> dict[str, Any]:
        events = changes.collect(self.day, self.today)
        write(CHANGE_EVENTS, events)
        incomplete, gaps = self.completeness()
        metrics = DayMetrics(self.day, self.version, incomplete, gaps).rows()
        write(METRICS_DAILY, metrics)
        write(JUDGE_QUALITY, judge_quality.measures(self.day, self.version))
        rows, new = AnomalyCheck(self.day).run()
        impact = release.impact(self.day, self.today)
        write(RELEASE_IMPACT, impact)
        sent = self.alerts(rows, new)
        summary = {
            "change_events": len(events),
            "metric_rows": len(metrics),
            "incomplete_channels": sum(incomplete.values()),
            "anomalies": len(new),
            "alerts_sent": sent,
            "release_rows": len(impact),
        }
        safe_log.log("daily_run", **summary)
        return summary


def run(day: str | None = None) -> dict[str, Any]:
    at = now()
    return Daily(date.fromisoformat(day) if day else at.date() - timedelta(days=1), at).execute()
