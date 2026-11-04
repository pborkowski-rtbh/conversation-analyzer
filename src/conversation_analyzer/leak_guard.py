"""The final check before anything is stored: numbers, closed-list values, hashes and allowlisted IDs only (§6.10)."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from conversation_analyzer.bq.schema import Col, Table
from conversation_analyzer.errors import LeakGuardError
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import DepartmentFamily, all_closed_values

_HASH = re.compile(r"^[0-9a-f]{12,64}$")
_ID = re.compile(r"^(run|alert|anom|evt|cluster|suite)-[0-9a-f]{8,64}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_DOC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_SLACK_TS = re.compile(r"^\d{1,12}\.\d{1,8}$")
_SLACK_USER = re.compile(r"^[UWB][A-Z0-9]{2,24}$")
_SLACK_CHANNEL = re.compile(r"^(#[a-z0-9_-]{1,80}|[CGD][A-Z0-9]{2,24})$")
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_EXECUTION = re.compile(r"^[a-z][a-z0-9-]{0,99}$")
_SCENARIO = re.compile(r"^[a-z0-9_]{1,40}:[A-Za-z0-9_]{1,40}$")
# Free text: anything with a space or longer than these patterns already rejects; the URL check below is separate.


def is_people_directory(data_store: str | None, doc_id: str | None = None, uri: str | None = None) -> bool:
    p = get_settings().people_directory
    if data_store and (data_store in p.data_store_ids or any(data_store.startswith(x) for x in p.data_store_prefixes)):
        return True
    if doc_id and any(doc_id.startswith(x) for x in p.doc_id_prefixes):
        return True
    return bool(uri and any(uri.lower().startswith(s + ":") for s in p.uri_schemes))


def allowed_data_store(data_store: str | None) -> bool:
    return (
        bool(data_store) and get_settings().data_store(data_store) is not None and not is_people_directory(data_store)
    )


def link_data_store(uri: str, data_store: str | None = None) -> str | None:
    """The data store a link belongs to: https, no credentials, and a host (and path prefix) of that data store."""
    try:
        parts = urlsplit(uri)
    except ValueError:
        return None
    if parts.scheme != "https" or parts.username or parts.password or " " in uri or len(uri) > 600:
        return None
    stores = [get_settings().data_store(data_store)] if data_store else get_settings().data_stores
    for ds in stores:
        if ds and parts.hostname in ds.hosts and (not ds.path_prefix or parts.path.startswith(ds.path_prefix)):
            return ds.id
    return None


def allowed_link(uri: str, data_store: str | None) -> bool:
    """A link passes when it is https, has no credentials, and its host belongs to the document's data store."""
    return link_data_store(uri, data_store) is not None


def _check_scalar(col: Col, value: Any, row: dict[str, Any]) -> Any:
    if value is None:
        return None
    k = col.kind
    if k == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise LeakGuardError()
        return value
    if k == "float":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise LeakGuardError()
        return float(value)
    if k == "bool":
        if not isinstance(value, bool):
            raise LeakGuardError()
        return value
    if k == "date":
        if isinstance(value, datetime) or not isinstance(value, date):
            raise LeakGuardError()
        return value
    if k == "ts":
        if not isinstance(value, datetime):
            raise LeakGuardError()
        return value
    if not isinstance(value, str):
        raise LeakGuardError()
    patterns = {
        "hash": _HASH,
        "id": _ID,
        "version": _VERSION,
        "doc_id": _DOC_ID,
        "slack_ts": _SLACK_TS,
        "slack_user": _SLACK_USER,
        "slack_channel": _SLACK_CHANNEL,
        "sha": _SHA,
        "execution": _EXECUTION,
        "scenario": _SCENARIO,
    }
    if k == "enum":
        if value not in all_closed_values():
            raise LeakGuardError()
        return value
    if k == "department":
        if value not in DepartmentFamily.__members__:
            raise LeakGuardError()
        return value
    if k in patterns:
        if not patterns[k].match(value):
            raise LeakGuardError()
        if k == "doc_id" and is_people_directory(None, value):
            raise LeakGuardError()
        return value
    if k == "data_store":
        if not allowed_data_store(value):
            raise LeakGuardError()
        return value
    if k == "repo":
        if value not in get_settings().github.repositories:
            raise LeakGuardError()
        return value
    if k == "link":
        return value if allowed_link(value, row.get("data_store")) else None
    raise LeakGuardError()


def _check_doc(col: Col, value: dict[str, Any]) -> dict[str, Any] | None:
    """A document reference: people-directory and non-allowlisted documents are dropped, not stored."""
    if value is None:
        return None
    if is_people_directory(value.get("data_store"), value.get("doc_id"), value.get("uri")):
        return None
    if not allowed_data_store(value.get("data_store")):
        return None
    return _check_struct(col, value)


def _check_struct(col: Col, value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {f.name for f in col.fields}:
        raise LeakGuardError()
    return {f.name: _check_value(f, value.get(f.name), value) for f in col.fields}


def _check_value(col: Col, value: Any, row: dict[str, Any]) -> Any:
    if col.mode == "REPEATED":
        if value is None:
            return []
        if not isinstance(value, list | tuple):
            raise LeakGuardError()
        out = []
        for item in value:
            checked = _check_one(col, item, row)
            if checked is not None:
                out.append(checked)
        return out
    return _check_one(col, value, row)


def _check_one(col: Col, value: Any, row: dict[str, Any]) -> Any:
    if col.kind == "doc":
        return _check_doc(col, value)
    if col.type == "STRUCT":
        return None if value is None else _check_struct(col, value)
    return _check_scalar(col, value, row)


def check_row(table: Table, row: dict[str, Any]) -> dict[str, Any]:
    """Return the row as it may be stored, or raise LeakGuardError; never include the offending value."""
    unknown = set(row) - {c.name for c in table.cols}
    if unknown:
        raise LeakGuardError()
    return {col.name: _check_value(col, row.get(col.name), row) for col in table.cols}


def check_rows(table: Table, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [check_row(table, r) for r in rows]
