"""Release impact (§10.3): the 5 complete weekdays before a change against the 5 after it, per metric and channel."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from conversation_analyzer.bq.client import fq, query, tbl
from conversation_analyzer.bq.schema import CHANGE_EVENTS, METRICS_DAILY
from conversation_analyzer.reporting.metrics import CHANNELS
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import (
    FAILURE_RATE_CODES,
    ChangeKind,
    DayKind,
    GateVerdict,
    ReleaseVerdict,
    SliceKind,
    failure_rate_metric,
)

# Changes that are releases. Indexer runs are hourly and judge changes move the measure, not quality; both still
# confound a release that falls in the same days.
RELEASE_KINDS = (
    ChangeKind.PROMPT,
    ChangeKind.DATA_STORE,
    ChangeKind.DOCUMENT,
    ChangeKind.MODEL,
    ChangeKind.ENGINE,
    ChangeKind.AGENT,
    ChangeKind.CONNECTOR,
)
CONFOUNDING_KINDS = (*RELEASE_KINDS, ChangeKind.JUDGE, ChangeKind.PARALLEL_RUN_END, ChangeKind.AQR_REBASE)
METRICS = ("AQR_STANDARDIZED", *(failure_rate_metric(c) for c in FAILURE_RATE_CODES))
LOOKBACK_DAYS = 31  # a change is followed until its 5 weekdays after are complete


def verdict(metric: str, before: float, after: float, se: float) -> str:
    """Improved or regressed only when the difference is larger than chance explains (§10.3)."""
    z = get_settings().metrics.release_impact.z
    diff = after - before
    if se == 0 or abs(diff) <= z * se:
        return ReleaseVerdict.NO_DETECTABLE_CHANGE.value
    better = diff > 0 if metric == "AQR_STANDARDIZED" else diff < 0
    return (ReleaseVerdict.IMPROVED if better else ReleaseVerdict.REGRESSED).value


def _pooled(days: list[dict[str, Any]]) -> tuple[float | None, float]:
    den = sum(d["denominator"] or 0.0 for d in days)
    return (sum(d["numerator"] or 0.0 for d in days) / den if den else None), den


def gate_verdicts(event_ids: list[str]) -> dict[str, str]:
    """The evaluator's latest release gate verdict per change event (§10.2, §12.11); other values are ignored."""
    if not event_ids:
        return {}
    rows = query(
        f"""
SELECT change_id, verdict FROM {fq("evals", "gate_results")}
WHERE change_id IN UNNEST(@ids) AND verdict IN UNNEST(@verdicts) ORDER BY created_at""",
        ids=event_ids,
        verdicts=[v.value for v in GateVerdict],
    )
    return {r["change_id"]: r["verdict"] for r in rows}


def impact(day: date, computed: date) -> list[dict[str, Any]]:
    weekdays = get_settings().metrics.release_impact.weekdays
    events = query(
        f"SELECT event_id, day, kind FROM {tbl(CHANGE_EVENTS)} WHERE day BETWEEN @a AND @d",
        a=day - timedelta(days=LOOKBACK_DAYS + 14),
        d=day,
    )
    rows = query(
        f"""
SELECT day, metric, channel, numerator, denominator, judge_version FROM {tbl(METRICS_DAILY)}
WHERE slice_kind = @all AND day_kind = @weekday AND NOT incomplete AND metric IN UNNEST(@metrics)
  AND day BETWEEN @a AND @d""",
        all=SliceKind.ALL.value,
        weekday=DayKind.WEEKDAY.value,
        metrics=list(METRICS),
        a=day - timedelta(days=LOOKBACK_DAYS + 14),
        d=day,
    )
    series: dict[tuple[str, str], dict[date, dict[str, Any]]] = defaultdict(dict)
    for r in rows:
        series[(r["metric"], r["channel"])][r["day"]] = r
    gates = gate_verdicts([e["event_id"] for e in events])
    complete_days = sorted({r["day"] for r in rows})
    out = []
    for e in events:
        if e["kind"] not in RELEASE_KINDS or e["day"] < day - timedelta(days=LOOKBACK_DAYS):
            continue
        before = [d for d in complete_days if d < e["day"]][-weekdays:]
        after = [d for d in complete_days if d > e["day"]][:weekdays]
        window = (before[0] if before else e["day"], after[-1] if after else day)
        confounding = sorted(
            o["event_id"]
            for o in events
            if o["event_id"] != e["event_id"] and o["kind"] in CONFOUNDING_KINDS and window[0] <= o["day"] <= window[1]
        )
        for metric in METRICS:
            for channel in CHANNELS:
                s = series.get((metric, channel), {})
                b = [s[d] for d in before if d in s]
                a = [s[d] for d in after if d in s]
                row = {
                    "event_id": e["event_id"],
                    "metric": metric,
                    "channel": channel,
                    "change_day": e["day"],
                    "confounding_events": confounding,
                    "computed_day": computed,
                    "gate_verdict": gates.get(e["event_id"]),
                }
                if len(b) < weekdays or len(a) < weekdays:
                    out.append({**row, "verdict": ReleaseVerdict.WAITING.value})
                    continue
                p1, n1 = _pooled(b)
                p2, n2 = _pooled(a)
                if p1 is None or p2 is None:
                    continue
                se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
                same_judge = len({d["judge_version"] for d in b + a}) == 1
                result = verdict(metric, p1, p2, se)
                if confounding or not same_judge:
                    result = ReleaseVerdict.CONFOUNDED.value
                out.append(
                    {
                        **row,
                        "before_value": p1,
                        "after_value": p2,
                        "diff": p2 - p1,
                        "se": se,
                        "n_before": int(n1),
                        "n_after": int(n2),
                        "verdict": result,
                        "same_judge": same_judge,
                    }
                )
    return out
