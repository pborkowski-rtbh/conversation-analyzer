from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from conversation_analyzer import errors, keys, safe_log, secrets
from conversation_analyzer.bq.schema import QUALITY_TURNS, RUNS, SEGMENTS, STAGE2_RESULTS, Table, ddl
from conversation_analyzer.errors import LeakGuardError
from conversation_analyzer.leak_guard import allowed_link, check_row, is_people_directory
from conversation_analyzer.settings import get_settings, now
from conversation_analyzer.vocab import (
    ANOMALY_METRICS,
    DepartmentFamily,
    ErrorClass,
    FailureCode,
    all_closed_values,
    closed_lists_version,
    count_bucket,
    duration_bucket,
    failure_rate_metric,
    gap_bucket,
    owner_of,
    strata_codes,
    topics,
)

PLANTED = "Jan Kowalski from Warsaw, phone +48 601 234 567, asked about salary"


def test_settings_and_env():
    s = get_settings()
    assert s.env.emulator and s.projects.write == "local-project"
    assert s.table("turns", "quality_turns") == "local-project.bolek_quality_turns.quality_turns"
    assert s.data_store("rtb-crj-confluence").topic == "CONFLUENCE"
    assert s.data_store("nope") is None
    assert s.bucket_for("rtb-crj-confluence") == s.content_bucket


def test_now_pinned(monkeypatch):
    monkeypatch.setenv("CA_NOW", "2026-10-28T10:00:00+00:00")
    assert now() == datetime(2026, 10, 28, 10, tzinfo=UTC)
    monkeypatch.delenv("CA_NOW")
    assert now().tzinfo is not None


def test_vocab_helpers():
    assert gap_bucket(0.5) == "UNDER_1_MIN" and gap_bucket(3) == "1_5_MIN" and gap_bucket(10) == "5_30_MIN"
    assert gap_bucket(45) == "30_60_MIN" and gap_bucket(90) == "OVER_60_MIN"
    assert duration_bucket(0) == "UNDER_1_MIN" and duration_bucket(90) == "1_2_H" and duration_bucket(500) == "OVER_2_H"
    assert count_bucket(0) == "0" and count_bucket(1) == "1" and count_bucket(5) == "2_OR_MORE"
    assert (
        owner_of(FailureCode.OUTDATED_SOURCE) == "DOCUMENT_OWNER"
        and owner_of(FailureCode.NOT_IN_CITED_SOURCES) == "TEAM"  # the team finds out if search or corpus failed
    )
    assert "OTHER" in topics() and "DOC_REPO" in topics()
    assert closed_lists_version().startswith("cl-")
    assert len(ANOMALY_METRICS) == 17  # standardized AQR, 14 failure rates, negative reactions, coverage (§8.7)
    assert failure_rate_metric(FailureCode.NOT_IN_CITED_SOURCES) in all_closed_values()
    assert len(strata_codes()) == 4 * 3 * 6  # intent × data-store × department families (§8.4)
    assert "PROCEDURE__ENGINEERING__UNKNOWN" in all_closed_values()


def test_department_families_are_closed(monkeypatch):
    s = get_settings().strata
    assert set(s.department_families) <= set(DepartmentFamily) - {DepartmentFamily.UNKNOWN}
    before = closed_lists_version()
    monkeypatch.setitem(s.department_families, "ENGINEERING", [*s.department_families["ENGINEERING"], "Board"])
    closed_lists_version.cache_clear()
    try:
        assert closed_lists_version() != before  # a change of the mapping is a new closed-lists version
    finally:
        monkeypatch.undo()
        closed_lists_version.cache_clear()
    with pytest.raises(ValueError, match="more than one"):
        type(s)(**{**s.model_dump(), "department_families": {"ENGINEERING": ["IT"], "CORPORATE": ["IT"]}})


