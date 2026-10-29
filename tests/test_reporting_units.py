"""Message templates, cluster keys and alert IDs, without the emulator (§9.1, §12.8)."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

import httpx
import pytest

from conversation_analyzer.errors import AnalyzerError
from conversation_analyzer.reporting import messages, slack
from conversation_analyzer.reporting.monitor import alert_id, floor_hour
from conversation_analyzer.reporting.results import ClusterKey, cluster_key
from conversation_analyzer.vocab import HealthCheck

DAY = date(2026, 10, 28)
CITED = {"doc_id": "d1", "data_store": "rtb-crj-confluence", "uri": "https://x/d1"}


def test_cluster_key_by_document_or_topic():
    base = {"primary_failure": "OUTDATED_SOURCE", "topic": "CONFLUENCE"}
    s2 = cluster_key(
        {**base, "has_stage2": True, "fix_doc_id": "d9", "fix_data_store": "rtb-crj-biztech", "fix_uri": "https://y"}
    )
    assert (s2.doc_id, s2.data_store, s2.topic) == ("d9", "rtb-crj-biztech", None)
    no_fix = cluster_key({**base, "has_stage2": True, "fix_doc_id": None, "cited_docs": [CITED]})
    assert no_fix.doc_id is None and no_fix.topic == "CONFLUENCE"  # stage 2 found no document to fix
    one = cluster_key({**base, "has_stage2": False, "cited_docs": [CITED, CITED]})
    assert one.doc_id == "d1"
    two = cluster_key({**base, "has_stage2": False, "cited_docs": [CITED, {**CITED, "doc_id": "d2"}]})
    assert two.doc_id is None and two.topic == "CONFLUENCE"
    people = {"doc_id": "associate-1", "data_store": "rtb-crj-associates", "uri": None}
    assert cluster_key({**base, "has_stage2": False, "cited_docs": [CITED, people]}).doc_id == "d1"
    gap = cluster_key(
        {
            **base,
            "primary_failure": "KNOWLEDGE_GAP",
            "has_stage2": True,
            "fix_doc_id": "d9",
            "fix_data_store": "rtb-crj-biztech",
        }
    )
    assert gap.doc_id is None and gap.topic == "CONFLUENCE"


def test_cluster_ids_are_stable_and_distinct():
    a = ClusterKey("X", "ds", "d", None, None)
    assert a.cluster_id == ClusterKey("X", "ds", "d", "https://other", None).cluster_id  # the link is not identity
    assert a.cluster_id != ClusterKey("X", None, None, None, "ds").cluster_id
    assert re.fullmatch(r"cluster-[0-9a-f]{16}", a.cluster_id)
    assert alert_id("A", 1) == alert_id("A", 1) != alert_id("A", 2)
    assert floor_hour(datetime(2026, 1, 1, 10, 59, 3, tzinfo=UTC)).hour == 10


def test_session_lines():
    assert messages.session_line(None, 3) == "3 turns, no grade yet"
    assert "not gradable" in messages.session_line({"grade_state": "NOT_GRADABLE"}, 4)
    grade = {
        "grade_state": "PROVISIONAL",
        "outcome": "UNRESOLVED",
        "first_bad_turn": 2,
        "rephrases_corrections": "2_OR_MORE",
        "recovered": "NO",
    }
    assert messages.session_line(grade, 5) == (
        "5 turns, unresolved (provisional), went wrong at turn 2, rephrased or corrected 2 or more times"
    )
    grade = {
        "grade_state": "FINAL",
        "outcome": "PARTIALLY_RESOLVED",
        "first_bad_turn": None,
        "rephrases_corrections": "0",
        "recovered": "YES",
    }
    assert messages.session_line(grade, 1) == (
        "1 turn, partly resolved (final), not rephrased or corrected, recovered after the correction"
    )


def test_high_cluster_message_has_only_derived_values():
    key = ClusterKey(
        "OUTDATED_SOURCE", "rtb-crj-hr-house", "doc_1", "https://sites.google.com/rtbhouse.com/hr-house/x", None
    )
    text = messages.high_cluster(
        "alert-abc", key, {"WEB_UI": 2, "SLACK_MCP": 1}, "DOCUMENT_OWNER", ["2 turns, no grade yet"], DAY, 9
    )
    assert "`OUTDATED_SOURCE`" in text and "3 new turns (1 SLACK_MCP, 2 WEB_UI)" in text
    assert "2026-10-28 09:00 UTC" in text and "|link>" in text and "make alert-lookup ALERT=alert-abc" in text
    topic = messages.high_cluster(
        "alert-abc",
        ClusterKey("KNOWLEDGE_GAP", None, None, None, "BIZTECH"),
        {"WEB_UI": 1},
        "CORPUS_OWNER",
        [],
        DAY,
        9,
    )
    assert "topic BIZTECH" in topic and "1 new turn (1 WEB_UI)" in topic and "link" not in topic


@pytest.mark.parametrize(
    ("check", "value", "ctx", "expected"),
    [
        (HealthCheck.COVERAGE, 0.9, {"run_id": "run-1", "target": 0.98}, "was 90.0% (target 98%)"),
        (HealthCheck.WAITING_TOO_LONG, 190.0, {"limit": 180}, "waited 3h10 for assessment (limit 3h00)"),
        (HealthCheck.NO_RUN, 40.0, {"limit": 25}, "No assessment run for 0h40 (limit 0h25)"),
        (HealthCheck.RUN_FAILED, None, {"run_id": "run-1", "error_class": "BIGQUERY"}, "failed: `BIGQUERY`"),
        (HealthCheck.LOG_GAP, 2.0, {"channel": "WEB_UI", "expected": 40.0, "checked": "x"}, "had 2 records"),
        (HealthCheck.WINDOW_SHORT, 200.0, {"limit": 225}, "The log window is 3h20, under 3h45"),
        (HealthCheck.TOKEN_LIMIT, 61.2e6, {"limit": 60e6}, "61.2M, over the daily limit of 60.0M"),
    ],
)
def test_health_messages(check, value, ctx, expected):
    text = messages.health("alert-1", check, value, DAY, 7, **ctx)
    assert expected in text and f"`{check.value}`, 2026-10-28 07:00 UTC" in text


def test_slack_client_errors_are_one_class(monkeypatch):
    def failing(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", failing)
    with pytest.raises(AnalyzerError) as exc:
        slack.post("#c", "t")
    assert exc.value.error_class == "SLACK"
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(200, json={"ok": False, "error": "x"}))
    with pytest.raises(AnalyzerError):
        slack.reactions("C1", "1.1")
    assert messages.acknowledged("U1", DAY).startswith(":white_check_mark: Acknowledged by <@U1> on 2026-10-28")


def test_reference_noise_is_the_larger_of_chance_and_spread():
    from conversation_analyzer.reporting.anomaly import Day, reference

    days = [Day(date(2026, 9, d), 0.8, 80.0, 100.0, 100) for d in range(1, 20)]
    ref = reference(days, 100)
    assert ref.value == pytest.approx(0.8) and ref.noise == pytest.approx((0.8 * 0.2 / 100) ** 0.5)
    spread = [Day(date(2026, 9, d), 0.7 + 0.1 * (d % 2), 0.0, 100.0, 100) for d in range(1, 20)]
    assert reference(spread, 100_000).noise > 0.04  # the days vary more than chance explains
    assert reference(days[:5], 100) is None  # fewer than 14 reference days
    assert reference([Day(date(2026, 9, d), 0.0, 0.0, 100.0, 100) for d in range(1, 20)], 100) is None


def test_anchor_set_follows_traffic_with_a_minimum_per_data_store():
    from conversation_analyzer.reporting.weekly import anchor_set, monday, quarter_start

    docs = [
        {"doc_id": "a", "data_store": "rtb-crj-hr-house", "uri": None, "n_cited": 90, "n_retrieved": 10},
        {"doc_id": "b", "data_store": "rtb-crj-hr-house", "uri": None, "n_cited": 50, "n_retrieved": 50},
        {"doc_id": "c", "data_store": "rtb-crj-biztech", "uri": None, "n_cited": 2, "n_retrieved": 0},
    ]
    out = {d["doc_id"]: d["n_questions"] for d in anchor_set(docs, date(2026, 10, 1), date(2026, 10, 5))}
    assert out == {"a": 198, "b": 198, "c": 20}
    assert anchor_set([{**docs[0], "n_cited": 0, "n_retrieved": 0}], date(2026, 10, 1), date(2026, 10, 5)) == []
    assert quarter_start(date(2026, 12, 31)) == date(2026, 10, 1) and monday(date(2026, 10, 25)) == date(2026, 10, 19)


def test_digest_without_data_says_so():
    text = messages.digest(DAY, {}, [], [], [], [], [], [], [], None)
    for line in ("*Top problem clusters*", "none", "none with enough turns", "nothing", "none this week"):
        assert line in text
    assert "Experimental" not in text
    assert messages.value("VOLUME", 12.0) == "12.0" and messages.value("AQR_RAW", None) == "n/a"
