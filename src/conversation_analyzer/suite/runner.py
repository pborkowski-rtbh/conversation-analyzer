"""The judge test suite run: every case through the judge as a live turn would go, scored and compared (§11.1-11.3)."""

from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from conversation_analyzer import safe_log
from conversation_analyzer.assessor.state import stage1_from_row
from conversation_analyzer.bq.client import query, tbl, write
from conversation_analyzer.bq.schema import SUITE_RUNS
from conversation_analyzer.errors import AnalyzerError, TokenLimitError
from conversation_analyzer.judge import evidence, session, stage1, stage2
from conversation_analyzer.judge.case import DocRef, DocText, EarlierTurn, JudgeCase
from conversation_analyzer.judge.client import Judge, Usage, default_judge
from conversation_analyzer.judge.version import JudgeVersion, load
from conversation_analyzer.log.parse import Reference, Span
from conversation_analyzer.pii.scrubber import Analyzer, PiiMap, scrub
from conversation_analyzer.settings import REPO_ROOT, get_settings, now
from conversation_analyzer.suite.cases import Stage1Labels, Suite, SuiteCase, load_suite
from conversation_analyzer.suite.scoring import Distance, add_evidence, add_session, add_stage2, stage1_distance
from conversation_analyzer.vocab import ErrorClass, FailureCode, FormField, SuiteDecision, SuitePart

REPORTS_DIR = REPO_ROOT / "suite_reports"
_SHOWN = (
    "intent",
    "relation",
    "relevance",
    "completeness",
    "clarity",
    "groundedness",
    "unsupported_spans",
    "needs_internal_knowledge",
    "language_matches",
    "refusal_or_empty",
    "contradicts_earlier",
    "failure_types",
    "primary_failure",
    "severity",
    "evidence_check_contradiction",
)


class FixedDocuments:
    """A case's DocumentSource: every search returns the case's documents; reads give the session's placeholders."""

    def __init__(self, suite: Suite, keys: list[str], pii: PiiMap) -> None:
        self.found = [suite.documents[k].ref for k in keys]
        self.texts = suite.doc_texts()
        self.by_uri = {d.uri: d.ref for d in suite.documents.values() if d.uri}
        self.pii = pii

    def search(self, text: str) -> list[DocRef]:
        return list(self.found)

    def read(self, ref: DocRef) -> DocText | None:
        doc = self.texts.get(ref)
        if doc is None:
            return None
        return DocText(doc.ref, self.pii.apply(doc.title), self.pii.apply(doc.text))

    def lookup_uri(self, uri: str) -> DocRef | None:
        return self.by_uri.get(uri)


def scrubbed(case: JudgeCase, pii: PiiMap, analyzer: Analyzer | None) -> JudgeCase:
    """The case as the live assessor builds it: conversation text scrubbed, references only get the placeholders."""

    def text(t: str | None) -> str | None:
        return None if t is None else scrub(t, pii, analyzer)

    earlier = [EarlierTurn(e.position_in_session, e.segment_no, text(e.question), text(e.answer)) for e in case.earlier]
    question, answer = text(case.question), text(case.answer)
    spans = [Span(s.index, s.start, s.end, text(s.text), s.reference_indices) for s in case.spans]

    def placed(r: Reference) -> Reference:
        return Reference(r.doc_id, r.data_store, r.uri, pii.apply(r.title), pii.apply(r.snippet))

    return JudgeCase(
        question=question,
        answer=answer,
        references=[placed(r) for r in case.references],
        spans=spans,
        answer_state=case.answer_state,
        earlier=earlier,
        earlier_references=[placed(r) for r in case.earlier_references],
        has_previous_turn=case.has_previous_turn,
        previous_text_available=case.previous_text_available,
    )


def _labelled(labels: Stage1Labels | dict[str, Any]) -> stage1.Stage1Result:
    """A fixed stage 1 result, so the session grade sees the same input on every run."""
    values = labels.model_dump() if isinstance(labels, Stage1Labels) else labels
    return stage1_from_row({**values, "failure_types": [values["primary_failure"]]})


