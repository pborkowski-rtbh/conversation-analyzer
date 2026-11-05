"""`ca leak-audit`: stored rows read back through the leak guard and a string-length check; counts only (§6.10)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from conversation_analyzer.bq.client import query, tbl
from conversation_analyzer.bq.schema import TABLES, Col, Table
from conversation_analyzer.errors import LeakGuardError
from conversation_analyzer.leak_guard import check_row
from conversation_analyzer.settings import get_settings

_BARE_DATE = re.compile(r"(?<=[:\[,])(\d{4}-\d{2}-\d{2}(?:[ T][0-9:.+-]+Z?)?)(?=[,}\]])")


@dataclass
class TableAudit:
    table: str
    rows: int = 0
    rejected: int = 0  # rows the leak guard refuses outright
    dropped: int = 0  # rows the guard would store differently (a link or document it removes)
    too_long: int = 0  # rows with a string longer than leak_audit.max_string_chars (links: max_link_chars)

    @property
    def findings(self) -> int:
        return self.rejected + self.dropped + self.too_long


def _value(col: Col, raw: Any) -> Any:
    """A TO_JSON_STRING value back as the Python type the writer gave the guard."""
    if col.mode == "REPEATED":
        return [_one(col, v) for v in raw or []]
    return _one(col, raw)


def _fold(raw: Any) -> dict[str, Any]:
    """The emulator renders a struct in a repeated struct as `[[{"a": 1}, {"b": 2}]]`; real BigQuery as a dict."""
    if isinstance(raw, dict):
        return raw
    out: dict[str, Any] = {}
    for item in raw:
        out.update(_fold(item))
    return out


def _one(col: Col, raw: Any) -> Any:
    if raw is None:
        return None
    if col.type == "STRUCT":
        raw = _fold(raw)
        return {f.name: _value(f, raw.get(f.name)) for f in col.fields}
    if col.type == "INT64":
        return int(raw)
    if col.type == "FLOAT64":
        return float(raw)
    if col.type == "BOOL":
        return bool(raw)  # the emulator gives 0/1
    if col.type == "DATE":
        return date.fromisoformat(raw[:10])
    if col.type == "TIMESTAMP":
        return datetime.fromisoformat(raw.replace(" ", "T").replace("Z", "+00:00"))
    return raw


def _too_long(cols: tuple[Col, ...], row: dict[str, Any]) -> bool:
    cfg = get_settings().leak_audit
    for col in cols:
        values = row.get(col.name)
        for v in values if col.mode == "REPEATED" else [values]:
            if v is None:
                continue
            if col.type == "STRUCT" and _too_long(col.fields, v):
                return True
            limit = cfg.max_link_chars if col.kind == "link" else cfg.max_string_chars
            if isinstance(v, str) and len(v) > limit:
                return True
    return False


def audit_table(table: Table, since: date) -> TableAudit:
    sql = f"SELECT TO_JSON_STRING(t) AS j FROM {tbl(table)} t"
    rows = query(f"{sql} WHERE {table.partition} >= @since", since=since) if table.partition else query(sql)
    out = TableAudit(table.name, rows=len(rows))
    for r in rows:
        text = _BARE_DATE.sub(r'"\1"', r["j"]) if get_settings().env.emulator else r["j"]  # unquoted dates
        raw = json.loads(text)
        row = {c.name: _value(c, raw.get(c.name)) for c in table.cols}
        if _too_long(table.cols, row):
            out.too_long += 1
        try:
            if check_row(table, row) != row:
                out.dropped += 1
        except LeakGuardError:
            out.rejected += 1
    return out


def audit(since: date) -> list[TableAudit]:
    """Every table we write; partitioned tables from `since`, the others whole."""
    return [audit_table(t, since) for t in TABLES]
