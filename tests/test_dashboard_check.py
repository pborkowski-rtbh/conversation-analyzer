"""dashboard-check: panel SQL extraction and macro replacement, then the run on the emulator."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from conversation_analyzer import cli
from conversation_analyzer.bq.client import write
from conversation_analyzer.bq.schema import ANOMALIES, CHANGE_EVENTS, METRICS_DAILY
from conversation_analyzer.devtools import dashboard_check as dc
from tests.conftest import wipe

SAMPLE = Path(__file__).parent / "data" / "sample-dashboard.json"
START = datetime(2026, 10, 29, tzinfo=UTC)
END = datetime(2026, 11, 5, 12, tzinfo=UTC)


def test_queries_of_panels_rows_and_annotations() -> None:
    qs = dc.queries(dc.load(SAMPLE))
    assert [(q.title, q.required) for q in qs] == [
        ("Volume", True),
        ("Per hour", True),  # inside a collapsed row, datasource on the target
        ("Open anomalies", False),  # "May be empty" in its description
        ("Broken", True),  # its hidden target B is skipped
        ("annotation: Changes", False),
    ]


def test_defaults_take_the_current_value_or_the_first_option() -> None:
    assert dc.defaults(dc.load(SAMPLE)) == {"channel": "ALL", "metric": "VOLUME"}


def test_render_fills_variables_and_time_macros() -> None:
    sql = dc.render(
        "SELECT $__timeGroupAlias(TIMESTAMP(day), '1d'), x FROM t WHERE c = '${channel}' AND m = '$metric' "
        "AND k = '[[channel]]' AND $__timeFilter(TIMESTAMP_ADD(TIMESTAMP(day), INTERVAL hour HOUR)) "
        "AND day < DATE($__timeTo())",
        {"channel": "WEB_UI", "metric": "VOLUME"},
        START,
        END,
    )
    assert sql == (
        "SELECT TIMESTAMP_SECONDS(DIV(UNIX_SECONDS(TIMESTAMP(day)), 86400) * 86400) AS time, x FROM t "
        "WHERE c = 'WEB_UI' AND m = 'VOLUME' AND k = 'WEB_UI' "
        "AND (TIMESTAMP_ADD(TIMESTAMP(day), INTERVAL hour HOUR) BETWEEN TIMESTAMP('2026-10-29T00:00:00+00:00') "
        "AND TIMESTAMP('2026-11-05T12:00:00+00:00')) AND day < DATE(TIMESTAMP('2026-11-05T12:00:00+00:00'))"
    )


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("SELECT '$nope'", "unknown variable"),
        ("SELECT $__interval", "unsupported macro"),
        ("SELECT $__timeGroup(day, 'often')", "unsupported interval"),
        ("SELECT $__timeFilter(TIMESTAMP(day)", "unbalanced"),
    ],
)
def test_render_refuses_what_it_cannot_make_runnable(sql: str, message: str) -> None:
    with pytest.raises(dc.DashboardError, match=message):
        dc.render(sql, {}, START, END)


def test_time_points() -> None:
    assert dc.time_point("now", END) == END
    assert dc.time_point("now-56d", END) == datetime(2026, 9, 10, 12, tzinfo=UTC)
    assert dc.time_point("2026-10-01T00:00:00+00:00", END) == datetime(2026, 10, 1, tzinfo=UTC)


def test_classic_dashboard_json_without_a_resource_wrapper(tmp_path: Path) -> None:
    path = tmp_path / "classic.json"
    path.write_text('{"title": "x", "panels": []}')
    assert dc.load(path) == {"title": "x", "panels": []}


@pytest.mark.emulator
def test_check_on_the_emulator(emulator) -> None:
    wipe(METRICS_DAILY, ANOMALIES, CHANGE_EVENTS)
    day = date(2026, 11, 4)
    write(
        METRICS_DAILY,
        [
            {
                "day": day,
                "day_kind": "WEEKDAY",
                "channel": "ALL",
                "metric": "VOLUME",
                "slice_kind": "ALL",
                "slice_value": "ALL",
                "value": 120.0,
                "n_turns": 120,
                "incomplete": False,
                "merged": False,
            }
        ],
    )
    args = ["dashboard-check", str(SAMPLE), "--from", START.isoformat(), "--to", END.isoformat()]
    result = CliRunner().invoke(cli.main, args)
    assert result.exit_code == 1, result.output
    lines = {line[14:]: line.split()[0] for line in result.output.splitlines() if line.endswith("]")}
    assert lines["Volume [A]"] == "ok"
    assert lines["Per hour [A]"] == "EMPTY"  # required, no anomaly stored
    assert lines["Open anomalies [A]"] == "empty"  # may be empty
    assert lines["Broken [A]"] == "ERROR"
    assert "3 of 5 queries passed" in result.output

    result = CliRunner().invoke(cli.main, [*args, "--allow-empty", "--var", "metric=COVERAGE"])
    assert result.exit_code == 1  # the broken query still fails
    assert "Volume [A]" in result.output and "4 of 5 queries passed" in result.output

    bad = CliRunner().invoke(cli.main, [*args, "--var", "metric"])
    assert bad.exit_code == 2 and "name=value" in bad.output
