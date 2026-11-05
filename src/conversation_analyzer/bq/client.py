"""BigQuery access: queries, and keyed writes that pass the leak guard and land with one MERGE per table (§12.6)."""

from __future__ import annotations

import threading
import uuid
from datetime import date, datetime
from functools import lru_cache
from typing import Any

from google.cloud import bigquery

from conversation_analyzer.bq.schema import Col, Table
from conversation_analyzer.leak_guard import check_rows
from conversation_analyzer.settings import get_settings


def retry() -> bigquery.retry.Retry:
    """The emulator answers some errors with 500; retrying those forever would hang a run."""
    return bigquery.DEFAULT_RETRY.with_deadline(20 if get_settings().env.emulator else 600)


@lru_cache(maxsize=1)
def client() -> bigquery.Client:
    env = get_settings().env
    if env.emulator:
        from google.api_core.client_options import ClientOptions
        from google.auth.credentials import AnonymousCredentials

        return bigquery.Client(
            project=get_settings().env.project,
            credentials=AnonymousCredentials(),
            client_options=ClientOptions(api_endpoint=env.bq_endpoint),
        )
    return bigquery.Client(project=get_settings().env.project, location="EU")


def fq(dataset: str, table: str) -> str:
    """Backticked fully qualified table name; dataset is a key of Settings.datasets."""
    return f"`{get_settings().table(dataset, table)}`"


def tbl(table: Table) -> str:
    return fq(table.dataset, table.name)


def _stringify(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _stringify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_stringify(v) for v in value]
    return str(value) if isinstance(value, int | float) and not isinstance(value, bool) else value


class _EmulatorScalar(bigquery.ScalarQueryParameter):
    """The emulator only accepts parameter values as JSON strings."""

    def to_api_repr(self) -> dict:
        return _stringify(super().to_api_repr())


class _EmulatorArray(bigquery.ArrayQueryParameter):
    def to_api_repr(self) -> dict:
        return _stringify(super().to_api_repr())


def _param(name: str, value: Any) -> bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter:
    emulator = get_settings().env.emulator
    if isinstance(value, list | tuple):
        sample = next((v for v in value if v is not None), "")
        cls = _EmulatorArray if emulator else bigquery.ArrayQueryParameter
        return cls(name, _bq_type(sample), list(value))
    cls = _EmulatorScalar if emulator else bigquery.ScalarQueryParameter
    return cls(name, _bq_type(value), value)


def _bq_type(value: Any) -> str:
    if isinstance(value, bool):
        return "BOOL"
    if isinstance(value, int):
        return "INT64"
    if isinstance(value, float):
        return "FLOAT64"
    if isinstance(value, datetime):
        return "TIMESTAMP"
    if isinstance(value, date):
        return "DATE"
    return "STRING"


def query(sql: str, **params: Any) -> list[dict[str, Any]]:
    config = bigquery.QueryJobConfig(query_parameters=[_param(k, v) for k, v in params.items()])
    job = client().query(sql, job_config=config, job_retry=None, retry=retry())
    return [dict(row) for row in job.result(timeout=600, retry=retry())]


def execute(sql: str, **params: Any) -> None:
    query(sql, **params)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


def schema_fields(cols: tuple[Col, ...]) -> list[bigquery.SchemaField]:
    out = []
    for col in cols:
        if col.type == "STRUCT":
            out.append(bigquery.SchemaField(col.name, "RECORD", mode=col.mode, fields=schema_fields(col.fields)))
        else:
            out.append(bigquery.SchemaField(col.name, col.type, mode=col.mode))
    return out


def _dedupe(table: Table, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One source row per key (the last one wins): a MERGE may match each target row once."""
    return list({tuple(row.get(c) for c in table.key): row for row in rows}.values())


def _partition_filter(table: Table, rows: list[dict[str, Any]]) -> str | None:
    """`T.<partition> IN (<days>)` for the staged rows' days, so the MERGE reads only those partitions."""
    if not table.prunable or not rows:
        return None
    assert table.partition is not None and table.col(table.partition).type == "DATE"
    days = {row.get(table.partition) for row in rows}
    if None in days:
        return None
    literals = ", ".join(f"DATE '{d}'" for d in sorted(date.fromisoformat(str(d)[:10]) for d in days))
    return f"T.{table.partition} IN ({literals})"


def merge_sql(table: Table, staging: str, rows: list[dict[str, Any]] | None = None) -> str:
    conditions = [f"(T.{k} = S.{k} OR (T.{k} IS NULL AND S.{k} IS NULL))" for k in table.key]
    pruning = _partition_filter(table, rows or [])
    on = " AND ".join(([pruning] if pruning else []) + conditions)
    updates = ", ".join(f"{col.name} = S.{col.name}" for col in table.cols if col.name not in table.key)
    names = ", ".join(c.name for c in table.cols)
    values = ", ".join(f"S.{c.name}" for c in table.cols)
    return (
        f"MERGE {tbl(table)} T USING {staging} S ON {on}\n"
        f"WHEN MATCHED THEN UPDATE SET {updates}\n"
        f"WHEN NOT MATCHED THEN INSERT ({names}) VALUES ({values})"
    )


def write(table: Table, rows: list[dict[str, Any]]) -> int:
    """Leak guard on every row, then staging table, then one MERGE keyed by the table's key."""
    from conversation_analyzer.bq.schema import ddl

    if not rows:
        return 0
    checked = _dedupe(table, check_rows(table, rows))
    s = get_settings()
    payload = [_jsonable(r) for r in checked]
    if s.env.emulator:
        # The emulator corrupts its catalog when tables are dropped, so its staging tables (made by create_all) are
        # reused, never dropped, and left empty; MERGE and emptying run as one script (every job slows it down).
        stg_id = s.table(table.dataset, f"_stg_{table.name}")
        empty = f"DELETE FROM `{stg_id}` WHERE TRUE"
        with _emulator_lock:
            try:
                if client().insert_rows_json(stg_id, payload, retry=retry()):
                    raise RuntimeError("staging insert failed")
                execute(merge_sql(table, f"`{stg_id}`", checked) + ";\n" + empty)
            except Exception:
                execute(empty)
                raise
        return len(checked)
    stg_name = f"_stg_{table.name}_{uuid.uuid4().hex[:12]}"
    stg_id = s.table(table.dataset, stg_name)
    execute(ddl(table, emulator=False, name_override=stg_name))
    try:
        job_config = bigquery.LoadJobConfig(
            schema=schema_fields(table.cols), write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
        )
        client().load_table_from_json(payload, stg_id, job_config=job_config).result()
        execute(merge_sql(table, f"`{stg_id}`", checked))
    finally:
        client().delete_table(stg_id, not_found_ok=True, retry=retry())
    return len(checked)


def insert_fresh(table: Table, rows: list[dict[str, Any]]) -> int:
    """Emulator only: leak guard on every row, then a plain insert (no MERGE) of rows whose keys are not stored yet."""
    if not get_settings().env.emulator:
        raise RuntimeError("insert_fresh runs only against the emulator")
    checked = _dedupe(table, check_rows(table, rows))
    stored = get_settings().table(table.dataset, table.name)
    for i in range(0, len(checked), 2000):
        if client().insert_rows_json(stored, [_jsonable(r) for r in checked[i : i + 2000]], retry=retry()):
            raise RuntimeError("insert failed")
    return len(checked)


_emulator_lock = threading.Lock()
