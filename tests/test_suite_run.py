"""A suite run is stored, compared with its baseline by the keep rule, and sets which labels are reliable (§11.3)."""

from __future__ import annotations

import dataclasses
import json

import pytest

from conversation_analyzer.bq.schema import SUITE_RUNS
from conversation_analyzer.errors import AnalyzerError, TokenLimitError
from conversation_analyzer.judge import forms
from conversation_analyzer.judge.fake import FakeJudge
from conversation_analyzer.judge.version import current
from conversation_analyzer.reporting.monitor import reliable_labels
from conversation_analyzer.suite import runner
from conversation_analyzer.suite.cases import load_suite
from tests.conftest import rows, wipe
from tests.test_suite import Oracle

pytestmark = pytest.mark.emulator


@pytest.fixture
def small_suite():
    full = load_suite()
    ids = ("leave_ondemand-ok", "leave_ondemand-contradicted", "annual_days-no-refs-wrong", "resolved-leave_ondemand")
    picked = [c for c in full.cases if c.id in ids]
    picked[-1] = picked[-1].model_copy(update={"part": "HELD_OUT"})
    return full.model_copy(update={"cases": picked, "raw": "small-suite"})


class PerCase:
    """The oracle for whichever case is being judged, found by its current question and answer."""

    def __init__(self, suite) -> None:
        self.oracles = [Oracle(c, suite) for c in suite.cases]

    def generate(self, model, system, prompt, form, usage):
        if form is forms.SessionGradeForm:
            oracle = next(o for o in self.oracles if o.case.expected.session)
        else:
            turn = "### QUESTION\n{0.question}\n### ANSWER\n{0.answer}\n"
            oracle = next(o for o in self.oracles if turn.format(o.case.turn) in prompt)
        return oracle.generate(model, system, prompt, form, usage)


def test_runs_are_stored_and_compared(emulator, small_suite, tmp_path, monkeypatch):
    wipe(SUITE_RUNS)
    kw = {"suite": small_suite, "reports_dir": tmp_path}
    first = runner.run(passes=2, judge=FakeJudge(), **kw)
    assert first["decision"] == "BASELINE" and first["baseline_run_id"] is None and not first["partial"]
    report = json.loads((tmp_path / f"{first['suite_run_id']}.json").read_text())
    assert report["per_case"].keys() == {c.id for c in small_suite.cases} and report["n_cases"] == 4

    stored = rows(SUITE_RUNS, f"suite_run_id = '{first['suite_run_id']}'")[0]
    assert stored["passes"] == 2 and stored["suite_version"] == small_suite.version
    assert stored["tokens"] and stored["estimated_usd"] > 0
    assert {x["scenario"] for x in stored["per_scenario"]} >= {"intent:FACT_LOOKUP", "outcome:RESOLVED"}

    # The same judge again only re-measures; a changed judge that is no better is rejected.
    assert runner.run(passes=1, judge=FakeJudge(), **kw)["decision"] == "BASELINE"
    changed = dataclasses.replace(current(), version_id="v1-000000000001")
    monkeypatch.setattr(runner, "load", lambda name: changed)
    rejected = runner.run(passes=1, judge=FakeJudge(), **kw)
    assert rejected["decision"] == "REJECT"
    kept = runner.run(passes=1, judge=PerCase(small_suite), **kw)  # a perfect judge beats the fake one
    assert kept["decision"] == "KEEP" and kept["tuning_distance"] == 0 and kept["false_high"] == 0
    assert "CONTRADICTED_CLAIM" in reliable_labels(changed.version_id)

    # A partial run is stored but never decides, and never becomes the baseline or sets reliability.
    partial = runner.run(passes=1, limit=1, judge=FakeJudge(), **kw)
    assert partial["partial"] and partial["decision"] is None and partial["baseline_run_id"] is None
    assert "CONTRADICTED_CLAIM" in reliable_labels(changed.version_id)
    explicit = runner.run(passes=1, judge=FakeJudge(), baseline=first["suite_run_id"], **kw)
    assert explicit["baseline_run_id"] == first["suite_run_id"]
    with pytest.raises(AnalyzerError):
        runner.run(passes=1, judge=FakeJudge(), baseline="suite-00000000", **kw)

    # After an emulator reset the stored runs come back from their reports.
    wipe(SUITE_RUNS)
    assert runner.load_reports([tmp_path / f"{kept['suite_run_id']}.json"]) == [kept["suite_run_id"]]
    assert runner.baseline_row(small_suite.version, None)["suite_run_id"] == kept["suite_run_id"]
    assert "CONTRADICTED_CLAIM" in reliable_labels(changed.version_id)


def test_spend_guard_stops_and_reports(emulator, small_suite, tmp_path, monkeypatch):
    from conversation_analyzer.settings import get_settings

    monkeypatch.setattr(get_settings().suite, "max_usd_per_run", 0.0001)
    with pytest.raises(TokenLimitError):
        runner.run(passes=2, judge=FakeJudge(), suite=small_suite, reports_dir=tmp_path)
