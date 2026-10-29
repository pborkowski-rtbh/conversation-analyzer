"""quality-record: a change event no source collects on its own, such as a document fix or an AQR rebase (§9.3)."""

from __future__ import annotations

from datetime import date

from conversation_analyzer import safe_log
from conversation_analyzer.bq.client import write
from conversation_analyzer.bq.schema import CHANGE_EVENTS
from conversation_analyzer.reporting.changes import event_id
from conversation_analyzer.settings import now
from conversation_analyzer.vocab import ChangeKind, ChangeSource


def record(
    kind: str, day: str | None, hour: int | None, doc_id: str | None, data_store: str | None, clusters: list[str]
) -> str:
    """Store the event (the leak guard checks the document and cluster IDs); returns its event ID."""
    recorded = now()
    when = date.fromisoformat(day) if day else recorded.date()
    kind = ChangeKind(kind).value
    row = {
        "event_id": event_id(ChangeSource.MANUAL, kind, when, hour, doc_id, data_store, *clusters, recorded),
        "day": when,
        "hour": hour,
        "source": ChangeSource.MANUAL.value,
        "kind": kind,
        "doc_id": doc_id,
        "data_store": data_store,
        "clusters": sorted(set(clusters)),
        "recorded_day": recorded.date(),
    }
    write(CHANGE_EVENTS, [row])
    safe_log.log("change_recorded", event_id=row["event_id"], kind=kind, clusters=len(row["clusters"]))
    return row["event_id"]
