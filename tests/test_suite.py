"""The judge test suite: the cases meet the scenario minimums, a perfect judge scores 0, scoring follows §11.2."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from conversation_analyzer.errors import JudgeApiError, TokenLimitError
from conversation_analyzer.judge import forms
from conversation_analyzer.judge.case import DocRef
from conversation_analyzer.judge.version import current
from conversation_analyzer.pii.scrubber import Entity, PiiMap
from conversation_analyzer.suite.cases import ExpectedStage1, Suite, SuiteCase, load_suite
from conversation_analyzer.suite.runner import CasePass, FixedDocuments, SuiteRun, decide, scrubbed, select, summarize
from conversation_analyzer.suite.scoring import (
    Distance,
    add_evidence,
    add_session,
    add_stage2,
    score_distance,
    severity_distance,
    stage1_distance,
)
from conversation_analyzer.vocab import EvidenceKind

JUDGED = set(forms.JudgedCodeL.__args__)
_DOC = re.compile(r"^\[(\d+)\] data store \S+, title: (.*)$", re.M)


class NoPii:
    def analyze(self, text: str) -> list[Entity]:
        return []


class Names:
    """Finds the names given, as the real scrubber would."""

    def __init__(self, *names: str) -> None:
        self.names = names

    def analyze(self, text: str) -> list[Entity]:
        out = []
        for name in self.names:
            for m in re.finditer(re.escape(name), text):
                out.append(Entity(m.start(), m.end(), "PERSON", 0.9))
        return out


class Oracle:
    """A judge that fills every form with the case's expected values; what distance remains, the rules put there."""

    def __init__(self, case: SuiteCase, suite: Suite) -> None:
        self.case = case
        self.suite = suite

    def generate(self, model, system, prompt, form, usage):
        exp = self.case.expected
        usage.add(model, 1000, 100)
        if form is forms.Stage1Form:
            e = exp.stage1
            codes = [c for c in e.failure_types if c in JUDGED]
            if self.case.evidence_kind(self.suite.documents) is EvidenceKind.NONE:
                codes = [c for c in codes if c != "CONTRADICTED_CLAIM"]  # the evidence check adds it
            return forms.Stage1Form(
                intent=e.intent,
                topic="OTHER",
                relation=e.relation,
                relevance=e.relevance,
                completeness=e.completeness,
                clarity=e.clarity,
                groundedness=e.groundedness,
                unsupported_spans=e.unsupported_spans,
                language_matches=e.language_matches,
                refusal_or_empty=e.refusal_or_empty,
                contradicts_earlier=e.contradicts_earlier,
                needs_internal_knowledge=e.needs_internal_knowledge,
                failure_types=codes,
                severity=e.severity,
                confidence=0.9,
            )
        if form is forms.EvidenceCheckForm:
            hit = bool(exp.evidence_check and exp.evidence_check.contradiction_found)
            return forms.EvidenceCheckForm(
                contradiction_found=hit, contradicting_document=1 if hit else None, confidence=0.9
            )
        if form is forms.Stage2Form:
            return self._stage2(prompt)
        s = exp.session
        return forms.SessionGradeForm(
            outcome=s.outcome, first_bad_turn=s.first_bad_turn, recovered_after_correction=s.recovered, confidence=0.9
        )

    def _stage2(self, prompt: str) -> forms.Stage2Form:
        exp = self.case.expected.stage2
        cited_part, _, linked_part = prompt.partition("## DOCUMENTS LINKED IN THE ANSWER (full text)")
        cited = {title: int(n) for n, title in _DOC.findall(cited_part.split("## CITED DOCUMENTS (full text)")[-1])}
        linked = {title: int(n) for n, title in _DOC.findall(linked_part)}
        fixes = [self.suite.documents[k].title for k in exp.fix_options() if k]
        why = exp.cause or "NONE"

        def number(docs: dict[str, int]) -> int | None:
            return next((docs[t] for t in fixes if t in docs), None)

        flags = {
            "snippets_support_claim": why in ("OUTDATED_SOURCE", "CONFLICTING_SOURCES"),
            "snippets_hold_right_content": why == "NONE",
            "in_full_text": why == "CHUNKING_ISSUE",
        }
        in_cited = number(cited)
        role, doc = {
            "OUTDATED_SOURCE": ("OUTDATED", number(cited)),
            "CONFLICTING_SOURCES": ("CONFLICTING", number(cited)),
            "CHUNKING_ISSUE": ("CITED", in_cited) if in_cited else ("HOLDS_RIGHT_ANSWER", number(linked)),
            "NOT_IN_CITED_SOURCES": ("CITED", None),
            "NONE": ("CITED", 1 if cited else None),
        }[why]
        what = "REASONING_ERROR" if exp.primary_failure == "REASONING_ERROR" else "CONTRADICTED_CLAIM"
        documents = [forms.DocumentRole(document=doc, role=role)] if doc else []
        return forms.Stage2Form(
            cited_documents_outdated=[doc] if why == "OUTDATED_SOURCE" and doc else [],
            cited_documents_conflicting=sorted(cited.values()) if why == "CONFLICTING_SOURCES" else [],
            claims=[forms.ClaimForm(span_index=0, what=what, documents=documents, **flags)],
            groundedness=2,
            confidence=0.9,
        )


