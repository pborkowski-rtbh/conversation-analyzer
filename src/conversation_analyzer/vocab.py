"""Closed lists: every label this system stores comes from here; the version is a hash of their content (§6.11)."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from functools import lru_cache

from conversation_analyzer.settings import get_settings


class Channel(StrEnum):
    WEB_UI = "WEB_UI"
    SLACK_MCP = "SLACK_MCP"  # Slack Bolek and MCP, reported together until the log tells them apart (§8.9)


class Intent(StrEnum):
    FACT_LOOKUP = "FACT_LOOKUP"
    HOW_TO = "HOW_TO"
    TROUBLESHOOTING = "TROUBLESHOOTING"
    PEOPLE_LOOKUP = "PEOPLE_LOOKUP"
    DATA_QUESTION = "DATA_QUESTION"
    GENERAL_TASK = "GENERAL_TASK"
    CHITCHAT = "CHITCHAT"
    OTHER = "OTHER"


KNOWLEDGE_INTENTS = frozenset({Intent.FACT_LOOKUP, Intent.HOW_TO, Intent.TROUBLESHOOTING, Intent.DATA_QUESTION})


class Relation(StrEnum):
    FIRST = "FIRST"
    FOLLOW_UP = "FOLLOW_UP"
    REPHRASE = "REPHRASE"
    CORRECTION = "CORRECTION"
    FRUSTRATION = "FRUSTRATION"
    NEW_TOPIC = "NEW_TOPIC"


NEGATIVE_REACTIONS = frozenset({Relation.REPHRASE, Relation.CORRECTION, Relation.FRUSTRATION})
LATE_TRIGGER_RELATIONS = frozenset({Relation.REPHRASE, Relation.CORRECTION})
CONTINUED_RELATIONS = frozenset({Relation.FOLLOW_UP, Relation.REPHRASE, Relation.CORRECTION, Relation.FRUSTRATION})


class Family(StrEnum):
    RETRIEVAL = "RETRIEVAL"
    CORPUS = "CORPUS"
    GENERATION = "GENERATION"
    QUESTION = "QUESTION"
    SYSTEM = "SYSTEM"


class Owner(StrEnum):
    TEAM = "TEAM"
    DOCUMENT_OWNER = "DOCUMENT_OWNER"
    CORPUS_OWNER = "CORPUS_OWNER"


class FailureCode(StrEnum):
    RETRIEVAL_MISS = "RETRIEVAL_MISS"
    CHUNKING_ISSUE = "CHUNKING_ISSUE"
    KNOWLEDGE_GAP = "KNOWLEDGE_GAP"
    OUTDATED_SOURCE = "OUTDATED_SOURCE"
    CONFLICTING_SOURCES = "CONFLICTING_SOURCES"
    CONTRADICTED_CLAIM = "CONTRADICTED_CLAIM"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    REASONING_ERROR = "REASONING_ERROR"
    INCOMPLETE_ANSWER = "INCOMPLETE_ANSWER"
    MISUNDERSTOOD_QUERY = "MISUNDERSTOOD_QUERY"
    PRESENTATION_ISSUE = "PRESENTATION_ISSUE"
    UNGROUNDED_INTERNAL_ANSWER = "UNGROUNDED_INTERNAL_ANSWER"
    AMBIGUOUS_QUESTION = "AMBIGUOUS_QUESTION"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    AGENT_OR_TOOL_ERROR = "AGENT_OR_TOOL_ERROR"
    NONE = "NONE"


F = FailureCode
FAMILY = {
    F.RETRIEVAL_MISS: Family.RETRIEVAL,
    F.CHUNKING_ISSUE: Family.RETRIEVAL,
    F.KNOWLEDGE_GAP: Family.CORPUS,
    F.OUTDATED_SOURCE: Family.CORPUS,
    F.CONFLICTING_SOURCES: Family.CORPUS,
    F.CONTRADICTED_CLAIM: Family.GENERATION,
    F.UNSUPPORTED_CLAIM: Family.GENERATION,
    F.REASONING_ERROR: Family.GENERATION,
    F.INCOMPLETE_ANSWER: Family.GENERATION,
    F.MISUNDERSTOOD_QUERY: Family.GENERATION,
    F.PRESENTATION_ISSUE: Family.GENERATION,
    F.UNGROUNDED_INTERNAL_ANSWER: Family.GENERATION,
    F.AMBIGUOUS_QUESTION: Family.QUESTION,
    F.OUT_OF_SCOPE: Family.QUESTION,
    F.AGENT_OR_TOOL_ERROR: Family.SYSTEM,
}

# Who fixes it (§6.7, §9.1)
OWNER = {
    F.KNOWLEDGE_GAP: Owner.CORPUS_OWNER,
    F.OUTDATED_SOURCE: Owner.DOCUMENT_OWNER,
    F.CONFLICTING_SOURCES: Owner.DOCUMENT_OWNER,
}


def owner_of(code: FailureCode) -> Owner:
    return OWNER.get(code, Owner.TEAM)


# Codes stage 1 may assign (§6.7): generation except REASONING_ERROR, question and system codes.
STAGE1_CODES = frozenset(
    {
        F.CONTRADICTED_CLAIM,
        F.UNSUPPORTED_CLAIM,
        F.INCOMPLETE_ANSWER,
        F.MISUNDERSTOOD_QUERY,
        F.PRESENTATION_ISSUE,
        F.UNGROUNDED_INTERNAL_ANSWER,
        F.AMBIGUOUS_QUESTION,
        F.OUT_OF_SCOPE,
        F.AGENT_OR_TOOL_ERROR,
    }
)
DETERMINISTIC_CODES = frozenset({F.UNGROUNDED_INTERNAL_ANSWER, F.AGENT_OR_TOOL_ERROR})
SOURCE_CODES = frozenset({F.CONTRADICTED_CLAIM, F.UNSUPPORTED_CLAIM, F.REASONING_ERROR, F.UNGROUNDED_INTERNAL_ANSWER})
CAUSE_CODES = frozenset({F.OUTDATED_SOURCE, F.CONFLICTING_SOURCES, F.CHUNKING_ISSUE, F.RETRIEVAL_MISS, F.KNOWLEDGE_GAP})
CLAIM_WHAT_CODES = frozenset({F.CONTRADICTED_CLAIM, F.UNSUPPORTED_CLAIM, F.REASONING_ERROR})

# Primary failure order of stage 1 (§6.8)
STAGE1_PRIMARY_ORDER = (
    F.AGENT_OR_TOOL_ERROR,
    F.CONTRADICTED_CLAIM,
    F.UNSUPPORTED_CLAIM,
    F.UNGROUNDED_INTERNAL_ANSWER,
    F.MISUNDERSTOOD_QUERY,
    F.INCOMPLETE_ANSWER,
    F.AMBIGUOUS_QUESTION,
    F.OUT_OF_SCOPE,
    F.PRESENTATION_ISSUE,
)


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TopicSource(StrEnum):
    REFERENCES = "REFERENCES"
    JUDGE = "JUDGE"


class EvidenceKind(StrEnum):
    OWN_REFERENCES = "OWN_REFERENCES"
    EARLIER_REFERENCES = "EARLIER_REFERENCES"
    NONE = "NONE"


class TurnStatus(StrEnum):
    ASSESSED = "ASSESSED"
    TOO_LARGE = "TOO_LARGE"
    MISSED = "MISSED"
    FAILED = "FAILED"


class Stage2State(StrEnum):
    NOT_FLAGGED = "NOT_FLAGGED"
    PENDING = "PENDING"
    DONE = "DONE"
    GAVE_UP = "GAVE_UP"
    FAILED = "FAILED"


class FlagReason(StrEnum):
    LOW_RELEVANCE = "LOW_RELEVANCE"
    LOW_GROUNDEDNESS = "LOW_GROUNDEDNESS"
    HIGH_SEVERITY = "HIGH_SEVERITY"
    DISLIKE = "DISLIKE"
    NEXT_REPHRASE = "NEXT_REPHRASE"
    NEXT_CORRECTION = "NEXT_CORRECTION"


class ClaimWhy(StrEnum):
    OUTDATED_SOURCE = "OUTDATED_SOURCE"
    CONFLICTING_SOURCES = "CONFLICTING_SOURCES"
    CHUNKING_ISSUE = "CHUNKING_ISSUE"
    RETRIEVAL_MISS = "RETRIEVAL_MISS"
    KNOWLEDGE_GAP = "KNOWLEDGE_GAP"
    NONE = "NONE"  # the snippets hold the right facts and the answer misread them


class DocRole(StrEnum):
    CITED = "CITED"
    HOLDS_RIGHT_ANSWER = "HOLDS_RIGHT_ANSWER"
    CONTRADICTS_CLAIM = "CONTRADICTS_CLAIM"
    OUTDATED = "OUTDATED"
    CONFLICTING = "CONFLICTING"


class FindingVerdict(StrEnum):
    CONFIRMED = "CONFIRMED"
    DROPPED = "DROPPED"


class Outcome(StrEnum):
    RESOLVED = "RESOLVED"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    UNCLEAR = "UNCLEAR"


class GradeState(StrEnum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    NOT_GRADABLE = "NOT_GRADABLE"


class Recovered(StrEnum):
    YES = "YES"
    NO = "NO"
    NO_CORRECTION = "NO_CORRECTION"


class CountBucket(StrEnum):
    ZERO = "0"
    ONE = "1"
    TWO_OR_MORE = "2_OR_MORE"


class SegmentState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CloseReason(StrEnum):
    IDLE = "IDLE"
    FORCED = "FORCED"


class GapBucket(StrEnum):
    UNDER_1_MIN = "UNDER_1_MIN"
    MIN_1_5 = "1_5_MIN"
    MIN_5_30 = "5_30_MIN"
    MIN_30_60 = "30_60_MIN"
    OVER_60_MIN = "OVER_60_MIN"


class DurationBucket(StrEnum):
    UNDER_1_MIN = "UNDER_1_MIN"
    MIN_1_5 = "1_5_MIN"
    MIN_5_30 = "5_30_MIN"
    MIN_30_60 = "30_60_MIN"
    H_1_2 = "1_2_H"
    OVER_2_H = "OVER_2_H"


def gap_bucket(minutes: float) -> GapBucket:
    if minutes < 1:
        return GapBucket.UNDER_1_MIN
    if minutes < 5:
        return GapBucket.MIN_1_5
    if minutes < 30:
        return GapBucket.MIN_5_30
    if minutes < 60:
        return GapBucket.MIN_30_60
    return GapBucket.OVER_60_MIN


def duration_bucket(minutes: float) -> DurationBucket:
    for limit, bucket in (
        (1, DurationBucket.UNDER_1_MIN),
        (5, DurationBucket.MIN_1_5),
        (30, DurationBucket.MIN_5_30),
        (60, DurationBucket.MIN_30_60),
        (120, DurationBucket.H_1_2),
    ):
        if minutes < limit:
            return bucket
    return DurationBucket.OVER_2_H


def count_bucket(n: int) -> CountBucket:
    return CountBucket.ZERO if n == 0 else CountBucket.ONE if n == 1 else CountBucket.TWO_OR_MORE


class Thumbs(StrEnum):
    UP = "UP"
    DOWN = "DOWN"


class FeedbackReason(StrEnum):
    """Reason codes of Google's closed list; anything not on it is stored as UNRECOGNIZED, never as text."""

    INACCURATE = "INACCURATE"
    NOT_RELEVANT = "NOT_RELEVANT"
    NOT_HELPFUL = "NOT_HELPFUL"
    INCOMPLETE = "INCOMPLETE"
    OUTDATED = "OUTDATED"
    BAD_CITATION = "BAD_CITATION"
    HARMFUL_OR_UNSAFE = "HARMFUL_OR_UNSAFE"
    OTHER = "OTHER"
    UNRECOGNIZED = "UNRECOGNIZED"


