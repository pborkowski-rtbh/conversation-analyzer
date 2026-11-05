"""Mocked rows for the metrics dataset (emulator only): eight weeks with a regression, a fix and an open anomaly."""

from __future__ import annotations

import hashlib
import math
import random
from datetime import date, timedelta
from typing import Any

from conversation_analyzer.bq import schema as sc
from conversation_analyzer.bq.client import insert_fresh, query, tbl
from conversation_analyzer.reporting.metrics import day_kind
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import (
    ALL,
    FAILURE_RATE_CODES,
    FAMILY,
    MERGED_OTHER,
    Channel,
    DepartmentFamily,
    FailureCode,
    Intent,
    failure_rate_metric,
    owner_of,
    topics,
)

JUDGE_VERSION = "v4-mock"
DAYS = 56
CHANNEL_SHARE = {Channel.WEB_UI.value: 0.72, Channel.SLACK_MCP.value: 0.28}
FAILURE_SHARE = {  # share of all assessed turns with this primary failure, before the regression
    FailureCode.NOT_IN_CITED_SOURCES: 0.045,
    FailureCode.CHUNKING_ISSUE: 0.02,
    FailureCode.OUTDATED_SOURCE: 0.03,
    FailureCode.CONFLICTING_SOURCES: 0.012,
    FailureCode.CONTRADICTED_CLAIM: 0.008,
    FailureCode.UNSUPPORTED_CLAIM: 0.035,
    FailureCode.REASONING_ERROR: 0.01,
    FailureCode.INCOMPLETE_ANSWER: 0.04,
    FailureCode.MISUNDERSTOOD_QUERY: 0.015,
    FailureCode.PRESENTATION_ISSUE: 0.01,
    FailureCode.UNGROUNDED_INTERNAL_ANSWER: 0.012,
    FailureCode.AMBIGUOUS_QUESTION: 0.02,
    FailureCode.OUT_OF_SCOPE: 0.015,
    FailureCode.AGENT_OR_TOOL_ERROR: 0.005,
}
INTENT_SHARE = {
    Intent.FACT_LOOKUP: 0.34,
    Intent.HOW_TO: 0.24,
    Intent.TROUBLESHOOTING: 0.12,
    Intent.PEOPLE_LOOKUP: 0.06,
    Intent.DATA_QUESTION: 0.08,
    Intent.GENERAL_TASK: 0.1,
    Intent.CHITCHAT: 0.04,
    Intent.OTHER: 0.02,
}
DEPARTMENT_SHARE = {
    DepartmentFamily.ENGINEERING: 0.36,
    DepartmentFamily.CAMPAIGNS: 0.25,
    DepartmentFamily.COMMERCIAL: 0.2,
    DepartmentFamily.CORPORATE: 0.12,
    DepartmentFamily.OTHER: 0.01,
    DepartmentFamily.UNKNOWN: 0.06,
}


def _id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-" + hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:16]


