"""Mocked metrics for the local Grafana: the story shows, rows pass the leak guard, seeding needs empty tables."""

from __future__ import annotations

from datetime import date

import pytest
from click.testing import CliRunner

from conversation_analyzer import cli
from conversation_analyzer.bq.client import query, tbl
from conversation_analyzer.bq.schema import ANOMALIES, METRICS_DAILY, PIPELINE_HEALTH
from conversation_analyzer.devtools import dashboard_mock
from conversation_analyzer.devtools.dashboard_mock import Mock
from tests.conftest import wipe

pytestmark = pytest.mark.emulator
TODAY = date(2026, 11, 5)


def aqr(m: Mock, day: date) -> float:
    return next(
        r["value"] for r in m.quality(day, "ALL", ("ALL", "ALL"), 900, 1.0) if r["metric"] == "AQR_STANDARDIZED"
    )


def test_story_regression_and_fix() -> None:
    m = Mock(TODAY)
    before, during = aqr(m, m.first), aqr(m, m.regression_day)
    assert during < before - 0.03
    assert aqr(m, TODAY) > during + 0.03


def test_seed_writes_every_table_and_refuses_a_second_time(emulator) -> None:
    wipe(*[t for t in dashboard_mock.sc.TABLES if t.dataset == "metrics"])
    result = CliRunner().invoke(cli.main, ["dev-seed-dashboard", "--today", TODAY.isoformat()])
    assert result.exit_code == 0, result.output
    days = query(f"SELECT COUNT(DISTINCT day) AS n FROM {tbl(METRICS_DAILY)}")[0]["n"]
    assert days == dashboard_mock.DAYS
    failed = query(f"SELECT COUNT(*) AS n FROM {tbl(PIPELINE_HEALTH)} WHERE run_status = 'FAILED'")[0]["n"]
    assert failed == 3
    assert query(f"SELECT COUNT(*) AS n FROM {tbl(ANOMALIES)} WHERE state = 'OPEN'")[0]["n"] == 1
    with pytest.raises(RuntimeError, match="not empty"):
        dashboard_mock.seed(TODAY)
