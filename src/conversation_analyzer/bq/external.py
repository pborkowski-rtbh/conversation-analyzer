"""Tables we read but don't own (log, ge_metrics, aiel_evals contract, §12.11); DDL only for emulator copies."""

from __future__ import annotations

from conversation_analyzer.bq.schema import Col, Table


def raw(name: str, type_: str, mode: str = "NULLABLE") -> Col:
    return Col(name, type_, "raw", mode)


# Gemini Enterprise activity log export, as defined in aiel-infrastructure/modules/agentspace-bigquery.
AUDIT_LOGS = Table(
    "log",
    "audit_logs",
    (
        raw("timestamp", "TIMESTAMP"),
        raw("methodName", "STRING"),
        raw("serviceAttributionToken", "STRING"),
        raw("assistToken", "STRING"),
        raw("request", "JSON"),
        raw("response", "JSON"),
        raw("userIamPrincipal", "STRING"),
        raw("userQuery", "STRING"),
        raw("serviceTextReply", "STRING"),
        raw("serviceLabel", "STRING"),
        raw("serviceName", "STRING"),
    ),
    key=(),
    writer="google",
)

GE_METRICS = Table(
    "log",
    "ge_metrics",
    (
        raw("project_number", "INT64"),
        raw("engine_id", "STRING"),
        raw("date", "STRING"),
        raw("data_source", "STRING"),
        raw("product_type", "STRING"),
        raw("search_count", "FLOAT64"),
        raw("answer_count", "FLOAT64"),
        raw("feedback_like_count", "FLOAT64"),
        raw("feedback_dislike_count", "FLOAT64"),
        raw("daily_active_user_count", "FLOAT64"),
        raw("weekly_active_user_count", "FLOAT64"),
        raw("monthly_active_user_count", "FLOAT64"),
        raw("user_retention_ratio_for7d", "FLOAT64"),
    ),
    key=(),
    writer="google",
)

# What we expect from the evaluator (AIENGLAB-519): one row per run, question and metric, with the question's hash,
# and gate results that name the change they test. Without our own search, the expected document is not needed.
EVAL_RESULTS = Table(
    "evals",
    "results",
    (
        raw("run_id", "STRING"),
        raw("run_kind", "STRING"),  # CANARY, GATE, ANCHOR, FOCUS
        raw("engine", "STRING"),
        raw("change_id", "STRING"),
        raw("variant", "STRING"),  # CURRENT, CANDIDATE
        raw("repeat", "INT64"),
        raw("question_set", "STRING"),
        raw("question_sha256", "STRING"),
        raw("cluster_id", "STRING"),
        raw("metric", "STRING"),
        raw("score", "FLOAT64"),
        raw("error_class", "STRING"),
        raw("created_at", "TIMESTAMP"),
    ),
    key=(),
    writer="evaluator",
)

EVAL_GATE_RESULTS = Table(
    "evals",
    "gate_results",
    (
        raw("run_id", "STRING"),
        raw("change_id", "STRING"),
        raw("verdict", "STRING"),  # PASS, FAIL
        raw("anchor_delta", "FLOAT64"),
        raw("anchor_noise", "FLOAT64"),
        raw("focus_delta", "FLOAT64"),
        raw("focus_noise", "FLOAT64"),
        raw("clusters", "STRING", "REPEATED"),
        raw("created_at", "TIMESTAMP"),
    ),
    key=(),
    writer="evaluator",
)

EXTERNAL_TABLES = (AUDIT_LOGS, GE_METRICS, EVAL_RESULTS, EVAL_GATE_RESULTS)
