"""One assessment run: read the window, assess, keep derived values only (§12.6).

Text exists only in this process's memory, and only while the run lasts.
"""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from conversation_analyzer import safe_log
from conversation_analyzer.assessor import canary as canary_mod
from conversation_analyzer.assessor import state as state_mod
from conversation_analyzer.assessor.sessions import Segment, TurnPlace, plan_session
from conversation_analyzer.bq.client import write
from conversation_analyzer.bq.schema import (
    CANARY_RESULTS,
    JUDGE_CHECKS,
    JUDGE_VERSIONS,
    QUALITY_TURNS,
    RETRIEVAL_COUNTS,
    RUNS,
    SEGMENTS,
    SESSION_GRADES,
    STAGE1_RESULTS,
    STAGE2_RESULTS,
    Table,
)
from conversation_analyzer.docs.index import DocumentIndex, SessionDocuments
from conversation_analyzer.errors import AnalyzerError, JudgeOutputError, LeakGuardError, report
from conversation_analyzer.judge import evidence, session, stage1, stage2
from conversation_analyzer.judge.case import EarlierTurn, JudgeCase
from conversation_analyzer.judge.client import Judge, Usage, default_judge
from conversation_analyzer.judge.stage1 import Stage1Result
from conversation_analyzer.judge.stage2 import Stage2Result
from conversation_analyzer.judge.version import JudgeVersion, current, previous
from conversation_analyzer.keys import stable_fraction
from conversation_analyzer.leak_guard import check_row
from conversation_analyzer.log.parse import Feedback, Span, Turn
from conversation_analyzer.log.reader import Window, read_window
from conversation_analyzer.pii.scrubber import PiiMap, scrub
from conversation_analyzer.settings import get_settings
from conversation_analyzer.settings import now as utc_now
from conversation_analyzer.vocab import (
    LATE_TRIGGER_RELATIONS,
    ErrorClass,
    FlagReason,
    FormField,
    GradeState,
    PlantedError,
    Relation,
    RunStatus,
    SegmentState,
    Severity,
    Stage2State,
    Thumbs,
    TurnStatus,
)

SECOND_MODEL_FIELDS = {
    FormField.INTENT: "intent",
    FormField.TOPIC: "topic",
    FormField.RELATION: "relation",
    FormField.RELEVANCE: "relevance",
    FormField.COMPLETENESS: "completeness",
    FormField.CLARITY: "clarity",
    FormField.GROUNDEDNESS: "groundedness",
    FormField.PRIMARY_FAILURE: "primary_failure",
    FormField.SEVERITY: "severity",
}


@dataclass
class TurnState:
    place: TurnPlace
    stored: dict[str, Any] | None
    status: str | None = None
    error_class: str | None = None
    case: JudgeCase | None = None
    new_s1: dict[str, Stage1Result] = field(default_factory=dict)
    s1: dict[str, Stage1Result] = field(default_factory=dict)  # new or stored, per judge version
    new_s2: dict[str, Stage2Result] = field(default_factory=dict)
    fingerprints: dict[str, str] = field(default_factory=dict)
    flag_reasons: list[str] = field(default_factory=list)
    stage2_state: str = Stage2State.NOT_FLAGGED.value
    feedback: Feedback | None = None
    reaction: str | None = None
    pace_excluded: bool = False
    second_model_checked: bool = False
    needs_stage1: bool = False

    @property
    def turn(self) -> Turn:
        return self.place.turn

    @property
    def key(self) -> str:
        return self.place.turn.turn_key


@dataclass
class Counters:
    values: Counter[str] = field(default_factory=Counter)
    failed_by_class: Counter[str] = field(default_factory=Counter)
    disagreements: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, name: str, n: int = 1) -> None:
        with self.lock:
            self.values[name] += n

    def fail(self, error_class: ErrorClass) -> None:
        with self.lock:
            self.failed_by_class[error_class.value] += 1


def _fingerprint(*parts: Any) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:32]


