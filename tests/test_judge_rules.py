"""Rules around the judge's forms: stage 1, evidence check, stage 2 cause path, grades, rendering (§6-§7)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from conversation_analyzer.judge import evidence, session, stage1, stage2
from conversation_analyzer.judge.case import DocRef, DocText, EarlierTurn, JudgeCase, render_documents, render_turn
from conversation_analyzer.judge.client import Usage
from conversation_analyzer.judge.forms import (
    ClaimForm,
    DocumentRole,
    EvidenceCheckForm,
    FindingForm,
    SessionGradeForm,
    Stage1Form,
    Stage2Form,
    Stage2Phrasings,
)
from conversation_analyzer.judge.version import current
from conversation_analyzer.log.parse import Reference, Span
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import ClaimWhy, EvidenceKind, FailureCode, Recovered, Relation, Severity

F = FailureCode
CONF = "rtb-crj-confluence"
HR = "rtb-crj-hr-house"
PEOPLE = "rtb-crj-associates"


def ref(doc_id: str = "d1", data_store: str = CONF, snippet: str = "snippet") -> Reference:
    return Reference(doc_id, data_store, f"https://x/{doc_id}", f"Title {doc_id}", snippet)


def make_case(**kw: Any) -> JudgeCase:
    base: dict[str, Any] = {"question": "How many days?", "answer": "Four days.", "references": [], "spans": []}
    base.update(kw)
    return JudgeCase(**base)


def form(**kw: Any) -> Stage1Form:
    base: dict[str, Any] = {
        "intent": "FACT_LOOKUP",
        "topic": "CONFLUENCE",
        "relation": "FIRST",
        "relevance": 5,
        "completeness": 4,
        "clarity": 4,
        "groundedness": 5,
        "unsupported_spans": 0,
        "language_matches": True,
        "refusal_or_empty": False,
        "contradicts_earlier": False,
        "needs_internal_knowledge": True,
        "failure_types": [],
        "severity": None,
        "confidence": 0.9,
    }
    base.update(kw)
    return Stage1Form(**base)


class Scripted:
    """Returns prepared forms by form type, in order, and records the prompts."""

    def __init__(self, *forms: BaseModel) -> None:
        self.forms = list(forms)
        self.prompts: list[tuple[str, str]] = []

    def generate(self, model, system, prompt, form_type, usage):
        self.prompts.append((form_type.__name__, prompt))
        i = next(i for i, f in enumerate(self.forms) if isinstance(f, form_type))
        return self.forms.pop(i)


class Docs:
    """A fixed document source."""

    def __init__(self, texts: dict[DocRef, str], results: list[DocRef], links: dict[str, DocRef] | None = None):
        self.texts = texts
        self.results = results
        self.links = links or {}
        self.searched: list[str] = []

    def search(self, text):
        self.searched.append(text)
        return list(self.results)

    def read(self, r):
        return DocText(r, f"Title {r.doc_id}", self.texts[r]) if r in self.texts else None

    def lookup_uri(self, uri):
        return self.links.get(uri)


# --- stage 1 ---------------------------------------------------------------------------------------------------------


def test_people_lookup_gets_no_completeness_clarity_or_judged_codes():
    r = stage1.apply_rules(
        form(intent="PEOPLE_LOOKUP", failure_types=["INCOMPLETE_ANSWER"], severity="MEDIUM"), make_case(), "m"
    )
    assert r.completeness is None and r.clarity is None and r.groundedness is None
    assert r.failure_types == ["NONE"] and r.primary_failure == "NONE" and r.severity is None
    assert r.verifiable and not r.knowledge_turn and r.needs_internal_knowledge is None


def test_knowledge_turn_without_evidence_is_not_verifiable():
    r = stage1.apply_rules(form(failure_types=["CONTRADICTED_CLAIM"], groundedness=1), make_case(), "m")
    assert not r.verifiable and r.groundedness is None and r.evidence_kind == EvidenceKind.NONE
    # judged codes need evidence; the deterministic one follows from the data
    assert r.failure_types == ["UNGROUNDED_INTERNAL_ANSWER"] and r.severity == "MEDIUM"
    assert r.total_spans is None and r.unsupported_spans is None


def test_empty_answer_is_an_agent_or_tool_error():
    r = stage1.apply_rules(form(intent="GENERAL_TASK"), make_case(answer="  "), "m")
    assert r.failure_types == ["AGENT_OR_TOOL_ERROR"] and r.severity == "MEDIUM"
    r = stage1.apply_rules(form(intent="CHITCHAT"), make_case(answer_state="FAILED"), "m")
    assert r.primary_failure == "AGENT_OR_TOOL_ERROR"


def test_contradiction_with_references_is_high_and_caps_groundedness():
    case = make_case(references=[ref()], spans=[Span(0, 0, 4, "Four", (0,)), Span(1, 5, 9, "days", (0,))])
    r = stage1.apply_rules(form(failure_types=["CONTRADICTED_CLAIM"], groundedness=4, unsupported_spans=9), case, "m")
    assert r.severity == "HIGH" and r.groundedness == 2
    assert r.total_spans == 2 and r.unsupported_spans == 2  # clamped to the spans the log has
    assert "HIGH_SEVERITY" in r.flag_reasons() and "LOW_GROUNDEDNESS" in r.flag_reasons()


def test_relation_rules():
    prev = {"has_previous_turn": True, "previous_text_available": True}
    assert stage1.apply_rules(form(relation="FOLLOW_UP"), make_case(), "m").relation == "FIRST"
    assert stage1.apply_rules(form(relation="FIRST"), make_case(**prev), "m").relation == "NEW_TOPIC"
    assert stage1.apply_rules(form(relation="CORRECTION"), make_case(**prev), "m").relation == "CORRECTION"
    erased = {"has_previous_turn": True, "previous_text_available": False}
    assert stage1.apply_rules(form(relation="CORRECTION"), make_case(**erased), "m").relation == "FIRST"


def test_topic_comes_from_references_when_there_are_any():
    two_hr = make_case(references=[ref("a", HR), ref("b", HR), ref("c", CONF)])
    assert stage1.topic_for(two_hr, "CONFLUENCE") == ("CONFLUENCE", "REFERENCES")
    assert stage1.topic_for(two_hr, "BIZTECH") == ("HR_HOUSE", "REFERENCES")
    assert stage1.topic_for(make_case(), "BIZTECH") == ("BIZTECH", "JUDGE")
    assert stage1.topic_for(make_case(references=[ref("p", PEOPLE)]), "OTHER") == ("OTHER", "JUDGE")


@pytest.mark.parametrize(
    ("codes", "intent", "judged", "expected"),
    [
        (set(), "FACT_LOOKUP", "HIGH", None),
        ({F.CONTRADICTED_CLAIM}, "HOW_TO", None, "HIGH"),
        ({F.CONTRADICTED_CLAIM}, "GENERAL_TASK", None, "LOW"),
        ({F.PRESENTATION_ISSUE}, "FACT_LOOKUP", None, "LOW"),
        ({F.PRESENTATION_ISSUE}, "FACT_LOOKUP", "HIGH", "MEDIUM"),  # nothing but a contradiction is HIGH
        ({F.PRESENTATION_ISSUE}, "FACT_LOOKUP", "MEDIUM", "MEDIUM"),
        ({F.INCOMPLETE_ANSWER}, "FACT_LOOKUP", "LOW", "LOW"),
        ({F.INCOMPLETE_ANSWER}, "FACT_LOOKUP", None, "MEDIUM"),
        ({F.AGENT_OR_TOOL_ERROR, F.PRESENTATION_ISSUE}, "CHITCHAT", "LOW", "MEDIUM"),  # deterministic floor
    ],
)
def test_severity(codes, intent, judged, expected):
    assert stage1.severity_for(codes, intent, judged) == expected


def test_add_code_reorders_and_raises_severity():
    case = make_case(references=[ref()])
    r = stage1.apply_rules(form(failure_types=["INCOMPLETE_ANSWER"], groundedness=4), case, "m")
    assert r.severity == "MEDIUM"
    r.add_code(F.CONTRADICTED_CLAIM)
    assert r.primary_failure == "CONTRADICTED_CLAIM" and r.severity == "HIGH" and r.groundedness == 2
    assert r.labels() == {
        "intent": "FACT_LOOKUP",
        "topic": "CONFLUENCE",
        "relevance": 5,
        "groundedness": 2,
        "primary_failure": "CONTRADICTED_CLAIM",
        "severity": "HIGH",
    }


def test_low_relevance_flags():
    r = stage1.apply_rules(form(intent="OTHER", relevance=2), make_case(), "m")
    assert r.flag_reasons() == ["LOW_RELEVANCE"]


def test_assess_uses_the_override_model():
    judge = Scripted(form())
    r = stage1.assess(make_case(), current(), judge, Usage(), model="second")
    assert r.model == "second" and judge.prompts[0][0] == "Stage1Form"


# --- evidence check --------------------------------------------------------------------------------------------------


def stage1_result(**kw: Any) -> stage1.Stage1Result:
    r = stage1.apply_rules(form(), make_case(), "m")
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def test_evidence_needed_only_for_knowledge_turns_without_evidence():
    assert evidence.needed(stage1_result())
    assert not evidence.needed(stage1_result(knowledge_turn=False))
    assert not evidence.needed(stage1_result(evidence_kind="OWN_REFERENCES"))


def test_evidence_candidates_links_first_people_directory_excluded():
    linked = DocRef("linked", CONF, "https://x/linked")
    a, people = DocRef("a", HR, None), DocRef("associate-1", PEOPLE, None)
    docs = Docs({}, [a, linked, people], links={"https://x/linked": linked})
    case = make_case(answer="See https://x/linked and https://x/linked and https://unknown/")
    assert evidence.candidates(case, docs) == [linked, a]


def test_evidence_read_up_to_skips_unreadable():
    refs = [DocRef(str(i), CONF, None) for i in range(5)]
    docs = Docs({refs[0]: "t0", refs[2]: "t2", refs[3]: "t3", refs[4]: "t4"}, [])
    assert [d.ref for d in evidence.read_up_to(refs, docs, 2)] == [refs[0], refs[2]]


def test_evidence_check_without_documents_makes_no_call():
    judge = Scripted()
    r = stage1_result()
    evidence.check(make_case(), r, current(), judge, Usage(), Docs({}, []))
    assert r.evidence_check_ran and not r.found_docs and not judge.prompts


def test_evidence_check_without_contradiction_keeps_result():
    d = DocRef("a", CONF, None)
    judge = Scripted(EvidenceCheckForm(contradiction_found=False, confidence=0.8))
    r = stage1_result()
    evidence.check(make_case(), r, current(), judge, Usage(), Docs({d: "text"}, [d]))
    assert r.found_docs == [d] and not r.evidence_check_contradiction and r.severity == "MEDIUM"
    assert "## DOCUMENTS\n\n[1]" in judge.prompts[0][1]


# --- stage 2 ---------------------------------------------------------------------------------------------------------


def claim(what="CONTRADICTED_CLAIM", support=False, right=False, full=False, other=False, documents=()) -> ClaimForm:
    return ClaimForm(
        what=what,
        snippets_support_claim=support,
        snippets_hold_right_content=right,
        in_cited_full_text=full,
        in_other_found_document=other,
        documents=[DocumentRole(document=d, role=r) for d, r in documents],
    )


@pytest.mark.parametrize(
    ("c", "has_cited", "outdated", "conflicting", "why"),
    [
        (claim(support=True), True, True, False, ClaimWhy.OUTDATED_SOURCE),
        (claim(support=True), True, False, True, ClaimWhy.CONFLICTING_SOURCES),
        (claim(support=True), True, False, False, None),
        (claim(right=True), True, False, False, ClaimWhy.NONE),
        (claim(full=True), True, False, False, ClaimWhy.CHUNKING_ISSUE),
        (claim(other=True), True, False, False, ClaimWhy.RETRIEVAL_MISS),
        (claim(), True, False, False, ClaimWhy.KNOWLEDGE_GAP),
        (claim(support=True, right=True, full=True), False, False, False, ClaimWhy.KNOWLEDGE_GAP),  # starts at Q3
        (claim(full=True, other=True), False, False, False, ClaimWhy.RETRIEVAL_MISS),
    ],
)
def test_cause_path(c, has_cited, outdated, conflicting, why):
    assert stage2._cause(c, has_cited, outdated, conflicting) == why


def docs_numbered(n: int) -> list[DocText]:
    return [DocText(DocRef(f"d{i}", CONF, None), "t", "x") for i in range(1, n + 1)]


def s1_flagged() -> stage1.Stage1Result:
    case = make_case(references=[ref()])
    return stage1.apply_rules(form(failure_types=["CONTRADICTED_CLAIM", "PRESENTATION_ISSUE"]), case, "m")


def test_stage2_rules_sort_claims_and_pick_primary_and_document():
    f = Stage2Form(
        cited_documents_outdated=[1, 7],
        claims=[
            claim("UNSUPPORTED_CLAIM", right=True, documents=[(1, "CITED")]),
            claim("CONTRADICTED_CLAIM", support=True, documents=[(1, "CITED"), (9, "CITED")]),
        ],
        groundedness=4,
        stage1_findings=[FindingForm(code="PRESENTATION_ISSUE", verdict="DROPPED")],
        confidence=0.7,
    )
    s1 = s1_flagged()
    r = stage2.apply_rules(f, make_case(references=[ref()]), s1, docs_numbered(2), 1, 3, "argon", [])
    assert [c.what for c in r.claims] == ["CONTRADICTED_CLAIM", "REASONING_ERROR"]
    assert [c.why for c in r.claims] == ["OUTDATED_SOURCE", "NONE"]
    assert r.primary_failure == "OUTDATED_SOURCE" and r.failure_types[0] == "OUTDATED_SOURCE"
    assert r.document_to_fix is None  # no document has the OUTDATED role
    assert r.groundedness == 2 and r.severity == "HIGH"
    assert {"code": "PRESENTATION_ISSUE", "verdict": "DROPPED"} in r.stage1_findings
    assert r.changed_stage1(s1)
    row = r.row()
    assert row["claims"][0]["position"] == 1 and len(row["claims"][0]["documents"]) == 1  # index 9 is not numbered


def test_stage2_chunking_issue_falls_back_to_the_first_cited_document():
    f = Stage2Form(claims=[claim(full=True)], confidence=0.5)
    s1 = s1_flagged()
    r = stage2.apply_rules(f, make_case(references=[ref()]), s1, docs_numbered(1), 1, 2, "argon", [])
    assert r.primary_failure == "CHUNKING_ISSUE" and r.document_to_fix == DocRef("d1", CONF, None)


def test_stage2_supported_claims_are_dropped_and_deterministic_codes_stay():
    case = make_case(references=[ref()], answer_state="FAILED")
    s1 = stage1.apply_rules(form(), case, "m")  # AGENT_OR_TOOL_ERROR follows from the data
    f = Stage2Form(
        claims=[claim(support=True, documents=[(1, "CITED")])],
        groundedness=5,
        stage1_findings=[FindingForm(code="AGENT_OR_TOOL_ERROR", verdict="DROPPED")],
        confidence=0.5,
    )
    r = stage2.apply_rules(f, case, s1, docs_numbered(1), 1, 2, "argon", [])
    assert not r.claims and r.primary_failure == "AGENT_OR_TOOL_ERROR" and r.groundedness == 5
    assert r.stage1_findings == [{"code": "AGENT_OR_TOOL_ERROR", "verdict": "CONFIRMED"}]
    assert not r.changed_stage1(s1) and r.document_to_fix is None
    not_verifiable = stage1.apply_rules(form(), make_case(), "m")
    r = stage2.apply_rules(Stage2Form(groundedness=5, confidence=0.5), make_case(), not_verifiable, [], 0, 2, "a", [])
    assert r.groundedness is None and r.primary_failure == "UNGROUNDED_INTERNAL_ANSWER"


def test_stage2_retrieval_miss_points_at_the_document_with_the_right_answer():
    f = Stage2Form(claims=[claim(other=True, documents=[(2, "HOLDS_RIGHT_ANSWER")])], confidence=0.5)
    r = stage2.apply_rules(f, make_case(references=[ref()]), s1_flagged(), docs_numbered(2), 1, 2, "argon", [])
    assert r.document_to_fix == DocRef("d2", CONF, None) and r.severity == "HIGH"


def test_stage2_documents_dedupe_fallback_and_cap(monkeypatch):
    monkeypatch.setattr(get_settings().sizes, "stage2_found_documents", 2)
    cited = ref("c1", CONF, "the snippet")
    found = [DocRef(f"f{i}", HR, None) for i in range(4)]
    people = DocRef("associate-9", PEOPLE, None)
    docs = Docs({found[0]: "a", found[2]: "c", found[3]: "d"}, [people, *found])
    case = make_case(references=[cited, cited])
    s1 = s1_flagged()
    s1.found_docs = [found[1]]
    cited_docs, found_docs = stage2._documents(case, s1, ["phrase one"], docs)
    assert len(cited_docs) == 1 and cited_docs[0].text == "the snippet"  # no full text: the snippet
    assert [d.ref for d in found_docs] == [found[0], found[2]]  # f1 has no content, people never
    assert docs.searched == ["How many days?", "phrase one"]


def test_diagnose_searches_question_and_phrasings():
    d = DocRef("f", HR, None)
    docs = Docs({d: "full text"}, [d])
    judge = Scripted(
        Stage2Phrasings(claims=["claim a", " "]),
        Stage2Form(claims=[claim(other=True, documents=[(1, "HOLDS_RIGHT_ANSWER")])], confidence=0.6),
    )
    r = stage2.diagnose(make_case(), s1_flagged(), ["HIGH_SEVERITY"], current(), judge, Usage(), docs)
    assert r.searched_phrasings == 2 and r.found_docs == [d] and r.document_to_fix == d
    assert "## DOCUMENTS FOUND BY SEARCH\n\n[1]" in judge.prompts[1][1]
    judge = Scripted(Stage2Phrasings(claims=[]), Stage2Form(confidence=0.6))
    docs = Docs({}, [])
    stage2.diagnose(make_case(), s1_flagged(), [], current(), judge, Usage(), docs)
    assert docs.searched == ["How many days?", "Four days."]  # fallback phrasing: the answer
    assert "## DOCUMENTS FOUND BY SEARCH\n(none)" in judge.prompts[1][1]


# --- session grades --------------------------------------------------------------------------------------------------


def seg_turn(position: int, relation: str | None) -> session.SegmentTurn:
    s1 = stage1_result(relation=relation) if relation else None
    return session.SegmentTurn(position, "q", "a", s1, None)


def grade_form(recovered: str, first_bad: int | None = 1) -> SessionGradeForm:
    return SessionGradeForm(
        outcome="UNRESOLVED", first_bad_turn=first_bad, recovered_after_correction=recovered, confidence=0.5
    )


def test_not_gradable_counts_rephrases():
    turns = [seg_turn(1, "FIRST"), seg_turn(2, "REPHRASE"), seg_turn(3, "CORRECTION"), seg_turn(4, None)]
    g = session.not_gradable(turns)
    assert g.grade_state == "NOT_GRADABLE" and g.rephrases_corrections == "2_OR_MORE" and g.graded_turns == 4


def test_grade_recovered_rules():
    v = current()
    no_corr = [seg_turn(1, "FIRST"), seg_turn(2, "REPHRASE")]
    g = session.grade(no_corr, True, v, Scripted(grade_form("YES", first_bad=7)), Usage())
    assert g.recovered == Recovered.NO_CORRECTION and g.first_bad_turn is None and g.grade_state == "FINAL"
    assert g.rephrases_corrections == "1"
    corr = [seg_turn(1, "FIRST"), seg_turn(2, Relation.CORRECTION.value)]
    g = session.grade(corr, False, v, Scripted(grade_form("NO_CORRECTION")), Usage())
    assert g.recovered == "NO" and g.grade_state == "PROVISIONAL" and g.first_bad_turn == 1
    assert g.row()["judge_model"] == v.stage2_model


def test_session_render_includes_stage_results():
    t = seg_turn(1, "FIRST")
    t.stage2 = stage2.Stage2Result([], None, ["NONE"], "NONE", None, [], None, 0.5, 1, "m")
    text = session.render([t])
    assert "Stage 1: relation FIRST" in text and "Stage 2: failure NONE" in text


# --- rendering -------------------------------------------------------------------------------------------------------


def test_render_turn_context_erased_labels_and_earlier_references():
    earlier = [
        EarlierTurn(1, 1, None, None, {"intent": "FACT_LOOKUP", "severity": None}),
        EarlierTurn(2, 1, "Earlier question?", "Earlier answer."),
    ]
    case = make_case(
        earlier=earlier,
        earlier_references=[ref("e1", HR)],
        has_previous_turn=True,
        previous_text_available=False,
    )
    text = render_turn(case)
    assert "### Turn 1 (segment 1, text erased): intent FACT_LOOKUP" in text and "severity" not in text
    assert "## REFERENCES OF EARLIER TURNS" in text and "previous turn text erased" in text
    assert "Evidence: EARLIER_REFERENCES" in text and "## REFERENCES OF THE CURRENT TURN\n(none)" in text
    assert "EARLIER TURNS" not in render_turn(case, with_context=False)


def test_answer_spans_point_at_the_reference_numbers_the_judge_sees():
    # The log counts references from 0 and includes the people directory; the judge sees them from 1 without it.
    refs = [ref("associate-1", PEOPLE), ref("d1"), ref("d2")]
    spans = [Span(0, 0, 5, "Four", (1,)), Span(1, 6, 11, "days.", (0, 2))]
    text = render_turn(make_case(references=refs, spans=spans))
    assert '[S0] "Four" -> references [1]' in text and '[S1] "days." -> references [2]' in text
    assert "[1] data store rtb-crj-confluence (topic CONFLUENCE), title: Title d1" in text


def test_render_context_keeps_the_most_recent_turns_within_the_cap(monkeypatch):
    monkeypatch.setattr(get_settings().sizes, "context_chars", 120)
    earlier = [EarlierTurn(i, 1, f"question {i} " * 3, "answer") for i in range(1, 6)]
    text = render_turn(make_case(earlier=earlier, has_previous_turn=True, previous_text_available=True))
    assert "### Turn 5" in text and "### Turn 1" not in text and "previous turn text available" in text
    monkeypatch.setattr(get_settings().sizes, "context_chars", 5)
    assert "## EARLIER TURNS OF THE SESSION\n(none)" in render_turn(make_case(earlier=earlier))


def test_render_documents_caps_text(monkeypatch):
    monkeypatch.setattr(get_settings().sizes, "document_chars", 3)
    out = render_documents([DocText(DocRef("a", CONF, None), "T", "abcdef")], "CITED")
    assert out.endswith("abc") and out.startswith("## CITED\n\n[1]")
    assert render_documents([]) == "## DOCUMENTS\n(none)"
    assert Severity.HIGH == "HIGH"