def test_safe_log_rejects_text(capsys):
    safe_log.log(
        "run_done",
        run_id="run-0123abcd",
        assessed=3,
        ratio=0.5,
        ok=True,
        code="HIGH",
        job="quality-assessor",
        version="v1",
        model="gemini-3.8-flash",
        note=PLANTED,
        nested={"n": 1, "t": PLANTED},
        items=[1, PLANTED],
        obj=object(),
        **{"Bad Key": 1},
    )
    safe_log.log("Bad Event", severity="LOUD")
    out = capsys.readouterr().out
    assert "Kowalski" not in out and "601" not in out
    first, second = (json.loads(line) for line in out.strip().splitlines())
    assert first["note"] == safe_log.REJECTED and first["assessed"] == 3 and first["code"] == "HIGH"
    assert first["nested"] == {"n": 1, "t": safe_log.REJECTED} and first["obj"] == safe_log.REJECTED
    assert second == {"severity": "INFO", "event": safe_log.REJECTED}


def test_keys_are_stable_keyed_hashes():
    name = "projects/1/locations/eu/collections/default_collection/engines/e1/sessions/S1/assistAnswers/A1"
    assert keys.parse_answer_name(name) == ("e1", "S1")
    assert keys.parse_answer_name("garbage") is None
    assert keys.session_from_name("projects/1/locations/eu/collections/c/engines/e1/sessions/S1") == ("e1", "S1")
    assert keys.session_from_name(None) is None
    sk = keys.session_key("e1", "S1")
    assert len(sk) == 32 and sk == keys.session_key("e1", "S1") and sk != keys.session_key("e1", "S2")
    assert keys.turn_key(name) != keys.turn_key(name + "x")
    assert 0 <= keys.stable_fraction("abc") < 1


def test_secrets_env_backend(monkeypatch):
    assert secrets.hash_key() == b"local-hash-key"
    assert secrets.content_secrets() == (b"local-content-key", b"local-content-salt")
    with pytest.raises(KeyError):
        secrets.secret("missing-secret")


def test_secrets_gcp_backend(monkeypatch):
    class FakeClient:
        def access_secret_version(self, name):
            assert name == "projects/p1/secrets/s1/versions/latest"
            return type("R", (), {"payload": type("P", (), {"data": b"v"})})()

    import google.cloud.secretmanager as sm

    monkeypatch.setattr(sm, "SecretManagerServiceClient", FakeClient)
    monkeypatch.setattr(get_settings().env, "secrets_backend", "gcp")
    secrets.secret.cache_clear()
    try:
        assert secrets.secret("s1", "p1") == b"v"
    finally:
        monkeypatch.setattr(get_settings().env, "secrets_backend", "env")
        secrets.secret.cache_clear()


def test_error_classes_and_sentry_scrub(monkeypatch):
    assert errors.classify(LeakGuardError()) == ErrorClass.LEAK_GUARD
    assert errors.classify(errors.AnalyzerError(ErrorClass.SLACK)) == ErrorClass.SLACK
    assert errors.classify(TimeoutError()) == ErrorClass.TIMEOUT
    assert errors.classify(ValueError(PLANTED)) == ErrorClass.UNEXPECTED
    from google.api_core.exceptions import BadRequest

    assert errors.classify(BadRequest("x")) == ErrorClass.BIGQUERY
    event = {
        "event_id": "e",
        "level": "error",
        "tags": {"error_class": "LEAK_GUARD", "user": PLANTED},
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": PLANTED,
                    "stacktrace": {
                        "frames": [{"filename": "a.py", "function": "f", "lineno": 3, "vars": {"q": PLANTED}}]
                    },
                }
            ]
        },
        "extra": {"q": PLANTED},
        "request": {"data": PLANTED},
        "breadcrumbs": [PLANTED],
    }
    clean = errors.scrub_event(event)
    assert PLANTED not in json.dumps(clean)
    assert clean["message"] == "LEAK_GUARD" and clean["exception"]["values"][0]["type"] == "ValueError"
    assert errors.report(LeakGuardError()) == ErrorClass.LEAK_GUARD  # no DSN: nothing is sent

    sent = []
    monkeypatch.setattr(get_settings().env, "sentry_dsn", "https://k@sentry.invalid/1")
    monkeypatch.setattr(errors.sentry_sdk, "init", lambda **kw: sent.append(("init", kw["before_send"])))
    monkeypatch.setattr(errors.sentry_sdk, "capture_exception", lambda exc: sent.append(("capture", type(exc))))
    errors.init_sentry("quality-assessor")
    assert errors.report(ValueError(PLANTED)) == ErrorClass.UNEXPECTED
    assert sent[0][1] is errors.scrub_event and sent[1] == ("capture", ValueError)