class ErrorClass(StrEnum):
    LEAK_GUARD = "LEAK_GUARD"
    JUDGE_INVALID_OUTPUT = "JUDGE_INVALID_OUTPUT"
    JUDGE_API = "JUDGE_API"
    JUDGE_THROTTLED = "JUDGE_THROTTLED"
    EMBEDDING_API = "EMBEDDING_API"
    CONTENT_MISSING = "CONTENT_MISSING"
    CONTENT_DECRYPT = "CONTENT_DECRYPT"
    BIGQUERY = "BIGQUERY"
    SLACK = "SLACK"
    GITHUB = "GITHUB"
    CLOUD_RUN = "CLOUD_RUN"
    TIMEOUT = "TIMEOUT"
    TOKEN_LIMIT = "TOKEN_LIMIT"
    UNEXPECTED = "UNEXPECTED"


class PlantedError(StrEnum):
    NONE = "NONE"
    SWAPPED_NUMBER = "SWAPPED_NUMBER"
    DROPPED_STEP = "DROPPED_STEP"
    WRONG_NAME = "WRONG_NAME"


class AlertKind(StrEnum):
    HIGH_CLUSTER = "HIGH_CLUSTER"
    PIPELINE_HEALTH = "PIPELINE_HEALTH"
    ANOMALY = "ANOMALY"