@dataclass
class CasePass:
    """One case on one pass: its distance, the labels it expected and found, and the calls that failed."""

    case_id: str
    distance: Distance
    labels: list[tuple[str, bool]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    actual: dict[str, Any] = field(default_factory=dict)  # the judge's codes and scores, for the local report


class SuiteRun:
    def __init__(
        self,
        suite: Suite,
        version: JudgeVersion,
        judge: Judge,
        analyzer: Analyzer | None = None,
        concurrency: int | None = None,
    ) -> None:
        self.suite = suite
        self.version = version
        self.judge = judge
        self.analyzer = analyzer
        self.concurrency = concurrency or get_settings().judge.concurrency
        self.usage = Usage()
        self.doc_ids = {k: d.doc_id for k, d in suite.documents.items()}

    def estimated_usd(self) -> float:
        s = get_settings().suite
        return sum(s.usd(m, self.usage.input_tokens[m], self.usage.output_tokens[m]) for m in self.usage.input_tokens)

    def _guard(self) -> None:
        if self.estimated_usd() > get_settings().suite.max_usd_per_run:
            raise TokenLimitError()

    def run_case(self, case: SuiteCase) -> CasePass:
        """The live path for one case: stage 1, evidence check, stage 2 when flagged, the session grade."""
        self._guard()
        w = self.suite.weights
        exp = case.expected
        pii = PiiMap()
        jc = scrubbed(case.judge_case(self.suite.documents), pii, self.analyzer)
        docs = FixedDocuments(self.suite, case.documents, pii)
        out = CasePass(case.id, Distance())
        s1 = None
        try:
            s1 = stage1.assess(jc, self.version, self.judge, self.usage)
            if evidence.needed(s1):
                evidence.check(jc, s1, self.version, self.judge, self.usage, docs)
        except TokenLimitError:
            raise
        except AnalyzerError as exc:
            out.errors.append(exc.error_class.value)
        out.distance = stage1_distance(exp.stage1.model_dump(), s1.row() if s1 else {}, w)
        if s1:
            out.actual["stage1"] = {k: v for k, v in s1.row().items() if k in _SHOWN}
        if exp.evidence_check:
            ran = s1.evidence_check_contradiction if s1 and s1.evidence_check_ran else None
            add_evidence(out.distance, exp.evidence_check.model_dump(), ran, w)
        found = set(s1.failure_types) if s1 else set()
        out.labels += [(c, c in found) for c in exp.stage1.failure_types if c != FailureCode.NONE]

        if exp.stage2:
            s2 = None
            reasons = sorted(set((s1.flag_reasons() if s1 else []) + (case.flag_reasons or [])))
            if s1 and reasons:
                try:
                    s2 = stage2.diagnose(jc, s1, reasons, self.version, self.judge, self.usage, docs)
                except TokenLimitError:
                    raise
                except AnalyzerError as exc:
                    out.errors.append(exc.error_class.value)
            fixes = [self.doc_ids[k] if k else None for k in exp.stage2.fix_options()]
            actual = None
            if s2:
                fix = s2.document_to_fix.doc_id if s2.document_to_fix else None
                actual = {"primary_failure": s2.primary_failure, "document_to_fix": fix}
                out.actual["stage2"] = {**actual, "whys": [c.why for c in s2.claims]}
            add_stage2(out.distance, {"primary_failure": exp.stage2.primary_failure, "fix_options": fixes}, actual, w)
            if exp.stage2.primary_failure != FailureCode.NONE:
                hit = s2 is not None and exp.stage2.primary_failure in s2.failure_types
                out.labels.append((exp.stage2.primary_failure, hit))

        if exp.session:
            turns = [
                session.SegmentTurn(
                    i + 1, e.question or "", e.answer or "", _labelled(t.stage1 or Stage1Labels()), None
                )
                for i, (e, t) in enumerate(zip(jc.earlier, case.earlier, strict=True))
            ]
            s1_exp = exp.stage1
            current = {
                "relation": s1_exp.relation,
                "relevance": s1_exp.relevance,
                "primary_failure": s1_exp.primary_failure,
                "severity": s1_exp.severity,
            }
            turns.append(session.SegmentTurn(len(turns) + 1, jc.question, jc.answer, _labelled(current), None))
            grade = None
            try:
                grade = session.grade(turns, True, self.version, self.judge, self.usage).row()
            except TokenLimitError:
                raise
            except AnalyzerError as exc:
                out.errors.append(exc.error_class.value)
            add_session(out.distance, exp.session.model_dump(), grade, w)
            if grade:
                out.actual["session"] = {k: grade[k] for k in ("outcome", "first_bad_turn", "recovered")}
        return out

    def run_pass(self, cases: list[SuiteCase]) -> list[CasePass]:
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = [pool.submit(self.run_case, c) for c in cases]
            for done, _ in enumerate(as_completed(futures), start=1):
                if done % 25 == 0:
                    usd = round(self.estimated_usd(), 2)
                    safe_log.log("judge_suite_progress", cases_done=done, cases=len(cases), estimated_usd=usd)
            return [f.result() for f in futures]


def select(suite: Suite, part: str, limit: int) -> list[SuiteCase]:
    cases = [c for c in suite.cases if part.upper() == SuitePart.ALL or c.part == part.upper()]
    return cases[:limit] if limit else cases


def summarize(suite: Suite, cases: list[SuiteCase], passes: list[list[CasePass]]) -> dict[str, Any]:
    """Mean distance per case over the passes, then overall, per field and per scenario; label recall (§11.2, §11.3)."""
    by_case: dict[str, list[CasePass]] = defaultdict(list)
    for p in passes:
        for cp in p:
            by_case[cp.case_id].append(cp)
    per_case = {cid: mean(cp.distance.total for cp in cps) for cid, cps in by_case.items()}
    part_of = {c.id: c.part for c in cases}

    def part_mean(part: str, values: dict[str, float]) -> float | None:
        xs = [v for cid, v in values.items() if part == SuitePart.ALL or part_of[cid] == part]
        return round(mean(xs), 4) if xs else None

    fields = sorted({f for cps in by_case.values() for cp in cps for f in cp.distance.parts})
    per_field = []
    for part in (SuitePart.TUNING, SuitePart.HELD_OUT, SuitePart.ALL):
        for f in [*fields, FormField.ALL.value]:
            values = {
                cid: mean(cp.distance.total if f == FormField.ALL else cp.distance.parts.get(f, 0.0) for cp in cps)
                for cid, cps in by_case.items()
            }
            value = part_mean(part, values)
            if value is not None:
                per_field.append({"field": f, "part": part.value, "distance": value})

    scenario_values: dict[str, list[float]] = defaultdict(list)
    for c in cases:
        for s in sorted(set(c.scenarios(suite.documents))):
            scenario_values[s].append(per_case[c.id])
    per_scenario = [
        {"scenario": s, "distance": round(mean(v), 4), "n": len(v)} for s, v in sorted(scenario_values.items())
    ]

    threshold = get_settings().clusters.reliability_threshold
    expected: Counter[str] = Counter()
    found: Counter[str] = Counter()
    for cps in by_case.values():
        for cp in cps:
            for label, hit in cp.labels:
                expected[label] += 1
                found[label] += hit
    label_recall = [
        {
            "label": label,
            "recall": round(found[label] / n, 4),
            "n": n,
            "reliable": found[label] / n >= threshold,
        }
        for label, n in sorted(expected.items())
    ]
    all_passes = [cp for p in passes for cp in p]
    return {
        "tuning_distance": part_mean(SuitePart.TUNING, per_case),
        "held_out_distance": part_mean(SuitePart.HELD_OUT, per_case),
        "false_high": sum(cp.distance.false_high for cp in all_passes),
        "missed_high": sum(cp.distance.missed_high for cp in all_passes),
        "failed_calls": sum(len(cp.errors) for cp in all_passes),
        "per_field": per_field,
        "per_scenario": per_scenario,
        "label_recall": label_recall,
        "per_case": {cid: round(v, 4) for cid, v in per_case.items()},
        "case_details": {
            cid: {
                "part": part_of[cid],
                "fields": {f: round(mean(cp.distance.parts.get(f, 0.0) for cp in cps), 4) for f in fields},
                "actual": [cp.actual for cp in cps],
            }
            for cid, cps in by_case.items()
            if per_case[cid]
        },
        "errors": dict(Counter(e for cp in all_passes for e in cp.errors)),
    }


def baseline_row(suite_version: str, baseline: str | None) -> dict[str, Any] | None:
    """The run a change is compared with: the given one, else the last full kept or baseline run of this suite."""
    cols = "suite_run_id, judge_version, passes, tuning_distance, held_out_distance, false_high"
    if baseline:
        rows = query(f"SELECT {cols} FROM {tbl(SUITE_RUNS)} WHERE suite_run_id = @id", id=baseline)
        if not rows:
            raise AnalyzerError(ErrorClass.UNEXPECTED)
        return rows[0]
    rows = query(
        f"""
SELECT {cols} FROM {tbl(SUITE_RUNS)}
WHERE suite_version = @sv AND NOT partial AND decision IN ('KEEP', 'BASELINE')
ORDER BY suite_run_id DESC LIMIT 1""",
        sv=suite_version,
    )
    return rows[0] if rows else None


def decide(summary: dict[str, Any], passes: int, judge_version: str, base: dict[str, Any] | None) -> str:
    """Kept only if tuning distance goes down, held-out does not go up and false HIGHs do not go up (§11.3)."""
    if base is None or base["judge_version"] == judge_version:
        return SuiteDecision.BASELINE.value
    better_tuning = (summary["tuning_distance"] or 0.0) < (base["tuning_distance"] or 0.0)
    held_out_ok = (summary["held_out_distance"] or 0.0) <= (base["held_out_distance"] or 0.0)
    false_high_ok = summary["false_high"] / passes <= base["false_high"] / max(base["passes"], 1)
    return (SuiteDecision.KEEP if better_tuning and held_out_ok and false_high_ok else SuiteDecision.REJECT).value


def run(
    passes: int = 3,
    part: str = "all",
    limit: int = 0,
    baseline: str | None = None,
    judge_version: str | None = None,
    judge: Judge | None = None,
    analyzer: Analyzer | None = None,
    suite: Suite | None = None,
    reports_dir: Path = REPORTS_DIR,
) -> dict[str, Any]:
    """Run the suite `passes` times, store the run and write a JSON report; returns the report."""
    started: datetime = now()
    suite = suite or load_suite()
    version = load(judge_version or get_settings().judge.current_version)
    cases = select(suite, part, limit)
    partial = bool(limit) or part.upper() != SuitePart.ALL
    runner = SuiteRun(suite, version, judge or default_judge(), analyzer)
    try:
        results = [runner.run_pass(cases) for _ in range(passes)]
    except TokenLimitError:
        safe_log.log("judge_suite_spend_guard", severity="ERROR", estimated_usd=round(runner.estimated_usd(), 4))
        raise
    summary = summarize(suite, cases, results)

    run_id = f"suite-{int(started.timestamp()):010x}{uuid.uuid4().hex[:6]}"
    base = None if partial else baseline_row(suite.version, baseline)
    decision = None if partial else decide(summary, passes, version.version_id, base)
    row = {
        "suite_run_id": run_id,
        "day": started.date(),
        "suite_version": suite.version,
        "judge_version": version.version_id,
        "stage1_model": version.stage1_model,
        "stage2_model": version.stage2_model,
        "passes": passes,
        "n_cases": len(cases),
        "partial": partial,
        "failed_calls": summary["failed_calls"],
        "estimated_usd": round(runner.estimated_usd(), 4),
        "tuning_distance": summary["tuning_distance"],
        "held_out_distance": summary["held_out_distance"],
        "false_high": summary["false_high"],
        "missed_high": summary["missed_high"],
        "per_field": summary["per_field"],
        "per_scenario": summary["per_scenario"],
        "label_recall": summary["label_recall"],
        "decision": decision,
        "baseline_run_id": base["suite_run_id"] if base else None,
        "tokens": runner.usage.rows(),
    }
    write(SUITE_RUNS, [row])
    extra = {k: summary[k] for k in ("per_case", "case_details", "errors")}
    report = {**row, "day": row["day"].isoformat(), **extra}
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{run_id}.json").write_text(json.dumps(report, indent=2))
    safe_log.log(
        "judge_suite_done",
        suite_run_id=run_id,
        decision=decision,
        partial=partial,
        cases=len(cases),
        passes=passes,
        failed_calls=summary["failed_calls"],
        false_high=summary["false_high"],
    )
    return report