def _turn_row(**over):
    row = {
        "turn_key": "a" * 32,
        "session_key": "b" * 32,
        "segment_no": 1,
        "day": date(2026, 10, 28),
        "channel": "WEB_UI",
        "status": "ASSESSED",
        "flag_reasons": ["DISLIKE"],
        "cited_docs": [
            {
                "doc_id": "confluence_X_1_v2",
                "data_store": "rtb-crj-confluence",
                "uri": "https://rtbhouseproduct.atlassian.net/wiki/x",
            }
        ],
    }
    row.update(over)
    return row


def test_leak_guard_accepts_derived_values():
    assert check_row(QUALITY_TURNS, _turn_row(department="CAMPAIGNS"))["department"] == "CAMPAIGNS"
    row = check_row(QUALITY_TURNS, _turn_row(base_function="Technical Support", user_key=keys.user_key("a@b.com")))
    assert row["base_function"] == "Technical Support" and len(row["user_key"]) == 32
    assert check_row(QUALITY_TURNS, _turn_row(base_function="OTHER"))["base_function"] == "OTHER"
    seg = {"session_key": "b" * 32, "segment_no": 1, "department": "UNKNOWN"}
    assert check_row(SEGMENTS, seg)["department"] == "UNKNOWN"
    with pytest.raises(LeakGuardError):
        check_row(SEGMENTS, {**seg, "department": "Technical Support"})
    out = check_row(QUALITY_TURNS, _turn_row())
    assert out["cited_docs"][0]["uri"].startswith("https://rtbhouseproduct")
    assert out["found_docs"] == [] and out["gap_bucket"] is None


@pytest.mark.parametrize(
    "over",
    [
        {"channel": PLANTED},
        {"turn_key": PLANTED},
        {"segment_no": "1"},
        {"segment_no": True},
        {"day": "2026-10-28"},
        {"day": datetime(2026, 10, 28)},
        {"flagged": 1},
        {"flag_reasons": PLANTED},
        {"unknown_column": 1},
        {"judge_version": "has space"},
        {"cited_docs": [{"doc_id": "x", "data_store": "rtb-crj-confluence", "q": 1}]},
        {"cited_docs": [{"doc_id": PLANTED, "data_store": "rtb-crj-confluence"}]},
        {"department": "IT"},  # a base_function, never stored (§8.4)
        {"department": "HIGH"},  # a closed value, but not a department family
        {"department": "anna@rtbhouse.com"},
        {"base_function": "Jan Kowalski"},  # not a listed base_function
        {"base_function": "ENGINEERING"},
        {"base_function": "anna@rtbhouse.com"},
        {"user_key": "anna@rtbhouse.com"},
    ],
)
def test_leak_guard_rejects_text(over):
    with pytest.raises(LeakGuardError):
        check_row(QUALITY_TURNS, _turn_row(**over))


def test_leak_guard_drops_people_directory_and_unknown_stores():
    docs = [
        {"doc_id": "associate-abc", "data_store": "rtb-crj-associates", "uri": "mailto:jan@rtbhouse.com"},
        {"doc_id": "p1", "data_store": "people-connections_1762414462976_users", "uri": None},
        {"doc_id": "x1", "data_store": "some-unknown-store", "uri": None},
        {
            "doc_id": "drive1",
            "data_store": "gdrive_collection_22062025_google_drive",
            "uri": "https://evil.example.com/x",
        },
    ]
    out = check_row(QUALITY_TURNS, _turn_row(cited_docs=docs, data_stores=["rtb-crj-confluence"]))
    assert out["cited_docs"] == [
        {"doc_id": "drive1", "data_store": "gdrive_collection_22062025_google_drive", "uri": None}
    ]
    with pytest.raises(LeakGuardError):
        check_row(QUALITY_TURNS, _turn_row(data_stores=["rtb-crj-associates"]))
    with pytest.raises(LeakGuardError):
        check_row(
            STAGE2_RESULTS,
            {
                "turn_key": "a" * 32,
                "judge_version": "v1",
                "claims": [{"position": 1, "what": "CONTRADICTED_CLAIM", "documents": [], "extra": 1}],
            },
        )


