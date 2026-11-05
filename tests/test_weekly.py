"""quality-weekly on the emulator and the Slack stub: clusters, closing after a fix, documents, eval sets, digest."""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest

from conversation_analyzer.bq.client import client, write
from conversation_analyzer.bq.external import EVAL_GATE_RESULTS
from conversation_analyzer.bq.schema import (
    DOCUMENT_STATS,
    EVAL_DOCUMENTS,
    METRICS_DAILY,
    PROBLEM_CLUSTERS,
    RELEASE_IMPACT,
    RETRIEVAL_COUNTS,
    SUITE_RUNS,
)
from conversation_analyzer.errors import AnalyzerError
from conversation_analyzer.judge.version import current
from conversation_analyzer.reporting import weekly
from conversation_analyzer.reporting.record import record
from conversation_analyzer.reporting.results import ClusterKey
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import ErrorClass
from tests import stored
from tests.conftest import rows, wipe

pytestmark = pytest.mark.emulator

WEEK = date(2026, 10, 19)  # a Monday
OUTDATED = {
    "primary_failure": "OUTDATED_SOURCE",
    "failure_types": ["OUTDATED_SOURCE"],
    "severity": "MEDIUM",
    "document_to_fix": stored.HR,
}
OUTDATED_ID = ClusterKey("OUTDATED_SOURCE", stored.HR["data_store"], stored.HR["doc_id"], None, None).cluster_id
CONTRADICTED_ID = ClusterKey("CONTRADICTED_CLAIM", "rtb-crj-confluence", "confluence_1", None, None).cluster_id


@pytest.fixture
def clean(emulator, stubs):
    wipe()
    return stubs


def week_turns(week: date, outdated: int = 5) -> list[dict]:
    t = stored.turn
    day = week + timedelta(days=2)
    out = [t(day) for _ in range(25)]
    out += [t(day, groundedness=1, stage2=OUTDATED) for _ in range(outdated)]
    out += [
        t(day, topic="CONFLUENCE", groundedness=2, primary="CONTRADICTED_CLAIM", severity="HIGH", cited=(stored.CONF,))
        for _ in range(3)
    ]
    out += [
        t(
            day,
            topic="OTHER",
            evidence="NONE",
            cited=(),
            found=(stored.HR,),
            spans=None,
            primary="UNGROUNDED_INTERNAL_ANSWER",
            severity="MEDIUM",
        )
        for _ in range(2)
    ]
    out += [t(day, canary=True, primary="CONTRADICTED_CLAIM", severity="HIGH"), t(day, pace=True)]
    return out


def daily_row(day: date, metric: str, value: float, n: float, kind="ALL", slice_value="ALL") -> dict:
    return {
        "day": day,
        "day_kind": "WEEKDAY",
        "channel": "ALL",
        "metric": metric,
        "slice_kind": kind,
        "slice_value": slice_value,
        "value": value,
        "numerator": value * n,
        "denominator": n,
        "n_turns": int(n),
        "incomplete": False,
        "merged": False,
    }


