"""Log completeness (§8.2): an hour's records per channel against the usual for that hour and weekday."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from conversation_analyzer.bq.client import fq, query
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import Channel


@dataclass(frozen=True)
class HourCheck:
    hour: datetime
    channel: str
    records: int
    expected: float | None  # median of the same hour 1-4 weeks back, on days with log data; None with fewer than 2
    gap: bool


def check_hours(hours: list[datetime]) -> list[HourCheck]:
    """One check per hour and channel; usual = the median of earlier weeks whose day has any log data."""
    if not hours:
        return []
    cfg = get_settings().metrics.log_gap
    first = min(hours) - timedelta(weeks=cfg.reference_weeks)
    rows = query(
        f"SELECT hour, day, channel, n_turns FROM {fq('log_views', 'quality_turn_counts_hourly')} "
        "WHERE day BETWEEN @a AND @b",
        a=first.date(),
        b=max(hours).date(),
    )
    counts: dict[tuple[datetime, str], int] = {}
    days_with_data: set[date] = set()
    for r in rows:
        h = r["hour"] if isinstance(r["hour"], datetime) else datetime.fromisoformat(str(r["hour"]))
        counts[(h, r["channel"])] = counts.get((h, r["channel"]), 0) + r["n_turns"]
        days_with_data.add(r["day"])
    out = []
    for hour in hours:
        for channel in Channel:
            references = [
                counts.get((h, channel.value), 0)
                for h in (hour - timedelta(weeks=k) for k in range(1, cfg.reference_weeks + 1))
                if h.date() in days_with_data
            ]
            records = counts.get((hour, channel.value), 0)
            expected = float(statistics.median(references)) if len(references) >= 2 else None
            gap = expected is not None and expected >= cfg.min_expected and records < cfg.min_ratio * expected
            out.append(HourCheck(hour, channel.value, records, expected, gap))
    return out
