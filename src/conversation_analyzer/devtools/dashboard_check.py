"""Run every panel's SQL of a Grafana dashboard file on the emulator, with macros and variables fixed (A7)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

BIGQUERY = "grafana-bigquery-datasource"
MAY_BE_EMPTY = "may be empty"  # in a panel's description: no rows is a valid state (no anomaly open, no run failed)
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}
_RELATIVE = re.compile(r"^now(?:-(\d+)([smhdw]))?$")
_VARIABLE = re.compile(r"\$\{(\w+)(?::\w+)?\}|\[\[(\w+)\]\]|\$(?!__)(\w+)")
_MACRO = re.compile(r"\$__(\w+)")


class DashboardError(Exception):
    """A query that cannot be made runnable: an unknown variable or an unsupported macro."""


@dataclass(frozen=True)
class Query:
    title: str
    ref: str
    sql: str
    required: bool


@dataclass(frozen=True)
class Result:
    query: Query
    rows: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and (self.rows or not self.query.required)


def load(path: Path) -> dict[str, Any]:
    """The dashboard spec of a `dashboard.grafana.app` resource file, or of a classic dashboard JSON."""
    doc = json.loads(path.read_text())
    return doc.get("spec", doc)


def _is_bigquery(datasource: Any, spec: dict[str, Any]) -> bool:
    if not isinstance(datasource, dict):
        return False
    if datasource.get("type") == BIGQUERY:
        return True
    uid = str(datasource.get("uid", ""))
    return uid.startswith("$") and _variable_type(spec, uid.strip("${}")) == BIGQUERY


def _variable_type(spec: dict[str, Any], name: str) -> str | None:
    for v in spec.get("templating", {}).get("list", []):
        if v.get("name") == name and v.get("type") == "datasource":
            return v.get("query")
    return None


def _panels(panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for p in panels:
        out.append(p)
        out += _panels(p.get("panels", []))  # panels inside a collapsed row
    return out


def queries(spec: dict[str, Any]) -> list[Query]:
    """Every BigQuery SQL of the dashboard: panel targets (inheriting the panel's datasource) and annotations."""
    out = []
    for p in _panels(spec.get("panels", [])):
        required = MAY_BE_EMPTY not in (p.get("description") or "").lower()
        for t in p.get("targets", []):
            if t.get("rawSql") and not t.get("hide") and _is_bigquery(t.get("datasource") or p.get("datasource"), spec):
                out.append(Query(p.get("title", ""), t.get("refId", "A"), t["rawSql"], required))
    for a in spec.get("annotations", {}).get("list", []):
        t = a.get("target") or {}
        if t.get("rawSql") and _is_bigquery(a.get("datasource"), spec):
            out.append(Query(f"annotation: {a.get('name', '')}", t.get("refId", "A"), t["rawSql"], False))
    return out


def defaults(spec: dict[str, Any]) -> dict[str, str]:
    """Each variable's saved current value, or its first option."""
    out = {}
    for v in spec.get("templating", {}).get("list", []):
        if v.get("type") == "datasource":
            continue
        value = (v.get("current") or {}).get("value")
        if value in (None, "", []) and v.get("options"):
            value = v["options"][0].get("value")
        if isinstance(value, list):
            value = value[0] if value else ""
        out[v["name"]] = "" if value is None else str(value)
    return out


def time_point(text: str, now: datetime) -> datetime:
    """Grafana's `now`, `now-7d` and so on, or an ISO time."""
    m = _RELATIVE.match(text.strip())
    if m:
        return now - timedelta(seconds=int(m.group(1) or 0) * _UNITS[m.group(2) or "s"])
    return datetime.fromisoformat(text)


def _args(sql: str, start: int) -> tuple[list[str], int]:
    """The comma-separated arguments of the macro call opening at `start` (a '('), and the index after it."""
    depth, args, current = 0, [], ""
    for i in range(start, len(sql)):
        ch = sql[i]
        if ch == "(":
            depth += 1
            if depth == 1:
                continue
        elif ch == ")":
            depth -= 1
            if depth == 0:
                args.append(current.strip())
                return [a for a in args if a], i + 1
        elif ch == "," and depth == 1:
            args.append(current.strip())
            current = ""
            continue
        current += ch
    raise DashboardError("unbalanced parentheses in a macro call")


def _seconds(interval: str) -> int:
    m = re.fullmatch(r"'?(\d+)([smhdw])'?", interval.strip())
    if not m:
        raise DashboardError(f"unsupported interval {interval!r}")
    return int(m.group(1)) * _UNITS[m.group(2)]


def _ts(t: datetime) -> str:
    return f"TIMESTAMP('{t.isoformat()}')"


def render(sql: str, variables: dict[str, str], start: datetime, end: datetime) -> str:
    """The query as Grafana's BigQuery plugin would send it: variables filled in, time macros made literal."""

    def variable(m: re.Match) -> str:
        name = m.group(1) or m.group(2) or m.group(3)
        if name not in variables:
            raise DashboardError(f"unknown variable ${name}")
        return variables[name]

    sql = _VARIABLE.sub(variable, sql)
    out, pos = "", 0
    for m in _MACRO.finditer(sql):
        if m.start() < pos:
            continue
        out += sql[pos : m.start()]
        name, after = m.group(1), m.end()
        has_args = after < len(sql) and sql[after] == "("
        args, after = _args(sql, after) if has_args else ([], after)
        if name == "timeFilter" and len(args) == 1:
            out += f"({args[0]} BETWEEN {_ts(start)} AND {_ts(end)})"
        elif name == "timeFrom":
            out += _ts(start)
        elif name == "timeTo":
            out += _ts(end)
        elif name in ("timeGroup", "timeGroupAlias") and len(args) >= 2:
            n = _seconds(args[1])
            out += f"TIMESTAMP_SECONDS(DIV(UNIX_SECONDS({args[0]}), {n}) * {n})"
            out += " AS time" if name == "timeGroupAlias" else ""
        else:
            raise DashboardError(f"unsupported macro $__{name}")
        pos = after
    return out + sql[pos:]


def check(spec: dict[str, Any], variables: dict[str, str], start: datetime, end: datetime) -> list[Result]:
    """Run every query on the emulator; a query that fails to render or to run is an error."""
    from conversation_analyzer.bq.client import query

    results = []
    for q in queries(spec):
        try:
            results.append(Result(q, rows=len(query(render(q.sql, variables, start, end)))))
        except Exception as e:  # noqa: BLE001 - every failure of a panel is reported, the others still run
            results.append(Result(q, error=f"{type(e).__name__}: {str(e).splitlines()[0][:300]}"))
    return results
