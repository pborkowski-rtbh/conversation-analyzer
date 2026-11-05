"""Environments, the run gate, dry run, kill switches, `db-init --check` and `leak-audit` (deployment-plan.md A6)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from click.testing import CliRunner
from google.cloud import bigquery

from conversation_analyzer import cli, run_gate
from conversation_analyzer import settings as settings_mod
from conversation_analyzer.assessor.run import run as assess
from conversation_analyzer.bq import audit, check
from conversation_analyzer.bq.client import client, fq, schema_fields, write
from conversation_analyzer.bq.external import AUDIT_LOGS
from conversation_analyzer.bq.schema import (
    ALERTS,
    EVAL_DOCUMENTS,
    PIPELINE_HEALTH,
    QUALITY_TURNS,
    RUNS,
    STAGE1_RESULTS,
    TABLES,
    Col,
    ddl,
)
from conversation_analyzer.bq.views import views
from conversation_analyzer.devtools import scenario
from conversation_analyzer.devtools.synthetic import ensure_bucket
from conversation_analyzer.docs.content import storage_client
from conversation_analyzer.docs.source import RunDocuments
from conversation_analyzer.judge.fake import FakeJudge
from conversation_analyzer.people.directory import split_uri
from conversation_analyzer.reporting import monitor
from conversation_analyzer.reporting.completeness import HourCheck
from conversation_analyzer.settings import get_settings
from tests.conftest import rows, wipe
from tests.test_monitor import run_row

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
GATE = "gs://local-quality-control/run-gate.json"


def events(output: str) -> list[dict]:
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


@pytest.fixture
def env(monkeypatch):
    """Load the settings of another environment for one test (string building only, no client is made)."""

    def load(name: str):
        monkeypatch.setenv("CA_ENV", name)
        get_settings.cache_clear()
        return get_settings()

    yield load
    monkeypatch.setenv("CA_ENV", "local")
    get_settings.cache_clear()


# ---------------------------------------------------------------------- environments (no emulator)


def test_stage_prefixes_our_datasets_and_reads_prod(env):
    s = env("stage")
    assert s.environment == "stage"
    assert s.dataset_id("turns") == "rtb-aiel-core-stage.stage_bolek_quality_turns"
    assert s.dataset_id("metrics") == "rtb-aiel-core-stage.stage_bolek_quality_metrics"
    assert s.dataset_id("log_views") == "rtb-aiel-core-stage.stage_bolek_quality_log_views"
    assert s.dataset_id("log") == "rtbhouse-agentspace.analytics"  # the prod log, not prefixed
    assert s.dataset_id("evals") == "rtbhouse-agentspace.aiel_evals"
    assert fq("turns", "quality_runs") == "`rtb-aiel-core-stage.stage_bolek_quality_turns.quality_runs`"
    assert "`rtb-aiel-core-stage.stage_bolek_quality_turns.quality_runs`" in ddl(RUNS, emulator=False)
    assert "partition_expiration_days = 365" in ddl(RUNS, emulator=False)
    assert "`rtbhouse-agentspace.analytics.audit_logs`" in views()["quality_turn_counts_hourly"]
    assert "rtbhouse-agentspace.analytics.audit_logs" in ddl(AUDIT_LOGS, emulator=True)
    assert s.run_gate.uri == "gs://rtb-aiel-core-stage-quality-control/run-gate.json"
    assert s.secrets.project == "rtb-aiel-core-stage" and s.secrets.content_project == "rtbhouse-agentspace"
    assert s.judge.vertex_project == "rtb-aiel-core-stage" and s.judge.location == "eu"
    assert s.judge.daily_token_limit == 6_000_000
    assert s.alerts.quality_channel == s.alerts.alerts_channel == "#bolek-quality-stage"
    assert s.people_directory.map_uri.startswith("gs://rtb-aiel-core-stage-indexers-state/")


def test_prod_has_no_prefix_and_no_gate(env):
    s = env("prod")
    assert s.dataset_id("turns") == "rtbhouse-agentspace.bolek_quality_turns"
    assert s.run_gate.uri is None and run_gate.is_open()
    assert s.judge.vertex_project == "rtbhouse-agentspace"
    assert (s.alerts.quality_channel, s.alerts.alerts_channel) == ("#bolek-quality", "#aiel-alerts")
    assert s.stage2.enabled and s.evidence_check.enabled
    # Common values come through the merge untouched.
    assert s.judge.current_version == env("local").judge.current_version


def test_ca_env_is_required(env, monkeypatch):
    monkeypatch.delenv("CA_ENV")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="CA_ENV"):
        get_settings()
    with pytest.raises(RuntimeError):
        env("staging")


def test_overlay_merges_nested_keys():
    base = {"judge": {"location": "eu", "concurrency": 8}, "list": [1, 2]}
    merged = settings_mod._merge(base, {"judge": {"concurrency": 2}, "list": [3]})
    assert merged == {"judge": {"location": "eu", "concurrency": 2}, "list": [3]}
    assert base["judge"]["concurrency"] == 8


# ---------------------------------------------------------------------- CLI (no emulator)


def fake_assessor(monkeypatch, calls):
    import sys
    import types

    module = types.ModuleType("conversation_analyzer.assessor.run")
    module.run = lambda dry_run=False: calls.append(("run", dry_run))
    module.paused = lambda: calls.append(("paused", None))
    monkeypatch.setitem(sys.modules, "conversation_analyzer.assessor.run", module)


def test_closed_gate_writes_a_paused_record_and_exits_0(monkeypatch):
    calls = []
    fake_assessor(monkeypatch, calls)
    monkeypatch.setattr(run_gate, "is_open", lambda at=None: False)
    result = CliRunner().invoke(cli.main, ["quality-assessor"])
    assert result.exit_code == 0 and calls == [("paused", None)]
    assert [e["event"] for e in events(result.output)] == ["job_start", "gate_closed", "job_done"]
    result = CliRunner().invoke(cli.main, ["quality-assessor", "--ignore-gate", "--dry-run"])
    assert result.exit_code == 0 and calls[-1] == ("run", True)


@pytest.mark.parametrize(
    ("args", "module"),
    [
        (["quality-monitor"], "conversation_analyzer.reporting.monitor"),
        (["quality-daily"], "conversation_analyzer.reporting.daily"),
        (["quality-weekly"], "conversation_analyzer.reporting.weekly"),
    ],
)
def test_closed_gate_stops_the_other_jobs_without_a_record(monkeypatch, args, module):
    import sys
    import types

    calls = []
    fake = types.ModuleType(module)
    fake.run = lambda *a: calls.append(a)
    monkeypatch.setitem(sys.modules, module, fake)
    monkeypatch.setattr(run_gate, "is_open", lambda at=None: False)
    result = CliRunner().invoke(cli.main, args)
    assert result.exit_code == 0 and calls == [] and "gate_closed" in result.output
    assert CliRunner().invoke(cli.main, [*args, "--ignore-gate"]).exit_code == 0 and len(calls) == 1


def test_db_check_and_leak_audit_exit_codes(monkeypatch):
    monkeypatch.setattr(check, "differences", lambda: ["quality_runs.dry_run: missing column"])
    result = CliRunner().invoke(cli.main, ["db-init", "--check"])
    assert result.exit_code == 1 and "quality_runs.dry_run: missing column" in result.output
    monkeypatch.setattr(check, "differences", lambda: [])
    assert CliRunner().invoke(cli.main, ["db-init", "--check"]).exit_code == 0

    counts = [audit.TableAudit("quality_runs", rows=3), audit.TableAudit("quality_turns", rows=2, too_long=1)]
    monkeypatch.setattr(audit, "audit", lambda since: counts)
    result = CliRunner().invoke(cli.main, ["leak-audit", "--since", "2026-10-01"])
    assert result.exit_code == 1 and events(result.output)[-1]["findings"] == 1
    counts.pop()
    assert CliRunner().invoke(cli.main, ["leak-audit", "--since", "2026-10-01"]).exit_code == 0


def test_run_gate_commands(monkeypatch):
    assert CliRunner().invoke(cli.main, ["run-gate", "resume", "--hours", "25"]).exit_code == 2
    result = CliRunner().invoke(cli.main, ["run-gate", "status"])
    assert result.exit_code == 0 and "no gate" in result.output
    with pytest.raises(ValueError):
        run_gate.resume(0)
    with pytest.raises(RuntimeError):
        run_gate.pause()  # no gate in this environment


# ---------------------------------------------------------------------- schema check and audit helpers


def test_compare_finds_every_kind_of_difference():
    want = check._shape(
        schema_fields((Col("a", "INT64", "int"), Col("s", "STRUCT", "struct", fields=(Col("x", "STRING", "enum"),))))
    )
    have = check._shape(
        [
            bigquery.SchemaField("a", "STRING"),
            bigquery.SchemaField("s", "RECORD", fields=[bigquery.SchemaField("y", "STRING")]),
            bigquery.SchemaField("extra", "BOOLEAN"),
        ]
    )
    assert check._compare("t", want, have) == [
        "t.a: NULLABLE STRING, expected NULLABLE INT64",
        "t.extra: column not in bq/schema.py",
        "t.s.x: missing column",
        "t.s.y: column not in bq/schema.py",
    ]
    legacy = check._shape([bigquery.SchemaField("a", "INTEGER")])
    assert check._compare("t", {"a": want["a"]}, legacy) == []


def test_partitioning_and_expiry_on_real_bigquery():
    live = bigquery.Table("p.d.quality_runs")
    assert check._partitioning(RUNS, live) == ["quality_runs: partitioned by None, expected run_day"]
    live.time_partitioning = bigquery.TimePartitioning(field="run_day", expiration_ms=365 * 86_400_000)
    assert check._partitioning(RUNS, live) == []
    live.time_partitioning = bigquery.TimePartitioning(field="run_day")
    assert "partition expiry" in check._partitioning(RUNS, live)[0]
    unpartitioned = next(t for t in TABLES if not t.partition)
    assert check._partitioning(unpartitioned, bigquery.Table(f"p.d.{unpartitioned.name}")) == []


def test_audit_reads_json_values_back():
    assert audit._fold([[{"a": 1}, {"b": 2}]]) == {"a": 1, "b": 2}
    assert audit._one(Col("n", "INT64", "int"), "12") == 12
    assert audit._one(Col("b", "BOOL", "bool"), 0) is False
    assert audit._one(Col("d", "DATE", "date"), "2026-10-28") == date(2026, 10, 28)
    assert audit._one(Col("t", "TIMESTAMP", "ts"), "2026-10-28 12:00:00Z") == NOW
    assert audit._value(Col("e", "STRING", "enum", "REPEATED"), None) == []
    long_link = {"uri": "https://x/" + "a" * 3000}
    assert audit._too_long((Col("uri", "STRING", "link"),), long_link)
    assert not audit._too_long((Col("uri", "STRING", "link"),), {"uri": "https://x/" + "a" * 300})
    assert audit._too_long((Col("e", "STRING", "enum", "REPEATED"),), {"e": ["a" * 201]})


# ---------------------------------------------------------------------- run gate on fake GCS


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.setattr(get_settings().run_gate, "uri", GATE)
    bucket, path = split_uri(GATE)
    ensure_bucket(bucket)
    blob = storage_client().bucket(bucket).blob(path)
    if blob.exists():
        blob.delete()
    return blob


@pytest.mark.emulator
def test_run_gate_opens_for_hours_and_closes_itself(gate, monkeypatch):
    assert run_gate.open_until() is None and not run_gate.is_open(NOW)  # no object: closed
    until = run_gate.resume(2, at=NOW)
    assert until == NOW + timedelta(hours=2) and run_gate.open_until() == until
    assert run_gate.is_open(NOW + timedelta(hours=1)) and not run_gate.is_open(NOW + timedelta(hours=2))
    run_gate.pause(at=NOW)
    assert not run_gate.is_open(NOW)
    gate.upload_from_string("{not json")
    assert not run_gate.is_open(NOW)
    gate.upload_from_string(json.dumps({"open_until": "2026-10-28T13:00:00"}))  # no time zone: not trusted
    assert not run_gate.is_open(NOW)
    monkeypatch.setenv("CA_NOW", NOW.isoformat())
    assert (
        "open until 2026-10-28T15:00:00+00:00"
        in CliRunner().invoke(cli.main, ["run-gate", "resume", "--hours", "3"]).output
    )
    assert CliRunner().invoke(cli.main, ["run-gate", "status"]).output.startswith("open")
    CliRunner().invoke(cli.main, ["run-gate", "pause"])
    assert CliRunner().invoke(cli.main, ["run-gate", "status"]).output.startswith("closed")


@pytest.mark.emulator
def test_closed_gate_on_the_emulator(gate, emulator, monkeypatch):
    wipe(RUNS, QUALITY_TURNS, PIPELINE_HEALTH)
    monkeypatch.setenv("CA_NOW", NOW.isoformat())
    result = CliRunner().invoke(cli.main, ["quality-assessor"])
    assert result.exit_code == 0, result.output
    (record,) = rows(RUNS)
    assert record["status"] == "PAUSED" and record["turns_read"] == 0 and record["tokens"] == []
    assert record["search_cutoff"] is None and not rows(QUALITY_TURNS)
    assert CliRunner().invoke(cli.main, ["quality-monitor"]).exit_code == 0
    assert not rows(PIPELINE_HEALTH)  # the monitor wrote nothing while closed


# ---------------------------------------------------------------------- dry run and kill switches


@pytest.mark.emulator
def test_dry_run_reads_the_window_and_writes_only_the_run_record(emulator):
    wipe()
    scenario.seed(NOW)  # the scenario also stores a suite run
    before = [len(rows(t)) for t in TABLES]
    record = assess(now=NOW, docs=RunDocuments(), dry_run=True)
    assert record["dry_run"] and record["status"] == "OK" and record["turns_read"] == 22
    assert record["eligible"] > 0 and record["assessed"] == 0 and record["tokens"] == []
    assert record["search_cutoff"] is None and record["feedback_cutoff"] is None
    after = [len(rows(t)) for t in TABLES]
    assert [t.name for t, n, m in zip(TABLES, before, after, strict=True) if n != m] == [RUNS.name]
    (stored,) = rows(RUNS)
    assert stored["dry_run"] is True
    real = assess(now=NOW + timedelta(minutes=10), judge=FakeJudge(), docs=RunDocuments())
    assert real["assessed"] > 0 and real["feedback_matched"] == record["feedback_matched"]  # nothing skipped


@pytest.mark.emulator
def test_kill_switches_keep_stage1_running(emulator, monkeypatch):
    wipe()
    monkeypatch.setattr(get_settings().stage2, "enabled", False)
    monkeypatch.setattr(get_settings().evidence_check, "enabled", False)
    scenario.seed(NOW)
    judge = FakeJudge()
    record = assess(now=NOW, judge=judge, docs=RunDocuments())
    assert record["assessed"] > 0 and rows(STAGE1_RESULTS)
    assert record["evidence_checks"] == 0 and record["stage2_done"] == 0 and record["session_grades"] == 0
    assert record["stage2_pending"] > 0  # flagged turns wait; they give up at 3h30 as usual
    forms = {form for _, form in judge.calls}
    assert not forms & {"EvidenceCheckForm", "Stage2Form", "SessionGradeForm"}


# ---------------------------------------------------------------------- monitor around paused periods


@pytest.mark.emulator
def test_monitor_expects_no_run_while_paused_and_for_3h30_after(emulator, stubs, monkeypatch):
    wipe()
    now = datetime(2026, 10, 28, 12, 5, tzinfo=UTC)
    write(
        RUNS,
        [
            run_row("run-000000a1", 120, status="PAUSED", eligible=0, covered=0),
            run_row("run-000000a2", 60, covered=5),  # 1h after the pause: low coverage is expected
            run_row("run-000000a3", 50, covered=5, dry_run=True),
        ],
    )
    monkeypatch.setattr(monitor, "check_hours", lambda hours: [HourCheck(hours[0], "WEB_UI", 0, 50.0, True)])
    monitor.run(now)
    health = {r["run_id"]: r for r in rows(PIPELINE_HEALTH)}
    assert health["run-000000a1"]["run_status"] == "PAUSED" and health["run-000000a1"]["checks_fired"] == []
    assert health["run-000000a2"]["no_run_expected"] and health["run-000000a2"]["checks_fired"] == []
    assert health[None]["kind"] == "LOG_HOUR" and health[None]["log_gap"] and health[None]["checks_fired"] == []
    assert not rows(ALERTS)  # no coverage, no-run or log-gap alert; the stale last run is within the pause too

    wipe(PIPELINE_HEALTH, ALERTS)
    later = now + timedelta(hours=4)
    write(RUNS, [run_row("run-000000a4", -4 * 60 + 5, covered=5)])  # 16:00, 5h55 after the pause
    monitor.run(later)
    checks = {r["run_id"]: r["checks_fired"] for r in rows(PIPELINE_HEALTH) if r["kind"] == "RUN"}
    assert checks["run-000000a4"] == ["COVERAGE"]
    assert checks["run-000000a3"] == []  # a dry run judges nothing, so it is never short of coverage


# ---------------------------------------------------------------------- db-init --check and leak-audit on the emulator


@pytest.mark.emulator
def test_schema_check_matches_and_finds_a_difference(emulator, monkeypatch):
    assert check.differences() == []
    changed = RUNS.__class__(**{**RUNS.__dict__, "cols": (*RUNS.cols, Col("new_count", "INT64", "int"))})
    monkeypatch.setattr(check, "TABLES", tuple(changed if t is RUNS else t for t in TABLES))
    assert check.differences() == ["quality_runs.new_count: missing column"]


@pytest.mark.emulator
def test_leak_audit_counts_what_the_guard_would_refuse(emulator):
    wipe(RUNS, EVAL_DOCUMENTS)
    write(RUNS, [run_row("run-000000b1", 5)])
    day = NOW.date().isoformat()
    # Rows that bypass bq/client.write, as a broken writer or a hand-made row would.
    good = {"period": day, "eval_set": "ANCHOR", "doc_id": "d1", "data_store": "rtb-crj-confluence", "n_questions": 1}
    bad = [
        {**good, "doc_id": "d2", "uri": "https://rtbhouseproduct.atlassian.net/" + "p" * 3000},  # too long, dropped
        {**good, "doc_id": "d3", "uri": "https://example.com/page"},  # a link the guard drops
        {**good, "doc_id": "d4", "eval_set": "Tell me about the bonus scheme"},  # text in a code column
    ]
    assert not client().insert_rows_json(get_settings().table("metrics", EVAL_DOCUMENTS.name), [good, *bad])
    found = {a.table: a for a in audit.audit(NOW.date() - timedelta(days=1))}
    assert found["quality_runs"].rows == 1 and found["quality_runs"].findings == 0
    docs = found["quality_eval_documents"]
    assert (docs.rows, docs.too_long, docs.dropped, docs.rejected) == (4, 1, 2, 1)
    assert sum(a.findings for a in found.values()) == 4