def test_weekly_clusters_documents_eval_sets_and_digest(clean, monkeypatch):
    monkeypatch.setattr(get_settings().metrics, "go_live_day", WEEK - timedelta(days=42))
    stored.store(week_turns(WEEK))
    write(
        PROBLEM_CLUSTERS,
        [
            {
                "week": WEEK - timedelta(weeks=k),
                "cluster_id": CONTRADICTED_ID,
                "primary_failure": "CONTRADICTED_CLAIM",
                "n_turns": 1,
                "rank": 1,
                "state": "ACTIVE",
            }
            for k in (1, 2, 3, 5)
        ],
    )
    write(
        DOCUMENT_STATS,
        [
            {"week": WEEK - timedelta(weeks=k), "doc_id": "hr_leave", "data_store": "rtb-crj-hr-house", "n_cited": 2}
            for k in range(1, 5)
        ],
    )
    write(
        RETRIEVAL_COUNTS,
        [{"day": WEEK + timedelta(days=1), "doc_id": "hr_leave", "data_store": "rtb-crj-hr-house", "n_returned": 42}],
    )
    write(
        SUITE_RUNS,
        [
            {
                "suite_run_id": "suite-00112233",
                "day": WEEK,
                "judge_version": current().version_id,
                "partial": False,
                "label_recall": [{"label": "CONTRADICTED_CLAIM", "recall": 0.9, "n": 10, "reliable": True}],
            }
        ],
    )
    write(
        METRICS_DAILY,
        [
            daily_row(WEEK + timedelta(days=1), "AQR_STANDARDIZED", 0.81, 300),
            daily_row(WEEK - timedelta(days=6), "AQR_STANDARDIZED", 0.76, 300),
            daily_row(WEEK + timedelta(days=1), "AQR_RAW", 0.9, 40, "TOPIC", "HR_HOUSE"),
            daily_row(WEEK - timedelta(days=6), "AQR_RAW", 0.9, 8, "TOPIC", "HR_HOUSE"),
        ],
    )
    write(
        RELEASE_IMPACT,
        [
            {
                "event_id": "evt-0123456789abcdef",
                "metric": "AQR_STANDARDIZED",
                "channel": "ALL",
                "change_day": WEEK - timedelta(days=9),
                "diff": 0.031,
                "verdict": "IMPROVED",
                "computed_day": WEEK + timedelta(days=1),
            }
        ],
    )
    s = get_settings()
    client().insert_rows_json(
        s.table("evals", EVAL_GATE_RESULTS.name),
        [
            {"change_id": "evt-0123456789abcdef", "verdict": "PASS", "created_at": f"{WEEK}T08:00:00Z"},
            {"change_id": "free text, not an id", "verdict": "FAIL", "created_at": f"{WEEK}T09:00:00Z"},
        ],
    )
    summary = weekly.Weekly(WEEK, WEEK + timedelta(days=7)).execute()
    assert summary["clusters"] == 3 and summary["digest_sent"]

    clusters = {c["cluster_id"]: c for c in rows(PROBLEM_CLUSTERS, f"week = '{WEEK}'")}
    outdated, contradicted = clusters[OUTDATED_ID], clusters[CONTRADICTED_ID]
    # OUTDATED_SOURCE weighs most, but only CONTRADICTED_CLAIM is reliable: an experimental label is never ranked.
    assert (outdated["rank"], outdated["n_turns"], outdated["weighted"], outdated["owner"]) == (
        None,
        5,
        10,
        "DOCUMENT_OWNER",
    )
    assert outdated["family"] == "CORPUS" and outdated["experimental"] and outdated["state"] == "ACTIVE"
    assert (contradicted["rank"], contradicted["n_high"], contradicted["owner"]) == (1, 3, "TEAM")
    assert contradicted["prev_4w_avg"] == 0.75 and contradicted["trend"] == 4.0 and not contradicted["experimental"]
    (topic,) = [c for c in clusters.values() if c["primary_failure"] == "UNGROUNDED_INTERNAL_ANSWER"]
    assert topic["topic"] == "OTHER" and topic["doc_id"] is None and topic["rank"] is None and topic["experimental"]

    (hr,) = rows(DOCUMENT_STATS, f"week = '{WEEK}' AND doc_id = 'hr_leave'")
    assert (hr["n_cited"], hr["n_verifiable"], hr["n_good"], hr["n_found"], hr["n_retrieved"]) == (30, 30, 25, 2, 42)
    assert hr["aqr"] == pytest.approx(25 / 30) and hr["cited_prev_4w_avg"] == 2.0 and hr["n_failures"] == 5

    evals = rows(EVAL_DOCUMENTS)
    anchor = {e["doc_id"]: e for e in evals if e["eval_set"] == "ANCHOR"}
    assert anchor["hr_leave"]["period"] == date(2026, 10, 1) and anchor["confluence_1"]["n_questions"] == 20
    focus = {e["cluster_id"] for e in evals if e["eval_set"] == "FOCUS"}
    assert focus == {OUTDATED_ID, CONTRADICTED_ID} and all(
        e["n_questions"] == 15 for e in evals if e["eval_set"] == "FOCUS"
    )

    text = httpx.get(f"{clean}/_test/state").json()["messages"][-1]["text"]
    assert "*Bolek quality digest*, week of 2026-10-19" in text and "ALL: 81.0% (4 weeks before: 76.0%)" in text
    assert "1. `CONTRADICTED_CLAIM` rtb-crj-confluence document confluence_1: 3 turns (3 HIGH), x4.0" in text
    assert text.index("*Experimental labels*") < text.index("• `OUTDATED_SOURCE` rtb-crj-hr-house document hr_leave")
    assert "2. " not in text
    assert "owner DOCUMENT_OWNER" in text and CONTRADICTED_ID in text and "x4.0" in text
    assert "AQR 83.3% over 30 turns" in text and "HR_HOUSE: AQR 90.0% over 40 turns" in text
    assert "fast-growing topic HR_HOUSE" in text and "document hr_leave cited 30 times" in text
    assert "`evt-0123456789abcdef`: improved (+3.1 points)" in text and "`evt-0123456789abcdef`: PASS" in text
    assert "a change: FAIL" in text and "free text" not in text
    assert "*Turns still in the baseline's top clusters*: 3" in text  # the baseline's last week ranked it first

    # A second run in the same quarter picks no new anchor set.
    weekly.Weekly(WEEK, WEEK + timedelta(days=7)).execute()
    assert len([e for e in rows(EVAL_DOCUMENTS) if e["eval_set"] == "ANCHOR"]) == len(anchor)


