"""`db-init --check`: the live datasets, tables, columns, partitioning and views against bq/schema.py (§12.14)."""

from __future__ import annotations

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from conversation_analyzer.bq.client import client, retry, schema_fields
from conversation_analyzer.bq.schema import TABLES
from conversation_analyzer.bq.views import views
from conversation_analyzer.settings import OWN_DATASETS, get_settings

_LEGACY = {"INTEGER": "INT64", "FLOAT": "FLOAT64", "BOOLEAN": "BOOL", "RECORD": "STRUCT"}
_DAY_MS = 24 * 3600 * 1000


def _shape(fields: list[bigquery.SchemaField] | tuple[bigquery.SchemaField, ...]) -> dict[str, tuple]:
    """Column name -> (type, mode, nested shape), with legacy type names mapped to standard ones."""
    out = {}
    for f in fields:
        type_ = _LEGACY.get(f.field_type.upper(), f.field_type.upper())
        out[f.name] = (type_, (f.mode or "NULLABLE").upper(), _shape(f.fields) if type_ == "STRUCT" else None)
    return out


def _compare(where: str, want: dict[str, tuple], have: dict[str, tuple]) -> list[str]:
    out = []
    for name in sorted(set(want) | set(have)):
        if name not in have:
            out.append(f"{where}.{name}: missing column")
        elif name not in want:
            out.append(f"{where}.{name}: column not in bq/schema.py")
        else:
            (wt, wm, wf), (ht, hm, hf) = want[name], have[name]
            if (wt, wm) != (ht, hm):
                out.append(f"{where}.{name}: {hm} {ht}, expected {wm} {wt}")
            elif wf is not None:
                out.extend(_compare(f"{where}.{name}", wf, hf or {}))
    return out


def _partitioning(table, live: bigquery.Table) -> list[str]:
    """Partition column and expiry; not checked on the emulator, which keeps neither."""
    where = live.table_id
    tp = live.time_partitioning
    if (tp.field if tp else None) != table.partition:
        return [f"{where}: partitioned by {tp.field if tp else None}, expected {table.partition}"]
    if not table.partition:
        return []
    want = table.expiration_days * _DAY_MS if table.expiration_days else None
    if tp.expiration_ms != want:
        return [f"{where}: partition expiry {tp.expiration_ms} ms, expected {want}"]
    return []


def _norm(sql: str) -> str:
    return " ".join(sql.split())


def differences() -> list[str]:
    """Every difference between what db-init would create and what exists; empty when they match."""
    s = get_settings()
    out: list[str] = []
    present = set()
    for key in OWN_DATASETS:
        try:
            client().get_dataset(s.dataset_id(key), retry=retry())
            present.add(key)
        except NotFound:
            out.append(f"{s.dataset_id(key)}: missing dataset")
    expected_views = views()
    known = {(t.dataset, t.name) for t in TABLES} | {("log_views", v) for v in expected_views}
    for key in sorted(present):
        for item in client().list_tables(s.dataset_id(key), retry=retry()):
            if not item.table_id.startswith("_stg_") and (key, item.table_id) not in known:
                out.append(f"{s.dataset_id(key)}.{item.table_id}: not in bq/schema.py")
    for table in TABLES:
        if table.dataset not in present:
            continue
        try:
            live = client().get_table(s.table(table.dataset, table.name), retry=retry())
        except NotFound:
            out.append(f"{table.name}: missing table")
            continue
        out += _compare(table.name, _shape(schema_fields(table.cols)), _shape(live.schema))
        if not s.env.emulator:
            out += _partitioning(table, live)
    if "log_views" in present:
        for name, sql in expected_views.items():
            try:
                live = client().get_table(s.table("log_views", name), retry=retry())
            except NotFound:
                out.append(f"{name}: missing view")
                continue
            if live.table_type != "VIEW":
                out.append(f"{name}: a {live.table_type}, expected a VIEW")
            elif not s.env.emulator and _norm(live.view_query or "") != _norm(sql):
                out.append(f"{name}: view query differs from bq/views.py")
    return out
