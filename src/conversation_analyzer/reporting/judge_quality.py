"""Judge quality measures of a day (§11.4, §11.5): canary agreement, planted errors, index hit rate, real traffic."""

from __future__ import annotations

from datetime import date
from typing import Any

from conversation_analyzer.bq.client import fq, query, tbl
from conversation_analyzer.bq.schema import CANARY_RESULTS, JUDGE_CHECKS, QUALITY_TURNS, STAGE1_RESULTS, STAGE2_RESULTS
from conversation_analyzer.reporting.metrics import facts
from conversation_analyzer.reporting.results import RESULT_COLUMNS
from conversation_analyzer.vocab import FindingVerdict, FormField, JudgeMeasure, PlantedError, Severity, Thumbs

# The evaluator's metric (aiel_evals.results, scores 0-1) that each of our fields is compared with; both sides are
# reduced to good or not: our score 4 or higher (no HIGH for severity), theirs 0.5 or higher.
AGREEMENT = {
    FormField.RELEVANCE: "RELEVANCE",
    FormField.GROUNDEDNESS: "GROUNDEDNESS",
    FormField.SEVERITY: "CORRECTNESS",
}


def _measure(day: date, measure: JudgeMeasure, field: str, hits: int, n: int) -> dict[str, Any] | None:
    if not n:
        return None
    return {"day": day, "measure": measure.value, "field": field, "value": hits / n, "n": n}


def canary(day: date, version: str) -> list[dict[str, Any] | None]:
    rows = query(
        f"""
SELECT c.planted_error, c.with_references, c.question_hash, c.relevance, c.groundedness, c.severity, c.caught,
       c.false_high
FROM {tbl(CANARY_RESULTS)} c WHERE c.day = @d AND c.judge_version = @v""",
        d=day,
        v=version,
    )
    answered = [r for r in rows if r["planted_error"] == PlantedError.NONE]
    planted = [r for r in rows if r["planted_error"] != PlantedError.NONE]
    out = []
    for kind in sorted({r["planted_error"] for r in planted}):
        mine = [r for r in planted if r["planted_error"] == kind]
        out.append(_measure(day, JudgeMeasure.PLANTED_CAUGHT, kind, sum(bool(r["caught"]) for r in mine), len(mine)))
    out.append(
        _measure(
            day,
            JudgeMeasure.PLANTED_FALSE_HIGH,
            FormField.ALL,
            sum(bool(r["false_high"]) for r in answered),
            len(answered),
        )
    )
    hashes = sorted({r["question_hash"] for r in answered})
    scores: dict[tuple[str, str], float] = {}
    if hashes:
        for r in query(
            f"""
SELECT question_sha256, metric, AVG(score) AS score FROM {fq("evals", "results")}
WHERE run_kind = 'CANARY' AND DATE(created_at) = @d AND question_sha256 IN UNNEST(@h) GROUP BY 1, 2""",
            d=day,
            h=hashes,
        ):
            scores[(r["question_sha256"], r["metric"])] = r["score"]
    for field, metric in AGREEMENT.items():
        pairs = []
        for r in answered:
            theirs = scores.get((r["question_hash"], metric))
            mine = r["severity"] != Severity.HIGH if field is FormField.SEVERITY else r[field.value.lower()]
            if theirs is None or mine is None:
                continue
            ours_good = mine if isinstance(mine, bool) else mine >= 4
            pairs.append(ours_good == (theirs >= 0.5))
        out.append(_measure(day, JudgeMeasure.CANARY_AGREEMENT, field.value, sum(pairs), len(pairs)))
    return out


def real_traffic(day: date, version: str) -> list[dict[str, Any] | None]:
    out = []
    for r in query(
        f"SELECT field, SUM(n_compared) AS n_compared, SUM(n_disagreements) AS n_disagreements "
        f"FROM {tbl(JUDGE_CHECKS)} WHERE day = @d GROUP BY field ORDER BY field",
        d=day,
    ):
        out.append(
            _measure(day, JudgeMeasure.SECOND_MODEL_DISAGREEMENT, r["field"], r["n_disagreements"], r["n_compared"])
        )
    rows = query(
        f"""
SELECT {RESULT_COLUMNS}, t.status, t.data_stores, s1.primary_failure AS s1_primary,
       (SELECT COUNTIF(f.verdict = @dropped) FROM UNNEST(s2.stage1_findings) f) AS dropped
FROM {tbl(QUALITY_TURNS)} t
JOIN {tbl(STAGE1_RESULTS)} s1 ON s1.turn_key = t.turn_key AND s1.judge_version = @v
LEFT JOIN {tbl(STAGE2_RESULTS)} s2 ON s2.turn_key = t.turn_key AND s2.judge_version = @v
WHERE t.day = @d AND NOT t.is_canary AND NOT t.pace_excluded""",
        d=day,
        v=version,
        dropped=FindingVerdict.DROPPED.value,
    )
    turns = [(r, facts(r)) for r in rows]
    disliked = [t for r, t in turns if r["feedback_thumbs"] == Thumbs.DOWN and t.verifiable]
    others = [t for r, t in turns if r["feedback_thumbs"] != Thumbs.DOWN and t.verifiable]
    out.append(_measure(day, JudgeMeasure.DISLIKED_AQR, FormField.ALL, sum(t.good for t in disliked), len(disliked)))
    out.append(_measure(day, JudgeMeasure.NOT_DISLIKED_AQR, FormField.ALL, sum(t.good for t in others), len(others)))
    stage2 = [r for r, _ in turns if r["has_stage2"]]
    changed = sum(r["primary_failure"] != r["s1_primary"] or (r["dropped"] or 0) > 0 for r in stage2)
    out.append(_measure(day, JudgeMeasure.STAGE2_CHANGE_RATE, FormField.ALL, changed, len(stage2)))
    dropped = sum((r["dropped"] or 0) > 0 for r in stage2)
    out.append(_measure(day, JudgeMeasure.STAGE2_DROP_RATE, FormField.ALL, dropped, len(stage2)))
    return out


def measures(day: date, version: str) -> list[dict[str, Any]]:
    return [m for m in (*canary(day, version), *real_traffic(day, version)) if m is not None]
