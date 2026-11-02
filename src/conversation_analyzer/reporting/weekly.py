"""quality-weekly (§9, §12.9): problem clusters, closing fixed ones, document stats, eval documents, the digest."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from conversation_analyzer import safe_log
from conversation_analyzer.bq.client import fq, query, tbl, write
from conversation_analyzer.bq.schema import (
    CHANGE_EVENTS,
    DOCUMENT_STATS,
    EVAL_DOCUMENTS,
    METRICS_DAILY,
    PROBLEM_CLUSTERS,
    RELEASE_IMPACT,
    RETRIEVAL_COUNTS,
)
from conversation_analyzer.errors import AnalyzerError, report
from conversation_analyzer.judge.version import metric_version
from conversation_analyzer.leak_guard import allowed_data_store, is_people_directory
from conversation_analyzer.reporting import messages, slack
from conversation_analyzer.reporting.metrics import facts
from conversation_analyzer.reporting.monitor import reliable_labels
from conversation_analyzer.reporting.results import cluster_key, results
from conversation_analyzer.settings import get_settings, now
from conversation_analyzer.vocab import (
    ALL,
    FAMILY,
    ClusterState,
    EvalSet,
    FailureCode,
    GateVerdict,
    ReleaseVerdict,
    Severity,
    SliceKind,
    owner_of,
)

TREND_WEEKS = 4


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def quarter_start(day: date) -> date:
    return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)


@dataclass
class Cluster:
    cluster_id: str
    primary_failure: str
    data_store: str | None
    doc_id: str | None
    uri: str | None
    topic: str | None
    severities: Counter[str] = field(default_factory=Counter)

    @property
    def n(self) -> int:
        return sum(self.severities.values())

    def weighted(self, weights: dict[str, int]) -> int:
        return sum(weights.get(s, 0) * n for s, n in self.severities.items())


class Weekly:
    def __init__(self, week: date, today: date) -> None:
        self.week = week
        self.last = week + timedelta(days=6)
        self.today = today
        self.s = get_settings()
        self.version = metric_version(self.last).version_id

    def turns(self) -> list[dict[str, Any]]:
        """The week's assessed turns with their one result, each day under the version its metrics used (§8.2)."""
        out = []
        by_version: dict[str, list[date]] = defaultdict(list)
        for i in range(7):
            d = self.week + timedelta(days=i)
            by_version[metric_version(d).version_id].append(d)
        for version, days in by_version.items():  # a version's days are consecutive: it changes once, at a run end
            out += results(
                "t.day BETWEEN @a AND @b AND NOT t.is_canary AND NOT t.pace_excluded",
                version,
                a=min(days),
                b=max(days),
            )
        return out

    # ------------------------------------------------------------------ clusters (§9.1, §9.3)

    def clusters(self, turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        found: dict[str, Cluster] = {}
        for t in turns:
            if t["primary_failure"] in (None, FailureCode.NONE):
                continue
            key = cluster_key(t)
            c = found.setdefault(
                key.cluster_id,
                Cluster(key.cluster_id, key.primary_failure, key.data_store, key.doc_id, key.uri, key.topic),
            )
            c.severities[t["severity"] or Severity.LOW.value] += 1
        history = self.history()
        fixes = self.fixes()
        for cid in set(fixes) | {cid for cid, h in history.items() if h["state"] == ClusterState.ACTIVE and h["fixed"]}:
            if cid not in found and cid in history:  # a fixed cluster is followed also through weeks without turns
                h = history[cid]
                found[cid] = Cluster(cid, h["primary_failure"], h["data_store"], h["doc_id"], h["uri"], h["topic"])
        weights = self.s.clusters.severity_weights
        reliable = reliable_labels(self.version)
        ranked = sorted(
            found.values(), key=lambda c: (c.primary_failure not in reliable, -c.weighted(weights), -c.n, c.cluster_id)
        )
        rows = []
        rank = 0
        for c in ranked:
            experimental = c.primary_failure not in reliable  # shown, never ranked (§11.3)
            rank += not experimental
            prev = self.previous_counts(c.cluster_id)
            avg = statistics.mean(prev) if prev else None
            row = {
                "week": self.week,
                "cluster_id": c.cluster_id,
                "primary_failure": c.primary_failure,
                "family": FAMILY[FailureCode(c.primary_failure)].value,
                "owner": owner_of(FailureCode(c.primary_failure)).value,
                "data_store": c.data_store,
                "doc_id": c.doc_id,
                "uri": c.uri,
                "topic": c.topic,
                "n_turns": c.n,
                "n_high": c.severities[Severity.HIGH.value],
                "n_medium": c.severities[Severity.MEDIUM.value],
                "n_low": c.severities[Severity.LOW.value],
                "weighted": c.weighted(weights),
                "rank": None if experimental else rank,
                "prev_4w_avg": avg,
                "trend": (c.n / avg) if avg else None,
                "experimental": experimental,
                **self.fix_state(c, fixes.get(c.cluster_id, []), history.get(c.cluster_id)),
            }
            rows.append(row)
        return rows

    def history(self) -> dict[str, dict[str, Any]]:
        """Each cluster's latest stored week before this one."""
        rows = query(
            f"""
SELECT * EXCEPT(rn) FROM (
  SELECT cluster_id, primary_failure, data_store, doc_id, uri, topic, state, level_before_fix, weeks_below,
         ARRAY_LENGTH(fix_events) > 0 AS fixed, ROW_NUMBER() OVER (PARTITION BY cluster_id ORDER BY week DESC) AS rn
  FROM {tbl(PROBLEM_CLUSTERS)} WHERE week < @w
) WHERE rn = 1""",
            w=self.week,
        )
        return {r["cluster_id"]: r for r in rows}

    def previous_counts(self, cluster_id: str) -> list[int]:
        rows = query(
            f"SELECT week, n_turns FROM {tbl(PROBLEM_CLUSTERS)} WHERE cluster_id = @c AND week >= @a AND week < @w",
            c=cluster_id,
            a=self.week - timedelta(weeks=TREND_WEEKS),
            w=self.week,
        )
        stored = {r["week"]: r["n_turns"] for r in rows}
        return [stored.get(self.week - timedelta(weeks=k), 0) for k in range(1, TREND_WEEKS + 1)]

    def fixes(self) -> dict[str, list[dict[str, Any]]]:
        """Change events up to this week's end that name clusters they fix (§9.3)."""
        rows = query(
            f"SELECT event_id, day, clusters, doc_id, data_store FROM {tbl(CHANGE_EVENTS)} "
            "WHERE day <= @d AND ARRAY_LENGTH(clusters) > 0",
            d=self.last,
        )
        out: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            for cid in r["clusters"] or []:
                out[cid].append(r)
        return out

    def fix_state(self, c: Cluster, fixes: list[dict[str, Any]], prev: dict[str, Any] | None) -> dict[str, Any]:
        """Closed when its weekly turns stay under a quarter of the level before the fix for 2 weeks in a row."""
        cfg = self.s.clusters
        if prev and prev["state"] == ClusterState.CLOSED:
            state = {"state": ClusterState.CLOSED.value, "level_before_fix": prev["level_before_fix"]}
            return {**state, "weeks_below": prev["weeks_below"], "fix_events": [f["event_id"] for f in fixes]}
        if not fixes:
            return {"state": ClusterState.ACTIVE.value, "fix_events": [], "level_before_fix": None, "weeks_below": 0}
        fix_week = monday(min(f["day"] for f in fixes))
        level = prev["level_before_fix"] if prev and prev["level_before_fix"] is not None else None
        if level is None:
            rows = query(
                f"SELECT SUM(n_turns) AS n FROM {tbl(PROBLEM_CLUSTERS)} WHERE cluster_id = @c AND week >= @a "
                "AND week < @w",
                c=c.cluster_id,
                a=fix_week - timedelta(weeks=TREND_WEEKS),
                w=fix_week,
            )
            level = ((rows[0]["n"] if rows else 0) or 0) / TREND_WEEKS
            if self.week < fix_week:
                level = None
        below = 0
        if level is not None and self.week > fix_week:
            below = (prev["weeks_below"] if prev else 0) + 1 if c.n < cfg.close_ratio * level else 0
        state = ClusterState.CLOSED if below >= cfg.close_weeks else ClusterState.ACTIVE
        return {
            "state": state.value,
            "fix_events": sorted(f["event_id"] for f in fixes),
            "level_before_fix": level,
            "weeks_below": below,
        }

    # ------------------------------------------------------------------ documents (§9.2, §10.1)

    def document_stats(self, turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        stats: dict[tuple[str, str], dict[str, Any]] = {}

        def entry(d: dict[str, Any]) -> dict[str, Any] | None:
            if not allowed_data_store(d["data_store"]) or is_people_directory(d["data_store"], d["doc_id"]):
                return None
            return stats.setdefault(
                (d["doc_id"], d["data_store"]),
                {
                    "week": self.week,
                    "doc_id": d["doc_id"],
                    "data_store": d["data_store"],
                    "uri": d.get("uri"),
                    "topic": None,
                    "n_cited": 0,
                    "n_found": 0,
                    "n_retrieved": 0,
                    "n_verifiable": 0,
                    "n_good": 0,
                    "n_failures": 0,
                },
            )

        for t in turns:
            f = facts({**t, "status": "ASSESSED", "data_stores": []})
            for d in {(x["doc_id"], x["data_store"]): x for x in t.get("cited_docs") or []}.values():
                e = entry(d)
                if e is None:
                    continue
                e["topic"] = e["topic"] or t["topic"]
                e["n_cited"] += 1
                e["n_verifiable"] += f.verifiable
                e["n_good"] += f.good
                e["n_failures"] += t["primary_failure"] not in (None, FailureCode.NONE)
            for d in t.get("found_docs") or []:
                e = entry(d)
                if e is not None:
                    e["n_found"] += 1
        for r in query(
            f"SELECT doc_id, data_store, SUM(n_returned) AS n FROM {tbl(RETRIEVAL_COUNTS)} "
            "WHERE day BETWEEN @a AND @b GROUP BY doc_id, data_store",
            a=self.week,
            b=self.last,
        ):
            e = entry({"doc_id": r["doc_id"], "data_store": r["data_store"]})
            if e is not None:
                e["n_retrieved"] += r["n"] or 0
        prev = {
            (r["doc_id"], r["data_store"]): r["n"]
            for r in query(
                f"SELECT doc_id, data_store, SUM(n_cited) AS n FROM {tbl(DOCUMENT_STATS)} "
                "WHERE week >= @a AND week < @w GROUP BY doc_id, data_store",
                a=self.week - timedelta(weeks=TREND_WEEKS),
                w=self.week,
            )
        }
        for key, e in stats.items():
            e["aqr"] = e["n_good"] / e["n_verifiable"] if e["n_verifiable"] else None
            e["cited_prev_4w_avg"] = (prev.get(key) or 0) / TREND_WEEKS
        return list(stats.values())

    def eval_documents(self, docs: list[dict[str, Any]], clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Anchor documents once a quarter by traffic; focus documents per active cluster (a gap's, once fixed)."""
        cfg = self.s.eval_documents
        period = quarter_start(self.week)
        out = []
        have = query(
            f"SELECT COUNT(*) AS n FROM {tbl(EVAL_DOCUMENTS)} WHERE period = @p AND eval_set = @a",
            p=period,
            a=EvalSet.ANCHOR.value,
        )
        if not (have and have[0]["n"]):
            out += anchor_set([d for d in docs if d["n_cited"] + d["n_retrieved"] > 0], period, self.week)
        fixes = self.fixes()
        for c in clusters:
            if c["state"] != ClusterState.ACTIVE or not c["n_turns"]:
                continue
            doc = {"doc_id": c["doc_id"], "data_store": c["data_store"], "uri": c["uri"]}
            if not c["doc_id"]:
                added = [f for f in fixes.get(c["cluster_id"], []) if f["doc_id"] and f["data_store"]]
                if not added:
                    continue
                doc = {"doc_id": added[-1]["doc_id"], "data_store": added[-1]["data_store"], "uri": None}
            if doc["doc_id"]:
                out.append(
                    {
                        "period": self.week,
                        "eval_set": EvalSet.FOCUS.value,
                        "doc_id": doc["doc_id"],
                        "data_store": doc["data_store"],
                        "uri": doc["uri"],
                        "cluster_id": c["cluster_id"],
                        "n_questions": cfg.focus_questions_per_cluster,
                        "traffic_share": None,
                        "week": self.week,
                    }
                )
        return out

    # ------------------------------------------------------------------ digest (§9.2)

    def digest(self, clusters: list[dict[str, Any]], docs: list[dict[str, Any]]) -> str:
        cfg = self.s.digest
        aqr = query(
            f"""
SELECT channel, IF(day >= @w, 'now', 'before') AS period, SUM(numerator) AS num, SUM(denominator) AS den
FROM {tbl(METRICS_DAILY)}
WHERE metric = 'AQR_STANDARDIZED' AND slice_kind = @all AND NOT incomplete AND day BETWEEN @a AND @b
GROUP BY channel, period""",
            w=self.week,
            all=SliceKind.ALL.value,
            a=self.week - timedelta(weeks=TREND_WEEKS),
            b=self.last,
        )
        trend: dict[str, dict[str, float | None]] = defaultdict(dict)
        for r in aqr:
            trend[r["channel"]][r["period"]] = r["num"] / r["den"] if r["den"] else None
        active = [c for c in clusters if c["state"] == ClusterState.ACTIVE and c["n_turns"]]
        top = [c for c in active if not c["experimental"]][: self.s.clusters.top_n]
        experimental = [c for c in active if c["experimental"]]
        min_turns = self.s.metrics.min_slice_size
        rated = [d for d in docs if d["n_verifiable"] >= min_turns and d["aqr"] is not None]
        best_docs = sorted(rated, key=lambda d: (-d["aqr"], -d["n_verifiable"]))[: cfg.best_n]
        topics = self.topic_aqr()
        best_topics = sorted((t for t in topics if t["n"] >= min_turns), key=lambda t: (-(t["aqr"] or 0), -t["n"]))[
            : cfg.best_n
        ]
        unusual = self.unusual(docs, topics)
        releases = query(
            f"""
SELECT event_id, verdict, diff FROM {tbl(RELEASE_IMPACT)}
WHERE computed_day BETWEEN @a AND @b AND metric = 'AQR_STANDARDIZED' AND channel = @all AND verdict != @waiting""",
            a=self.week,
            b=self.last + timedelta(days=1),
            all=ALL,
            waiting=ReleaseVerdict.WAITING.value,
        )
        gates = query(
            f"""
SELECT change_id, verdict FROM {fq("evals", "gate_results")}
WHERE DATE(created_at) BETWEEN @a AND @b AND verdict IN UNNEST(@verdicts)""",
            a=self.week,
            b=self.last,
            verdicts=[v.value for v in GateVerdict],
        )
        return messages.digest(
            self.week,
            trend,
            top,
            experimental,
            best_docs,
            best_topics,
            unusual,
            releases,
            gates,
            self.baseline_top_turns(),
        )

    def topic_aqr(self) -> list[dict[str, Any]]:
        rows = query(
            f"""
SELECT slice_value AS topic, IF(day >= @w, 'now', 'before') AS period, SUM(numerator) AS num,
       SUM(denominator) AS den, SUM(n_turns) AS n
FROM {tbl(METRICS_DAILY)}
WHERE metric = 'AQR_RAW' AND channel = @all AND slice_kind = @topic AND NOT merged AND day BETWEEN @a AND @b
GROUP BY topic, period""",
            w=self.week,
            all=ALL,
            topic=SliceKind.TOPIC.value,
            a=self.week - timedelta(weeks=TREND_WEEKS),
            b=self.last,
        )
        by: dict[str, dict[str, Any]] = defaultdict(lambda: {"n": 0, "n_before": 0, "aqr": None})
        for r in rows:
            t = by[r["topic"]]
            t["topic"] = r["topic"]
            if r["period"] == "now":
                t["n"] = r["n"] or 0
                t["aqr"] = r["num"] / r["den"] if r["den"] else None
            else:
                t["n_before"] = (r["n"] or 0) / TREND_WEEKS
        return list(by.values())

    def unusual(self, docs: list[dict[str, Any]], topics: list[dict[str, Any]]) -> list[str]:
        """Fast-growing topics, growth of OTHER, documents suddenly cited much more (§9.2)."""
        ratio = self.s.digest.growth_ratio
        small = self.s.metrics.min_slice_size
        out = []
        for t in sorted(topics, key=lambda t: t["topic"]):
            if t["n"] >= small and t["n_before"] and t["n"] >= ratio * t["n_before"]:
                label = "OTHER topic grew" if t["topic"] == "OTHER" else f"fast-growing topic {t['topic']}"
                out.append(f"{label}: {t['n']} turns, {t['n_before']:.0f} a week before")
        for d in sorted(docs, key=lambda d: -d["n_cited"]):
            if d["n_cited"] >= small and d["cited_prev_4w_avg"] and d["n_cited"] >= ratio * d["cited_prev_4w_avg"]:
                out.append(
                    f"{d['data_store']} document {d['doc_id']} cited {d['n_cited']} times, "
                    f"{d['cited_prev_4w_avg']:.0f} a week before"
                )
        return out

    def baseline_top_turns(self) -> int | None:
        """This week's turns still in the top clusters of the baseline's last week: is the loop working (§9.3)?"""
        go_live = self.s.metrics.go_live_day
        if go_live is None:
            return None
        baseline_week = monday(go_live + timedelta(days=27))
        rows = query(
            f"""
SELECT SUM(now.n_turns) AS n FROM {tbl(PROBLEM_CLUSTERS)} base
JOIN {tbl(PROBLEM_CLUSTERS)} now ON now.cluster_id = base.cluster_id AND now.week = @w
WHERE base.week = @b AND base.rank <= @top""",
            w=self.week,
            b=baseline_week,
            top=self.s.clusters.top_n,
        )
        return (rows[0]["n"] or 0) if rows and self.week > baseline_week else None

    def execute(self) -> dict[str, Any]:
        turns = self.turns()
        clusters = self.clusters(turns)
        write(PROBLEM_CLUSTERS, clusters)
        docs = self.document_stats(turns)
        write(DOCUMENT_STATS, docs)
        evals = self.eval_documents(docs, clusters)
        write(EVAL_DOCUMENTS, evals)
        sent = False
        try:
            slack.post(self.s.alerts.quality_channel, self.digest(clusters, docs))
            sent = True
        except AnalyzerError as exc:
            report(exc)
        summary = {
            "turns": len(turns),
            "clusters": len(clusters),
            "documents": len(docs),
            "eval_documents": len(evals),
            "digest_sent": sent,
        }
        safe_log.log("weekly_run", **summary)
        return summary


def anchor_set(docs: list[dict[str, Any]], period: date, week: date) -> list[dict[str, Any]]:
    """Questions per document in proportion to how often traffic cites or retrieves it, at least 20 per data store."""
    cfg = get_settings().eval_documents
    weight = {(d["doc_id"], d["data_store"]): d["n_cited"] + d["n_retrieved"] for d in docs}
    total = sum(weight.values())
    if not total:
        return []
    per_store: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in docs:
        per_store[d["data_store"]].append(d)
    out = []
    for store, members in sorted(per_store.items()):
        share = {(d["doc_id"], d["data_store"]): weight[(d["doc_id"], d["data_store"])] / total for d in members}
        store_questions = max(round(cfg.anchor_questions * sum(share.values())), cfg.anchor_min_per_data_store)
        store_total = sum(share.values())
        for d in sorted(members, key=lambda d: -share[(d["doc_id"], d["data_store"])]):
            n = round(store_questions * share[(d["doc_id"], d["data_store"])] / store_total)
            if n:
                out.append(
                    {
                        "period": period,
                        "eval_set": EvalSet.ANCHOR.value,
                        "doc_id": d["doc_id"],
                        "data_store": store,
                        "uri": d.get("uri"),
                        "cluster_id": None,
                        "n_questions": n,
                        "traffic_share": share[(d["doc_id"], d["data_store"])],
                        "week": week,
                    }
                )
    return out


def run(week: str | None = None) -> dict[str, Any]:
    today = now().date()
    start = date.fromisoformat(week) if week else monday(today) - timedelta(days=7)
    return Weekly(monday(start), today).execute()
