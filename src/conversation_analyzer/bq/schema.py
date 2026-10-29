"""Every table of §12.10, defined once: the DDL and the leak guard's per-field rules both come from here."""

from __future__ import annotations

from dataclasses import dataclass, field

from conversation_analyzer.settings import get_settings


@dataclass(frozen=True)
class Col:
    name: str
    type: str  # BigQuery type: STRING, INT64, FLOAT64, BOOL, DATE, TIMESTAMP, JSON, STRUCT
    kind: str  # leak-guard kind, see leak_guard.py
    mode: str = "NULLABLE"
    fields: tuple[Col, ...] = ()

    def ddl(self) -> str:
        if self.type == "STRUCT":
            inner = ", ".join(f.ddl() for f in self.fields)
            base = f"STRUCT<{inner}>"
        else:
            base = self.type
        if self.mode == "REPEATED":
            base = f"ARRAY<{base}>"
        return f"{self.name} {base}"


@dataclass(frozen=True)
class Table:
    dataset: str  # key of Settings.datasets
    name: str
    cols: tuple[Col, ...]
    key: tuple[str, ...]
    writer: str
    partition: str | None = None
    expiration_days: int | None = None
    additive: tuple[str, ...] = field(default=())  # columns a MERGE adds up instead of replacing

    def col(self, name: str) -> Col:
        return next(c for c in self.cols if c.name == name)


def c(name: str, type_: str, kind: str) -> Col:
    return Col(name, type_, kind)


def enum(name: str) -> Col:
    return Col(name, "STRING", "enum")


def enums(name: str) -> Col:
    return Col(name, "STRING", "enum", "REPEATED")


def i(name: str) -> Col:
    return Col(name, "INT64", "int")


def f(name: str) -> Col:
    return Col(name, "FLOAT64", "float")


def b(name: str) -> Col:
    return Col(name, "BOOL", "bool")


def d(name: str) -> Col:
    return Col(name, "DATE", "date")


def ts(name: str) -> Col:
    return Col(name, "TIMESTAMP", "ts")


def h(name: str) -> Col:
    return Col(name, "STRING", "hash")


def ident(name: str) -> Col:
    return Col(name, "STRING", "id")


def ver(name: str) -> Col:
    return Col(name, "STRING", "version")


def struct(name: str, *fields: Col, repeated: bool = False) -> Col:
    return Col(name, "STRUCT", "struct", "REPEATED" if repeated else "NULLABLE", fields)


DOC_FIELDS = (
    Col("doc_id", "STRING", "doc_id"),
    Col("data_store", "STRING", "data_store"),
    Col("uri", "STRING", "link"),
)


def doc(name: str) -> Col:
    return Col(name, "STRUCT", "doc", "NULLABLE", DOC_FIELDS)


def docs(name: str) -> Col:
    return Col(name, "STRUCT", "doc", "REPEATED", DOC_FIELDS)


VERSIONS = (
    ver("judge_version"),
    ver("rubric_version"),
    ver("closed_lists_version"),
    ver("judge_model"),
    ver("prompt_version"),
    ver("code_version"),
)
TOKENS = struct("tokens", ver("model"), i("input_tokens"), i("output_tokens"), repeated=True)
PER_TURN_DAYS = 365

# ---------------------------------------------------------------- bolek_quality_turns (assessor + monitor)

QUALITY_TURNS = Table(
    "turns",
    "quality_turns",
    (
        h("turn_key"),
        h("session_key"),
        i("segment_no"),
        i("position_in_segment"),
        i("position_in_session"),
        d("day"),
        enum("channel"),
        b("is_canary"),
        b("pace_excluded"),
        enum("gap_bucket"),
        b("resumed"),
        b("earlier_text_missing"),
        enum("status"),
        enum("error_class"),
        enum("evidence_kind"),
        Col("data_stores", "STRING", "data_store", "REPEATED"),
        docs("cited_docs"),
        docs("found_docs"),
        b("flagged"),
        enums("flag_reasons"),
        enum("stage2_state"),
        enum("feedback_thumbs"),
        enums("feedback_reasons"),
        enum("reaction"),
        b("second_model_checked"),
        h("fingerprint"),
        ver("judge_version"),
    ),
    key=("turn_key",),
    writer="assessor",
    partition="day",
    expiration_days=PER_TURN_DAYS,
)