@pytest.fixture(scope="module")
def suite() -> Suite:
    return load_suite()


def test_cases_meet_every_scenario_minimum(suite):
    assert suite.short() == {}
    held_out = sum(c.part == "HELD_OUT" for c in suite.cases) / len(suite.cases)
    assert 0.15 <= held_out <= 0.25  # about 20 % are kept aside (§11.1)
    assert not any(c.reviewed for c in suite.cases)  # drafted, not yet checked by an engineer
    assert suite.version == load_suite().version and suite.version.startswith("suite-")


def test_a_perfect_judge_is_at_distance_zero_on_every_case(suite):
    version = current()
    off = {}
    for case in suite.cases:
        result = SuiteRun(suite, version, Oracle(case, suite), NoPii(), concurrency=1).run_case(case)
        if result.distance.total or result.errors:
            off[case.id] = (result.distance.parts, result.errors)
    assert off == {}


def test_case_inputs_become_what_the_live_judge_sees(suite):
    case = next(c for c in suite.cases if c.id == "conflicting" or c.id.endswith("vpn-portal-conflicting"))
    jc = case.judge_case(suite.documents)
    assert [r.data_store for r in jc.references] == ["rtb-crj-helpdesk-qa", "rtb-crj-knowhow"]
    assert jc.spans[0].reference_indices == (1,) and jc.answer[jc.spans[0].start : jc.spans[0].end] == jc.spans[0].text
    erased = next(c for c in suite.cases if not c.previous_text_available)
    jc = erased.judge_case(suite.documents)
    assert jc.earlier[0].question is None and jc.earlier[0].labels["relation"] == "FIRST"
    assert not jc.previous_text_available and not jc.earlier_references
    people = next(c for c in suite.cases if c.id == "people-1")
    assert people.evidence_kind(suite.documents) is EvidenceKind.NONE  # the people directory is never evidence


def test_scenarios_of_a_case(suite):
    by_id = {c.id: c for c in suite.cases}
    near_miss = by_id["leave_ondemand-near-miss"].scenarios(suite.documents)
    assert {"severity:MEDIUM", "severity:NEAR_MISS", "failure:UNSUPPORTED_CLAIM", "evidence:OWN_REFERENCES"} <= set(
        near_miss
    )
    answer = by_id["leave_ondemand-contradicted"].scenarios(suite.documents)
    assert "cause:ANSWER" in answer and "severity:HIGH" in answer
    session = by_id["resolved-leave_ondemand"].scenarios(suite.documents)
    assert "outcome:RESOLVED" in session and "relation:FOLLOW_UP" in session
    assert "edge:long_context" in by_id["long-vpn-log"].scenarios(suite.documents)


def _write_suite(tmp_path: Path, cases: list[dict], documents: dict | None = None) -> Path:
    (tmp_path / "cases").mkdir(parents=True)
    (tmp_path / "suite.yaml").write_text(yaml.safe_dump({"weights": {"intent": 3}, "minimums": {"intent:OTHER": 1}}))
    doc = {"doc_id": "d1", "data_store": "rtb-crj-hr-house", "uri": "https://x/1", "title": "T", "text": "body"}
    (tmp_path / "documents.yaml").write_text(yaml.safe_dump(documents or {"d": doc}))
    (tmp_path / "cases" / "a.yaml").write_text(yaml.safe_dump(cases))
    return tmp_path


def _case(cid: str, **extra) -> dict:
    expected = {"stage1": {"intent": "OTHER", "relation": "FIRST", "relevance": 4}}
    return {"id": cid, "turn": {"question": "q", "answer": "a"}, "expected": expected, **extra}


def test_load_suite_rejects_broken_cases(tmp_path):
    ok = load_suite(_write_suite(tmp_path / "ok", [_case("a")]))
    assert ok.coverage() == {"intent:OTHER": (1, 1)} and not ok.short()
    with pytest.raises(ValueError, match="duplicate"):
        load_suite(_write_suite(tmp_path / "dup", [_case("a"), _case("a")]))
    bad_ref = _case("a", turn={"question": "q", "answer": "a", "references": [{"doc": "nope", "snippet": "s"}]})
    with pytest.raises(ValueError, match="unknown document nope"):
        load_suite(_write_suite(tmp_path / "ref", [bad_ref]))
    bad_fix = _case("a")
    bad_fix["expected"]["stage2"] = {"primary_failure": "CHUNKING_ISSUE", "document_to_fix": ["d", "gone"]}
    with pytest.raises(ValueError, match="unknown document gone"):
        load_suite(_write_suite(tmp_path / "fix", [bad_fix]))
    with pytest.raises(ValueError, match="primary_failure"):
        ExpectedStage1(
            intent="OTHER", relation="FIRST", relevance=3, failure_types=["NONE"], primary_failure="OUT_OF_SCOPE"
        )


