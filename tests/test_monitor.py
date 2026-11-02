"""quality-monitor on the emulator and the Slack stub: health checks, log gaps, HIGH cluster alerts, ✅ (§12.8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from conversation_analyzer.assessor.run import run as assess
from conversation_analyzer.bq.client import write
from conversation_analyzer.bq.schema import (
    ACKNOWLEDGEMENTS,
    ALERT_SESSIONS,
    ALERTS,
    ANOMALIES,
    PIPELINE_HEALTH,
    RUNS,
    SUITE_RUNS,
)
from conversation_analyzer.devtools import scenario
from conversation_analyzer.devtools.synthetic import SynthTurn, insert_log, turn_rows
from conversation_analyzer.docs.source import RunDocuments, link_doc_id
from conversation_analyzer.judge.fake import FakeJudge
from conversation_analyzer.reporting import monitor
from conversation_analyzer.reporting.lookup import lookup
from conversation_analyzer.settings import get_settings
from tests.conftest import rows, wipe

pytestmark = pytest.mark.emulator

NOW = datetime(2026, 10, 28, 12, 5, tzinfo=UTC)


def messages(stubs: str) -> list[dict]:
    return httpx.get(f"{stubs}/_test/state").json()["messages"]


def run_row(run_id: str, minutes_ago: float, **kw) -> dict:
    row = {
        "run_id": run_id,
        "run_day": (NOW - timedelta(minutes=minutes_ago)).date(),
        "started_at": NOW - timedelta(minutes=minutes_ago),
        "status": "OK",
        "eligible": 20,
        "covered": 20,
        "assessed": 3,
        "too_large": 0,
        "missed": 0,
        "failed": 0,
        "oldest_waiting_minutes": 0.0,
        "window_margin_minutes": 250.0,
        "tokens": [{"model": "gemini-3.8-flash", "input_tokens": 1000, "output_tokens": 100}],
    }
    row.update(kw)
    return row


@pytest.fixture
def clean(emulator, stubs):
    wipe()
    return stubs


def test_healthy_run_fires_nothing(clean):
    write(RUNS, [run_row("run-00000001", 5)])
    summary = monitor.run(NOW)
    assert summary["health_alerts"] == 0 and not messages(clean)
    health = [r for r in rows(PIPELINE_HEALTH) if r["kind"] == "RUN"]
    assert len(health) == 1 and health[0]["coverage"] == 1.0 and health[0]["checks_fired"] == []
    assert monitor.run(NOW + timedelta(minutes=1))["health_rows"] == 0  # each run is checked once


def test_every_run_check_alerts_once_per_period(clean, monkeypatch):
    monkeypatch.setattr(get_settings().judge, "daily_token_limit", 1500)
    write(
        RUNS,
        [
            run_row("run-00000001", 4, covered=18),
            run_row(
                "run-00000002",
                3,
                status="FAILED",
                error_class="JUDGE_API",
                covered=15,
                oldest_waiting_minutes=190.0,
                window_margin_minutes=200.0,
            ),
            run_row("run-00000003", 2, covered=10),
        ],
    )
    monitor.run(NOW)
    sent = messages(clean)
    assert all(m["channel"] == get_settings().alerts.alerts_channel for m in sent)
    checks = sorted(a["check"] for a in rows(ALERTS))
    # coverage once per hour; tokens once per day; the failed run once
    assert checks == ["COVERAGE", "RUN_FAILED", "TOKEN_LIMIT", "WAITING_TOO_LONG", "WINDOW_SHORT"]
    assert any("`JUDGE_API`" in m["text"] for m in sent) and any("90.0%" in m["text"] for m in sent)
    fired = {r["run_id"]: r["checks_fired"] for r in rows(PIPELINE_HEALTH) if r["run_id"]}
    assert fired["run-00000003"] == ["COVERAGE", "TOKEN_LIMIT"]
    monitor.run(NOW + timedelta(minutes=10))
    assert len(messages(clean)) == len(sent)


def test_no_run_alerts_once_an_hour(clean):
    write(RUNS, [run_row("run-00000001", 40)])
    monitor.run(NOW)
    monitor.run(NOW + timedelta(minutes=10))
    no_run = [a for a in rows(ALERTS) if a["check"] == "NO_RUN"]
    assert len(no_run) == 1 and no_run[0]["value"] == 40.0
    assert "No assessment run for 0h40 (limit 0h25)" in messages(clean)[0]["text"]


def test_log_gap_against_the_same_hour_of_earlier_weeks(clean):
    hour = datetime(2026, 10, 28, 10, 20, tzinfo=UTC)  # checked at 11:35: the hour 10:00-11:00
    turns = []
    for week in range(1, 5):
        for i in range(10):
            ago = (NOW - (hour - timedelta(weeks=week, minutes=-i))).total_seconds() / 60
            turns.append(SynthTurn(f"w{week}-{i}", ago, "q", "a"))
    turns.append(SynthTurn("now", (NOW - hour).total_seconds() / 60, "q", "a"))
    insert_log([r for t in turns for r in turn_rows(t, NOW)])
    write(RUNS, [run_row("run-00000001", 5)])
    monitor.run(datetime(2026, 10, 28, 11, 35, tzinfo=UTC))
    log_rows = {r["channel"]: r for r in rows(PIPELINE_HEALTH) if r["kind"] == "LOG_HOUR"}
    assert log_rows["WEB_UI"]["log_records"] == 1 and log_rows["WEB_UI"]["log_expected"] == 10.0
    assert log_rows["WEB_UI"]["log_gap"] and not log_rows["SLACK_MCP"]["log_gap"]
    assert log_rows["SLACK_MCP"]["log_expected"] == 0.0  # too few usual records to check
    (gap,) = [m for m in messages(clean) if "Log gap" in m["text"]]
    assert "WEB_UI had 1 records in the hour 2026-10-28 10:00 UTC, usually 10" in gap["text"]
    monitor.run(datetime(2026, 10, 28, 11, 45, tzinfo=UTC))
    assert len([r for r in rows(PIPELINE_HEALTH) if r["kind"] == "LOG_HOUR"]) == 2  # checked once an hour


def test_acknowledgement_by_reaction(clean):
    channel = "#bolek-quality"
    posted = httpx.post(f"{clean}/slack/api/chat.postMessage", json={"channel": channel, "text": "anomaly"}).json()
    ts = posted["ts"]
    write(
        ANOMALIES,
        [
            {
                "anomaly_id": "anom-00000001",
                "metric": "AQR_STANDARDIZED",
                "channel": "WEB_UI",
                "kind": "JUMP",
                "day": NOW.date(),
                "state": "OPEN",
                "slack_channel": channel,
                "slack_ts": ts,
            },
            {
                "anomaly_id": "anom-00000002",
                "metric": "AQR_STANDARDIZED",
                "channel": "SLACK_MCP",
                "kind": "JUMP",
                "day": NOW.date(),
                "state": "OPEN",
                "slack_channel": channel,
                "slack_ts": "1.000001",
            },
        ],
    )
    write(RUNS, [run_row("run-00000001", 5)])
    assert monitor.run(NOW)["acknowledged"] == 0
    httpx.post(f"{clean}/_test/slack/reaction", json={"channel": channel, "ts": ts, "name": "eyes", "user": "U1"})
    httpx.post(
        f"{clean}/_test/slack/reaction",
        json={"channel": channel, "ts": ts, "name": "white_check_mark", "user": "U0ABC"},
    )
    assert monitor.run(NOW + timedelta(minutes=10))["acknowledged"] == 1
    (ack,) = rows(ACKNOWLEDGEMENTS)
    assert ack["anomaly_id"] == "anom-00000001" and ack["acknowledged_by"] == "U0ABC" and ack["replied"]
    reply = messages(clean)[-1]
    assert reply["thread_ts"] == ts and "<@U0ABC>" in reply["text"]
    assert monitor.run(NOW + timedelta(minutes=20))["acknowledged"] == 0


def test_high_cluster_alerts_after_the_scenario(clean):
    s = get_settings()
    accounts = list(s.evaluator.accounts)
    s.evaluator.accounts = ["user:evaluator@rtbhouse.com"]
    try:
        scenario.seed(NOW - timedelta(minutes=5))
        assess(now=NOW - timedelta(minutes=5), judge=FakeJudge(), docs=RunDocuments())
    finally:
        s.evaluator.accounts = accounts
    # A later suite run of the same judge version finds CHUNKING_ISSUE too rarely: it becomes experimental,
    # and an experimental label never alerts.
    later = scenario.suite_run(NOW.date())
    for label in later["label_recall"]:
        if label["label"] == "CHUNKING_ISSUE":
            label.update(recall=0.4, reliable=False)
    write(SUITE_RUNS, [{**later, "suite_run_id": "suite-00000000000000df"}])
    assert monitor.run(NOW)["high_alerts"] == 0
    # The next suite run finds it reliably again: both HIGH chunking clusters alert, the cited leave policy and the
    # trips page the second answer only links to.
    write(SUITE_RUNS, [{**scenario.suite_run(NOW.date()), "suite_run_id": "suite-00000000000000e0"}])
    summary = monitor.run(NOW)
    assert summary["high_alerts"] == 2
    high = {a["doc_id"]: a for a in rows(ALERTS) if a["kind"] == "HIGH_CLUSTER"}
    assert set(high) == {scenario.LEAVE.doc_id, link_doc_id(scenario.TRIP.uri)}
    assert {a["primary_failure"] for a in high.values()} == {"CHUNKING_ISSUE"}
    chunking = high[scenario.LEAVE.doc_id]
    assert chunking["n_turns"] == 1
    texts = [m["text"] for m in messages(clean) if m["channel"] == s.alerts.quality_channel]
    assert any("2 turns, resolved (final), went wrong at turn 1, rephrased or corrected once" in t for t in texts)
    for t in texts:
        for planted in scenario.PLANTED_PII:
            assert planted not in t
    sessions = rows(ALERT_SESSIONS, f"alert_id = '{chunking['alert_id']}'")
    assert len(sessions) == 1 and sessions[0]["grade_state_shown"] == "FINAL"
    found = lookup(chunking["alert_id"])
    assert found["alert"]["primary_failure"] == "CHUNKING_ISSUE" and found["sessions"][0]["outcome"] == "RESOLVED"
    assert lookup("alert-0000000000000000") is None
    assert monitor.run(NOW + timedelta(minutes=10))["high_alerts"] == 0  # the same failures are not sent again
