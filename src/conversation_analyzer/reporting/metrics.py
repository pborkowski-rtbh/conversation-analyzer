"""Daily metrics (§8): one result per turn, rates per channel and slice, standardized AQR; recomputed from scratch."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from conversation_analyzer.bq.client import fq, query, tbl
from conversation_analyzer.bq.schema import (
    CHANGE_EVENTS,
    METRICS_DAILY,
    QUALITY_TURNS,
    RUNS,
    SEGMENTS,
    STAGE1_RESULTS,
    STAGE2_RESULTS,
)
from conversation_analyzer.leak_guard import allowed_data_store
from conversation_analyzer.reporting.results import RESULT_COLUMNS
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import (
    ALL,
    CONTINUED_RELATIONS,
    FAILURE_RATE_CODES,
    MERGED_OTHER,
    NEGATIVE_REACTIONS,
    ChangeKind,
    Channel,
    CloseReason,
    DayKind,
    DepartmentFamily,
    EvidenceKind,
    Severity,
    SliceKind,
    Thumbs,
    TurnStatus,
    failure_rate_metric,
    stratum_code,
)

BASELINE_DAYS = 28
CHANNELS = (Channel.WEB_UI.value, Channel.SLACK_MCP.value, ALL)
_FAMILY_SLICES = {SliceKind.INTENT: SliceKind.INTENT_FAMILY, SliceKind.TOPIC: SliceKind.DATA_STORE_FAMILY}


def day_kind(day: date) -> str:
    return (DayKind.WEEKEND if day.weekday() >= 5 else DayKind.WEEKDAY).value


def _family(families: dict[str, list[str]], value: str | None) -> str:
    return next((f for f, members in families.items() if value in members), MERGED_OTHER)


@dataclass
class TurnFacts:
    """What the metrics need of one turn; text never reaches this job."""

    channel: str
    assessed: bool
    pace_excluded: bool
    reaction: str | None
    disliked: bool
    department: str = DepartmentFamily.UNKNOWN.value
    intent: str | None = None
    topic: str | None = None
    data_stores: tuple[str, ...] = ()
    knowledge: bool = False
    verifiable: bool = False
    evidence: str | None = None
    good: bool = False
    high: bool = False
    primary: str | None = None
    spans: bool = False
    unsupported: bool = False
    flagged: bool = False

    def slices(self) -> list[tuple[str, str]]:
        s = get_settings().strata
        out = [(SliceKind.ALL.value, ALL)]
        if not self.assessed:
            return out
        intent_family = _family(s.intent_families, self.intent)
        topic_family = _family(s.data_store_families, self.topic)
        out += [
            (SliceKind.INTENT.value, self.intent),
            (SliceKind.TOPIC.value, self.topic),
            (SliceKind.INTENT_FAMILY.value, intent_family),
            (SliceKind.DATA_STORE_FAMILY.value, topic_family),
            (SliceKind.DEPARTMENT.value, self.department),
            (SliceKind.STRATUM.value, stratum_code(intent_family, topic_family, self.department)),
        ]
        out += [(SliceKind.DATA_STORE.value, ds) for ds in self.data_stores]
        return out


def facts(row: dict[str, Any]) -> TurnFacts:
    assessed = row["status"] == TurnStatus.ASSESSED and row.get("intent") is not None
    t = TurnFacts(
        channel=row["channel"],
        assessed=assessed,
        pace_excluded=bool(row["pace_excluded"]),
        reaction=row.get("reaction"),
        disliked=row.get("feedback_thumbs") == Thumbs.DOWN,
        department=row.get("department") or DepartmentFamily.UNKNOWN.value,
    )
    if not assessed:
        return t
    t.intent, t.topic = row["intent"], row["topic"]
    t.data_stores = tuple(sorted({d for d in row.get("data_stores") or [] if allowed_data_store(d)}))
    t.knowledge, t.verifiable = bool(row["knowledge_turn"]), bool(row["verifiable"])
    t.evidence = row["evidence_kind"]
    t.high = row["severity"] == Severity.HIGH
    t.primary = row["primary_failure"]
    grounded = not t.knowledge or (row["final_groundedness"] or 0) >= 4
    t.good = t.verifiable and row["relevance"] >= 4 and grounded and not t.high
    t.spans = t.knowledge and t.verifiable and bool(row.get("total_spans"))
    t.unsupported = t.spans and (row.get("unsupported_spans") or 0) > 0
    t.flagged = bool(row.get("flagged"))
    return t


Rule = tuple[Callable[[TurnFacts], bool], Callable[[TurnFacts], bool] | None]
# Metric: (numerator, denominator) over the turns of a slice; a None denominator makes the metric a count.
QUALITY: dict[str, Rule] = {
    "AQR_RAW": (lambda t: t.good, lambda t: t.verifiable),
    "NOT_VERIFIABLE_SHARE": (lambda t: t.knowledge and not t.verifiable, lambda t: t.knowledge),
    "EVIDENCE_OWN_SHARE": (lambda t: t.evidence == EvidenceKind.OWN_REFERENCES, lambda t: t.knowledge),
    "EVIDENCE_EARLIER_SHARE": (lambda t: t.evidence == EvidenceKind.EARLIER_REFERENCES, lambda t: t.knowledge),
    "EVIDENCE_NONE_SHARE": (lambda t: t.knowledge and t.evidence == EvidenceKind.NONE, lambda t: t.knowledge),
    "CONTRADICTED_COUNT": (lambda t: t.high, None),
    "CONTRADICTED_SHARE": (lambda t: t.high, lambda t: t.knowledge),
    "UNSUPPORTED_SHARE": (lambda t: t.unsupported, lambda t: t.spans),
    "FLAGGED_SHARE": (lambda t: t.flagged, lambda t: True),
    **{failure_rate_metric(c): ((lambda t, c=c: t.primary == c), (lambda t: True)) for c in FAILURE_RATE_CODES},
}


def _rate(turns: Iterable[TurnFacts], rule: Rule) -> tuple[float, float | None]:
    num_f, den_f = rule
    num = den = 0
    for t in turns:
        if den_f is None or den_f(t):
            den += 1
            num += num_f(t)
    return float(num), (float(den) if den_f is not None else None)


def _row(day, channel, metric, kind, value, num, den, n, incomplete, version, merged=False) -> dict[str, Any]:
    if den is not None:
        value = num / den if den else None
    return {
        "day": day,
        "day_kind": day_kind(day),
        "channel": channel,
        "metric": metric,
        "slice_kind": kind[0],
        "slice_value": kind[1],
        "value": value,
        "numerator": num,
        "denominator": den,
        "n_turns": n,
        "incomplete": incomplete,
        "merged": merged,
        "judge_version": version,
    }


class DayMetrics:
    """All metric rows of one day: per channel (and all channels), per slice, with small slices merged (§8.5)."""

    def __init__(self, day: date, version: str, incomplete: dict[str, bool], gap_hours: dict[str, int]) -> None:
        self.day = day
        self.version = version
        self.incomplete = incomplete
        self.gap_hours = gap_hours
        self.s = get_settings()

    def turns(self) -> list[TurnFacts]:
        rows = query(
            f"""
