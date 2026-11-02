"""The canary: evaluator turns assessed like real ones, kept apart, and changed to plant errors (§11.4, §12.11)."""

from __future__ import annotations

import hashlib
import re

from conversation_analyzer.bq.client import fq, query
from conversation_analyzer.judge.case import JudgeCase
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import FailureCode, PlantedError, Severity

_NUMBER = re.compile(r"(?<![\w.])(\d{1,6})(?!\w|\.\d)")  # whole numbers, also at the end of a sentence
_STEP = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+\S.*$", re.MULTILINE)
_CAPITALIZED = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]{2,})\b")


def bare_question(question: str) -> str:
    """The evaluator's question without its prompt prefix: what the evaluator itself hashes."""
    marker = get_settings().evaluator.question_marker
    return question.split(marker, 1)[1].strip() if marker in question else question.strip()


def question_hash(question: str) -> str:
    return hashlib.sha256(bare_question(question).encode()).hexdigest()


def expected_documents(hashes: list[str]) -> dict[str, tuple[str, str]]:
    """The document that holds each canary question's answer, from the evaluator's results (§12.11)."""
    if not hashes:
        return {}
    rows = query(
        f"""
SELECT question_sha256, ANY_VALUE(expected_doc_id) AS doc_id, ANY_VALUE(expected_data_store) AS data_store
FROM {fq("evals", "results")}
WHERE run_kind = 'CANARY' AND question_sha256 IN UNNEST(@h) AND expected_doc_id IS NOT NULL
GROUP BY question_sha256""",
        h=hashes,
    )
    return {r["question_sha256"]: (r["doc_id"], r["data_store"]) for r in rows}


def swap_number(answer: str, evidence: str) -> str | None:
    for m in _NUMBER.finditer(answer):
        n = int(m.group(1))
        return answer[: m.start()] + str(n + 2 if n < 1000 else n * 2) + answer[m.end() :]
    return None


def drop_step(answer: str, evidence: str) -> str | None:
    steps = list(_STEP.finditer(answer))
    if len(steps) < 2:
        return None
    m = steps[len(steps) // 2]
    return answer[: m.start()] + answer[m.end() + 1 :]


def wrong_name(answer: str, evidence: str) -> str | None:
    """Replace a name the evidence backs with another name from the evidence, so the change stays plausible."""
    in_answer = [m for m in _CAPITALIZED.finditer(answer) if m.group(1) in evidence]
    others = [w for w in dict.fromkeys(_CAPITALIZED.findall(evidence))]
    for m in in_answer:
        replacement = next((w for w in others if w != m.group(1) and w not in answer), None)
        if replacement:
            return answer[: m.start()] + replacement + answer[m.end() :]
    return None


MUTATIONS = {
    PlantedError.SWAPPED_NUMBER: swap_number,
    PlantedError.DROPPED_STEP: drop_step,
    PlantedError.WRONG_NAME: wrong_name,
}


def planted_cases(case: JudgeCase) -> list[tuple[PlantedError, bool, JudgeCase]]:
    """Changed copies of a canary answer, with and without its references (§11.4)."""
    evidence = "\n".join(r.snippet for r in case.references)
    out = []
    for error, mutate in MUTATIONS.items():
        changed = mutate(case.answer, evidence)
        if changed is None or changed == case.answer:
            continue
        for with_refs in (True, False):
            out.append(
                (
                    error,
                    with_refs,
                    JudgeCase(
                        question=case.question,
                        answer=changed,
                        references=case.references if with_refs else [],
                        spans=[],
                        answer_state=case.answer_state,
                        earlier=[],
                        earlier_references=[],
                        has_previous_turn=False,
                        previous_text_available=False,
                    ),
                )
            )
    return out


def caught(error: PlantedError, failure_types: list[str], severity: str | None) -> bool:
    """A swapped number or name is caught as a contradiction; a dropped step also as a missing or unsupported part."""
    codes = set(failure_types)
    if error is PlantedError.DROPPED_STEP:
        return bool(
            codes & {FailureCode.INCOMPLETE_ANSWER, FailureCode.CONTRADICTED_CLAIM, FailureCode.UNSUPPORTED_CLAIM}
        )
    return FailureCode.CONTRADICTED_CLAIM in codes and severity == Severity.HIGH
