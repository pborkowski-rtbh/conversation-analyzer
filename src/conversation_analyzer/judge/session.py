"""Session grades: informational context for alerts, used by no metric (§7.7)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from conversation_analyzer.judge.client import Judge, Usage, generate_validated
from conversation_analyzer.judge.forms import SessionGradeForm
from conversation_analyzer.judge.stage1 import Stage1Result
from conversation_analyzer.judge.stage2 import Stage2Result
from conversation_analyzer.judge.version import JudgeVersion
from conversation_analyzer.vocab import GradeState, Recovered, Relation, count_bucket


@dataclass
class SegmentTurn:
    position: int
    question: str
    answer: str
    stage1: Stage1Result | None
    stage2: Stage2Result | None


@dataclass
class GradeResult:
    grade_state: str
    outcome: str | None
    first_bad_turn: int | None
    rephrases_corrections: str
    recovered: str | None
    confidence: float | None
    model: str | None
    graded_turns: int

    def row(self) -> dict[str, Any]:
        return {
            "grade_state": self.grade_state,
            "outcome": self.outcome,
            "first_bad_turn": self.first_bad_turn,
            "rephrases_corrections": self.rephrases_corrections,
            "recovered": self.recovered,
            "confidence": self.confidence,
            "judge_model": self.model,
            "graded_turns": self.graded_turns,
        }


def _counted(turns: list[SegmentTurn]) -> tuple[int, int]:
    rel = [t.stage1.relation for t in turns if t.stage1]
    return sum(r in (Relation.REPHRASE, Relation.CORRECTION) for r in rel), sum(r == Relation.CORRECTION for r in rel)


def not_gradable(turns: list[SegmentTurn]) -> GradeResult:
    n, _ = _counted(turns)
    return GradeResult(GradeState.NOT_GRADABLE.value, None, None, count_bucket(n).value, None, None, None, len(turns))


def render(turns: list[SegmentTurn]) -> str:
    out = ["## SESSION SEGMENT"]
    for t in turns:
        line = f"### Turn {t.position}\nQuestion: {t.question}\nAnswer: {t.answer}\n"
        if t.stage1:
            line += (
                f"Stage 1: relation {t.stage1.relation}, relevance {t.stage1.relevance}, "
                f"failure {t.stage1.primary_failure}, severity {t.stage1.severity}\n"
            )
        if t.stage2:
            line += f"Stage 2: failure {t.stage2.primary_failure}, severity {t.stage2.severity}\n"
        out.append(line)
    return "\n".join(out)


def grade(turns: list[SegmentTurn], final: bool, version: JudgeVersion, judge: Judge, usage: Usage) -> GradeResult:
    """Provisional while the segment is open, final once graded on the closed segment."""
    form = generate_validated(
        judge, version.stage2_model, version.system("session_grade", "session"), render(turns), SessionGradeForm, usage
    )
    n_rephrase_or_correction, n_corrections = _counted(turns)
    recovered = form.recovered_after_correction
    if n_corrections == 0:
        recovered = Recovered.NO_CORRECTION.value
    elif recovered == Recovered.NO_CORRECTION:
        recovered = Recovered.NO.value
    first_bad = form.first_bad_turn if form.first_bad_turn and form.first_bad_turn <= len(turns) else None
    return GradeResult(
        grade_state=(GradeState.FINAL if final else GradeState.PROVISIONAL).value,
        outcome=form.outcome,
        first_bad_turn=first_bad,
        rephrases_corrections=count_bucket(n_rephrase_or_correction).value,
        recovered=recovered,
        confidence=float(form.confidence),
        model=version.stage2_model,
        graded_turns=len(turns),
    )
