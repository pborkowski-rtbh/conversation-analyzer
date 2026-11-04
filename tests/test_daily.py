"""quality-daily on the emulator and the stubs: change events, metrics, completeness, anomalies, release impact."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import httpx
import pytest

from conversation_analyzer.bq.client import client, query, tbl, write
from conversation_analyzer.bq.external import EVAL_GATE_RESULTS, EVAL_RESULTS
from conversation_analyzer.bq.schema import (
    ACKNOWLEDGEMENTS,
    ANOMALIES,
    CANARY_RESULTS,
    CHANGE_EVENTS,
    JUDGE_CHECKS,
    JUDGE_QUALITY,
    JUDGE_VERSIONS,
    METRICS_DAILY,
    RELEASE_IMPACT,
    RUNS,
    SEGMENTS,
)
from conversation_analyzer.devtools.synthetic import SynthTurn, change_row, insert_log, turn_rows
from conversation_analyzer.errors import AnalyzerError, LeakGuardError
from conversation_analyzer.judge.version import current
from conversation_analyzer.reporting import changes, daily, judge_quality, release
from conversation_analyzer.reporting.anomaly import AnomalyCheck
from conversation_analyzer.reporting.metrics import DayMetrics
from conversation_analyzer.reporting.record import record
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import ErrorClass
from tests import stored
from tests.conftest import rows, wipe

pytestmark = pytest.mark.emulator

DAY = date(2026, 10, 27)  # a Tuesday
NOON = datetime.combine(DAY, time(12), UTC)


def state(stubs: str) -> dict:
    return httpx.get(f"{stubs}/_test/state").json()


@pytest.fixture
def clean(emulator, stubs):
    wipe()
    return stubs


def log_turns(day: date, web: int, api: int, hour: int = 10) -> None:
    now = datetime.combine(day, time(hour, 30), UTC)
    turns = [
        SynthTurn(f"s-{c}-{i}", i * 0.1, "q", "a", channel=c) for c, n in (("web", web), ("api", api)) for i in range(n)
    ]
    insert_log([r for t in turns for r in turn_rows(t, now) if r["methodName"] == "StreamAssist"])


def test_change_events_from_every_source(clean):
    insert_log(
        [
            change_row("UpdateDataStore", 180, NOON, "rtb-crj-hr-house"),
            change_row("UpdateEngine", 120, NOON),
            change_row("UpdateDataStore", 60, NOON, "unknown-store"),
        ]
    )
    commit = {
        "sha": "a" * 40,
        "commit": {"committer": {"date": f"{DAY}T09:15:00Z"}, "message": "Fix prompt, fixes cluster-0123456789abcdef"},
    }
    old = {"sha": "b" * 40, "commit": {"committer": {"date": "2026-10-20T09:15:00Z"}, "message": "older"}}
    httpx.post(
        f"{clean}/_test/github/commits",
        json={"repository": "RTBHouse-OEET/aiel-infrastructure", "commits": [commit, old]},
    )
    httpx.post(
        f"{clean}/_test/cloudrun/executions",
        json={
            "job": "indexer-confluence",
            "executions": [
                {"name": "x/executions/indexer-confluence-abc12", "completionTime": f"{DAY}T03:10:00Z"},
                {"name": "x/executions/indexer-confluence-run01"},
            ],
        },
    )
    httpx.post(
        f"{clean}/_test/cloudrun/executions",
        json={
            "job": "other-job",
            "executions": [{"name": "x/executions/other-job-1", "completionTime": f"{DAY}T03:10:00Z"}],
        },
    )
    write(
        JUDGE_VERSIONS,
        [
            {"judge_version": "v2-0123456789ab", "first_used_day": DAY},
            {"judge_version": "v1-0123456789ab", "parallel_run_until": DAY - timedelta(days=1)},
        ],
    )
    events = changes.collect(DAY, DAY + timedelta(days=1))
    by_source: dict[str, list] = {}
    for e in events:
        by_source.setdefault(e["source"], []).append(e)
    log = sorted(by_source["LOG"], key=lambda e: e["hour"])
    assert [(e["kind"], e["data_store"]) for e in log] == [
        ("DATA_STORE", "rtb-crj-hr-house"),
        ("ENGINE", None),
        ("DATA_STORE", None),
    ]
    (gh,) = by_source["GITHUB"]
    assert gh["kind"] == "PROMPT" and gh["hour"] == 9 and gh["clusters"] == ["cluster-0123456789abcdef"]
    (idx,) = by_source["INDEXER"]
    assert idx["execution"] == "indexer-confluence-abc12" and idx["hour"] == 3
    assert {e["kind"] for e in by_source["JUDGE"]} == {"JUDGE", "PARALLEL_RUN_END"}
    write(CHANGE_EVENTS, events)
    assert len(rows(CHANGE_EVENTS)) == 7 and len(changes.events_between(DAY, DAY)) == 7


def test_record_writes_a_manual_event(clean):
    eid = record("DOCUMENT", "2026-10-26", 14, "hr_leave", "rtb-crj-hr-house", ["cluster-0123456789abcdef"])
    (row,) = rows(CHANGE_EVENTS)
    assert row["event_id"] == eid and row["source"] == "MANUAL" and row["clusters"] == ["cluster-0123456789abcdef"]
    assert row["day"] == date(2026, 10, 26) and row["hour"] == 14
    with pytest.raises(LeakGuardError):
        record("DOCUMENT", None, None, None, None, ["not a cluster id"])


def day_turns() -> list[dict]:
    t = stored.turn
    web = [t(DAY) for _ in range(20)]
    web += [
        t(
            DAY,
            relevance=5,
            groundedness=2,
            primary="CONTRADICTED_CLAIM",
            severity="HIGH",
            spans=(2, 1),
            reaction="CORRECTION",
        )
        for _ in range(4)
    ]
    web += [t(DAY, pace=True), t(DAY, pace=True), t(DAY, status="TOO_LARGE"), t(DAY, canary=True)]
    slack = [
        t(
            DAY,
            channel="SLACK_MCP",
            intent="HOW_TO",
            topic="CONFLUENCE",
            cited=(stored.CONF,),
            reaction="FOLLOW_UP",
            department="COMMERCIAL",
        )
        for _ in range(3)
    ]
    slack += [
        t(
            DAY,
            channel="SLACK_MCP",
            intent="HOW_TO",
            topic="OTHER",
            evidence="NONE",
            cited=(),
            spans=None,
            primary="UNGROUNDED_INTERNAL_ANSWER",
            severity="MEDIUM",
        )
        for _ in range(2)
    ]
    slack += [
        t(
            DAY,
            channel="SLACK_MCP",
            intent="HOW_TO",
            topic="CONFLUENCE",
            cited=(stored.CONF,),
            relevance=1,
            primary="MISUNDERSTOOD_QUERY",
            severity="MEDIUM",
            reaction="REPHRASE",
        ),
        t(DAY, channel="SLACK_MCP", status="FAILED"),
    ]
    return web + slack


def metric(rows_: list[dict], name: str, channel: str = "ALL", kind: str = "ALL", value: str = "ALL") -> dict:
    return next(
        r
        for r in rows_
        if (r["metric"], r["channel"], r["slice_kind"], r["slice_value"]) == (name, channel, kind, value)
    )


def test_day_metrics_from_stored_turns_and_the_log(clean):
    stored.store(day_turns())
    log_turns(DAY, web=28, api=7)
    write(RUNS, [{"run_id": "run-00000001", "run_day": DAY, "oldest_waiting_minutes": 42.0}])
    write(
        SEGMENTS,
        [
            {
                "session_key": stored.key(),
                "segment_no": 2,
                "first_day": DAY,
                "resumed": True,
                "previous_close_reason": "IDLE",
                "earlier_text_missing": False,
                "first_turn_relation": "FOLLOW_UP",
            },
            {
                "session_key": stored.key(),
                "segment_no": 2,
                "first_day": DAY,
                "resumed": True,
                "previous_close_reason": "FORCED",
                "earlier_text_missing": True,
            },
        ],
    )
    ok = {ch: False for ch in ("WEB_UI", "SLACK_MCP", "ALL")}
    out = DayMetrics(DAY, current().version_id, ok, {"WEB_UI": 0, "SLACK_MCP": 0, "ALL": 0}).rows()
    web_aqr = metric(out, "AQR_RAW", "WEB_UI")
    assert (web_aqr["numerator"], web_aqr["denominator"], web_aqr["n_turns"]) == (20, 24, 24)
    assert metric(out, "PACE_EXCLUDED_COUNT", "WEB_UI")["value"] == 2
    assert metric(out, "FLAGGED_SHARE", "WEB_UI")["value"] == pytest.approx(4 / 24)
    assert metric(out, "CONTRADICTED_COUNT", "WEB_UI")["value"] == 4
    assert metric(out, "FAILURE_RATE_CONTRADICTED_CLAIM", "WEB_UI")["value"] == pytest.approx(4 / 24)
    assert metric(out, "UNSUPPORTED_SHARE", "WEB_UI")["value"] == pytest.approx(4 / 24)
    assert metric(out, "NEGATIVE_REACTION_RATE", "WEB_UI")["value"] == 1.0
    slack = metric(out, "AQR_RAW", "SLACK_MCP")
    assert (slack["numerator"], slack["denominator"]) == (3, 4)
    assert metric(out, "NOT_VERIFIABLE_SHARE", "SLACK_MCP")["value"] == pytest.approx(2 / 6)
    assert metric(out, "EVIDENCE_NONE_SHARE", "SLACK_MCP")["value"] == pytest.approx(2 / 6)
    assert metric(out, "NEGATIVE_REACTION_RATE", "SLACK_MCP")["value"] == pytest.approx(1 / 4)
    # Small slices are merged; strata are always kept, the parts of standardized AQR (§8.4, §8.5).
    assert metric(out, "AQR_RAW", "ALL", "INTENT", "FACT_LOOKUP")["n_turns"] == 24
    merged = metric(out, "AQR_RAW", "ALL", "INTENT", "MERGED_OTHER")
    assert merged["merged"] and merged["n_turns"] == 6
    assert metric(out, "AQR_RAW", "SLACK_MCP", "STRATUM", "PROCEDURE__ENGINEERING__ENGINEERING")["n_turns"] == 1
    assert metric(out, "AQR_RAW", "SLACK_MCP", "STRATUM", "PROCEDURE__ENGINEERING__COMMERCIAL")["n_turns"] == 3
    assert metric(out, "AQR_RAW", "ALL", "DEPARTMENT", "ENGINEERING")["n_turns"] == 27
    department = metric(out, "AQR_RAW", "ALL", "DEPARTMENT", "MERGED_OTHER")  # COMMERCIAL: 3 turns, under 20
    assert department["merged"] and department["n_turns"] == 3
    std = metric(out, "AQR_STANDARDIZED", "ALL")
    assert std["value"] == pytest.approx((24 / 28) * (20 / 24) + (4 / 28) * (23 / 28))  # small stratum: overall AQR
    assert metric(out, "COVERAGE", "WEB_UI")["value"] == pytest.approx(27 / 28)
    assert metric(out, "MISSED_COUNT", "SLACK_MCP")["value"] == 1 and metric(out, "VOLUME", "ALL")["value"] == 35
    assert metric(out, "TOO_LARGE_SHARE", "WEB_UI")["value"] == pytest.approx(1 / 28)
    assert metric(out, "OLDEST_WAITING_MINUTES")["value"] == 42.0
    assert metric(out, "RESUMED_WITHOUT_TEXT")["value"] == 0.5 and metric(out, "RESUMED_AND_CONTINUED")["value"] == 1.0
    write(METRICS_DAILY, out)
    assert len(rows(METRICS_DAILY, "metric = 'AQR_STANDARDIZED'")) == 3


def test_standardized_aqr_uses_the_baseline_mix(clean, monkeypatch):
    monkeypatch.setattr(get_settings().metrics, "go_live_day", DAY - timedelta(days=10))
    base = []
    for d in range(1, 4):
        for stratum, n in (("FACT__COMPANY__ENGINEERING", 10.0), ("PROCEDURE__ENGINEERING__ENGINEERING", 30.0)):
            base.append(
                {
                    "day": DAY - timedelta(days=d),
                    "day_kind": "WEEKDAY",
                    "channel": "ALL",
                    "metric": "AQR_RAW",
                    "slice_kind": "STRATUM",
                    "slice_value": stratum,
                    "value": 0.5,
                    "numerator": n / 2,
                    "denominator": n,
                    "n_turns": int(n),
                    "incomplete": False,
                    "merged": False,
                }
            )
    write(METRICS_DAILY, base)
    stored.store(day_turns())
    out = DayMetrics(DAY, current().version_id, {c: False for c in ("WEB_UI", "SLACK_MCP", "ALL")}, {}).rows()
    std = metric(out, "AQR_STANDARDIZED", "ALL")
    assert std["value"] == pytest.approx(0.25 * (20 / 24) + 0.75 * (23 / 28))  # baseline: 1 fact turn to 3 procedure
    record("AQR_REBASE", str(DAY), 0, None, None, [])  # a rebase on the day: no baseline days before it yet
    out = DayMetrics(DAY, current().version_id, {c: False for c in ("WEB_UI", "SLACK_MCP", "ALL")}, {}).rows()
    today_mix = (24 / 28) * (20 / 24) + (4 / 28) * (23 / 28)
    assert metric(out, "AQR_STANDARDIZED", "ALL")["value"] == pytest.approx(today_mix)


def test_completeness_marks_a_gap_day(clean):
    for weeks in (1, 2, 3):
        log_turns(DAY - timedelta(weeks=weeks), web=12, api=0, hour=10)
    log_turns(DAY, web=1, api=0, hour=10)
    job = daily.Daily(DAY, NOON + timedelta(days=1))
    incomplete, gaps = job.completeness()
    assert incomplete == {"WEB_UI": True, "SLACK_MCP": False, "ALL": True} and gaps["WEB_UI"] == 1


def series_rows(metric_name: str, values: list[tuple[date, float]], n: int = 400, channel: str = "ALL") -> list[dict]:
    return [
        {
            "day": d,
            "day_kind": "WEEKEND" if d.weekday() >= 5 else "WEEKDAY",
            "channel": channel,
            "metric": metric_name,
            "slice_kind": "ALL",
            "slice_value": "ALL",
            "value": v,
            "numerator": v * n,
            "denominator": float(n),
            "n_turns": n,
            "incomplete": False,
            "merged": False,
        }
        for d, v in values
    ]


def weekdays_before(day: date, n: int) -> list[date]:
    out, d = [], day
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return sorted(out)


def test_anomaly_jump_alert_acknowledgement_and_restart(clean, monkeypatch):
    monkeypatch.setattr(get_settings().metrics, "go_live_day", DAY - timedelta(days=90))
    history = [(d, 0.98 + (0.004 if i % 2 else -0.004)) for i, d in enumerate(weekdays_before(DAY, 30))]
    write(METRICS_DAILY, series_rows("COVERAGE", [*history, (DAY, 0.80)]))
    record("PROMPT", str(DAY - timedelta(days=1)), 22, None, None, [])
    job = daily.Daily(DAY, NOON + timedelta(days=1))
    rows_, new = AnomalyCheck(DAY).run()
    assert len(new) == 1 and job.alerts(rows_, new) == 1
    (a,) = rows(ANOMALIES)
    assert (a["metric"], a["channel"], a["kind"], a["state"]) == ("COVERAGE", "ALL", "JUMP", "OPEN")
    assert a["explained"] and len(a["change_events"]) == 1 and a["band_low"] < 0.98 < a["band_high"]
    text = state(clean)["messages"][-1]["text"]
    assert "`COVERAGE` on ALL" in text and "sudden jump" in text and "likely caused by" in text and "80.0%" in text
    assert AnomalyCheck(DAY).run() == ([], [])  # open: no second alert for the same series
    write(ACKNOWLEDGEMENTS, [{"anomaly_id": a["anomaly_id"], "acknowledged_by": "U123", "ack_day": DAY, "ack_hour": 9}])
    rows_, new = AnomalyCheck(DAY + timedelta(days=1)).run()
    assert not new and rows_[0]["state"] == "ACKNOWLEDGED" and rows_[0]["acknowledged_day"] == DAY
    write(ANOMALIES, rows_)
    write(METRICS_DAILY, series_rows("COVERAGE", [(DAY + timedelta(days=1), 0.70)]))
    assert AnomalyCheck(DAY + timedelta(days=1)).run() == ([], [])  # reference restarted at the acknowledgement


def test_anomaly_drift_and_quality_waits_for_the_baseline(clean, monkeypatch):
    days = weekdays_before(DAY, 40)
    values = [(d, 0.80 + (0.01 if i % 2 else -0.01)) for i, d in enumerate(days[:30])]
    values += [(d, 0.785) for d in days[30:]] + [(DAY, 0.785)]  # each day within the band, together a drift
    write(METRICS_DAILY, series_rows("AQR_STANDARDIZED", values, n=4000))
    monkeypatch.setattr(get_settings().metrics, "go_live_day", None)
    assert AnomalyCheck(DAY).run() == ([], [])  # quality anomalies only once the baseline has ended (§8.6)
    monkeypatch.setattr(get_settings().metrics, "go_live_day", DAY - timedelta(days=120))
    _, new = AnomalyCheck(DAY).run()
    assert [(n["metric"], n["kind"]) for n in new] == [("AQR_STANDARDIZED", "DRIFT")]
    assert new[0]["cusum"] > get_settings().metrics.anomaly.cusum_limit


def test_unsent_anomaly_alert_is_retried(clean, monkeypatch):
    write(
        ANOMALIES,
        [
            {
                "anomaly_id": "anom-0123456789abcdef",
                "metric": "COVERAGE",
                "channel": "ALL",
                "kind": "JUMP",
                "day": DAY,
                "opened_day": DAY,
                "value": 0.8,
                "reference_value": 0.98,
                "noise": 0.01,
                "band_low": 0.95,
                "band_high": 1.01,
                "state": "OPEN",
                "change_events": [],
                "alert_id": "alert-0123456789abcdef",
            }
        ],
    )

    def broken(*args, **kwargs):
        raise AnalyzerError(ErrorClass.SLACK)

    monkeypatch.setattr(daily.slack, "post", broken)
    assert daily.Daily(DAY, NOON).alerts([], []) == 0
    monkeypatch.undo()
    assert daily.Daily(DAY, NOON).alerts([], []) == 1
    assert rows(ANOMALIES)[0]["slack_ts"] and "unexplained" in state(clean)["messages"][-1]["text"]


def test_release_impact_verdicts(clean):
    change = DAY - timedelta(days=8)  # a Monday: 5 weekdays before it, 5 after it up to DAY
    before = weekdays_before(change, 5)
    after = [d for d in (change + timedelta(days=i) for i in range(1, 9)) if d.weekday() < 5][:5]
    assert after[-1] <= DAY
    write(
        METRICS_DAILY, series_rows("AQR_STANDARDIZED", [(d, 0.70) for d in before] + [(d, 0.80) for d in after], n=2000)
    )
    write(METRICS_DAILY, series_rows("FAILURE_RATE_CONTRADICTED_CLAIM", [(d, 0.05) for d in before + after], n=2000))
    eid = record("PROMPT", str(change), 10, None, None, [])
    s = get_settings()
    client().insert_rows_json(  # the gate's latest verdict on the change is shown with it; other values never
        f"{s.env.bq_project}.{s.datasets.evals}.{EVAL_GATE_RESULTS.name}",
        [
            {"change_id": eid, "verdict": "FAIL", "created_at": f"{change}T08:00:00Z"},
            {"change_id": eid, "verdict": "PASS", "created_at": f"{change}T09:00:00Z"},
            {"change_id": eid, "verdict": "free text", "created_at": f"{change}T10:00:00Z"},
        ],
    )
    out = {(r["metric"], r["channel"]): r for r in release.impact(DAY, DAY)}
    aqr = out[("AQR_STANDARDIZED", "ALL")]
    assert aqr["event_id"] == eid and aqr["verdict"] == "IMPROVED" and aqr["diff"] == pytest.approx(0.10)
    assert aqr["gate_verdict"] == "PASS" and release.gate_verdicts([]) == {}
    assert aqr["same_judge"] and aqr["n_before"] == 10000
    assert out[("FAILURE_RATE_CONTRADICTED_CLAIM", "ALL")]["verdict"] == "NO_DETECTABLE_CHANGE"
    assert out[("AQR_STANDARDIZED", "WEB_UI")]["verdict"] == "WAITING"  # no web UI days stored
    record("INDEXER", str(after[1]), 3, None, None, [])  # indexer runs do not confound
    assert {r["verdict"] for r in release.impact(DAY, DAY) if r["channel"] == "ALL"} == {
        "IMPROVED",
        "NO_DETECTABLE_CHANGE",
        "WAITING",
    }
    record("DOCUMENT", str(after[2]), 3, "hr_leave", "rtb-crj-hr-house", [])
    confounded = [
        r
        for r in release.impact(DAY, DAY)
        if r["event_id"] == eid and r["metric"] == "AQR_STANDARDIZED" and r["channel"] == "ALL"
    ]
    assert {r["verdict"] for r in confounded} == {"CONFOUNDED"} and len(confounded[0]["confounding_events"]) == 1
    write(RELEASE_IMPACT, release.impact(DAY, DAY))
    assert rows(RELEASE_IMPACT)
    assert release.verdict("FAILURE_RATE_X", 0.10, 0.05, 0.01) == "IMPROVED"
    assert release.verdict("AQR_STANDARDIZED", 0.8, 0.7, 0.01) == "REGRESSED"
    assert release.verdict("AQR_STANDARDIZED", 0.8, 0.7, 0.0) == "NO_DETECTABLE_CHANGE"


def test_judge_quality_measures(clean):
    v = current().version_id
    write(
        CANARY_RESULTS,
        [
            {
                "turn_key": stored.key(),
                "planted_error": "NONE",
                "with_references": True,
                "judge_version": v,
                "day": DAY,
                "question_hash": "a" * 64,
                "relevance": 5,
                "groundedness": 5,
                "severity": None,
                "false_high": False,
            },
            {
                "turn_key": stored.key(),
                "planted_error": "NONE",
                "with_references": False,
                "judge_version": v,
                "day": DAY,
                "question_hash": "b" * 64,
                "relevance": 2,
                "groundedness": None,
                "severity": "HIGH",
                "false_high": True,
            },
            {
                "turn_key": stored.key(),
                "planted_error": "SWAPPED_NUMBER",
                "with_references": True,
                "judge_version": v,
                "day": DAY,
                "question_hash": "a" * 64,
                "caught": True,
            },
            {
                "turn_key": stored.key(),
                "planted_error": "SWAPPED_NUMBER",
                "with_references": False,
                "judge_version": v,
                "day": DAY,
                "question_hash": "b" * 64,
                "caught": False,
            },
        ],
    )
    s = get_settings()
    client().insert_rows_json(
        f"{s.env.bq_project}.{s.datasets.evals}.{EVAL_RESULTS.name}",
        [
            {
                "run_kind": "CANARY",
                "question_sha256": "a" * 64,
                "metric": "RELEVANCE",
                "score": 0.9,
                "created_at": f"{DAY}T05:00:00Z",
            },
            {
                "run_kind": "CANARY",
                "question_sha256": "b" * 64,
                "metric": "RELEVANCE",
                "score": 0.8,
                "created_at": f"{DAY}T05:00:00Z",
            },
            {
                "run_kind": "CANARY",
                "question_sha256": "b" * 64,
                "metric": "CORRECTNESS",
                "score": 0.9,
                "created_at": f"{DAY}T05:00:00Z",
            },
        ],
    )
    write(JUDGE_CHECKS, [{"day": DAY, "field": "RELEVANCE", "n_compared": 20, "n_disagreements": 3}])
    t = stored.turn
    stored.store(
        [
            t(DAY, thumbs="DOWN", relevance=2, primary="MISUNDERSTOOD_QUERY", severity="MEDIUM"),
            t(DAY),
            t(DAY),
            t(
                DAY,
                groundedness=1,
                primary="CHUNKING_ISSUE",
                severity="MEDIUM",
                stage2={
                    "primary_failure": "CHUNKING_ISSUE",
                    "failure_types": ["CHUNKING_ISSUE"],
                    "stage1_findings": [{"code": "UNSUPPORTED_CLAIM", "verdict": "DROPPED"}],
                },
            ),
        ]
    )
    got = {(m["measure"], m["field"]): (m["value"], m["n"]) for m in judge_quality.measures(DAY, v)}
    assert got[("PLANTED_CAUGHT", "SWAPPED_NUMBER")] == (0.5, 2)
    assert got[("PLANTED_FALSE_HIGH", "ALL")] == (0.5, 2)
    assert not any(m in got for m in (("INDEX_HIT_RATE", "ALL"), ("KNOWLEDGE_GAP_MISS_RATE", "ALL")))
    assert got[("CANARY_AGREEMENT", "RELEVANCE")] == (0.5, 2)  # 5 vs 0.9 agree; 2 vs 0.8 do not
    assert got[("CANARY_AGREEMENT", "SEVERITY")] == (0.0, 1)  # HIGH, while the evaluator found it correct
    assert got[("SECOND_MODEL_DISAGREEMENT", "RELEVANCE")] == (0.15, 20)
    assert got[("DISLIKED_AQR", "ALL")] == (0.0, 1) and got[("NOT_DISLIKED_AQR", "ALL")] == (2 / 3, 3)
    assert got[("STAGE2_CHANGE_RATE", "ALL")] == (1.0, 1) and got[("STAGE2_DROP_RATE", "ALL")] == (1.0, 1)
    write(JUDGE_QUALITY, judge_quality.measures(DAY, v))


def test_daily_run_end_to_end(clean, monkeypatch):
    stored.store(day_turns())
    log_turns(DAY, web=28, api=7)
    monkeypatch.setenv("CA_NOW", f"{DAY + timedelta(days=1)}T05:00:00+00:00")
    summary = daily.run(None)
    assert summary["metric_rows"] > 100 and summary["anomalies"] == 0 and summary["incomplete_channels"] == 0
    assert (
        query(f"SELECT COUNT(*) AS n FROM {tbl(METRICS_DAILY)} WHERE day = @d", d=DAY)[0]["n"] == summary["metric_rows"]
    )
