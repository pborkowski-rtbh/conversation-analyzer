"""The `ca` command: each job runs its module, failures leave as an error class and exit code 1."""

from __future__ import annotations

import json
import sys
import types

import pytest
from click.testing import CliRunner

from conversation_analyzer import cli
from conversation_analyzer.errors import JudgeApiError
from conversation_analyzer.settings import get_settings


def events(output: str) -> list[dict]:
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


def fake_module(monkeypatch, name: str, **attrs) -> None:
    module = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(module, k, v)
    monkeypatch.setitem(sys.modules, name, module)


def test_assessor_job_runs_and_logs(monkeypatch):
    calls = []
    fake_module(monkeypatch, "conversation_analyzer.assessor.run", run=lambda: calls.append(1))
    result = CliRunner().invoke(cli.main, ["quality-assessor"])
    assert result.exit_code == 0 and calls == [1]
    assert [e["event"] for e in events(result.output)] == ["job_start", "job_done"]


def test_failed_job_exits_with_error_class_only(monkeypatch):
    def boom():
        raise JudgeApiError()

    fake_module(monkeypatch, "conversation_analyzer.assessor.run", run=boom)
    result = CliRunner().invoke(cli.main, ["quality-assessor"])
    assert result.exit_code == 1
    failed = events(result.output)[-1]
    assert failed == {"severity": "ERROR", "event": "job_failed", "job": "quality-assessor", "error_class": "JUDGE_API"}


@pytest.mark.parametrize(
    ("args", "module", "func", "expected"),
    [
        (["quality-monitor"], "conversation_analyzer.reporting.monitor", "run", ()),
        (["quality-daily", "--day", "2026-10-27"], "conversation_analyzer.reporting.daily", "run", ("2026-10-27",)),
        (["quality-weekly"], "conversation_analyzer.reporting.weekly", "run", (None,)),
        (
            [
                "quality-record",
                "--kind",
                "DOCUMENT",
                "--doc-id",
                "d",
                "--data-store",
                "rtb-crj-confluence",
                "--cluster",
                "c1",
                "--cluster",
                "c2",
            ],
            "conversation_analyzer.reporting.record",
            "record",
            ("DOCUMENT", None, None, "d", "rtb-crj-confluence", ["c1", "c2"]),
        ),
    ],
)
def test_jobs_dispatch_to_their_modules(monkeypatch, args, module, func, expected):
    seen = []
    fake_module(monkeypatch, module, **{func: lambda *a, **k: seen.append((a, k))})
    result = CliRunner().invoke(cli.main, args)
    assert result.exit_code == 0, result.output
    assert seen == [(expected, {})]


def test_judge_suite_options(monkeypatch):
    seen = []
    report = {
        "suite_run_id": "suite-00112233",
        "decision": "KEEP",
        "n_cases": 5,
        "passes": 1,
        "tuning_distance": 1.5,
        "held_out_distance": None,
        "false_high": 0,
        "failed_calls": 0,
        "estimated_usd": 0.1,
    }

    def run(**k):
        seen.append(k)
        return report

    fake_module(monkeypatch, "conversation_analyzer.suite.runner", run=run)
    args = ["quality-judge-suite", "--passes", "1", "--part", "tuning", "--limit", "5", "--judge-version", "v2"]
    result = CliRunner().invoke(cli.main, args)
    assert result.exit_code == 0, result.output
    assert seen == [{"passes": 1, "part": "tuning", "limit": 5, "baseline": None, "judge_version": "v2"}]
    assert "suite_run_id=suite-00112233 decision=KEEP" in result.output


def test_judge_suite_check_reports_coverage(monkeypatch):
    from conversation_analyzer.suite import cases

    result = CliRunner().invoke(cli.main, ["quality-judge-suite", "--check"])
    assert result.exit_code == 0, result.output
    assert "intent:FACT_LOOKUP" in result.output and "SHORT" not in result.output
    suite = cases.load_suite()
    monkeypatch.setattr(cases, "load_suite", lambda: suite.model_copy(update={"cases": suite.cases[:3]}))
    result = CliRunner().invoke(cli.main, ["quality-judge-suite", "--check"])
    assert result.exit_code == 1 and "SHORT" in result.output and "below their minimum" in result.output


def test_db_init(monkeypatch):
    fake_module(monkeypatch, "conversation_analyzer.bq.init", create_all=lambda: ["a", "b"])
    result = CliRunner().invoke(cli.main, ["db-init"])
    assert result.exit_code == 0 and events(result.output) == [{"severity": "INFO", "event": "db_init", "tables": 2}]


def test_dev_seed_only_on_the_emulator(monkeypatch):
    seeded = []
    fake_module(
        monkeypatch,
        "conversation_analyzer.devtools.scenario",
        seed=lambda now: seeded.append(now),
        turns=lambda: [1, 2],
    )
    import conversation_analyzer.devtools as devtools

    monkeypatch.setattr(devtools, "scenario", sys.modules["conversation_analyzer.devtools.scenario"], raising=False)
    result = CliRunner().invoke(cli.main, ["dev-seed", "--now", "2026-10-28T12:00:00+00:00"])
    assert result.exit_code == 0 and seeded[0].hour == 12
    monkeypatch.setattr(get_settings().env, "bq_endpoint", None)
    result = CliRunner().invoke(cli.main, ["dev-seed"])
    assert result.exit_code == 2 and len(seeded) == 1


def test_alert_lookup_prints_json_or_fails(monkeypatch):
    found = {"alert": {"alert_id": "alert-1", "kind": "HIGH_CLUSTER"}, "sessions": []}
    fake_module(
        monkeypatch, "conversation_analyzer.reporting.lookup", lookup=lambda a: found if a == "alert-1" else None
    )
    result = CliRunner().invoke(cli.main, ["quality-alert-lookup", "--alert", "alert-1"])
    assert result.exit_code == 0 and json.loads(result.output) == found
    result = CliRunner().invoke(cli.main, ["quality-alert-lookup", "--alert", "alert-2"])
    assert result.exit_code == 1 and "no such alert" in result.output