class HealthCheck(StrEnum):
    COVERAGE = "COVERAGE"
    WAITING_TOO_LONG = "WAITING_TOO_LONG"
    NO_RUN = "NO_RUN"
    RUN_FAILED = "RUN_FAILED"
    LOG_GAP = "LOG_GAP"
    WINDOW_SHORT = "WINDOW_SHORT"
    TOKEN_LIMIT = "TOKEN_LIMIT"


class AnomalyKind(StrEnum):
    JUMP = "JUMP"
    DRIFT = "DRIFT"


class AnomalyState(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class ChangeSource(StrEnum):
    LOG = "LOG"
    GITHUB = "GITHUB"
    INDEXER = "INDEXER"
    JUDGE = "JUDGE"
    MANUAL = "MANUAL"


class ChangeKind(StrEnum):
    PROMPT = "PROMPT"
    DATA_STORE = "DATA_STORE"
    DOCUMENT = "DOCUMENT"
    MODEL = "MODEL"
    ENGINE = "ENGINE"
    AGENT = "AGENT"
    CONNECTOR = "CONNECTOR"
    INDEXER = "INDEXER"
    JUDGE = "JUDGE"
    PARALLEL_RUN_END = "PARALLEL_RUN_END"
    AQR_REBASE = "AQR_REBASE"


class ReleaseVerdict(StrEnum):
    IMPROVED = "IMPROVED"
    REGRESSED = "REGRESSED"
    NO_DETECTABLE_CHANGE = "NO_DETECTABLE_CHANGE"
    CONFOUNDED = "CONFOUNDED"
    WAITING = "WAITING"


class GateVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class ClusterState(StrEnum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class EvalSet(StrEnum):
    ANCHOR = "ANCHOR"
    FOCUS = "FOCUS"


class DayKind(StrEnum):
    WEEKDAY = "WEEKDAY"
    WEEKEND = "WEEKEND"


class RunStatus(StrEnum):
    OK = "OK"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class HealthKind(StrEnum):
    RUN = "RUN"
    LOG_HOUR = "LOG_HOUR"


class SliceKind(StrEnum):
    ALL = "ALL"
    INTENT = "INTENT"
    TOPIC = "TOPIC"
    DATA_STORE = "DATA_STORE"
    STRATUM = "STRATUM"
    INTENT_FAMILY = "INTENT_FAMILY"
    DATA_STORE_FAMILY = "DATA_STORE_FAMILY"


ALL = "ALL"  # slice value and channel value of "everything together"
MERGED_OTHER = "MERGED_OTHER"  # where small slices without a family go (§8.5)


class FormField(StrEnum):
    INTENT = "INTENT"
    TOPIC = "TOPIC"
    RELATION = "RELATION"
    RELEVANCE = "RELEVANCE"
    COMPLETENESS = "COMPLETENESS"
    CLARITY = "CLARITY"
    GROUNDEDNESS = "GROUNDEDNESS"
    SPAN_COUNTS = "SPAN_COUNTS"
    LANGUAGE_MATCHES = "LANGUAGE_MATCHES"
    REFUSAL_OR_EMPTY = "REFUSAL_OR_EMPTY"
    CONTRADICTS_EARLIER = "CONTRADICTS_EARLIER"
    NEEDS_INTERNAL_KNOWLEDGE = "NEEDS_INTERNAL_KNOWLEDGE"
    FAILURE_TYPES = "FAILURE_TYPES"
    PRIMARY_FAILURE = "PRIMARY_FAILURE"
    SEVERITY = "SEVERITY"
    FILLED_FIELDS = "FILLED_FIELDS"
    EVIDENCE_CHECK = "EVIDENCE_CHECK"
    STAGE2_CAUSE = "STAGE2_CAUSE"
    DOCUMENT_TO_FIX = "DOCUMENT_TO_FIX"
    SESSION_OUTCOME = "SESSION_OUTCOME"
    FIRST_BAD_TURN = "FIRST_BAD_TURN"
    RECOVERED = "RECOVERED"
    ALL = "ALL"


class JudgeMeasure(StrEnum):
    CANARY_AGREEMENT = "CANARY_AGREEMENT"
    PLANTED_CAUGHT = "PLANTED_CAUGHT"
    PLANTED_FALSE_HIGH = "PLANTED_FALSE_HIGH"
    INDEX_HIT_RATE = "INDEX_HIT_RATE"
    KNOWLEDGE_GAP_MISS_RATE = "KNOWLEDGE_GAP_MISS_RATE"
    SECOND_MODEL_DISAGREEMENT = "SECOND_MODEL_DISAGREEMENT"
    DISLIKED_AQR = "DISLIKED_AQR"
    NOT_DISLIKED_AQR = "NOT_DISLIKED_AQR"
    STAGE2_CHANGE_RATE = "STAGE2_CHANGE_RATE"
    STAGE2_DROP_RATE = "STAGE2_DROP_RATE"


class SuitePart(StrEnum):
    TUNING = "TUNING"
    HELD_OUT = "HELD_OUT"
    ALL = "ALL"


class SuiteDecision(StrEnum):
    BASELINE = "BASELINE"
    KEEP = "KEEP"
    REJECT = "REJECT"


_BASE_METRICS = [
    "AQR_STANDARDIZED",
    "AQR_RAW",
    "NOT_VERIFIABLE_SHARE",
    "EVIDENCE_OWN_SHARE",
    "EVIDENCE_EARLIER_SHARE",
    "EVIDENCE_NONE_SHARE",
    "CONTRADICTED_COUNT",
    "CONTRADICTED_SHARE",
    "UNSUPPORTED_SHARE",
    "NEGATIVE_REACTION_RATE",
    "DISLIKE_COUNT",
    "DISLIKE_RATE",
    "VOLUME",
    "ACTIVE_USERS",
    "RETENTION_7D",
    "COVERAGE",
    "TOO_LARGE_SHARE",
    "MISSED_COUNT",
    "OLDEST_WAITING_MINUTES",
    "LOG_GAP_HOURS",
    "RESUMED_WITHOUT_TEXT",
    "RESUMED_AND_CONTINUED",
    "PACE_EXCLUDED_COUNT",
    "FLAGGED_SHARE",  # flagged turns of the day over assessed turns: the stage 2 load (milestone 3)
]
FAILURE_RATE_CODES = [c for c in FailureCode if c is not FailureCode.NONE]
Metric = StrEnum("Metric", {m: m for m in _BASE_METRICS + [f"FAILURE_RATE_{c.value}" for c in FAILURE_RATE_CODES]})


def failure_rate_metric(code: FailureCode) -> str:
    return f"FAILURE_RATE_{code.value}"


# The series the anomaly check watches (§8.7): standardized AQR, each failure rate, negative reactions, coverage.
ANOMALY_METRICS = [
    "AQR_STANDARDIZED",
    *[failure_rate_metric(c) for c in FAILURE_RATE_CODES],
    "NEGATIVE_REACTION_RATE",
    "COVERAGE",
]


def stratum_code(intent_family: str, data_store_family: str) -> str:
    return f"{intent_family}__{data_store_family}"


def strata_codes() -> list[str]:
    s = get_settings().strata
    return [stratum_code(i, d) for i in s.intent_families for d in s.data_store_families]


def topics() -> list[str]:
    """One topic per data store, plus OTHER (§2.2)."""
    return sorted({ds.topic for ds in get_settings().data_stores}) + ["OTHER"]


@lru_cache(maxsize=1)
def closed_lists_version() -> str:
    payload = {
        "failure_codes": [c.value for c in FailureCode],
        "families": {c.value: f.value for c, f in FAMILY.items()},
        "topics": topics(),
        "intents": [i.value for i in Intent],
        "relations": [r.value for r in Relation],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]
    return f"cl-{digest}"


@lru_cache(maxsize=1)
def all_closed_values() -> frozenset[str]:
    """Every value of every closed list; the leak guard accepts these strings."""
    s = get_settings().strata
    values: set[str] = set(topics()) | set(strata_codes()) | set(s.intent_families) | set(s.data_store_families)
    values |= {ALL, MERGED_OTHER}
    values |= {d.id for d in get_settings().data_stores}  # the allowlisted data stores, a slice of the metrics
    for enum in (
        Channel,
        Intent,
        Relation,
        Family,
        Owner,
        FailureCode,
        Severity,
        TopicSource,
        EvidenceKind,
        TurnStatus,
        Stage2State,
        FlagReason,
        ClaimWhy,
        DocRole,
        FindingVerdict,
        Outcome,
        GradeState,
        Recovered,
        CountBucket,
        SegmentState,
        CloseReason,
        GapBucket,
        DurationBucket,
        Thumbs,
        FeedbackReason,
        ErrorClass,
        PlantedError,
        AlertKind,
        HealthCheck,
        AnomalyKind,
        AnomalyState,
        ChangeSource,
        ChangeKind,
        ReleaseVerdict,
        GateVerdict,
        ClusterState,
        EvalSet,
        DayKind,
        RunStatus,
        HealthKind,
        SliceKind,
        FormField,
        JudgeMeasure,
        SuitePart,
        SuiteDecision,
        Metric,
    ):
        values.update(m.value for m in enum)
    return frozenset(values)
