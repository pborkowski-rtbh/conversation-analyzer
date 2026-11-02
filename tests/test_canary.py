"""Canary helpers: bare questions, planted mutations and whether the judge caught them (§11.4)."""

from __future__ import annotations

import hashlib

from conversation_analyzer.assessor import canary
from conversation_analyzer.judge.case import JudgeCase
from conversation_analyzer.log.parse import Reference
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import FailureCode, PlantedError, Severity


def case(answer: str, snippet: str) -> JudgeCase:
    ref = Reference("doc", "rtb-crj-confluence", "https://x", "Title", snippet)
    return JudgeCase(
        question="Q",
        answer=answer,
        references=[ref],
        spans=[],
        answer_state="SUCCEEDED",
        earlier=[],
        earlier_references=[],
        has_previous_turn=False,
        previous_text_available=False,
    )


def test_bare_question_and_hash():
    marker = get_settings().evaluator.question_marker
    prompted = f"Provide concise, focused answers.{marker}  What is X? "
    assert canary.bare_question(prompted) == "What is X?"
    assert canary.bare_question("  plain  ") == "plain"
    assert canary.question_hash(prompted) == hashlib.sha256(b"What is X?").hexdigest()


def test_swap_number():
    assert canary.swap_number("You get 4 days and 26 weeks.", "") == "You get 6 days and 26 weeks."
    assert canary.swap_number("Limit is 5000.", "") == "Limit is 10000."
    assert canary.swap_number("Version 1.5 only", "") is None  # decimals are left alone
    assert canary.swap_number("no numbers", "") is None


def test_drop_step():
    answer = "Steps:\n1. Open the tool\n2. Fill the form\n3. Submit\n"
    assert canary.drop_step(answer, "") == "Steps:\n1. Open the tool\n3. Submit\n"
    assert canary.drop_step("- only one step", "") is None


def test_wrong_name():
    evidence = "Ask Anna in Finance. Marek approves trips."
    assert canary.wrong_name("Talk to Anna about it.", evidence) == "Talk to Finance about it."
    assert canary.wrong_name("Talk to Zofia about it.", evidence) is None  # no name the evidence backs
    assert canary.wrong_name("Talk to Anna.", "Ask Anna.") is None  # no other name to swap in


def test_planted_cases_with_and_without_references():
    c = case("You get 4 days.\n1. Open\n2. Fill\n3. Send", "Anna says 4 days")
    planted = canary.planted_cases(c)
    kinds = {(e, refs) for e, refs, _ in planted}
    assert kinds == {
        (PlantedError.SWAPPED_NUMBER, True),
        (PlantedError.SWAPPED_NUMBER, False),
        (PlantedError.DROPPED_STEP, True),
        (PlantedError.DROPPED_STEP, False),
    }
    for _, with_refs, changed in planted:
        assert changed.answer != c.answer and bool(changed.references) == with_refs and not changed.spans


def test_caught():
    contradicted = [FailureCode.CONTRADICTED_CLAIM.value]
    assert canary.caught(PlantedError.SWAPPED_NUMBER, contradicted, Severity.HIGH.value)
    assert not canary.caught(PlantedError.SWAPPED_NUMBER, contradicted, Severity.MEDIUM.value)
    assert not canary.caught(PlantedError.WRONG_NAME, [], None)
    assert canary.caught(PlantedError.DROPPED_STEP, [FailureCode.INCOMPLETE_ANSWER.value], Severity.LOW.value)
    assert not canary.caught(PlantedError.DROPPED_STEP, [FailureCode.PRESENTATION_ISSUE.value], None)
