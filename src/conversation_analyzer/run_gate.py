"""Stage's run gate: a control object holding `open_until`; scheduled jobs run only before that time (§12.14)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from google.api_core.exceptions import NotFound

from conversation_analyzer.docs.content import storage_client
from conversation_analyzer.people.directory import split_uri
from conversation_analyzer.settings import get_settings, now

MAX_HOURS = 24  # forgetting to pause costs at most this many hours


def _blob():
    uri = get_settings().run_gate.uri
    if not uri:
        raise RuntimeError("this environment has no run gate")
    bucket, path = split_uri(uri)
    return storage_client().bucket(bucket).blob(path)


def open_until() -> datetime | None:
    """The end of the open period; None when the object is missing or unreadable (the gate is then closed)."""
    try:
        data = json.loads(_blob().download_as_bytes())
        until = datetime.fromisoformat(data["open_until"])
    except (NotFound, KeyError, TypeError, ValueError):
        return None
    return until if until.tzinfo else None


def is_open(at: datetime | None = None) -> bool:
    """Always open without a gate (prod, local); otherwise open until `open_until`."""
    if not get_settings().run_gate.uri:
        return True
    until = open_until()
    return until is not None and (at or now()) < until


def set_open_until(until: datetime) -> None:
    payload = {"open_until": until.astimezone(UTC).isoformat()}
    _blob().upload_from_string(json.dumps(payload), content_type="application/json")


def resume(hours: int, at: datetime | None = None) -> datetime:
    """Open the gate for `hours` (1 to 24) from now."""
    if not 1 <= hours <= MAX_HOURS:
        raise ValueError(f"hours must be between 1 and {MAX_HOURS}")
    until = (at or now()) + timedelta(hours=hours)
    set_open_until(until)
    return until


def pause(at: datetime | None = None) -> None:
    """Close the gate: an end time in the past."""
    set_open_until((at or now()) - timedelta(minutes=1))
