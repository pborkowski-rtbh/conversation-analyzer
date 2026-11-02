"""A deterministic stand-in for the judge, scripted by `[[fake key=value]]` markers in synthetic text."""

# Markers: intent, topic, relation, relevance, completeness, clarity, groundedness, unsupported_spans, language_matches,
# refusal, contradicts_earlier, internal, codes=A|B, severity; contradiction=1 (evidence check); why, what, drop,
# s2_groundedness, claim (stage 2); outcome, first_bad, recovered (session grade); fail=output|api with optional
# fail_on=<FormName> makes that call fail.

from __future__ import annotations

import re

from pydantic import BaseModel

from conversation_analyzer.errors import JudgeApiError, JudgeOutputError
from conversation_analyzer.judge import forms
from conversation_analyzer.judge.client import Usage

_MARKER = re.compile(r"\[\[fake ([^\]]*)\]\]")
_TOPIC = re.compile(r"\(topic ([A-Z_]+)\)")


def markers(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _MARKER.finditer(text):
        for pair in m.group(1).split():
            if "=" in pair:
                k, v = pair.split("=", 1)
                out[k] = v
    return out


def _current(prompt: str) -> str:
    """The current turn and its references: the part a marker may script."""
    i = prompt.find("## CURRENT TURN")
    return prompt[i:] if i >= 0 else prompt


class FakeJudge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def generate(self, model: str, system: str, prompt: str, form: type[BaseModel], usage: Usage) -> BaseModel:
        self.calls.append((model, form.__name__))
        usage.add(model, len(system + prompt) // 4, 60)
        current = _current(prompt)
        m = markers(current.split("## STAGE 1 RESULT")[0])
        if form is forms.SessionGradeForm:
            m = markers(prompt)
        if "fail" in m and m.get("fail_on", form.__name__) == form.__name__:
            raise JudgeOutputError() if m["fail"] == "output" else JudgeApiError()
        if form is forms.Stage1Form:
            return self._stage1(current, m)
        if form is forms.EvidenceCheckForm:
            hit = m.get("contradiction") == "1" and re.search(r"## DOCUMENTS\s+\[1\]", prompt) is not None
            return forms.EvidenceCheckForm(
                contradiction_found=hit, contradicting_document=1 if hit else None, confidence=0.8
            )
        if form is forms.Stage2Form:
            return self._stage2(prompt, m)
        if form is forms.SessionGradeForm:
            return forms.SessionGradeForm(
                outcome=m.get("outcome", "RESOLVED"),
                first_bad_turn=int(m["first_bad"]) if "first_bad" in m else None,
                recovered_after_correction=m.get("recovered", "NO_CORRECTION"),
                confidence=0.7,
            )
        raise TypeError(form.__name__)

    @staticmethod
    def _stage1(current: str, m: dict[str, str]) -> forms.Stage1Form:
        topics = _TOPIC.findall(current)
        no_previous = "no previous turn" in current or "previous turn text erased" in current
        codes = [c for c in m.get("codes", "").split("|") if c]
        return forms.Stage1Form(
            intent=m.get("intent", "FACT_LOOKUP"),
            topic=m.get("topic", topics[0] if topics else "OTHER"),
            relation=m.get("relation", "FIRST" if no_previous else "FOLLOW_UP"),
            relevance=int(m.get("relevance", 4)),
            completeness=int(m.get("completeness", 4)),
            clarity=int(m.get("clarity", 4)),
            groundedness=int(m.get("groundedness", 4)),
            unsupported_spans=int(m.get("unsupported_spans", 0)),
            language_matches=m.get("language_matches", "1") == "1",
            refusal_or_empty=m.get("refusal", "0") == "1",
            contradicts_earlier=m.get("contradicts_earlier", "0") == "1",
            needs_internal_knowledge=m.get("internal", "1") == "1",
            failure_types=codes,
            severity=m.get("severity"),
            confidence=0.8,
        )

    @staticmethod
    def _stage2(prompt: str, m: dict[str, str]) -> forms.Stage2Form:
        why = m.get("why", "NONE")
        path = {
            "OUTDATED_SOURCE": dict(snippets_support_claim=True),
            "CONFLICTING_SOURCES": dict(snippets_support_claim=True),
            "NONE": dict(snippets_hold_right_content=True),
            "CHUNKING_ISSUE": dict(in_full_text=True),
            "NOT_IN_CITED_SOURCES": {},
            "SUPPORTED": dict(snippets_support_claim=True),
        }[why]
        flags = {
            "snippets_support_claim": False,
            "snippets_hold_right_content": False,
            "in_full_text": False,
            **path,
        }
        role = {"OUTDATED_SOURCE": "OUTDATED", "CONFLICTING_SOURCES": "CONFLICTING"}.get(why, "CITED")
        claims = [
            forms.ClaimForm(
                span_index=0,
                what=m.get("what", "CONTRADICTED_CLAIM"),
                documents=[forms.DocumentRole(document=1, role=role)],
                **flags,
            )
        ]
        drop = [c for c in m.get("drop", "").split("|") if c]
        return forms.Stage2Form(
            cited_documents_outdated=[1] if why == "OUTDATED_SOURCE" else [],
            cited_documents_conflicting=[1] if why == "CONFLICTING_SOURCES" else [],
            claims=claims,
            groundedness=int(m.get("s2_groundedness", 2)),
            stage1_findings=[forms.FindingForm(code=c, verdict="DROPPED") for c in drop],
            confidence=0.75,
        )