SELECT {RESULT_COLUMNS}, t.status, t.data_stores, t.department
FROM {tbl(QUALITY_TURNS)} t
LEFT JOIN {tbl(STAGE1_RESULTS)} s1 ON s1.turn_key = t.turn_key AND s1.judge_version = @v
LEFT JOIN {tbl(STAGE2_RESULTS)} s2 ON s2.turn_key = t.turn_key AND s2.judge_version = @v
WHERE t.day = @d AND NOT t.is_canary""",
            d=self.day,
            v=self.version,
        )
        return [facts(r) for r in rows]

    def rows(self) -> list[dict[str, Any]]:
        turns = self.turns()
        out: list[dict[str, Any]] = []
        for channel in CHANNELS:
            mine = [t for t in turns if channel == ALL or t.channel == channel]
            counted = [t for t in mine if not t.pace_excluded]
            out += self.quality_rows(channel, counted)
            out.append(self.row(channel, "PACE_EXCLUDED_COUNT", (ALL, ALL), len(mine) - len(counted), None, None))
        out += self.pipeline_rows(turns)
        return out

    def row(self, channel, metric, kind, num, den, n, merged=False, value=None) -> dict[str, Any]:
        k = (SliceKind.ALL.value, ALL) if kind == (ALL, ALL) else kind
        value = num if den is None and value is None else value
        return _row(self.day, channel, metric, k, value, num, den, n, self.incomplete[channel], self.version, merged)

    def quality_rows(self, channel: str, turns: list[TurnFacts]) -> list[dict[str, Any]]:
        by_slice: dict[tuple[str, str], list[TurnFacts]] = defaultdict(list)
        for t in turns:
            for s in t.slices():
                by_slice[s].append(t)
        small = self.s.metrics.min_slice_size
        merged: dict[str, list[TurnFacts]] = defaultdict(list)
        out = []
        for (kind, value), members in sorted(by_slice.items()):
            assessed = [t for t in members if t.assessed]
            # Strata are always kept: they are the parts standardized AQR is built from (§8.4).
            if kind not in (SliceKind.ALL, SliceKind.STRATUM) and len(assessed) < small:
                merged[kind] += assessed
                continue
            out += self.slice_rows(channel, (kind, value), members, assessed)
        for kind, members in sorted(merged.items()):
            out += self.slice_rows(channel, (kind, MERGED_OTHER), members, members, merged=True)
        out.append(self.standardized(channel, [t for t in turns if t.assessed]))
        return out

    def slice_rows(self, channel, kind, members, assessed, merged=False) -> list[dict[str, Any]]:
        out = [self.row(channel, m, kind, *_rate(assessed, rule), len(assessed), merged) for m, rule in QUALITY.items()]
        num, den = _rate(members, (lambda t: t.reaction in NEGATIVE_REACTIONS, lambda t: t.reaction is not None))
        out.append(self.row(channel, "NEGATIVE_REACTION_RATE", kind, num, den, len(members), merged))
        return out

    def weights(self, channel: str, today_mix: dict[str, float]) -> dict[str, float]:
        """Each stratum's share of verifiable turns in the baseline: the 4 weeks from go-live or the last rebase."""
        start = self.s.metrics.go_live_day
        rebases = query(
            f"SELECT MAX(day) AS day FROM {tbl(CHANGE_EVENTS)} WHERE kind = @k AND day <= @d",
            k=ChangeKind.AQR_REBASE.value,
            d=self.day,
        )
        if rebases and rebases[0]["day"]:
            start = rebases[0]["day"]
        rows = []
        if start is not None:
            rows = query(
                f"""
SELECT slice_value AS stratum, SUM(denominator) AS n FROM {tbl(METRICS_DAILY)}
WHERE metric = 'AQR_RAW' AND slice_kind = @kind AND channel = @c AND NOT incomplete
  AND day >= @a AND day < @b AND day < @d
GROUP BY stratum""",
                kind=SliceKind.STRATUM.value,
                c=channel,
                a=start,
                b=start + timedelta(days=BASELINE_DAYS),
                d=self.day,
            )
        mix = {r["stratum"]: float(r["n"] or 0) for r in rows} or today_mix
        total = sum(mix.values())
        return {k: v / total for k, v in mix.items() if v} if total else {}

    def standardized(self, channel: str, assessed: list[TurnFacts]) -> dict[str, Any]:
        """Stratum AQRs weighted by the baseline mix; a small stratum takes its intent family's or the channel's AQR."""
        small = self.s.metrics.min_slice_size
        verifiable = [t for t in assessed if t.verifiable]
        by: dict[tuple[str, str], list[TurnFacts]] = defaultdict(list)
        for t in verifiable:
            kinds = dict(t.slices())
            by[(SliceKind.STRATUM.value, kinds[SliceKind.STRATUM.value])].append(t)
            by[(SliceKind.INTENT_FAMILY.value, kinds[SliceKind.INTENT_FAMILY.value])].append(t)

        def aqr(group: list[TurnFacts]) -> float:
            return sum(t.good for t in group) / len(group)

        overall = aqr(verifiable) if verifiable else None
        today_mix = {k[1]: float(len(v)) for k, v in by.items() if k[0] == SliceKind.STRATUM}
        value = None
        weights = self.weights(channel, today_mix)
        if overall is not None and weights:
            value = 0.0
            for stratum, w in weights.items():
                own = by.get((SliceKind.STRATUM.value, stratum), [])
                family = by.get((SliceKind.INTENT_FAMILY.value, stratum.split("__")[0]), [])
                value += w * (aqr(own) if len(own) >= small else aqr(family) if len(family) >= small else overall)
        n = len(verifiable)
        return self.row(channel, "AQR_STANDARDIZED", (ALL, ALL), (value or 0.0) * n, n, len(assessed), value=value)

    def pipeline_rows(self, turns: list[TurnFacts]) -> list[dict[str, Any]]:
        """Coverage against the log's own counts; usage; log gaps; resumed segments; the day's oldest waiting turn."""
        logs = fq("log_views", "quality_turn_counts_hourly")
        volume = {
            r["channel"]: r["n"]
            for r in query(f"SELECT channel, SUM(n_turns) AS n FROM {logs} WHERE day = @d GROUP BY channel", d=self.day)
        }
        volume[ALL] = sum(volume.values())
        stored = query(
            f"SELECT channel, status, COUNT(*) AS n FROM {tbl(QUALITY_TURNS)} WHERE day = @d AND NOT is_canary "
            "GROUP BY channel, status",
            d=self.day,
        )
        done: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for r in stored:
            for ch in (r["channel"], ALL):
                done[ch][r["status"]] += r["n"]
        out = []
        for ch in CHANNELS:
            eligible = float(volume.get(ch, 0))
            covered = done[ch][TurnStatus.ASSESSED] + done[ch][TurnStatus.TOO_LARGE]
            out += [
                self.row(ch, "VOLUME", (ALL, ALL), eligible, None, int(eligible)),
                self.row(ch, "COVERAGE", (ALL, ALL), float(covered), eligible, int(eligible)),
                self.row(ch, "TOO_LARGE_SHARE", (ALL, ALL), float(done[ch][TurnStatus.TOO_LARGE]), eligible, None),
                self.row(ch, "MISSED_COUNT", (ALL, ALL), max(eligible - covered, 0.0), None, None),
                self.row(ch, "LOG_GAP_HOURS", (ALL, ALL), float(self.gap_hours.get(ch, 0)), None, None),
            ]
        feedback = query(
            f"SELECT SUM(n_dislikes) AS n FROM {fq('log_views', 'quality_feedback_counts_daily')} WHERE day = @d",
            d=self.day,
        )
        dislikes = float((feedback[0]["n"] if feedback else 0) or 0)
        web = float(volume.get(Channel.WEB_UI.value, 0))
        for ch in (Channel.WEB_UI.value, ALL):  # feedback exists in the web UI only (§8.9)
            out.append(self.row(ch, "DISLIKE_COUNT", (ALL, ALL), dislikes, None, None))
            out.append(self.row(ch, "DISLIKE_RATE", (ALL, ALL), dislikes, web, int(web)))
        oldest = query(f"SELECT MAX(oldest_waiting_minutes) AS m FROM {tbl(RUNS)} WHERE run_day = @d", d=self.day)
        if oldest and oldest[0]["m"] is not None:
            out.append(self.row(ALL, "OLDEST_WAITING_MINUTES", (ALL, ALL), float(oldest[0]["m"]), None, None))
        out += self.segment_rows()
        out += self.engine_usage()
        return out

    def segment_rows(self) -> list[dict[str, Any]]:
        rows = query(
            f"""
SELECT COUNTIF(resumed) AS resumed, COUNTIF(resumed AND earlier_text_missing) AS without_text,
       COUNTIF(resumed AND previous_close_reason = @idle AND NOT earlier_text_missing) AS idle_with_text,
       COUNTIF(resumed AND previous_close_reason = @idle AND NOT earlier_text_missing
               AND first_turn_relation IN UNNEST(@continued)) AS continued
FROM {tbl(SEGMENTS)} WHERE first_day = @d""",
            d=self.day,
            idle=CloseReason.IDLE.value,
            continued=sorted(r.value for r in CONTINUED_RELATIONS),
        )
        r = rows[0] if rows else {}
        resumed = float(r.get("resumed") or 0)
        return [
            self.row(ALL, "RESUMED_WITHOUT_TEXT", (ALL, ALL), float(r.get("without_text") or 0), resumed, None),
            self.row(
                ALL,
                "RESUMED_AND_CONTINUED",
                (ALL, ALL),
                float(r.get("continued") or 0),
                float(r.get("idle_with_text") or 0),
                None,
            ),
        ]

    def engine_usage(self) -> list[dict[str, Any]]:
        """Active users and 7-day retention, as Google reports them for the engine, about 3 days late."""
        rows = query(
            f"""
SELECT date, MAX(daily_active_user_count) AS users, MAX(user_retention_ratio_for7d) AS retention
FROM {fq("log", self.s.ge_metrics_table)}
WHERE engine_id = @engine AND date >= @a AND date <= @b GROUP BY date""",
            engine=self.s.production_engine,
            a=(self.day - timedelta(days=7)).isoformat(),
            b=self.day.isoformat(),
        )
        out = []
        for r in rows:
            day = date.fromisoformat(r["date"])
            for metric, value in (("ACTIVE_USERS", r["users"]), ("RETENTION_7D", r["retention"])):
                if value is not None:
                    row = _row(
                        day,
                        ALL,
                        metric,
                        (SliceKind.ALL.value, ALL),
                        float(value),
                        float(value),
                        None,
                        None,
                        False,
                        self.version,
                    )
                    out.append(row)
        return out