def test_score_distances_follow_the_design_examples():
    assert score_distance("relevance", 4, 3) == 1.25  # the turn stops counting as good
    assert score_distance("relevance", 5, 4) == 0.25
    assert score_distance("completeness", 4, 2) == 0.5  # no decision line on completeness
    assert score_distance("groundedness", 3, 2) == 1.25
    assert severity_distance("MEDIUM", "HIGH") == (5.0, True, False)
    assert severity_distance("HIGH", "MEDIUM") == (3.0, False, True)
    assert severity_distance("LOW", "MEDIUM") == (1.0, False, False)
    assert severity_distance(None, None) == (0.0, False, False)


WEIGHTS = load_suite().weights


def test_stage1_distance_counts_every_field():
    expected = {
        "intent": "FACT_LOOKUP",
        "relation": "FIRST",
        "relevance": 5,
        "completeness": 5,
        "clarity": 5,
        "groundedness": 1,
        "unsupported_spans": 1,
        "needs_internal_knowledge": True,
        "language_matches": True,
        "refusal_or_empty": False,
        "contradicts_earlier": False,
        "failure_types": ["CONTRADICTED_CLAIM"],
        "primary_failure": "CONTRADICTED_CLAIM",
        "severity": "HIGH",
    }
    assert stage1_distance(expected, {**expected, "total_spans": 2}, WEIGHTS).total == 0
    actual = {
        **expected,
        "intent": "HOW_TO",
        "groundedness": 4,
        "unsupported_spans": 0,
        "total_spans": 2,
        "clarity": None,
        "failure_types": ["UNSUPPORTED_CLAIM", "INCOMPLETE_ANSWER"],
        "primary_failure": "UNSUPPORTED_CLAIM",
        "severity": "MEDIUM",
    }
    d = stage1_distance(expected, actual, WEIGHTS)
    assert d.parts == {
        "INTENT": 3.0,
        "FILLED_FIELDS": 1.0,
        "GROUNDEDNESS": 1.75,
        "SPAN_COUNTS": 0.5,
        "FAILURE_TYPES": 2.0,
        "PRIMARY_FAILURE": 2.0,
        "SEVERITY": 3.0,
    }
    assert (d.false_high, d.missed_high) == (0, 1)
    failed = stage1_distance(expected, {}, WEIGHTS)  # a failed call misses everything
    assert failed.parts["INTENT"] == 3 and failed.parts["RELATION"] == 1 and failed.parts["FILLED_FIELDS"] == 6
    assert failed.missed_high == 1


def test_evidence_stage2_and_session_parts():
    d = Distance()
    add_evidence(d, None, True, WEIGHTS)
    add_evidence(d, {"contradiction_found": True}, None, WEIGHTS)
    assert d.parts == {"EVIDENCE_CHECK": 1.0}
    d = Distance()
    expected = {"primary_failure": "CONFLICTING_SOURCES", "fix_options": ["a", "b"]}
    add_stage2(d, expected, {"primary_failure": "CONFLICTING_SOURCES", "document_to_fix": "b"}, WEIGHTS)
    assert d.total == 0
    add_stage2(d, expected, None, WEIGHTS)  # stage 2 never ran
    assert d.parts == {"STAGE2_CAUSE": 2.0, "DOCUMENT_TO_FIX": 1.0}
    add_stage2(d, None, None, WEIGHTS)
    d = Distance()
    session = {"outcome": "RESOLVED", "first_bad_turn": 1, "recovered": "YES"}
    add_session(d, session, {"outcome": "RESOLVED", "first_bad_turn": 3, "recovered": "YES"}, WEIGHTS)
    assert d.parts == {"FIRST_BAD_TURN": 1.0}  # the difference in turns, at most 1
    add_session(d, session, None, WEIGHTS)
    assert d.parts == {"FIRST_BAD_TURN": 2.0, "SESSION_OUTCOME": 2.0, "RECOVERED": 1.0}
    add_session(d, None, None, WEIGHTS)


