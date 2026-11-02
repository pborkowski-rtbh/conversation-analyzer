"""One result per turn (stage 2 where it exists, else stage 1; §7.6, §8.2) and its problem cluster (§9.1)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from conversation_analyzer.bq.client import query, tbl
from conversation_analyzer.bq.schema import QUALITY_TURNS, STAGE1_RESULTS, STAGE2_RESULTS
from conversation_analyzer.leak_guard import is_people_directory
from conversation_analyzer.vocab import FailureCode, TurnStatus

RESULT_COLUMNS = """
  t.turn_key, t.session_key, t.segment_no, t.day, t.channel, t.is_canary, t.pace_excluded, t.stage2_state,
  t.flagged, t.flag_reasons, t.cited_docs, t.found_docs, t.feedback_thumbs, t.reaction,
  s1.intent, s1.topic, s1.relevance, s1.completeness, s1.clarity, s1.groundedness, s1.unsupported_spans,
  s1.total_spans, s1.language_matches, s1.refusal_or_empty, s1.knowledge_turn, s1.verifiable, s1.evidence_kind,
  s1.needs_internal_knowledge,
  s2.turn_key IS NOT NULL AS has_stage2,
  IF(s2.turn_key IS NULL, s1.primary_failure, s2.primary_failure) AS primary_failure,
  IF(s2.turn_key IS NULL, s1.severity, s2.severity) AS severity,
  IF(s2.turn_key IS NULL, s1.groundedness, s2.groundedness) AS final_groundedness,
  s2.document_to_fix.doc_id AS fix_doc_id, s2.document_to_fix.data_store AS fix_data_store,
  s2.document_to_fix.uri AS fix_uri"""


def results_sql(where: str) -> str:
    """Assessed turns with their one result for judge version @v; `where` filters on `t.` and `s1.` columns."""
    return f"""
SELECT {RESULT_COLUMNS}
FROM {tbl(QUALITY_TURNS)} t
JOIN {tbl(STAGE1_RESULTS)} s1 ON s1.turn_key = t.turn_key AND s1.judge_version = @v
LEFT JOIN {tbl(STAGE2_RESULTS)} s2 ON s2.turn_key = t.turn_key AND s2.judge_version = @v
WHERE t.status = '{TurnStatus.ASSESSED.value}' AND {where}"""


def results(where: str, version_id: str, **params: Any) -> list[dict[str, Any]]:
    return query(results_sql(where), v=version_id, **params)


@dataclass(frozen=True)
class ClusterKey:
    """The same primary failure and the same document, or the same topic when there is no single document."""

    primary_failure: str
    data_store: str | None
    doc_id: str | None
    uri: str | None
    topic: str | None

    @property
    def cluster_id(self) -> str:
        raw = "|".join(x or "" for x in (self.primary_failure, self.data_store, self.doc_id, self.topic))
        return "cluster-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def cluster_key(row: dict[str, Any]) -> ClusterKey:
    """Stage 2 turns cluster by the document to fix, others by the one cited document; else by topic (§9.1)."""
    failure = row["primary_failure"]
    doc: dict[str, Any] | None = None
    if failure != FailureCode.NOT_IN_CITED_SOURCES:  # no document to fix: clustered by topic
        if row.get("has_stage2"):
            if row.get("fix_doc_id"):
                doc = {"doc_id": row["fix_doc_id"], "data_store": row["fix_data_store"], "uri": row.get("fix_uri")}
        else:
            cited = {
                (d["doc_id"], d["data_store"]): d
                for d in row.get("cited_docs") or []
                if not is_people_directory(d["data_store"], d["doc_id"], d.get("uri"))
            }
            if len(cited) == 1:
                doc = next(iter(cited.values()))
    if doc is None:
        return ClusterKey(failure, None, None, None, row.get("topic"))
    return ClusterKey(failure, doc["data_store"], doc["doc_id"], doc.get("uri"), None)