def test_a_fixed_cluster_closes_after_two_weeks_below_a_quarter(clean, monkeypatch):
    fix_week = WEEK - timedelta(weeks=1)
    write(
        PROBLEM_CLUSTERS,
        [
            {
                "week": fix_week - timedelta(weeks=k),
                "cluster_id": OUTDATED_ID,
                "primary_failure": "OUTDATED_SOURCE",
                "data_store": stored.HR["data_store"],
                "doc_id": stored.HR["doc_id"],
                "n_turns": 8,
                "rank": 1,
                "state": "ACTIVE",
                "fix_events": [],
            }
            for k in range(1, 5)
        ],
    )
    record("DOCUMENT", str(fix_week + timedelta(days=2)), 10, "hr_leave", "rtb-crj-hr-house", [OUTDATED_ID])
    stored.store(week_turns(fix_week, outdated=6))
    first = weekly.Weekly(fix_week, WEEK).clusters(weekly.Weekly(fix_week, WEEK).turns())
    (x,) = [c for c in first if c["cluster_id"] == OUTDATED_ID]
    assert x["level_before_fix"] == 8.0 and x["weeks_below"] == 0 and x["state"] == "ACTIVE"
    write(PROBLEM_CLUSTERS, first)
    states = []
    for k, outdated in ((0, 1), (1, 0), (2, 0)):
        week = WEEK + timedelta(weeks=k)
        stored.store(week_turns(week, outdated=outdated))
        job = weekly.Weekly(week, week + timedelta(days=7))
        out = job.clusters(job.turns())
        write(PROBLEM_CLUSTERS, out)
        (x,) = [c for c in out if c["cluster_id"] == OUTDATED_ID]
        states.append((x["n_turns"], x["weeks_below"], x["state"]))
    assert states == [(1, 1, "ACTIVE"), (0, 2, "CLOSED"), (0, 2, "CLOSED")]


def test_digest_failure_is_reported_and_the_rest_stored(clean, monkeypatch):
    stored.store(week_turns(WEEK))

    def broken(*args, **kwargs):
        raise AnalyzerError(ErrorClass.SLACK)

    monkeypatch.setattr(weekly.slack, "post", broken)
    summary = weekly.run(str(WEEK + timedelta(days=3)))  # any day of the week names its Monday
    assert not summary["digest_sent"] and summary["clusters"] == 3 and rows(PROBLEM_CLUSTERS)


def test_a_not_in_cited_sources_cluster_gets_a_focus_set_once_a_fix_adds_the_document(clean):
    gap = {"primary_failure": "NOT_IN_CITED_SOURCES", "failure_types": ["NOT_IN_CITED_SOURCES"], "severity": "MEDIUM"}
    stored.store(
        [stored.turn(WEEK + timedelta(days=1), topic="HR_HOUSE", groundedness=1, stage2=gap) for _ in range(2)]
    )
    job = weekly.Weekly(WEEK, WEEK + timedelta(days=7))
    (cluster,) = job.clusters(job.turns())
    assert cluster["doc_id"] is None and cluster["topic"] == "HR_HOUSE" and cluster["owner"] == "TEAM"
    assert job.eval_documents([], [cluster]) == []  # nothing to generate questions from yet
    record(
        "DOCUMENT", str(WEEK + timedelta(days=3)), 9, "hr_meal_allowance", "rtb-crj-hr-house", [cluster["cluster_id"]]
    )
    (focus,) = job.eval_documents([], [cluster])
    assert focus["doc_id"] == "hr_meal_allowance" and focus["cluster_id"] == cluster["cluster_id"]