def test_fixed_documents_and_scrubbing(suite):
    pii = PiiMap()
    case = next(c for c in suite.cases if c.id == "trips_booking-private-details")
    jc = scrubbed(case.judge_case(suite.documents), pii, Names("Anna Nowak"))
    assert "<PERSON_1>" in jc.question and "Anna" not in jc.question
    docs = FixedDocuments(suite, pii)
    person = suite.documents["person_finance"]
    assert docs.read(person.ref).text.startswith("<PERSON_1>, Head of Finance Operations")
    assert docs.read(DocRef("gone", "rtb-crj-hr-house", None)) is None
    assert docs.lookup_uri(suite.documents["trips"].uri) == suite.documents["trips"].ref
    assert docs.lookup_uri("https://elsewhere") is None


def _pass(cid: str, total: float, labels=(), false_high=0, errors=()) -> CasePass:
    return CasePass(cid, Distance({"INTENT": total}, false_high=false_high), list(labels), list(errors))


def test_summary_averages_passes_and_marks_reliable_labels(suite):
    knowledge = [c for c in suite.cases if c.id.endswith("-ok")]
    tuning = next(c for c in knowledge if c.part == "TUNING")
    held_out = next(c for c in knowledge if c.part == "HELD_OUT")
    cases = [tuning, held_out]
    passes = [
        [_pass(tuning.id, 1.0, [("CONTRADICTED_CLAIM", True)]), _pass(held_out.id, 3.0, false_high=1)],
        [_pass(tuning.id, 2.0, [("CONTRADICTED_CLAIM", False)]), _pass(held_out.id, 5.0, errors=["JUDGE_API"])],
        [_pass(tuning.id, 3.0, [("CONTRADICTED_CLAIM", True)]), _pass(held_out.id, 4.0)],
    ]
    s = summarize(suite, cases, passes)
    assert (s["tuning_distance"], s["held_out_distance"]) == (2.0, 4.0)
    assert (s["false_high"], s["failed_calls"], s["errors"]) == (1, 1, {"JUDGE_API": 1})
    assert {"field": "INTENT", "part": "ALL", "distance": 3.0} in s["per_field"]
    assert {"scenario": "relation:FIRST", "distance": 3.0, "n": 2} in s["per_scenario"]
    assert s["label_recall"] == [{"label": "CONTRADICTED_CLAIM", "recall": 0.6667, "n": 3, "reliable": False}]


def test_keep_rule():
    base = {
        "suite_run_id": "suite-0001",
        "judge_version": "v1-a",
        "passes": 3,
        "tuning_distance": 2.0,
        "held_out_distance": 2.5,
        "false_high": 3,
    }
    better = {"tuning_distance": 1.8, "held_out_distance": 2.5, "false_high": 3}
    assert decide(better, 3, "v2-b", None) == "BASELINE"
    assert decide(better, 3, "v1-a", base) == "BASELINE"  # the same judge again only re-measures
    assert decide(better, 3, "v2-b", base) == "KEEP"
    assert decide({**better, "held_out_distance": 2.6}, 3, "v2-b", base) == "REJECT"
    assert decide({**better, "false_high": 2}, 1, "v2-b", base) == "REJECT"  # 2 per pass is more than 1
    assert decide({**better, "tuning_distance": 2.0}, 3, "v2-b", base) == "REJECT"


def test_select_parts_and_limit(suite):
    assert len(select(suite, "all", 0)) == len(suite.cases)
    assert {c.part for c in select(suite, "held_out", 0)} == {"HELD_OUT"}
    assert len(select(suite, "tuning", 5)) == 5


class Failing(Oracle):
    def __init__(self, case: SuiteCase, suite: Suite, fail_on: type) -> None:
        super().__init__(case, suite)
        self.fail_on = fail_on

    def generate(self, model, system, prompt, form, usage):
        if form is self.fail_on:
            raise JudgeApiError()
        return super().generate(model, system, prompt, form, usage)


@pytest.mark.parametrize(
    ("case_id", "form", "field"),
    [
        ("leave_ondemand-ok", forms.Stage1Form, "INTENT"),
        ("leave_ondemand-contradicted", forms.Stage2Form, "STAGE2_CAUSE"),
        ("resolved-leave_ondemand", forms.SessionGradeForm, "SESSION_OUTCOME"),
    ],
)
def test_a_failed_call_counts_as_missed(suite, case_id, form, field):
    case = next(c for c in suite.cases if c.id == case_id)
    result = SuiteRun(suite, current(), Failing(case, suite, form), NoPii(), concurrency=1).run_case(case)
    assert result.errors == ["JUDGE_API"] and result.distance.parts[field] > 0


def test_spend_guard_stops_the_run(suite):
    case = suite.cases[0]
    run = SuiteRun(suite, current(), Oracle(case, suite), NoPii(), concurrency=1)
    run.usage.add("gemini-4-argon", 10_000_000, 0)
    assert run.estimated_usd() == pytest.approx(44.0)  # 10 M input tokens at 4.40 USD per M
    with pytest.raises(TokenLimitError):
        run.run_case(case)