STAGE1_RESULTS = Table(
    "turns",
    "quality_stage1_results",
    (
        h("turn_key"),
        d("day"),
        h("fingerprint"),
        *VERSIONS,
        enum("intent"),
        enum("topic"),
        enum("topic_source"),
        enum("relation"),
        i("relevance"),
        i("completeness"),
        i("clarity"),
        i("groundedness"),
        i("unsupported_spans"),
        i("total_spans"),
        b("language_matches"),
        b("refusal_or_empty"),
        b("contradicts_earlier"),
        b("needs_internal_knowledge"),
        enums("failure_types"),
        enum("primary_failure"),
        enum("severity"),
        f("confidence"),
        b("knowledge_turn"),
        b("verifiable"),
        enum("evidence_kind"),
        b("evidence_check_ran"),
        b("evidence_check_contradiction"),
    ),
    key=("turn_key", "judge_version"),
    writer="assessor",
    partition="day",
    expiration_days=PER_TURN_DAYS,
)

CLAIM_DOC = Col("documents", "STRUCT", "doc", "REPEATED", (*DOC_FIELDS, enum("role")))
STAGE2_RESULTS = Table(
    "turns",
    "quality_stage2_results",
    (
        h("turn_key"),
        d("day"),
        h("fingerprint"),
        *VERSIONS,
        struct("claims", i("position"), i("span_index"), enum("what"), enum("why"), CLAIM_DOC, repeated=True),
        i("groundedness"),
        enums("failure_types"),
        enum("primary_failure"),
        enum("severity"),
        struct("stage1_findings", enum("code"), enum("verdict"), repeated=True),
        doc("document_to_fix"),
        f("confidence"),
        i("searched_phrasings"),
    ),
    key=("turn_key", "judge_version"),
    writer="assessor",
    partition="day",
    expiration_days=PER_TURN_DAYS,
)

SEGMENTS = Table(
    "turns",
    "quality_segments",
    (
        h("session_key"),
        i("segment_no"),
        d("first_day"),
        d("last_day"),
        enum("state"),
        enum("close_reason"),
        b("forced_closed"),
        b("resumed"),
        enum("previous_close_reason"),
        b("earlier_text_missing"),
        i("first_position_in_session"),
        i("n_turns"),
        i("n_rephrases"),
        i("n_corrections"),
        i("n_frustrations"),
        enum("duration_bucket"),
        enum("first_turn_relation"),
    ),
    key=("session_key", "segment_no"),
    writer="assessor",
    partition="first_day",
    expiration_days=PER_TURN_DAYS,
)

SESSION_GRADES = Table(
    "turns",
    "quality_session_grades",
    (
        h("session_key"),
        i("segment_no"),
        d("day"),
        enum("grade_state"),
        enum("outcome"),
        i("first_bad_turn"),
        enum("rephrases_corrections"),
        enum("recovered"),
        f("confidence"),
        ver("judge_version"),
        ver("judge_model"),
        i("graded_turns"),
    ),
    key=("session_key", "segment_no"),
    writer="assessor",
    partition="day",
    expiration_days=PER_TURN_DAYS,
)

CANARY_RESULTS = Table(
    "turns",
    "quality_canary_results",
    (
        h("turn_key"),
        enum("planted_error"),
        b("with_references"),
        ver("judge_version"),
        d("day"),
        h("question_hash"),
        Col("expected_doc_id", "STRING", "doc_id"),
        Col("expected_data_store", "STRING", "data_store"),
        enum("intent"),
        i("relevance"),
        i("completeness"),
        i("clarity"),
        i("groundedness"),
        enums("failure_types"),
        enum("primary_failure"),
        enum("severity"),
        b("evidence_check_contradiction"),
        enum("stage2_primary_failure"),
        b("caught"),
        b("false_high"),
        b("index_found_expected"),
        i("index_rank"),
    ),
    key=("turn_key", "planted_error", "with_references", "judge_version"),
    writer="assessor",
    partition="day",
    expiration_days=PER_TURN_DAYS,
)

