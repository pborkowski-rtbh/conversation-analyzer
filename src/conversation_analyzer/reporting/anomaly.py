"""The daily anomaly check (§8.7): a sudden jump out of the reference band, or a slow drift found by CUSUM."""

from __future__ import annotations

import hashlib
import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from conversation_analyzer.bq.client import query, tbl
from conversation_analyzer.bq.schema import ACKNOWLEDGEMENTS, ANOMALIES, METRICS_DAILY
from conversation_analyzer.reporting.metrics import BASELINE_DAYS, CHANNELS, day_kind
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import ANOMALY_METRICS, AnomalyKind, AnomalyState, SliceKind

HISTORY_DAYS = 120  # how far back the drift sum is rebuilt; it restarts at an acknowledgement anyway
PIPELINE_METRICS = ("COVERAGE",)  # checked from the first day; quality metrics only after the baseline (§8.6)


def anomaly_id(metric: str, channel: str, day: date) -> str:
    return "anom-" + hashlib.sha256(f"{metric}|{channel}|{day}".encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Day:
    day: date
    value: float
    numerator: float
    denominator: float
    n: int


@dataclass(frozen=True)
class Reference:
    value: float
    noise: float
    days: int


def reference(days: list[Day], n_today: float) -> Reference | None:
    """Pooled rate of the reference days; noise = the larger of chance for today's size and the days' own spread."""
    cfg = get_settings().metrics.anomaly
    if len(days) < cfg.min_reference_days:
        return None
    den = sum(d.denominator for d in days)
    if not den:
        return None
    value = sum(d.numerator for d in days) / den
    chance = math.sqrt(max(value * (1 - value), 0.0) / n_today) if n_today else 0.0
    spread = statistics.stdev([d.value for d in days]) if len(days) > 1 else 0.0
    noise = max(chance, spread)
    return Reference(value, noise, len(days)) if noise > 0 else None


@dataclass
class Finding:
    kind: str
    day: Day
    ref: Reference
    cusum: float


def find(history: list[Day], today: date, restart: date | None, blocked_from: date | None) -> Finding | None:
    """Check `today` against its series; days before `restart` are forgotten, days from `blocked_from` never count."""
    cfg = get_settings().metrics.anomaly
    usable = [d for d in history if (restart is None or d.day >= restart) and d.day <= today]
    up = down = 0.0
    found: Finding | None = None
    for i, d in enumerate(usable):
        earlier = [e for e in usable[:i] if blocked_from is None or e.day < blocked_from][-cfg.reference_days :]
        ref = reference(earlier, d.denominator)
        if ref is None:
            continue
        z = (d.value - ref.value) / ref.noise
        up = max(0.0, up + z - cfg.cusum_slack)
        down = max(0.0, down - z - cfg.cusum_slack)
        if d.day == today:
            if abs(z) > cfg.jump_noise_levels:
                found = Finding(AnomalyKind.JUMP.value, d, ref, max(up, down))
            elif max(up, down) > cfg.cusum_limit:
                found = Finding(AnomalyKind.DRIFT.value, d, ref, max(up, down))
    return found


def series(metric: str, channel: str, day: date) -> list[Day]:
    """Complete days of the same kind, with enough turns, oldest first (§8.7)."""
    cfg = get_settings().metrics.anomaly
    rows = query(
        f"""
SELECT day, value, numerator, denominator, n_turns FROM {tbl(METRICS_DAILY)}
WHERE metric = @m AND channel = @c AND slice_kind = @all AND day_kind = @kind AND NOT incomplete
  AND value IS NOT NULL AND day BETWEEN @a AND @d
ORDER BY day""",
        m=metric,
        c=channel,
        all=SliceKind.ALL.value,
        kind=day_kind(day),
        a=day - timedelta(days=HISTORY_DAYS),
        d=day,
    )
    return [
        Day(r["day"], r["value"], r["numerator"] or 0.0, r["denominator"] or 0.0, r["n_turns"] or 0)
        for r in rows
        if (r["n_turns"] or 0) >= cfg.min_day_turns and r["denominator"]
    ]


class AnomalyCheck:
    def __init__(self, day: date) -> None:
        self.day = day
        self.s = get_settings()

    def stored(self) -> list[dict[str, Any]]:
        return query(
            f"""
SELECT a.anomaly_id, a.metric, a.channel, a.kind, a.day, a.opened_day, a.value, a.reference_value, a.noise,
       a.band_low, a.band_high, a.cusum, a.state, a.change_events, a.explained, a.alert_id, a.slack_channel,
       a.slack_ts, a.acknowledged_day, k.ack_day
FROM {tbl(ANOMALIES)} a LEFT JOIN {tbl(ACKNOWLEDGEMENTS)} k ON k.anomaly_id = a.anomaly_id"""
        )

    def run(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Acknowledged anomalies closed, then new findings; returns (rows to write, new anomalies)."""
        updates: list[dict[str, Any]] = []
        anomalies = self.stored()
        for a in anomalies:
            if a["state"] == AnomalyState.OPEN and a["ack_day"]:
                a.update(state=AnomalyState.ACKNOWLEDGED.value, acknowledged_day=a["ack_day"])
                updates.append(a)
        go_live = self.s.metrics.go_live_day
        baseline_over = go_live is not None and self.day >= go_live + timedelta(days=BASELINE_DAYS)
        new = []
        for metric in ANOMALY_METRICS:
            if metric not in PIPELINE_METRICS and not baseline_over:
                continue
            for channel in CHANNELS:
                mine = [a for a in anomalies if a["metric"] == metric and a["channel"] == channel]
                if any(a["state"] == AnomalyState.OPEN for a in mine):
                    continue  # one alert per lasting change: nothing new until it is acknowledged
                acks = [a["acknowledged_day"] for a in mine if a["acknowledged_day"]]
                f = find(series(metric, channel, self.day), self.day, max(acks) if acks else None, None)
                if f is not None:
                    new.append(self.row(metric, channel, f))
        for a in updates:
            a.pop("ack_day", None)
        return updates + new, new

    def row(self, metric: str, channel: str, f: Finding) -> dict[str, Any]:
        band = self.s.metrics.anomaly.jump_noise_levels * f.ref.noise
        aid = anomaly_id(metric, channel, self.day)
        return {
            "anomaly_id": aid,
            "metric": metric,
            "channel": channel,
            "kind": f.kind,
            "day": self.day,
            "opened_day": self.day,
            "value": f.day.value,
            "reference_value": f.ref.value,
            "noise": f.ref.noise,
            "band_low": f.ref.value - band,
            "band_high": f.ref.value + band,
            "cusum": f.cusum,
            "state": AnomalyState.OPEN.value,
            "change_events": [],
            "explained": False,
            "alert_id": "alert-" + aid.removeprefix("anom-"),
            "slack_channel": None,
            "slack_ts": None,
            "acknowledged_day": None,
        }
