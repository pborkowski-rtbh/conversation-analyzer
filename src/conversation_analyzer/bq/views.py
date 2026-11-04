"""Shared SQL over the log, and the authorized views (§12.4) that give reporting jobs counts, never the log."""

from __future__ import annotations

from conversation_analyzer.bq.client import fq
from conversation_analyzer.settings import get_settings


def partition_filter(days: int) -> str:
    """The log requires a partition filter in production; rows not yet in a partition (NULL) are the newest ones."""
    if get_settings().env.emulator:
        return "TRUE"
    # About 7 % of the last hour's turns had no partition yet (2026-11-04): without them, searches and feedback past
    # the last run's cutoff would never be read.
    return f"(_PARTITIONTIME >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY) OR _PARTITIONTIME IS NULL)"


def engine_filter(column: str = "JSON_VALUE(request, '$.name')") -> str:
    return f"STRPOS(CONCAT(IFNULL({column}, ''), '/'), '/engines/{get_settings().production_engine}/') > 0"


# Search requests carry `query` as a plain string; only StreamAssist requests are asked for query.text (the emulator
# fails on the path otherwise, and CASE keeps it from evaluating it on other rows).
QUERY_TEXT = "CASE WHEN methodName = 'StreamAssist' THEN JSON_VALUE(request, '$.query.text') END"


def channel_sql() -> str:
    """web UI requests carry agentsSpec; Slack Bolek and MCP send query.text (§8.9)."""
    return (
        "CASE WHEN JSON_QUERY(request, '$.agentsSpec') IS NOT NULL THEN 'WEB_UI' "
        f"WHEN {QUERY_TEXT} IS NOT NULL THEN 'SLACK_MCP' ELSE 'WEB_UI' END"
    )


def canary_prefix_sql(text_column: str = QUERY_TEXT) -> str:
    prefix = get_settings().evaluator.prompt_prefix.replace("'", "\\'")
    return f"STARTS_WITH(LTRIM(IFNULL({text_column}, '')), '{prefix}')"


def views() -> dict[str, str]:
    s = get_settings()
    log = fq("log", s.log_table)
    methods = ", ".join(f"'{m}'" for m in s.engine_change_methods)
    return {
        "quality_turn_counts_hourly": f"""
SELECT TIMESTAMP_TRUNC(timestamp, HOUR) AS hour, DATE(timestamp) AS day, {channel_sql()} AS channel,
       COUNT(*) AS n_turns
FROM {log}
WHERE {partition_filter(60)} AND methodName = 'StreamAssist' AND {engine_filter()} AND NOT {canary_prefix_sql()}
GROUP BY hour, day, channel""",
        "quality_feedback_counts_daily": f"""
SELECT DATE(timestamp) AS day, 'WEB_UI' AS channel,
       COUNTIF(JSON_VALUE(request, '$.userEvent.feedback.feedbackType') = 'DISLIKE') AS n_dislikes,
       COUNTIF(JSON_VALUE(request, '$.userEvent.feedback.feedbackType') = 'LIKE') AS n_likes,
       COUNT(*) AS n_feedback
FROM {log}
WHERE {partition_filter(60)} AND methodName = 'WriteUserEvent'
  AND JSON_VALUE(request, '$.userEvent.eventType') = 'add-feedback'
  AND {engine_filter("JSON_VALUE(request, '$.userEvent.engine')")}
GROUP BY day""",
        "quality_engine_changes": f"""
SELECT DATE(timestamp) AS day, EXTRACT(HOUR FROM timestamp) AS hour, methodName AS method,
       CASE WHEN STRPOS(methodName, 'Agent') > 0 THEN 'AGENT'
            WHEN STRPOS(methodName, 'Connector') > 0 THEN 'CONNECTOR'
            WHEN STRPOS(methodName, 'DataStore') > 0 THEN 'DATA_STORE'
            ELSE 'ENGINE' END AS kind,
       REGEXP_EXTRACT(JSON_VALUE(request, '$.name'), r'/dataStores/([^/]+)') AS data_store,
       TO_HEX(SHA256(CONCAT(methodName, '|', CAST(timestamp AS STRING), '|', IFNULL(serviceAttributionToken, ''))))
         AS change_ref
FROM {log}
WHERE {partition_filter(60)} AND methodName IN ({methods})""",
    }