JUDGE_CHECKS = Table(
    "turns",
    "quality_judge_checks",
    (
        d("day"),
        enum("field"),
        i("n_compared"),
        i("n_disagreements"),
    ),
    key=("day", "field"),
    writer="assessor",
    partition="day",
    expiration_days=PER_TURN_DAYS,
    additive=("n_compared", "n_disagreements"),
)

RETRIEVAL_COUNTS = Table(
    "turns",
    "quality_retrieval_counts",
    (
        d("day"),
        Col("doc_id", "STRING", "doc_id"),
        Col("data_store", "STRING", "data_store"),
        i("n_returned"),
    ),
    key=("day", "doc_id", "data_store"),
    writer="assessor",
    partition="day",
    expiration_days=PER_TURN_DAYS,
    additive=("n_returned",),
)

JUDGE_VERSIONS = Table(
    "turns",
    "quality_judge_versions",
    (
        ver("judge_version"),
        ver("rubric_version"),
        ver("prompt_version"),
        ver("form_version"),
        ver("stage1_model"),
        ver("stage2_model"),
        ver("closed_lists_version"),
        d("first_used_day"),
        ver("previous_version"),
        d("parallel_run_until"),
    ),
    key=("judge_version",),
    writer="assessor",
)

RUNS = Table(
    "turns",
    "quality_runs",
    (
        ident("run_id"),
        d("run_day"),
        ts("started_at"),
        ts("finished_at"),
        enum("status"),
        enum("error_class"),
        i("turns_read"),
        i("eligible"),
        i("covered"),
        i("assessed"),
        i("too_large"),
        i("missed"),
        i("failed"),
        struct("failed_by_class", enum("error_class"), i("n"), repeated=True),
        i("canary_assessed"),
        i("pace_marked"),
        i("evidence_checks"),
        i("stage2_done"),
        i("stage2_pending"),
        i("stage2_gave_up"),
        i("session_grades"),
        i("second_model_checks"),
        i("feedback_matched"),
        i("feedback_after_window"),
        i("retrieval_rows"),
        f("oldest_waiting_minutes"),
        f("window_margin_minutes"),
        i("throttled_calls"),
        TOKENS,
        Col("judge_versions", "STRING", "version", "REPEATED"),
        ts("search_cutoff"),
        ts("feedback_cutoff"),
    ),
    key=("run_id",),
    writer="assessor",
    partition="run_day",
    expiration_days=PER_TURN_DAYS,
)

ALERTS = Table(
    "turns",
    "quality_alerts",
    (
        ident("alert_id"),
        enum("kind"),
        d("day"),
        i("hour"),
        Col("slack_channel", "STRING", "slack_channel"),
        Col("slack_ts", "STRING", "slack_ts"),
        enum("check"),
        enum("channel"),
        enum("primary_failure"),
        Col("data_store", "STRING", "data_store"),
        Col("doc_id", "STRING", "doc_id"),
        Col("uri", "STRING", "link"),
        enum("topic"),
        i("n_turns"),
        ident("run_id"),
        f("value"),
    ),
    key=("alert_id",),
    writer="monitor",
    partition="day",
    expiration_days=PER_TURN_DAYS,
)

ALERT_SESSIONS = Table(
    "turns",
    "quality_alert_sessions",
    (
        ident("alert_id"),
        h("session_key"),
        i("segment_no"),
        d("day"),
        enum("grade_state_shown"),
        enum("outcome_shown"),
    ),
    key=("alert_id", "session_key", "segment_no"),
    writer="monitor",
    partition="day",
    expiration_days=PER_TURN_DAYS,
)

# ---------------------------------------------------------------- bolek_quality_metrics (reporting jobs)

METRICS_DAILY = Table(
    "metrics",
    "quality_metrics_daily",
    (
        d("day"),
        enum("day_kind"),
        enum("channel"),
        enum("metric"),
        enum("slice_kind"),
        enum("slice_value"),
        f("value"),
        f("numerator"),
        f("denominator"),
        i("n_turns"),
        b("incomplete"),
        b("merged"),
        ver("judge_version"),
    ),
    key=("day", "channel", "metric", "slice_kind", "slice_value"),
    writer="daily",
    partition="day",
)

