from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from conversation_analyzer.bq import client as bqc
from conversation_analyzer.bq.client import fq, merge_sql, query, tbl, write
from conversation_analyzer.bq.schema import JUDGE_CHECKS, QUALITY_TURNS, RUNS, SESSION_GRADES, ddl
from conversation_analyzer.errors import LeakGuardError
from conversation_analyzer.settings import get_settings
from tests.conftest import wipe

pytestmark = pytest.mark.emulator


def test_write_merges_by_key(emulator):
    wipe(QUALITY_TURNS)
    row = {
        "turn_key": "a" * 32,
        "day": date(2026, 10, 28),
        "channel": "WEB_UI",
        "status": "ASSESSED",
        "flag_reasons": ["DISLIKE"],
        "cited_docs": [{"doc_id": "d1", "data_store": "rtb-crj-confluence", "uri": None}],
    }
    assert write(QUALITY_TURNS, [row, {**row, "status": "FAILED"}]) == 1  # deduped, last wins
    write(QUALITY_TURNS, [{**row, "status": "TOO_LARGE"}])
    rows = query(f"SELECT turn_key, status, cited_docs FROM {tbl(QUALITY_TURNS)}")
    assert len(rows) == 1 and rows[0]["status"] == "TOO_LARGE"
    assert rows[0]["cited_docs"][0]["doc_id"] == "d1"
    assert write(QUALITY_TURNS, []) == 0


def test_rewrite_replaces_rows(emulator):
    """No table adds up on MERGE: writing the same rows again leaves them as they were."""
    wipe(JUDGE_CHECKS)
    day = date(2026, 10, 28)
    rows_ = [{"day": day, "turn_key": "b" * 32, "field": "INTENT", "n_compared": 1, "n_disagreements": 1}]
    write(JUDGE_CHECKS, rows_)
    write(JUDGE_CHECKS, rows_)
    assert query(f"SELECT n_compared, n_disagreements FROM {tbl(JUDGE_CHECKS)}") == [
        {"n_compared": 1, "n_disagreements": 1}
    ]


def test_merge_prunes_partitions_only_where_the_key_fixes_them():
    day = date(2026, 10, 28)
    sql = merge_sql(QUALITY_TURNS, "`s`", [{"day": day.isoformat()}, {"day": "2026-10-27"}])
    assert "ON T.day IN (DATE '2026-10-27', DATE '2026-10-28') AND (T.turn_key = S.turn_key" in sql
    assert "T.day IN" in merge_sql(JUDGE_CHECKS, "`s`", [{"day": day}])
    assert "IN (" not in merge_sql(SESSION_GRADES, "`s`", [{"day": day}])  # a grade's day moves with the run
    assert "IN (" not in merge_sql(QUALITY_TURNS, "`s`", [{"day": None}])
    assert "IN (" not in merge_sql(QUALITY_TURNS, "`s`")
    assert "COALESCE" not in merge_sql(JUDGE_CHECKS, "`s`", [{"day": day}])


def test_staging_tables_expire_on_real_bigquery():
    real = ddl(RUNS, emulator=False, name_override="_stg_quality_runs_ab")
    assert "expiration_timestamp = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)" in real
    assert "PARTITION BY" not in real
    assert "OPTIONS" not in ddl(RUNS, emulator=True, name_override="_stg_quality_runs")
    assert "partition_expiration_days" in ddl(RUNS, emulator=False)


def test_write_runs_leak_guard_first(emulator):
    wipe(RUNS)
    with pytest.raises(LeakGuardError):
        write(RUNS, [{"run_id": "run-00aa11bb", "status": "free text here"}])
    assert query(f"SELECT COUNT(*) AS n FROM {tbl(RUNS)}") == [{"n": 0}]


def test_query_params(emulator):
    rows = query(
        "SELECT @s AS s, @i AS i, @f AS f, @b AS b, @d AS d, @t AS t, ARRAY_LENGTH(@a) AS n",
        s="x",
        i=1,
        f=0.5,
        b=True,
        d=date(2026, 1, 2),
        t=datetime(2026, 1, 2, tzinfo=UTC),
        a=["p", "q"],
    )
    assert rows[0]["s"] == "x" and rows[0]["i"] == 1 and rows[0]["b"] is True and rows[0]["n"] == 2
    assert fq("turns", "x") == "`local-project.bolek_quality_turns.x`"


def test_production_paths(monkeypatch):
    """The production branches: real client in EU, load jobs instead of streaming inserts."""
    created = {}

    class FakeBQ:
        def __init__(self, project=None, location=None, **kw):
            created.update(project=project, location=location)

    monkeypatch.setattr(get_settings().env, "bq_endpoint", None)
    monkeypatch.setattr(bqc.bigquery, "Client", FakeBQ)
    real_client = bqc.client
    real_client.cache_clear()
    try:
        bqc.client()
        assert created == {"project": "local-project", "location": "EU"}

        calls = []

        class Job:
            def result(self):
                calls.append("loaded")

        class FakeClient:
            def load_table_from_json(self, payload, dest, job_config):
                calls.append(("load", len(payload), job_config.write_disposition))
                return Job()

            def delete_table(self, *a, **k):
                calls.append("deleted")

        monkeypatch.setattr(bqc, "client", lambda: FakeClient())
        monkeypatch.setattr(bqc, "execute", lambda sql, **p: calls.append(sql.split()[0]))
        write(RUNS, [{"run_id": "run-00aa11bb", "status": "OK"}])
        assert calls[0] == "CREATE" and calls[1][0] == "load" and "MERGE" in calls and calls[-1] == "deleted"
        fields = bqc.schema_fields(QUALITY_TURNS.cols)
        assert any(f.field_type == "RECORD" and f.mode == "REPEATED" for f in fields)
    finally:
        real_client.cache_clear()


def test_views_production_sql(monkeypatch):
    from conversation_analyzer.bq.views import partition_filter, views

    monkeypatch.setattr(get_settings().env, "bq_endpoint", None)
    assert partition_filter(3) == (
        "(_PARTITIONTIME >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 DAY) OR _PARTITIONTIME IS NULL)"
    )
    assert "_PARTITIONTIME" in views()["quality_turn_counts_hourly"]
