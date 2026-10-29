"""The only way jobs log: accepts run IDs, counts, codes and error classes, nothing else (§12.13)."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from typing import Any

_NAME = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
_ID = re.compile(r"^(run|alert|anom|evt|cluster|suite)-[0-9a-f]{8,64}$")
_HASH = re.compile(r"^[0-9a-f]{12,64}$")
_VERSION = re.compile(r"^(v[0-9][0-9a-z.-]{0,30}|cl-[0-9a-f]{12}|rb-[0-9a-f]{12}|pr-[0-9a-f]{12}|fm-[0-9a-f]{12})$")
_JOBS = frozenset(
    {
        "quality-assessor",
        "quality-monitor",
        "quality-daily",
        "quality-weekly",
        "quality-judge-suite",
        "quality-record",
    }
)
_MODELS = re.compile(r"^(gemini|text-multilingual-embedding|text-embedding|fake)[a-z0-9.-]{0,40}$")
_SEVERITIES = {"DEBUG", "INFO", "WARNING", "ERROR"}

REJECTED = "<rejected>"
rejections: Counter[str] = Counter()


def _closed_values() -> frozenset[str]:
    from conversation_analyzer.vocab import all_closed_values

    return all_closed_values()


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        if (
            value in _closed_values()
            or value in _JOBS
            or _ID.match(value)
            or _HASH.match(value)
            or _VERSION.match(value)
            or _MODELS.match(value)
        ):
            return value
        return REJECTED
    if isinstance(value, dict):
        return {k: _safe_value(v) for k, v in value.items() if isinstance(k, str) and _NAME.match(k)}
    if isinstance(value, list | tuple):
        return [_safe_value(v) for v in value]
    return REJECTED


def log(event: str, severity: str = "INFO", **fields: Any) -> None:
    """Write one JSON line for Cloud Logging; any value that is not a count, code or ID is replaced."""
    record: dict[str, Any] = {
        "severity": severity if severity in _SEVERITIES else "INFO",
        "event": event if _NAME.match(event) else REJECTED,
    }
    for key, value in fields.items():
        if not _NAME.match(key):
            rejections["field_name"] += 1
            continue
        safe = _safe_value(value)
        if safe == REJECTED:
            rejections[key] += 1
        record[key] = safe
    sys.stdout.write(json.dumps(record, separators=(",", ":")) + "\n")
    sys.stdout.flush()