ANOMALIES = Table(
    "metrics",
    "quality_anomalies",
    (
        ident("anomaly_id"),
        enum("metric"),
        enum("channel"),
        enum("kind"),
        d("day"),
        d("opened_day"),
        f("value"),
        f("reference_value"),
        f("noise"),
        f("band_low"),
        f("band_high"),
        f("cusum"),
        enum("state"),
        Col("change_events", "STRING", "id", "REPEATED"),
        b("explained"),
        ident("alert_id"),
        Col("slack_channel", "STRING", "slack_channel"),
        Col("slack_ts", "STRING", "slack_ts"),
        d("acknowledged_day"),
    ),
    key=("anomaly_id",),
    writer="daily",
)

ACKNOWLEDGEMENTS = Table(
    "metrics",
    "quality_acknowledgements",
    (
        ident("anomaly_id"),
        Col("acknowledged_by", "STRING", "slack_user"),
        d("ack_day"),
        i("ack_hour"),
        b("replied"),
    ),
    key=("anomaly_id",),
    writer="monitor",
)

PIPELINE_HEALTH = Table(
    "metrics",
    "quality_pipeline_health",
    (
        d("day"),
        enum("kind"),
        ident("run_id"),
        i("hour"),
        enum("channel"),
        enum("run_status"),
        f("coverage"),
        i("eligible"),
        i("assessed"),
        i("too_large"),
        i("missed"),
        i("failed"),
        f("oldest_waiting_minutes"),
        f("window_margin_minutes"),
        i("log_records"),
        f("log_expected"),
        b("log_gap"),
        enums("checks_fired"),
    ),
    key=("day", "kind", "run_id", "hour", "channel"),
    writer="monitor",
    partition="day",
)

PROBLEM_CLUSTERS = Table(
    "metrics",
    "quality_problem_clusters",
    (
        d("week"),
        ident("cluster_id"),
        enum("primary_failure"),
        enum("family"),
        enum("owner"),
        Col("data_store", "STRING", "data_store"),
        Col("doc_id", "STRING", "doc_id"),
        Col("uri", "STRING", "link"),
        enum("topic"),
        i("n_turns"),
        i("n_high"),
        i("n_medium"),
        i("n_low"),
        i("weighted"),
        i("rank"),
        f("prev_4w_avg"),
        f("trend"),
        enum("state"),
        b("experimental"),
        Col("fix_events", "STRING", "id", "REPEATED"),
        f("level_before_fix"),
        i("weeks_below"),
    ),
    key=("week", "cluster_id"),
    writer="weekly",
    partition="week",
)

DOCUMENT_STATS = Table(
    "metrics",
    "quality_document_stats",
    (
        d("week"),
        Col("doc_id", "STRING", "doc_id"),
        Col("data_store", "STRING", "data_store"),
        Col("uri", "STRING", "link"),
        enum("topic"),
        i("n_cited"),
        i("n_found"),
        i("n_retrieved"),
        i("n_verifiable"),
        i("n_good"),
        f("aqr"),
        i("n_failures"),
        f("cited_prev_4w_avg"),
    ),
    key=("week", "doc_id", "data_store"),
    writer="weekly",
    partition="week",
)

RELEASE_IMPACT = Table(
    "metrics",
    "quality_release_impact",
    (
        ident("event_id"),
        enum("metric"),
        enum("channel"),
        d("change_day"),
        f("before_value"),
        f("after_value"),
        f("diff"),
        f("se"),
        i("n_before"),
        i("n_after"),
        enum("verdict"),
        Col("confounding_events", "STRING", "id", "REPEATED"),
        b("same_judge"),
        d("computed_day"),
    ),
    key=("event_id", "metric", "channel"),
    writer="daily",
)

CHANGE_EVENTS = Table(
    "metrics",
    "quality_change_events",
    (
        ident("event_id"),
        d("day"),
        i("hour"),
        enum("source"),
        enum("kind"),
        Col("repository", "STRING", "repo"),
        Col("commit_sha", "STRING", "sha"),
        Col("execution", "STRING", "execution"),
        ver("judge_version"),
        Col("doc_id", "STRING", "doc_id"),
        Col("data_store", "STRING", "data_store"),
        Col("clusters", "STRING", "id", "REPEATED"),
        d("recorded_day"),
    ),
    key=("event_id",),
    writer="daily+record",
)