def test_people_directory_and_links():
    assert is_people_directory("rtb-crj-associates") and is_people_directory(None, "associate-1")
    assert is_people_directory(None, None, "mailto:x@y") and not is_people_directory("rtb-crj-confluence")
    assert allowed_link("https://sites.google.com/rtbhouse.com/hr-house/leave", "rtb-crj-hr-house")
    assert not allowed_link("https://sites.google.com/rtbhouse.com/other", "rtb-crj-hr-house")
    assert not allowed_link("http://rtbhouseproduct.atlassian.net/x", None)
    assert not allowed_link("https://u:p@rtbhouseproduct.atlassian.net/x", None)
    assert allowed_link("https://rtbhouseproduct.atlassian.net/x", None)
    assert not allowed_link("https://[bad", None)


def test_leak_guard_kinds():
    from conversation_analyzer.bq.schema import ALERTS, CHANGE_EVENTS, RUNS, SUITE_RUNS

    ok = check_row(
        RUNS,
        {
            "run_id": "run-0011aabb",
            "started_at": datetime(2026, 10, 28, tzinfo=UTC),
            "oldest_waiting_minutes": 3,
            "tokens": [{"model": "gemini-3.8-flash", "input_tokens": 5}],
        },
    )
    assert ok["oldest_waiting_minutes"] == 3.0
    for bad in (
        {"started_at": date(2026, 1, 1)},
        {"oldest_waiting_minutes": "3"},
        {"oldest_waiting_minutes": True},
        {"tokens": {"model": "x"}},
        {"run_id": "run-xyz"},
    ):
        with pytest.raises(LeakGuardError):
            check_row(RUNS, {"run_id": "run-0011aabb", **bad})
    check_row(ALERTS, {"alert_id": "alert-00112233", "slack_ts": "1700000000.000100", "slack_channel": "#q"})
    with pytest.raises(LeakGuardError):
        check_row(ALERTS, {"alert_id": "alert-00112233", "slack_ts": "yesterday"})
    check_row(
        CHANGE_EVENTS,
        {
            "event_id": "evt-00112233",
            "repository": "RTBHouse-OEET/aiel-infrastructure",
            "commit_sha": "abc1234",
            "execution": "indexer-confluence-x1",
        },
    )
    with pytest.raises(LeakGuardError):
        check_row(CHANGE_EVENTS, {"event_id": "evt-00112233", "repository": "someone/else"})
    check_row(
        SUITE_RUNS,
        {
            "suite_run_id": "suite-00112233",
            "per_scenario": [{"scenario": "intent:FACT_LOOKUP", "distance": 0.1, "n": 3}],
        },
    )
    with pytest.raises(LeakGuardError):
        check_row(SUITE_RUNS, {"suite_run_id": "suite-00112233", "per_scenario": [{"scenario": PLANTED}]})
    weird = Table("turns", "t", (RUNS.cols[0].__class__("x", "STRING", "unknown-kind"),), key=("x",), writer="w")
    with pytest.raises(LeakGuardError):
        check_row(weird, {"x": "v"})


def test_ddl():
    sql = ddl(QUALITY_TURNS, emulator=False)
    assert "PARTITION BY day" in sql and "partition_expiration_days = 365" in sql
    assert "ARRAY<STRUCT<doc_id STRING, data_store STRING, uri STRING>>" in sql
    assert "partition_expiration_days" not in ddl(QUALITY_TURNS, emulator=True)
    assert "PARTITION" not in ddl(RUNS, emulator=True, name_override="_stg")