class Mock:
    """A deterministic story: the outdated-source regression on day -21 (document change), fixed on day -11."""

    def __init__(self, today: date, seed: int = 7) -> None:
        self.today = today
        self.first = today - timedelta(days=DAYS)
        self.rng = random.Random(seed)
        self.regression_day = today - timedelta(days=21)
        self.fix_day = today - timedelta(days=11)
        self.prompt_day = today - timedelta(days=4)
        self.incomplete_day = today - timedelta(days=17)
        self.data_stores = [d.id for d in get_settings().data_stores]

    def days(self) -> list[date]:
        return [self.first + timedelta(days=n) for n in range(DAYS)]

    def volume(self, day: date) -> int:
        base = 900 if day_kind(day) == "WEEKDAY" else 110
        growth = 1 + 0.004 * (day - self.first).days
        return int(base * growth * self.rng.uniform(0.9, 1.1))

    def regression(self, day: date) -> float:
        """Extra outdated-source share: 0 before the regression, +5 points while it lasts, fading after the fix."""
        if day < self.regression_day:
            return 0.0
        if day < self.fix_day:
            return 0.05
        return 0.05 * math.exp(-(day - self.fix_day).days / 2.5)

    def failure_shares(self, day: date, scale: float = 1.0) -> dict[FailureCode, float]:
        out = {c: s * scale * self.rng.uniform(0.75, 1.25) for c, s in FAILURE_SHARE.items()}
        out[FailureCode.OUTDATED_SOURCE] += self.regression(day) * scale
        if day >= self.prompt_day:  # the prompt change shortens answers a little
            out[FailureCode.INCOMPLETE_ANSWER] *= 0.7
        return out

    # ---------------------------------------------------------------- quality_metrics_daily

    def row(self, day, channel, metric, kind, value, num=None, den=None, n=None, merged=False) -> dict[str, Any]:
        return {
            "day": day,
            "day_kind": day_kind(day),
            "channel": channel,
            "metric": metric,
            "slice_kind": kind[0],
            "slice_value": kind[1],
            "value": value,
            "numerator": num,
            "denominator": den,
            "n_turns": n,
            "incomplete": day == self.incomplete_day,
            "merged": merged,
            "judge_version": JUDGE_VERSION,
        }

    def quality(self, day: date, channel: str, kind: tuple[str, str], n: int, scale: float) -> list[dict[str, Any]]:
        """Every quality metric of one slice of n turns; scale moves the slice's failure level."""
        shares = self.failure_shares(day, scale)
        failing = min(sum(shares.values()), 0.9)
        knowledge = round(n * self.rng.uniform(0.74, 0.8))
        verifiable = round(knowledge * self.rng.uniform(0.82, 0.88))
        aqr = max(0.0, min(1.0, 1 - failing * 1.15))
        good = round(verifiable * aqr)
        own = round(knowledge * self.rng.uniform(0.68, 0.72))
        earlier = round(knowledge * self.rng.uniform(0.08, 0.1))
        contradicted = round(n * shares[FailureCode.CONTRADICTED_CLAIM])
        spans = round(n * 3.2)
        merged = kind[1] == MERGED_OTHER

        def rate(metric: str, num: float, den: float) -> dict[str, Any]:
            return self.row(day, channel, metric, kind, num / den if den else None, float(num), float(den), n, merged)

        out = [
            rate("AQR_RAW", good, verifiable),
            rate("NOT_VERIFIABLE_SHARE", knowledge - verifiable, knowledge),
            rate("EVIDENCE_OWN_SHARE", own, knowledge),
            rate("EVIDENCE_EARLIER_SHARE", earlier, knowledge),
            rate("EVIDENCE_NONE_SHARE", knowledge - own - earlier, knowledge),
            self.row(
                day, channel, "CONTRADICTED_COUNT", kind, float(contradicted), float(contradicted), None, n, merged
            ),
            rate("CONTRADICTED_SHARE", contradicted, knowledge),
            rate("UNSUPPORTED_SHARE", round(spans * shares[FailureCode.UNSUPPORTED_CLAIM] * 0.6), spans),
            rate("FLAGGED_SHARE", round(n * failing * 0.8), n),
            rate("NEGATIVE_REACTION_RATE", round(n * 0.35 * (0.08 + failing * 0.4)), round(n * 0.35)),
        ]
        out += [rate(failure_rate_metric(c), round(n * shares[c]), n) for c in FAILURE_RATE_CODES]
        if kind == ("ALL", ALL):
            out.append(rate("AQR_STANDARDIZED", round(verifiable * min(1.0, aqr + 0.006)), verifiable))
        return out

    def slices(self) -> list[tuple[tuple[str, str], float, float]]:
        """(slice, share of turns, failure scale) of every slice the daily job writes for one channel."""
        out: list[tuple[tuple[str, str], float, float]] = []
        for intent, share in INTENT_SHARE.items():
            out.append((("INTENT", intent.value), share, {"PEOPLE_LOOKUP": 1.4, "CHITCHAT": 0.4}.get(intent, 1.0)))
        tops = [t for t in topics() if t != "OTHER"]
        weights = [1 / (i + 1.5) for i in range(len(tops))]
        total = sum(weights) * 1.12
        for i, topic in enumerate(tops):
            scale = 0.6 + (i % 5) * 0.2
            out.append((("TOPIC", topic), weights[i] / total, scale))
        out.append((("TOPIC", "OTHER"), 0.12 / 1.12, 1.3))
        for dep, share in DEPARTMENT_SHARE.items():
            if dep is DepartmentFamily.OTHER:
                continue  # under the minimum slice size every day: merged below
            out.append((("DEPARTMENT", dep.value), share, {"ENGINEERING": 0.85, "COMMERCIAL": 1.2}.get(dep, 1.0)))
        out.append((("DEPARTMENT", MERGED_OTHER), DEPARTMENT_SHARE[DepartmentFamily.OTHER], 1.0))
        for fam, share in {"FACT": 0.42, "PROCEDURE": 0.36, "PEOPLE": 0.06, "TASK": 0.16}.items():
            out.append((("INTENT_FAMILY", fam), share, 1.0))
        for fam, share in {"ENGINEERING": 0.55, "COMPANY": 0.33, "NONE": 0.12}.items():
            out.append((("DATA_STORE_FAMILY", fam), share, 1.0))
        return out

    def metrics_daily(self) -> list[dict[str, Any]]:
        out = []
        for day in self.days():
            total = self.volume(day)
            per_channel = {ch: round(total * s) for ch, s in CHANNEL_SHARE.items()}
            per_channel[ALL] = sum(per_channel.values())
            for ch, n in per_channel.items():
                scale = {Channel.SLACK_MCP.value: 1.25, Channel.WEB_UI.value: 0.92}.get(ch, 1.0)
                out += self.quality(day, ch, ("ALL", ALL), n, scale)
                for kind, share, slice_scale in self.slices():
                    sn = round(n * share)
                    if sn >= get_settings().metrics.min_slice_size:
                        out += self.quality(day, ch, kind, sn, scale * slice_scale)
                out += self.pipeline(day, ch, n)
            out += self.day_totals(day, per_channel)
        return out

    def pipeline(self, day: date, ch: str, n: int) -> list[dict[str, Any]]:
        missed = 0 if self.rng.random() < 0.8 else self.rng.randint(1, 12)
        too_large = round(n * self.rng.uniform(0.001, 0.005))
        gap = 3.0 if day == self.incomplete_day else 0.0
        if day == self.incomplete_day:
            missed += round(n * 0.12)
        row = self.row
        out = [
            row(day, ch, "VOLUME", ("ALL", ALL), float(n), float(n), None, n),
            row(day, ch, "COVERAGE", ("ALL", ALL), (n - missed) / n, float(n - missed), float(n), n),
            row(day, ch, "TOO_LARGE_SHARE", ("ALL", ALL), too_large / n, float(too_large), float(n)),
            row(day, ch, "MISSED_COUNT", ("ALL", ALL), float(missed), float(missed)),
            row(day, ch, "LOG_GAP_HOURS", ("ALL", ALL), gap, gap),
            row(day, ch, "PACE_EXCLUDED_COUNT", ("ALL", ALL), 0.0, 0.0),
        ]
        if ch != Channel.SLACK_MCP.value:
            web = round(n * (1 if ch == Channel.WEB_UI.value else CHANNEL_SHARE[Channel.WEB_UI.value]))
            dislikes = round(web * (0.012 + self.regression(day) * 0.2) * self.rng.uniform(0.7, 1.3))
            out += [
                row(day, ch, "DISLIKE_COUNT", ("ALL", ALL), float(dislikes), float(dislikes)),
                row(day, ch, "DISLIKE_RATE", ("ALL", ALL), dislikes / web, float(dislikes), float(web), web),
            ]
        return out

    def day_totals(self, day: date, per_channel: dict[str, int]) -> list[dict[str, Any]]:
        row = self.row
        resumed = round(per_channel[ALL] * 0.06)
        without = round(resumed * self.rng.uniform(0.02, 0.06))
        idle = resumed - without
        continued = round(idle * self.rng.uniform(0.26, 0.36))
        oldest = self.rng.uniform(25, 55) + (140 if day == self.incomplete_day else 0)
        out = [
            row(day, ALL, "RESUMED_WITHOUT_TEXT", ("ALL", ALL), without / resumed, float(without), float(resumed)),
            row(day, ALL, "RESUMED_AND_CONTINUED", ("ALL", ALL), continued / idle, float(continued), float(idle)),
            row(day, ALL, "OLDEST_WAITING_MINUTES", ("ALL", ALL), oldest, oldest),
        ]
        if day <= self.today - timedelta(days=3):  # Google reports engine usage about 3 days late
            users = round(per_channel[ALL] / 3.1)
            out += [
                row(day, ALL, "ACTIVE_USERS", ("ALL", ALL), float(users), float(users)),
                row(day, ALL, "RETENTION_7D", ("ALL", ALL), self.rng.uniform(0.55, 0.62)),
            ]
        return out

    # ---------------------------------------------------------------- the other metrics tables

    def pipeline_health(self) -> list[dict[str, Any]]:
        out = []
        for day in self.days() + [self.today]:
            for hour in range(24 if day < self.today else 12):
                eligible = self.rng.randint(5, 70) if 6 <= hour <= 19 else self.rng.randint(0, 6)
                failed_run = day == self.incomplete_day and hour in (9, 10, 11)
                missed = eligible if failed_run else (0 if self.rng.random() < 0.95 else 1)
                checks = ["RUN_FAILED", "LOG_GAP"] if failed_run else []
                out.append(
                    {
                        "day": day,
                        "kind": "RUN",
                        "run_id": _id("run", day, hour),
                        "hour": hour,
                        "channel": ALL,
                        "run_status": "FAILED" if failed_run else "OK",
                        "coverage": (eligible - missed) / eligible if eligible else 1.0,
                        "eligible": eligible,
                        "assessed": eligible - missed,
                        "too_large": 0,
                        "missed": missed,
                        "failed": 0,
                        "oldest_waiting_minutes": self.rng.uniform(5, 50) + (180 if failed_run else 0),
                        "window_margin_minutes": self.rng.uniform(40, 80),
                        "log_records": eligible * 3,
                        "log_expected": eligible * 3.0,
                        "log_gap": failed_run,
                        "checks_fired": checks,
                        "no_run_expected": False,
                    }
                )
        return out

    def change_events(self) -> list[dict[str, Any]]:
        repo = get_settings().github.repositories[0]
        base = {
            "hour": 10,
            "repository": None,
            "commit_sha": None,
            "execution": None,
            "judge_version": None,
            "doc_id": None,
            "data_store": None,
            "clusters": [],
        }
        events = [
            (self.regression_day, "INDEXER", "INDEXER", {"execution": "confluence-indexer-mock-1"}),
            (self.regression_day, "LOG", "DATA_STORE", {"data_store": "rtb-crj-confluence"}),
            (self.fix_day, "MANUAL", "DOCUMENT", {"doc_id": "CONF-123456", "data_store": "rtb-crj-confluence"}),
            (self.prompt_day, "GITHUB", "PROMPT", {"repository": repo, "commit_sha": "3f9c2a1b7d"}),
            (self.first + timedelta(days=9), "GITHUB", "MODEL", {"repository": repo, "commit_sha": "a01b2c3d4e"}),
            (self.first + timedelta(days=30), "LOG", "AGENT", {}),
            (self.first + timedelta(days=14), "JUDGE", "JUDGE", {"judge_version": JUDGE_VERSION}),
        ]
        return [
            {
                **base,
                **extra,
                "event_id": _id("evt", day, kind),
                "day": day,
                "source": src,
                "kind": kind,
                "recorded_day": day,
            }
            for day, src, kind, extra in events
        ]

    def release_impact(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        verdicts = {
            "INDEXER": ("REGRESSED", -0.048),
            "DOCUMENT": ("IMPROVED", 0.041),
            "PROMPT": ("WAITING", 0.006),
            "MODEL": ("NO_DETECTABLE_CHANGE", 0.004),
            "AGENT": ("NO_DETECTABLE_CHANGE", -0.003),
            "DATA_STORE": ("CONFOUNDED", -0.045),
        }
        out = []
        for e in [e for e in events if e["kind"] != "JUDGE"]:  # a judge change is not a release
            verdict, diff = verdicts[e["kind"]]
            for ch in (ALL, Channel.WEB_UI.value):
                before = 0.79
                out.append(
                    {
                        "event_id": e["event_id"],
                        "metric": "AQR_STANDARDIZED",
                        "channel": ch,
                        "change_day": e["day"],
                        "before_value": before,
                        "after_value": before + diff,
                        "diff": diff,
                        "se": 0.012,
                        "n_before": 3800,
                        "n_after": 0 if verdict == "WAITING" else 3600,
                        "verdict": verdict,
                        "confounding_events": [],
                        "same_judge": True,
                        "computed_day": self.today - timedelta(days=1),
                        "gate_verdict": "PASS" if e["kind"] in ("PROMPT", "MODEL") else None,
                    }
                )
        return out

    def anomalies(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        caused = [e["event_id"] for e in events if e["day"] == self.regression_day]
        common = {
            "channel": ALL,
            "noise": 0.006,
            "cusum": None,
            "alert_id": None,
            "slack_channel": None,
            "slack_ts": None,
        }
        return [
            {
                **common,
                "anomaly_id": _id("anom", 1),
                "metric": failure_rate_metric(FailureCode.OUTDATED_SOURCE),
                "kind": "JUMP",
                "day": self.regression_day + timedelta(days=1),
                "opened_day": self.regression_day,
                "value": 0.081,
                "reference_value": 0.03,
                "band_low": 0.018,
                "band_high": 0.042,
                "state": "ACKNOWLEDGED",
                "change_events": caused,
                "explained": True,
                "acknowledged_day": self.regression_day + timedelta(days=1),
            },
            {
                **common,
                "anomaly_id": _id("anom", 2),
                "metric": "AQR_STANDARDIZED",
                "kind": "JUMP",
                "day": self.regression_day + timedelta(days=1),
                "opened_day": self.regression_day,
                "value": 0.735,
                "reference_value": 0.79,
                "band_low": 0.766,
                "band_high": 0.814,
                "state": "ACKNOWLEDGED",
                "change_events": caused,
                "explained": True,
                "acknowledged_day": self.regression_day + timedelta(days=2),
            },
            {
                **common,
                "anomaly_id": _id("anom", 3),
                "metric": failure_rate_metric(FailureCode.UNSUPPORTED_CLAIM),
                "channel": Channel.SLACK_MCP.value,
                "kind": "DRIFT",
                "day": self.today - timedelta(days=1),
                "opened_day": self.today - timedelta(days=2),
                "value": 0.052,
                "reference_value": 0.035,
                "band_low": 0.022,
                "band_high": 0.048,
                "cusum": 4.6,
                "state": "OPEN",
                "change_events": [],
                "explained": False,
                "acknowledged_day": None,
            },
        ]

    def clusters(self) -> list[dict[str, Any]]:
        out = []
        mondays = [self.today - timedelta(days=self.today.weekday() + 7 * w) for w in range(8, 0, -1)]
        specs = [
            (FailureCode.OUTDATED_SOURCE, "rtb-crj-confluence", "CONF-123456", "CONFLUENCE", 14),
            (FailureCode.NOT_IN_CITED_SOURCES, "rtb-crj-knowhow", None, "KNOWHOW", 22),
            (FailureCode.INCOMPLETE_ANSWER, None, None, "BIZTECH", 18),
            (FailureCode.UNSUPPORTED_CLAIM, "rtb-crj-traffic-wiki", "TW-4471", "TRAFFIC_WIKI", 11),
            (FailureCode.CHUNKING_ISSUE, "rtb-crj-helpdesk-qa", "HDQA-0912", "HELPDESK_QA", 9),
            (FailureCode.AMBIGUOUS_QUESTION, None, None, "OTHER", 8),
            (FailureCode.CONFLICTING_SOURCES, "rtb-crj-inhouse", "INH-77", "INHOUSE", 6),
        ]
        for week in mondays:
            rows = []
            for code, ds, doc, topic, base in specs:
                n = base + self.rng.randint(-3, 3)
                if code is FailureCode.OUTDATED_SOURCE:
                    n = round(base * (1 + 30 * self.regression(week + timedelta(days=3))))
                weighted = n * 2 + self.rng.randint(0, 6)
                rows.append(
                    {
                        "week": week,
                        "cluster_id": _id("cluster", code, ds, doc),
                        "primary_failure": code.value,
                        "family": FAMILY[code].value,
                        "owner": owner_of(code).value,
                        "data_store": ds,
                        "doc_id": doc,
                        "uri": None,
                        "topic": topic,
                        "n_turns": n,
                        "n_high": round(n * 0.2),
                        "n_medium": round(n * 0.5),
                        "n_low": n - round(n * 0.2) - round(n * 0.5),
                        "weighted": weighted,
                        "rank": 0,
                        "prev_4w_avg": float(base),
                        "trend": (n - base) / base,
                        "state": "ACTIVE",
                        "experimental": False,
                        "fix_events": [],
                        "level_before_fix": None,
                        "weeks_below": 0,
                    }
                )
            for rank, r in enumerate(sorted(rows, key=lambda r: -r["weighted"]), start=1):
                r["rank"] = rank
            out += rows
        return out

    def judge_quality(self) -> list[dict[str, Any]]:
        out = []
        for day in self.days():
            for measure, lo, hi in (
                ("CANARY_AGREEMENT", 0.86, 0.95),
                ("STAGE2_CHANGE_RATE", 0.08, 0.16),
                ("DISLIKED_AQR", 0.35, 0.5),
                ("NOT_DISLIKED_AQR", 0.76, 0.82),
            ):
                out.append(
                    {
                        "day": day,
                        "measure": measure,
                        "field": "ALL",
                        "value": self.rng.uniform(lo, hi),
                        "n": self.rng.randint(20, 60),
                    }
                )
        return out


def seed(today: date) -> dict[str, int]:
    """Write every mocked table (they must be empty, as after make db-reset); returns rows written per table."""
    m = Mock(today)
    events = m.change_events()
    tables = {
        sc.METRICS_DAILY: m.metrics_daily(),
        sc.PIPELINE_HEALTH: m.pipeline_health(),
        sc.CHANGE_EVENTS: events,
        sc.RELEASE_IMPACT: m.release_impact(events),
        sc.ANOMALIES: m.anomalies(events),
        sc.PROBLEM_CLUSTERS: m.clusters(),
        sc.JUDGE_QUALITY: m.judge_quality(),
    }
    for table in tables:
        if query(f"SELECT COUNT(*) AS n FROM {tbl(table)}")[0]["n"]:
            raise RuntimeError("the metrics tables are not empty: run make db-reset first")
    return {table.name: insert_fresh(table, rows) for table, rows in tables.items()}
