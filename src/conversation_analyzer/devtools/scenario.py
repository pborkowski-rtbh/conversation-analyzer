"""A synthetic window that walks every path of the assessor; used by `make seed` and the end-to-end tests."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any

from conversation_analyzer.bq.client import client, write
from conversation_analyzer.bq.schema import SUITE_RUNS
from conversation_analyzer.devtools.synthetic import (
    Ref,
    SynthDoc,
    SynthTurn,
    insert_log,
    search_row,
    store_department_map,
    store_documents,
    turn_rows,
)
from conversation_analyzer.judge.version import current
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import SuiteDecision

LEAVE = SynthDoc(
    "rtb-crj-hr-house",
    "sites_google_com_rtbhouse_com_hr-house_leave",
    "https://sites.google.com/rtbhouse.com/hr-house/leave",
    "On-demand leave policy",
    "On-demand leave\n\nEmployees have up to 4 days of on-demand leave per year, taken from annual "
    "leave.\n\nSick leave\n\nSick leave needs a doctor's certificate.",
)
TRIP = SynthDoc(
    "rtb-crj-confluence",
    "confluence_HR_100_v3",
    "https://rtbhouseproduct.atlassian.net/wiki/spaces/HR/pages/100",
    "Business trips",
    "Business trips\n\nBook every business trip in the Travel Tool.\n\nApproval\n\nOnly trips outside "
    "Europe need finance approval; trips inside Europe need the manager's approval.",
)
API = SynthDoc(
    "rtb-crj-api-docs",
    "web_api_campaigns_endpoint",
    "https://api.rtbhouse.com/docs/campaigns",
    "Campaigns endpoint",
    "Campaigns endpoint\n\nGET /campaigns returns at most 100 campaigns per page.",
)
DOCUMENTS = [LEAVE, TRIP, API]

PLANTED_PII = ("Jan Kowalski", "jan.kowalski@rtbhouse.com", "+48 601 234 567", "44051401359")


def ref(doc: SynthDoc, snippet: str) -> Ref:
    return Ref(doc.data_store, doc.doc_id, doc.uri, doc.title, snippet)


def turns() -> list[SynthTurn]:
    leave_ref = ref(LEAVE, "Employees have up to 4 days of on-demand leave per year, taken from annual leave.")
    out = [
        # A contradicted claim with references, then a correction: HIGH, flagged, stage 2, session grade.
        SynthTurn(
            "S1",
            60,
            "Hi, I'm Jan Kowalski (jan.kowalski@rtbhouse.com, +48 601 234 567, PESEL 44051401359). "
            "How many days of on-demand leave do I have?",
            "Jan Kowalski, you have 6 days of on-demand leave per year. "
            "[[fake codes=CONTRADICTED_CLAIM severity=HIGH groundedness=1 relevance=5 why=CHUNKING_ISSUE "
            "outcome=RESOLVED first_bad=1 recovered=YES]]",
            refs=[leave_ref],
            spans=[("you have 6 days of on-demand leave per year", [0])],
        ),
        SynthTurn(
            "S1",
            55,
            "That's wrong, it's 4 days. [[fake relation=CORRECTION]]",
            "You are right: up to 4 days of on-demand leave per year.",
        ),
        # A knowledge turn without evidence: the evidence check reads the linked document, which contradicts it.
        SynthTurn(
            "S2",
            30,
            "How do I get a business trip approved?",
            f"Book it in the Travel Tool; all business trips need finance approval. See {TRIP.uri} "
            "[[fake intent=HOW_TO contradiction=1 why=CHUNKING_ISSUE]]",
            principal="user:piotr@rtbhouse.com",
        ),
        # Slack Bolek or MCP: a general task, disliked by the user.
        SynthTurn(
            "S3",
            20,
            "Write a haiku about Mondays",
            "Coffee steams, inbox wakes...[[fake intent=GENERAL_TASK internal=0 why=NONE what=REASONING_ERROR]]",
            channel="api",
            principal="user:ola@rtbhouse.com",
            feedback="DISLIKE",
        ),
        # Too large: never sent to the judge.
        SynthTurn(
            "S4", 40, "Please review: " + "lorem ipsum " * 4300, "Looks fine.", principal="user:marek@rtbhouse.com"
        ),
        # Older than 3h30 and never assessed: missed.
        SynthTurn("S5", 215, "What is the VPN address?", "vpn.example", principal="user:kasia@rtbhouse.com"),
        # Past the anonymizer: invisible.
        SynthTurn("S6", 250, "Old question", "Old answer", erased=True),
        # Not eligible yet.
        SynthTurn(
            "S7",
            2,
            "Where is the office?",
            "In Warsaw. [[fake intent=FACT_LOOKUP]]",
            principal="user:tomek@rtbhouse.com",
        ),
        # The canary: an evaluator question with references.
        SynthTurn(
            "S8",
            50,
            "How many days of on-demand leave are there?",
            "Employees have up to 4 days of on-demand leave per year.",
            channel="canary",
            principal="user:evaluator@rtbhouse.com",
            refs=[leave_ref],
            spans=[("up to 4 days of on-demand leave per year", [0])],
        ),
        # A session resumed after a pause of more than 30 minutes: segment 2, marked resumed.
        SynthTurn(
            "S9",
            150,
            "What is the campaigns page size?",
            "100 campaigns per page.",
            principal="user:ewa@rtbhouse.com",
            refs=[ref(API, "GET /campaigns returns at most 100 campaigns per page.")],
        ),
        SynthTurn(
            "S9",
            100,
            "And how do I get the next page? [[fake relation=FOLLOW_UP]]",
            "Use the page parameter.",
            principal="user:ewa@rtbhouse.com",
        ),
    ]
    # A user too fast to be human: 12 turns in 8 minutes.
    for i in range(12):
        out.append(
            SynthTurn(
                f"BOT{i}",
                80 - i * 0.7,
                f"status check {i}",
                "ok [[fake intent=CHITCHAT]]",
                principal="user:script@rtbhouse.com",
            )
        )
    return out


def canary_question_hash() -> str:
    return hashlib.sha256(b"How many days of on-demand leave are there?").hexdigest()


# Label recall of the judge suite's v2 run (suite-006ae3961f390f5f): every label reliable except REASONING_ERROR.
# NOT_IN_CITED_SOURCES takes RETRIEVAL_MISS's recall until judge v3 has a full run (ticket 09).
SUITE_RECALL = {
    "AGENT_OR_TOOL_ERROR": 1.0,
    "AMBIGUOUS_QUESTION": 1.0,
    "CHUNKING_ISSUE": 1.0,
    "CONFLICTING_SOURCES": 1.0,
    "CONTRADICTED_CLAIM": 1.0,
    "INCOMPLETE_ANSWER": 1.0,
    "MISUNDERSTOOD_QUERY": 1.0,
    "NOT_IN_CITED_SOURCES": 0.93,
    "OUTDATED_SOURCE": 1.0,
    "OUT_OF_SCOPE": 1.0,
    "PRESENTATION_ISSUE": 1.0,
    "REASONING_ERROR": 0.2,
    "UNGROUNDED_INTERNAL_ANSWER": 1.0,
    "UNSUPPORTED_CLAIM": 0.85,
}


def suite_run(day: date) -> dict[str, Any]:
    """A stand-in full suite run of the current judge version, so the demo's labels are reliable as in the v2 run."""
    threshold = get_settings().clusters.reliability_threshold
    return {
        "suite_run_id": "suite-00000000000000de",
        "day": day,
        "suite_version": "demo",
        "judge_version": current().version_id,
        "partial": False,
        "label_recall": [
            {"label": label, "recall": recall, "n": 5, "reliable": recall >= threshold}
            for label, recall in SUITE_RECALL.items()
        ],
        "decision": SuiteDecision.KEEP.value,
    }