JUDGE_QUALITY = Table(
    "metrics",
    "quality_judge_quality",
    (
        d("day"),
        enum("measure"),
        enum("field"),
        f("value"),
        i("n"),
    ),
    key=("day", "measure", "field"),
    writer="daily",
    partition="day",
)

SUITE_RUNS = Table(
    "metrics",
    "quality_judge_suite_runs",
    (
        ident("suite_run_id"),
        d("day"),
        ver("suite_version"),
        ver("judge_version"),
        ver("stage1_model"),
        ver("stage2_model"),
        i("passes"),
        i("n_cases"),
        b("partial"),  # a run of some cases only (--limit, --part): never a baseline, never sets reliability
        i("failed_calls"),
        f("estimated_usd"),
        f("tuning_distance"),
        f("held_out_distance"),
        i("false_high"),
        i("missed_high"),
        struct("per_field", enum("field"), enum("part"), f("distance"), repeated=True),
        struct("per_scenario", Col("scenario", "STRING", "scenario"), f("distance"), i("n"), repeated=True),
        struct("label_recall", enum("label"), f("recall"), i("n"), b("reliable"), repeated=True),
        enum("decision"),
        ident("baseline_run_id"),
        TOKENS,
    ),
    key=("suite_run_id",),
    writer="judge-suite",
)

EVAL_DOCUMENTS = Table(
    "metrics",
    "quality_eval_documents",
    (
        d("period"),
        enum("eval_set"),
        Col("doc_id", "STRING", "doc_id"),
        Col("data_store", "STRING", "data_store"),
        Col("uri", "STRING", "link"),
        ident("cluster_id"),
        i("n_questions"),
        f("traffic_share"),
        d("week"),
    ),
    key=("period", "eval_set", "doc_id", "data_store", "cluster_id"),
    writer="weekly",
)

TABLES: tuple[Table, ...] = (
    QUALITY_TURNS,
    STAGE1_RESULTS,
    STAGE2_RESULTS,
    SEGMENTS,
    SESSION_GRADES,
    CANARY_RESULTS,
    JUDGE_CHECKS,
    RETRIEVAL_COUNTS,
    JUDGE_VERSIONS,
    RUNS,
    ALERTS,
    ALERT_SESSIONS,
    METRICS_DAILY,
    ANOMALIES,
    ACKNOWLEDGEMENTS,
    PIPELINE_HEALTH,
    PROBLEM_CLUSTERS,
    DOCUMENT_STATS,
    RELEASE_IMPACT,
    CHANGE_EVENTS,
    JUDGE_QUALITY,
    SUITE_RUNS,
    EVAL_DOCUMENTS,
)

# ---------------------------------------------------------------- document index (written by the indexers, §12.7)

CHUNK_COLS = (
    Col("doc_id", "STRING", "doc_id"),
    Col("uri", "STRING", "link"),
    Col("data_store", "STRING", "data_store"),
    i("chunk_no"),
    Col("embedding", "FLOAT64", "float", "REPEATED"),
    h("text_hash"),
    ver("embedding_model"),
    ts("indexed_at"),
)


def chunk_table_name(data_store_id: str) -> str:
    return "quality_chunks_" + data_store_id.replace("-", "_")


def chunk_table(data_store_id: str) -> Table:
    return Table(
        "doc_index",
        chunk_table_name(data_store_id),
        CHUNK_COLS,
        key=("doc_id", "chunk_no", "text_hash"),
        writer="indexer",
    )


def ddl(table: Table, emulator: bool, name_override: str | None = None) -> str:
    s = get_settings()
    name = name_override or table.name
    full = f"`{s.env.bq_project}.{getattr(s.datasets, table.dataset)}.{name}`"
    cols = ",\n  ".join(col.ddl() for col in table.cols)
    sql = f"CREATE TABLE IF NOT EXISTS {full} (\n  {cols}\n)"
    if table.partition and not name_override:
        sql += f"\nPARTITION BY {table.partition}"
        if table.expiration_days and not emulator:
            sql += f"\nOPTIONS (partition_expiration_days = {table.expiration_days})"
    return sql