class AssessmentRun:
    def __init__(self, now: datetime, judge: Judge, docs: DocumentIndex) -> None:
        s = get_settings()
        self.s = s
        self.now = now
        self.today = now.date()
        self.judge = judge
        self.docs = docs
        self.usage = Usage()
        self.counters = Counters()
        self.run_id = "run-" + uuid.uuid4().hex[:16]
        self.started = time.monotonic()
        self.stop_at = self.started + s.timing.stop_new_calls_after_seconds
        self.hard = timedelta(minutes=s.timing.hard_limit_minutes)
        self.eligible_after = timedelta(minutes=s.timing.eligible_after_minutes)
        self.cur = current()
        prev = previous()
        until = s.judge.parallel_run_until
        self.parallel = prev is not None and until is not None and self.today <= until
        self.versions: list[JudgeVersion] = [self.cur] + ([prev] if self.parallel else [])
        # During a parallel run, metrics, flags and late triggers use the old version (§8.2).
        self.metric_version = prev if self.parallel else self.cur
        self.pii: dict[str, PiiMap] = {}
        self.grades: dict[tuple[str, int], session.GradeResult] = {}
        self.canary_rows: list[dict[str, Any]] = []
        self.window: Window | None = None

    # ------------------------------------------------------------------ helpers

    def has_time(self) -> bool:
        return time.monotonic() < self.stop_at

    def age(self, t: Turn) -> timedelta:
        return self.now - t.timestamp

    def scrub_text(self, session_key: str, text: str) -> str:
        return scrub(text, self.pii.setdefault(session_key, PiiMap()))

    def build_case(self, ts: TurnState, stored: state_mod.Stored) -> JudgeCase:
        """The scrubbed conversation the judge sees; references only get the turn's placeholders (§6.3)."""
        p = ts.place
        sk = p.turn.session_key
        pii = self.pii.setdefault(sk, PiiMap())
        earlier: list[EarlierTurn] = []
        seg = p.segment
        for no in (seg.segment_no - 1, seg.segment_no):
            for key, row in sorted(
                stored.session_turns(sk).items(), key=lambda kv: kv[1].get("position_in_session") or 0
            ):
                in_window = any(c.turn_key == key for c in p.context) or key == ts.key
                if row.get("segment_no") != no or in_window:
                    continue
                if (row.get("position_in_session") or 0) >= p.position_in_session:
                    continue
                s1 = stored.stage1.get((key, self.cur.version_id)) or stored.stage1.get(
                    (key, self.metric_version.version_id)
                )
                labels = state_mod.stage1_from_row(s1).labels() if s1 else {}
                earlier.append(EarlierTurn(row.get("position_in_session") or 0, no, None, None, labels))
        for c in p.context:
            cp = self.place_by_key[c.turn_key]
            earlier.append(
                EarlierTurn(
                    cp.position_in_session,
                    cp.segment.segment_no,
                    self.scrub_text(sk, c.question),
                    self.scrub_text(sk, c.answer),
                )
            )
        earlier.sort(key=lambda e: e.position_in_session)
        refs = [r for c in p.earlier_references_from for r in c.references]

        def placed(r):
            return type(r)(r.doc_id, r.data_store, r.uri, pii.apply(r.title), pii.apply(r.snippet))

        question = self.scrub_text(sk, p.turn.question)
        answer = self.scrub_text(sk, p.turn.answer)
        spans = [Span(x.index, x.start, x.end, self.scrub_text(sk, x.text), x.reference_indices) for x in p.turn.spans]
        return JudgeCase(
            question=question,
            answer=answer,
            references=[placed(r) for r in p.turn.references],
            spans=spans,
            answer_state=p.turn.answer_state,
            earlier=earlier,
            earlier_references=[placed(r) for r in refs],
            has_previous_turn=p.has_previous_turn,
            previous_text_available=p.previous is not None,
        )

    def docs_view(self, ts: TurnState) -> SessionDocuments:
        return self.docs.view(self.pii.get(ts.turn.session_key))

    def stage1_fingerprint(self, ts: TurnState, version: JudgeVersion) -> str:
        p = ts.place
        return _fingerprint(
            ts.key,
            version.version_id,
            p.segment.segment_no,
            p.position_in_segment,
            ",".join(c.turn_key for c in p.context),
        )

    def _call(self, fn: Callable[[], Any], ts: TurnState | None = None) -> Any:
        """One judge step; output errors fail the turn, other errors leave it waiting for the next run."""
        try:
            return fn()
        except JudgeOutputError as exc:
            self.counters.fail(exc.error_class)
            if ts is not None:
                ts.status, ts.error_class = TurnStatus.FAILED.value, exc.error_class.value
            return None
        except AnalyzerError as exc:
            self.counters.fail(exc.error_class)
            return None

    # ------------------------------------------------------------------ phases

    def plan(self, stored: state_mod.Stored) -> list[TurnState]:
        assert self.window is not None
        by_session: dict[str, list[Turn]] = defaultdict(list)
        for t in self.window.turns:
            by_session[t.session_key].append(t)
        self.plans = {
            sk: plan_session(sk, ts, stored.session_turns(sk), stored.segments.get(sk, {}), self.now)
            for sk, ts in by_session.items()
        }
        self.place_by_key = {p.turn.turn_key: p for plan in self.plans.values() for p in plan.places}
        paced = self.pace_marked()
        latest_feedback: dict[str, Feedback] = {}
        for fb in sorted(self.window.feedback, key=lambda f: f.timestamp):
            if fb.assist_token:
                latest_feedback[fb.assist_token] = fb
        states: list[TurnState] = []
        new_keys = {t.turn_key for t in self.window.turns if t.turn_key not in stored.turns}
        for plan in self.plans.values():
            for place in plan.places:
                t = place.turn
                ts = TurnState(place=place, stored=stored.turns.get(t.turn_key))
                ts.feedback = latest_feedback.get(t.assist_token or "")
                ts.pace_excluded = t.principal in paced and not t.is_canary
                if ts.stored:
                    ts.flag_reasons = list(ts.stored.get("flag_reasons") or [])
                    ts.stage2_state = ts.stored.get("stage2_state") or Stage2State.NOT_FLAGGED.value
                    ts.second_model_checked = bool(ts.stored.get("second_model_checked"))
                    for v in self.versions:
                        row = stored.stage1.get((ts.key, v.version_id))
                        if row:
                            ts.s1[v.version_id] = state_mod.stage1_from_row(row, ts.stored.get("found_docs"))
                            ts.fingerprints[v.version_id] = row.get("fingerprint")
                age = self.age(t)
                if age < self.eligible_after:
                    continue
                status = (ts.stored or {}).get("status")
                if status is None:
                    if age >= self.hard:
                        ts.status = TurnStatus.MISSED.value
                    elif t.size() > self.s.sizes.too_large_chars:
                        ts.status = TurnStatus.TOO_LARGE.value
                    else:
                        ts.needs_stage1 = True
                elif status == TurnStatus.ASSESSED and age < self.hard:
                    late_context = any(c.turn_key in new_keys for c in place.context)
                    if late_context and any(
                        self.stage1_fingerprint(ts, v) != ts.fingerprints.get(v.version_id) for v in self.versions
                    ):
                        ts.needs_stage1 = True
                states.append(ts)
        return states

    def pace_marked(self) -> set[str]:
        """Users with more than 10 turns in 10 minutes are most likely scripts (§8.2); only a mark is kept."""
        assert self.window is not None
        window = timedelta(minutes=self.s.pace.window_minutes)
        times: dict[str, list[datetime]] = defaultdict(list)
        for t in self.window.turns:
            if t.principal:
                times[t.principal].append(t.timestamp)
        marked = set()
        for principal, stamps in times.items():
            stamps.sort()
            j = 0
            for i, ts in enumerate(stamps):
                while ts - stamps[j] > window:
                    j += 1
                if i - j + 1 > self.s.pace.max_turns:
                    marked.add(principal)
                    break
        return marked

    def phase1(self, states: list[TurnState], stored: state_mod.Stored) -> None:
        """Stage 1, sessions in parallel, the turns of one session in order, oldest first (§12.6)."""
        by_session: dict[str, list[TurnState]] = defaultdict(list)
        for ts in states:
            if ts.needs_stage1:
                by_session[ts.turn.session_key].append(ts)

        def one_session(items: list[TurnState]) -> None:
            for ts in sorted(items, key=lambda x: x.turn.timestamp):
                if not self.has_time():
                    return
                ts.case = self.build_case(ts, stored)
                for v in self.versions:
                    result = self._call(lambda v=v, ts=ts: stage1.assess(ts.case, v, self.judge, self.usage), ts)
                    if result is None:
                        break
                    ts.new_s1[v.version_id] = ts.s1[v.version_id] = result
                    ts.fingerprints[v.version_id] = self.stage1_fingerprint(ts, v)
                if ts.status == TurnStatus.FAILED or len(ts.new_s1) < len(self.versions):
                    ts.new_s1.clear()
                    continue
                ts.status = TurnStatus.ASSESSED.value
                self.counters.add("canary_assessed" if ts.turn.is_canary else "assessed")
                self.second_model(ts)

        oldest_first = sorted(by_session.values(), key=lambda items: min(x.turn.timestamp for x in items))
        with ThreadPoolExecutor(max_workers=self.s.judge.concurrency) as pool:
            list(pool.map(one_session, oldest_first))

    def second_model(self, ts: TurnState) -> None:
        """5 % of real turns graded again with the stage 2 model; only the disagreement counts are kept (§11.5)."""
        if ts.turn.is_canary or ts.second_model_checked or ts.stored is not None:
            return
        if stable_fraction("second-model:" + ts.key) >= self.s.judge.second_model_share or not self.has_time():
            return
        base = ts.new_s1[self.cur.version_id]
        other = self._call(
            lambda: stage1.assess(ts.case, self.cur, self.judge, self.usage, model=self.cur.stage2_model)
        )
        if other is None:
            return
        ts.second_model_checked = True
        self.counters.add("second_model_checks")
        with self.counters.lock:
            for f, attr in SECOND_MODEL_FIELDS.items():
                self.counters.disagreements[f.value][0] += 1
                self.counters.disagreements[f.value][1] += getattr(base, attr) != getattr(other, attr)

    def phase2(self, states: list[TurnState]) -> None:
        """The evidence check: one index search for all turns that need it, then one judge call each (§12.6)."""
        todo = [
            (ts, v)
            for ts in states
            for v in self.versions
            if v.version_id in ts.new_s1 and evidence.needed(ts.new_s1[v.version_id])
        ]
        if not todo:
            return
        self.docs.prefetch([ts.case.question for ts, _ in todo])

        def one(item: tuple[TurnState, JudgeVersion]) -> None:
            ts, v = item
            if not self.has_time():
                return
            result = ts.new_s1[v.version_id]
            self._call(lambda: evidence.check(ts.case, result, v, self.judge, self.usage, self.docs_view(ts)))
            self.counters.add("evidence_checks")

        with ThreadPoolExecutor(max_workers=self.s.judge.concurrency) as pool:
            list(pool.map(one, todo))

    def flags(self, states: list[TurnState], stored: state_mod.Stored) -> None:
        """Flags, late triggers and reactions (§5.3, §7.1); a turn is flagged at most once."""
        order = sorted(states, key=lambda x: (x.turn.session_key, x.place.position_in_session))
        position = {(x.turn.session_key, x.place.position_in_session): x for x in order}
        mv = self.metric_version.version_id
        for ts in order:
            s1 = ts.s1.get(mv)
            reasons = list(ts.flag_reasons)
            young = self.age(ts.turn) < self.hard
            if mv in ts.new_s1:
                reasons += s1.flag_reasons()
            if ts.feedback and ts.feedback.thumbs is Thumbs.DOWN and young and s1 is not None:
                reasons.append(FlagReason.DISLIKE.value)
            nxt = position.get((ts.turn.session_key, ts.place.position_in_session + 1))
            nxt_s1 = nxt.s1.get(mv) if nxt else None
            if nxt_s1 is None and nxt is None:
                nxt_s1 = self._stored_next(ts, stored)
            if nxt_s1 is not None and nxt_s1.relation != Relation.FIRST:
                ts.reaction = nxt_s1.relation
                if nxt_s1.relation in LATE_TRIGGER_RELATIONS and young and s1 is not None:
                    reasons.append(
                        {Relation.REPHRASE: FlagReason.NEXT_REPHRASE, Relation.CORRECTION: FlagReason.NEXT_CORRECTION}[
                            nxt_s1.relation
                        ].value
                    )
            elif ts.stored:
                ts.reaction = ts.stored.get("reaction")
            ts.flag_reasons = list(dict.fromkeys(reasons))
            if ts.flag_reasons and ts.stage2_state == Stage2State.NOT_FLAGGED:
                ts.stage2_state = Stage2State.PENDING.value
            if ts.stage2_state == Stage2State.PENDING and not young:
                ts.stage2_state = Stage2State.GAVE_UP.value
                self.counters.add("stage2_gave_up")

    def _stored_next(self, ts: TurnState, stored: state_mod.Stored) -> Stage1Result | None:
        for key, row in stored.session_turns(ts.turn.session_key).items():
            if row.get("position_in_session") == ts.place.position_in_session + 1:
                s1 = stored.stage1.get((key, self.metric_version.version_id))
                return state_mod.stage1_from_row(s1) if s1 else None
        return None

    def phase3(self, states: list[TurnState], stored: state_mod.Stored) -> None:
        """Stage 2 and session grades for flagged turns, pending ones first, while time remains (§12.6)."""
        pending = [ts for ts in states if ts.stage2_state == Stage2State.PENDING and ts.s1]
        pending.sort(key=lambda x: (x.stored is None, x.turn.timestamp))
        graded: set[tuple[str, int]] = set()
        lock = threading.Lock()

        def one(ts: TurnState) -> None:
            if not self.has_time():
                return
            if ts.case is None:
                ts.case = self.build_case(ts, stored)
            for v in self.versions:
                s1 = ts.s1.get(v.version_id)
                if s1 is None:
                    continue
                result = self._call(
                    lambda v=v, s1=s1: stage2.diagnose(
                        ts.case, s1, ts.flag_reasons, v, self.judge, self.usage, self.docs_view(ts)
                    )
                )
                if result is None:
                    return
                ts.new_s2[v.version_id] = result
            ts.stage2_state = Stage2State.DONE.value
            self.counters.add("stage2_done")
            seg = ts.place.segment
            with lock:
                if (seg.session_key, seg.segment_no) in graded:
                    return
                graded.add((seg.session_key, seg.segment_no))
            self.grade(seg, states, stored)

        with ThreadPoolExecutor(max_workers=self.s.judge.concurrency) as pool:
            list(pool.map(one, pending))
        for plan in self.plans.values():
            for seg in plan.segments:
                key = (seg.session_key, seg.segment_no)
                old = stored.grades.get(key)
                closing = seg.was_open and seg.state == SegmentState.CLOSED
                if (
                    key not in graded
                    and closing
                    and old
                    and old.get("grade_state") == GradeState.PROVISIONAL
                    and seg.complete_text
                    and self.has_time()
                ):
                    self.grade(seg, states, stored)

    def grade(self, seg: Segment, states: list[TurnState], stored: state_mod.Stored) -> None:
        """Provisional while open, final when closed, not gradable when part of its text is erased (§7.7)."""
        by_key = {ts.key: ts for ts in states}
        sk = seg.session_key
        turns = []
        for i, t in enumerate(seg.turns, start=seg.erased_turns + 1):
            ts = by_key.get(t.turn_key)
            s1 = ts.s1.get(self.cur.version_id) if ts else None
            s2 = ts.new_s2.get(self.cur.version_id) if ts else None
            turns.append(session.SegmentTurn(i, self.scrub_text(sk, t.question), self.scrub_text(sk, t.answer), s1, s2))
        if not seg.complete_text:
            result = session.not_gradable(turns)
        else:
            final = seg.state == SegmentState.CLOSED
            result = self._call(lambda: session.grade(turns, final, self.cur, self.judge, self.usage))
            if result is None:
                return
        self.grades[(sk, seg.segment_no)] = result
        self.counters.add("session_grades")

    def run_canary(self, states: list[TurnState]) -> None:
        """Canary results, planted errors and the index hit rate (§11.4)."""
        canaries = [ts for ts in states if ts.turn.is_canary and self.cur.version_id in ts.new_s1]
        if not canaries:
            return
        hashes = {ts.key: canary_mod.question_hash(ts.turn.question) for ts in canaries}
        expected = canary_mod.expected_documents(sorted(set(hashes.values())))
        self.docs.prefetch([canary_mod.bare_question(ts.turn.question) for ts in canaries])
        for ts in canaries:
            r = ts.new_s1[self.cur.version_id]
            exp = expected.get(hashes[ts.key])
            found_rank = None
            if exp:
                refs = self.docs.search(canary_mod.bare_question(ts.turn.question))
                found_rank = next((i + 1 for i, d in enumerate(refs) if d.doc_id == exp[0]), None)
            base = {
                "turn_key": ts.key,
                "judge_version": self.cur.version_id,
                "day": ts.turn.timestamp.date(),
                "question_hash": hashes[ts.key],
                "expected_doc_id": exp[0] if exp else None,
                "expected_data_store": exp[1] if exp else None,
                "index_found_expected": (found_rank is not None) if exp else None,
                "index_rank": found_rank,
            }
            s2 = ts.new_s2.get(self.cur.version_id)
            self.canary_rows.append(
                {
                    **base,
                    **self._canary_form(r),
                    "planted_error": PlantedError.NONE.value,
                    "with_references": bool(ts.case.own_evidence),
                    "caught": None,
                    "false_high": r.severity == Severity.HIGH,
                    "stage2_primary_failure": s2.primary_failure if s2 else None,
                }
            )
            if stable_fraction("planted:" + ts.key) >= self.s.canary.planted_share:
                continue
            for error, with_refs, pcase in canary_mod.planted_cases(ts.case):
                if not self.has_time():
                    return
                pr = self._call(lambda pcase=pcase: stage1.assess(pcase, self.cur, self.judge, self.usage))
                if pr is None:
                    continue
                if evidence.needed(pr):
                    self._call(
                        lambda pr=pr, pcase=pcase: evidence.check(
                            pcase, pr, self.cur, self.judge, self.usage, self.docs_view(ts)  # noqa: B023
                        )
                    )
                self.canary_rows.append(
                    {
                        **base,
                        **self._canary_form(pr),
                        "planted_error": error.value,
                        "with_references": with_refs,
                        "stage2_primary_failure": None,
                        "caught": canary_mod.caught(error, pr.failure_types, pr.severity),
                        "false_high": False,
                    }
                )

    @staticmethod
    def _canary_form(r: Stage1Result) -> dict[str, Any]:
        return {
            "intent": r.intent,
            "relevance": r.relevance,
            "completeness": r.completeness,
            "clarity": r.clarity,
            "groundedness": r.groundedness,
            "failure_types": r.failure_types,
            "primary_failure": r.primary_failure,
            "severity": r.severity,
            "evidence_check_contradiction": r.evidence_check_contradiction,
        }

    def retrieval_counts(self) -> list[dict[str, Any]]:
        """How often Bolek's searches returned each document, per day, while the results still exist (§12.6)."""
        assert self.window is not None
        accounts = set(self.s.evaluator.accounts)
        counts: Counter[tuple[Any, str]] = Counter()
        for search in self.window.searches:
            if search.principal in accounts:
                continue
            for doc_id in set(search.doc_ids):
                counts[(search.timestamp.date(), doc_id)] += 1
        stores = self.docs.data_stores_of(sorted({d for _, d in counts}))
        rows = [
            {"day": day, "doc_id": doc_id, "data_store": stores[doc_id], "n_returned": n}
            for (day, doc_id), n in counts.items()
            if doc_id in stores
        ]
        self.counters.add("retrieval_rows", len(rows))
        return rows

    # ------------------------------------------------------------------ rows

    def turn_row(self, ts: TurnState) -> dict[str, Any] | None:
        status = ts.status or (ts.stored or {}).get("status")
        if status is None:
            return None
        p = ts.place
        t = p.turn
        mv = self.metric_version.version_id
        s1 = ts.s1.get(mv)
        found = s1.found_docs if s1 else []
        evidence_refs = [r for r in t.references if not r.people_directory]
        fb = ts.feedback
        stored = ts.stored or {}
        return {
            "turn_key": ts.key,
            "session_key": t.session_key,
            "segment_no": p.segment.segment_no,
            "position_in_segment": p.position_in_segment,
            "position_in_session": p.position_in_session,
            "day": t.timestamp.date(),
            "channel": t.channel.value,
            "is_canary": t.is_canary,
            "pace_excluded": ts.pace_excluded,
            "gap_bucket": p.gap_bucket,
            "resumed": p.segment.resumed,
            "earlier_text_missing": p.earlier_text_missing,
            "status": status,
            "error_class": ts.error_class or stored.get("error_class"),
            "evidence_kind": s1.evidence_kind if s1 else stored.get("evidence_kind"),
            "data_stores": sorted({r.data_store for r in evidence_refs}),
            "cited_docs": [r.as_doc() for r in {(r.doc_id, r.data_store): r for r in evidence_refs}.values()],
            "found_docs": [d.as_doc() for d in found] if found else stored.get("found_docs") or [],
            "flagged": bool(ts.flag_reasons),
            "flag_reasons": ts.flag_reasons,
            "stage2_state": ts.stage2_state,
            "feedback_thumbs": fb.thumbs.value if fb and fb.thumbs else stored.get("feedback_thumbs"),
            "feedback_reasons": [r.value for r in fb.reasons] if fb else list(stored.get("feedback_reasons") or []),
            "reaction": ts.reaction,
            "second_model_checked": ts.second_model_checked,
            "fingerprint": ts.fingerprints.get(mv) or stored.get("fingerprint"),
            "judge_version": mv if s1 else stored.get("judge_version"),
        }

    def version_fields(self, v: JudgeVersion, model: str) -> dict[str, Any]:
        from conversation_analyzer.vocab import closed_lists_version

        return {
            "judge_version": v.version_id,
            "rubric_version": v.rubric_version,
            "closed_lists_version": closed_lists_version(),
            "judge_model": model,
            "prompt_version": v.prompt_version,
            "code_version": self.s.env.code_version,
        }

    def segment_row(self, seg: Segment, states_by_key: dict[str, TurnState]) -> dict[str, Any]:
        mv = self.metric_version.version_id
        stored = seg.stored or {}
        rel = [
            states_by_key[t.turn_key].s1[mv].relation
            for t in seg.turns
            if t.turn_key in states_by_key and mv in states_by_key[t.turn_key].s1
        ]
        complete = seg.complete_text
        first_rel = (
            rel[0]
            if complete and rel and seg.turns and seg.turns[0].turn_key in states_by_key
            else stored.get("first_turn_relation")
        )
        counts = {
            "n_rephrases": rel.count(Relation.REPHRASE),
            "n_corrections": rel.count(Relation.CORRECTION),
            "n_frustrations": rel.count(Relation.FRUSTRATION),
        }
        if not complete:
            counts = {k: max(v, stored.get(k) or 0) for k, v in counts.items()}
        return {
            "session_key": seg.session_key,
            "segment_no": seg.segment_no,
            "first_day": stored.get("first_day") or seg.turns[0].timestamp.date(),
            "last_day": seg.turns[-1].timestamp.date(),
            "state": seg.state,
            "close_reason": seg.close_reason,
            "forced_closed": seg.close_reason == "FORCED",
            "resumed": seg.resumed,
            "previous_close_reason": seg.previous_close_reason,
            "earlier_text_missing": seg.previous_text_missing,
            "first_position_in_session": seg.first_position_in_session,
            "n_turns": seg.n_turns,
            **counts,
            "duration_bucket": seg.duration_bucket(),
            "first_turn_relation": first_rel,
        }

    def guarded(
        self, table: Table, rows: list[dict[str, Any]], key: str | None, failed: set[str]
    ) -> list[dict[str, Any]]:
        """Rows that pass the leak guard; a turn whose row fails is recorded as failed (§6.10)."""
        ok = []
        for row in rows:
            try:
                check_row(table, row)
                ok.append(row)
            except LeakGuardError:
                self.counters.fail(ErrorClass.LEAK_GUARD)
                if key:
                    failed.add(row[key])
        return ok

    def write_all(self, states: list[TurnState], stored: state_mod.Stored) -> None:
        """Leak guard on every row, then one MERGE per table (§12.6)."""
        failed: set[str] = set()
        s1_rows, s2_rows = [], []
        for ts in states:
            for vid, r in ts.new_s1.items():
                v = next(x for x in self.versions if x.version_id == vid)
                s1_rows.append(
                    {
                        "turn_key": ts.key,
                        "day": ts.turn.timestamp.date(),
                        "fingerprint": ts.fingerprints[vid],
                        **self.version_fields(v, r.model),
                        **r.row(),
                    }
                )
            for vid, r in ts.new_s2.items():
                v = next(x for x in self.versions if x.version_id == vid)
                s2_rows.append(
                    {
                        "turn_key": ts.key,
                        "day": ts.turn.timestamp.date(),
                        "fingerprint": _fingerprint(ts.fingerprints.get(vid), ",".join(ts.flag_reasons)),
                        **self.version_fields(v, r.model),
                        **r.row(),
                    }
                )
        s1_rows = self.guarded(STAGE1_RESULTS, s1_rows, "turn_key", failed)
        s2_rows = self.guarded(STAGE2_RESULTS, s2_rows, "turn_key", failed)
        for ts in states:
            if ts.key in failed:
                ts.status, ts.error_class = TurnStatus.FAILED.value, ErrorClass.LEAK_GUARD.value
        turn_rows = [r for r in (self.turn_row(ts) for ts in states) if r is not None]
        turn_rows = self.guarded(QUALITY_TURNS, turn_rows, "turn_key", failed)
        s1_rows = [r for r in s1_rows if r["turn_key"] not in failed]
        s2_rows = [r for r in s2_rows if r["turn_key"] not in failed]
        written = {r["turn_key"] for r in turn_rows}
        by_key = {ts.key: ts for ts in states}
        seg_rows = [
            self.segment_row(seg, by_key)
            for plan in self.plans.values()
            for seg in plan.segments
            if any(t.turn_key in written for t in seg.turns)
        ]
        grade_rows = [
            {"session_key": sk, "segment_no": no, "day": self.today, "judge_version": self.cur.version_id, **g.row()}
            for (sk, no), g in self.grades.items()
        ]
        checks = [
            {"day": self.today, "field": f, "n_compared": n, "n_disagreements": d}
            for f, (n, d) in self.counters.disagreements.items()
        ]
        versions = [
            {
                "judge_version": v.version_id,
                "rubric_version": v.rubric_version,
                "prompt_version": v.prompt_version,
                "form_version": v.form_version,
                "stage1_model": v.stage1_model,
                "stage2_model": v.stage2_model,
                "closed_lists_version": self.version_fields(v, "")["closed_lists_version"],
                "first_used_day": self.today,
                "previous_version": previous().version_id if (previous() and v is self.cur) else None,
                "parallel_run_until": self.s.judge.parallel_run_until if v is self.cur else None,
            }
            for v in self.versions
            if v.version_id not in stored.versions
        ]
        write(QUALITY_TURNS, turn_rows)
        write(STAGE1_RESULTS, s1_rows)
        write(STAGE2_RESULTS, s2_rows)
        write(SEGMENTS, self.guarded(SEGMENTS, seg_rows, None, set()))
        write(SESSION_GRADES, self.guarded(SESSION_GRADES, grade_rows, None, set()))
        write(CANARY_RESULTS, self.guarded(CANARY_RESULTS, self.canary_rows, None, set()))
        write(JUDGE_CHECKS, checks)
        write(RETRIEVAL_COUNTS, self.guarded(RETRIEVAL_COUNTS, self.retrieval_counts(), None, set()))
        write(JUDGE_VERSIONS, versions)
        c = self.counters.values
        for ts in states:
            if ts.status == TurnStatus.TOO_LARGE and ts.stored is None:
                c["too_large"] += 1
            elif ts.status == TurnStatus.MISSED and ts.stored is None:
                c["missed"] += 1
            elif ts.status == TurnStatus.FAILED and (ts.stored or {}).get("status") != TurnStatus.FAILED:
                c["failed"] += 1
            if ts.pace_excluded:
                c["pace_marked"] += 1
            if ts.stage2_state == Stage2State.PENDING:
                c["stage2_pending"] += 1

    def run_record(
        self,
        states: list[TurnState],
        status: RunStatus,
        error_class: str | None,
        search_cutoff: datetime | None,
        feedback_cutoff: datetime | None,
    ) -> dict[str, Any]:
        c = self.counters.values
        eligible = [ts for ts in states if not ts.turn.is_canary and self.age(ts.turn) < self.hard]
        covered = [
            ts
            for ts in eligible
            if (ts.status or (ts.stored or {}).get("status")) in (TurnStatus.ASSESSED, TurnStatus.TOO_LARGE)
        ]
        waiting = [
            self.age(ts.turn).total_seconds() / 60
            for ts in eligible
            if (ts.status or (ts.stored or {}).get("status")) is None
        ]
        return {
            "run_id": self.run_id,
            "run_day": self.today,
            "started_at": self.now,
            "finished_at": self.now + timedelta(seconds=time.monotonic() - self.started),
            "status": status.value,
            "error_class": error_class,
            "turns_read": len(self.window.turns) if self.window else 0,
            "eligible": len(eligible),
            "covered": len(covered),
            "assessed": c["assessed"],
            "too_large": c["too_large"],
            "missed": c["missed"],
            "failed": c["failed"],
            "failed_by_class": [{"error_class": k, "n": v} for k, v in sorted(self.counters.failed_by_class.items())],
            "canary_assessed": c["canary_assessed"],
            "pace_marked": c["pace_marked"],
            "evidence_checks": c["evidence_checks"],
            "stage2_done": c["stage2_done"],
            "stage2_pending": c["stage2_pending"],
            "stage2_gave_up": c["stage2_gave_up"],
            "session_grades": c["session_grades"],
            "second_model_checks": c["second_model_checks"],
            "feedback_matched": c["feedback_matched"],
            "feedback_after_window": c["feedback_after_window"],
            "retrieval_rows": c["retrieval_rows"],
            "oldest_waiting_minutes": max(waiting) if waiting else 0.0,
            "window_margin_minutes": self.window.oldest_answer_age_minutes if self.window else None,
            "throttled_calls": self.usage.throttled,
            "tokens": self.usage.rows(),
            "judge_versions": [v.version_id for v in self.versions],
            "search_cutoff": search_cutoff,
            "feedback_cutoff": feedback_cutoff,
        }

    def feedback_counts(self, states: list[TurnState], since: datetime) -> None:
        assert self.window is not None
        in_window = {ts.turn.assist_token for ts in states if ts.turn.assist_token}
        for fb in self.window.feedback:
            if fb.timestamp <= since:
                continue
            if fb.assist_token in in_window:
                self.counters.add("feedback_matched")
            else:
                self.counters.add("feedback_after_window")

    # ------------------------------------------------------------------ the run

    def execute(self) -> dict[str, Any]:
        states: list[TurnState] = []
        search_cutoff = feedback_cutoff = None
        try:
            run_info = state_mod.load([], self.today)
            self.usage.tokens_before_today = run_info.tokens_today
            search_since, feedback_since = state_mod.window_cutoffs(
                run_info, self.now, self.s.timing.window_read_minutes
            )
            search_cutoff, feedback_cutoff = self.now - timedelta(minutes=15), self.now
            self.window = read_window(self.now, feedback_since, search_since, search_cutoff)
            stored = state_mod.load(sorted({t.session_key for t in self.window.turns}), self.today)
            stored.versions = run_info.versions
            states = self.plan(stored)
            self.feedback_counts(states, feedback_since)
            self.phase1(states, stored)
            self.phase2(states)
            self.flags(states, stored)
            self.phase3(states, stored)
            self.run_canary(states)
            self.write_all(states, stored)
            record = self.run_record(states, RunStatus.OK, None, search_cutoff, feedback_cutoff)
        except Exception as exc:
            error_class = report(exc)
            record = self.run_record(states, RunStatus.FAILED, error_class.value, None, None)
            write(RUNS, [record])
            raise
        write(RUNS, [record])
        safe_log.log(
            "assessment_run",
            run_id=self.run_id,
            assessed=record["assessed"],
            eligible=record["eligible"],
            covered=record["covered"],
            missed=record["missed"],
            failed=record["failed"],
            stage2_done=record["stage2_done"],
            tokens=self.usage.total(),
        )
        return record


def run(now: datetime | None = None, judge: Judge | None = None, docs: DocumentIndex | None = None) -> dict[str, Any]:
    return AssessmentRun(now or utc_now(), judge or default_judge(), docs or DocumentIndex()).execute()