# The associates indexer's department map: every family once, OTHER (a base_function in no family) and, for
# evaluator@ and script@, UNKNOWN (left out, as service accounts are). Each family is padded over the privacy floor.
DEPARTMENTS = {
    "anna.test@rtbhouse.com": "IT",  # ENGINEERING
    "piotr@rtbhouse.com": "Technical Support",  # CAMPAIGNS
    "ola@rtbhouse.com": "Sales",  # COMMERCIAL
    "marek@rtbhouse.com": "Finance",  # CORPORATE
    "kasia@rtbhouse.com": "WhitePress",  # OTHER
    "tomek@rtbhouse.com": "Account Management",  # COMMERCIAL
    "ewa@rtbhouse.com": "Traffic",  # CAMPAIGNS
    **{
        f"associate{i:03d}.{n}@rtbhouse.com": base_function
        for n, base_function in enumerate(["IT", "Technical Support", "Sales", "Finance"])
        for i in range(30)
    },
}


def seed(now: datetime) -> None:
    rows = [r for t in turns() for r in turn_rows(t, now)]
    rows.append(search_row("user:anna.test@rtbhouse.com", 60.5, [LEAVE.doc_id, "associate-0123", "unknown_doc"], now))
    rows.append(search_row("user:anna.test@rtbhouse.com", 55.5, [LEAVE.doc_id], now))
    rows.append(search_row("user:evaluator@rtbhouse.com", 50.5, [LEAVE.doc_id], now))
    insert_log(rows)
    store_documents(DOCUMENTS)
    store_department_map(DEPARTMENTS, now)
    write(SUITE_RUNS, [suite_run(now.date())])
    s = get_settings()
    client().insert_rows_json(
        s.table("evals", "results"),
        [
            {
                "run_id": "eval-1",
                "run_kind": "CANARY",
                "engine": s.production_engine,
                "question_sha256": canary_question_hash(),
                "metric": "correctness",
                "score": 1.0,
                "created_at": now.isoformat(),
            }
        ],
    )
