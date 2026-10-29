"""Stored per-turn rows written straight to the emulator, for the reporting jobs (they never see the log's text)."""

from __future__ import annotations

import hashlib
import itertools
from datetime import date
from typing import Any

from conversation_analyzer.bq.client import write
from conversation_analyzer.bq.schema import QUALITY_TURNS, STAGE1_RESULTS, STAGE2_RESULTS
from conversation_analyzer.judge.version import current

_SEQ = itertools.count()
KNOWLEDGE = ("FACT_LOOKUP", "HOW_TO", "TROUBLESHOOTING", "DATA_QUESTION")
HR = {"doc_id": "hr_leave", "data_store": "rtb-crj-hr-house", "uri": "https://sites.google.com/rtbhouse.com/hr-house/x"}
CONF = {"doc_id": "confluence_1", "data_store": "rtb-crj-confluence", "uri": None}


def key() -> str:
    return hashlib.md5(str(next(_SEQ)).encode()).hexdigest()


def turn(
    day: date,
    *,
    channel: str = "WEB_UI",
    intent: str = "FACT_LOOKUP",
    topic: str = "HR_HOUSE",
    relevance: int = 5,
    groundedness: int | None = 5,
    primary: str = "NONE",
    severity: str | None = None,
    evidence: str = "OWN_REFERENCES",
    cited: tuple[dict[str, Any], ...] = (HR,),
    found: tuple[dict[str, Any], ...] = (),
    spans: tuple[int, int] | None = (2, 0),
    stage2: dict[str, Any] | None = None,
    reaction: str | None = None,
    thumbs: str | None = None,
    status: str = "ASSESSED",
    pace: bool = False,
    canary: bool = False,
) -> dict[str, Any]:
    """One turn: its quality_turns row and, when assessed, its stage 1 (and stage 2) result."""
    knowledge = intent in KNOWLEDGE
    verifiable = not knowledge or evidence != "NONE"
    k = key()
    out: dict[str, Any] = {
        "turn": {
            "turn_key": k,
            "session_key": key(),
            "segment_no": 1,
            "position_in_segment": 1,
            "position_in_session": 1,
            "day": day,
            "channel": channel,
            "is_canary": canary,
            "pace_excluded": pace,
            "status": status,
            "evidence_kind": evidence,
            "data_stores": sorted({d["data_store"] for d in cited}),
            "cited_docs": list(cited),
            "found_docs": list(found),
            "flagged": stage2 is not None or severity == "HIGH",
            "feedback_thumbs": thumbs,
            "reaction": reaction,
        }
    }
    if status != "ASSESSED":
        return out
    version = current()
    s1 = {
        "turn_key": k,
        "day": day,
        "judge_version": version.version_id,
        "intent": intent,
        "topic": topic,
        "relation": "FIRST",
        "relevance": relevance,
        "groundedness": groundedness if knowledge and verifiable else None,
        "total_spans": spans[0] if spans and knowledge and verifiable else None,
        "unsupported_spans": spans[1] if spans and knowledge and verifiable else None,
        "failure_types": [primary],
        "primary_failure": primary,
        "severity": severity,
        "knowledge_turn": knowledge,
        "verifiable": verifiable,
        "evidence_kind": evidence,
    }
    out["s1"] = s1
    if stage2:
        out["s2"] = {"turn_key": k, "day": day, "judge_version": version.version_id, **stage2}
    return out


def store(turns: list[dict[str, Any]]) -> None:
    write(QUALITY_TURNS, [t["turn"] for t in turns])
    write(STAGE1_RESULTS, [t["s1"] for t in turns if "s1" in t])
    write(STAGE2_RESULTS, [t["s2"] for t in turns if "s2" in t])
