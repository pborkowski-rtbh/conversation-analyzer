# Identity and conversation data outside the 4h boundary (note for SECOPS)

| | |
|---|---|
| Ticket | AIENGLAB-803 (epic AIENGLAB-543), `design.md` Q8 and §10.3 |
| Status | Findings, 2026-10-21 |
| Data | Table metadata (schemas, expiry, row counts), bucket metadata, field fill counts, DAG and terraform code. Read-only. No personal data was copied or output: counts and field names only. |

## 1. Context

The project's privacy model (`design.md` D1, §10): answers and identities exist for about 4h in `analytics.audit_logs`, then `audit_logs_annonymizer` NULLs them. Question text is kept 30 days. The places below keep identity, or identity plus content, much longer. Each one weakens the "4h" promise that the Conversation Analyzer relies on, whether or not the analyzer ever touches it.

## 2. Findings

| # | Where | What is kept | How long | Written by | Severity |
|---|---|---|---|---|---|
| F1 | `analytics.agent_usage_analytics_YYYYMMDD` (175 daily tables since 2026-03-25) | Bolek **Slack** logs: `user_email`, `user_query`, `agent_response` (filled on 191 of 6,904 rows), `session_id`, `slack_channel_id` | **No expiry** (tables and dataset have none) | Log Router sink `agent-usage-sink` (logName `agent-usage-analytics`) | High: identity plus question text plus some answers, kept forever |
| F2 | GCS `audit-logs-rtbhouse-agentspace` | All project logs (sink `audit-logs-sink`, **empty filter**), including Cloud Audit `data_access` (objects every day). Contents were not opened; by the sink definition this includes Gemini Enterprise data-access entries with principals, and probably request and response payloads. | Retention policy **7 years** (220,903,200 s), **not locked**; 7-day soft delete | Log Router | High: the raw copy of everything the BigQuery anonymizer removes |
| F3 | `analytics.daily_user_activity` | `day`, `user_email` (raw, lowercased principal), `channel`, `query_count`; 25,835 rows | **No expiry** | DAG `user_activity_materialize` (`airflow-dags/dags/user_activity_materialize.py:117, 290-307`) | Medium: who used Bolek, per day, forever. The dashboard design doc promises SHA256. |
| F4 | `analytics.hourly_user_activity` | `hour`, `user_email`, `channel`, `query_count` | 35-day partition expiry | same DAG | Medium: hourly per-person activity. Joined with `audit_logs.timestamp` (kept 30 days), it can re-identify the author of a question. |
| F5 | `analytics.mcp_usage_analytics_YYYYMMDD` (193 daily tables) | `user_email`, `tool_name`, status, timings | No expiry | Sink `mcp-usage-sink` | Low-medium: identity plus usage, no text |
| F6 | `analytics.web_channel_backfill_audit` | `day`, `user_email`, counts; 1,350 rows | No expiry | `airflow-dags/scripts/backfill_web_channel_attribution.py` | Low: one-off backfill audit trail |
| F7 | `analytics.audit_logs`, `WriteUserEvent` rows | `userPseudoId` and feedback `comment` (free text) survive anonymization; `conversationInfo.session` links feedback to a session | 30 days | Gemini Enterprise export | Low: pseudonymous, but the comment is user-written text |

## 3. Why it matters for this project

- **Re-identification of "anonymized" questions.** `audit_logs.userQuery` and `timestamp` stay for 30 days. `hourly_user_activity` (F4) has `user_email` per hour per channel. For a user with one web question in an hour, the two tables together give the author. So `audit_logs` past 4h is pseudonymous at best. That's why `design.md` §10.2 forbids an hour field on derived rows. This note confirms that rule is needed.
- **The anonymizer is bypassed** by F2 (the full raw copy) and by F1 for Slack (where nothing is ever anonymized).
- **New derived tables proposed in this epic** must not add another join path. Examples are the session map in `session-analysis.md` §5.3 and `doc_catalog` in `document-mapping.md` §5. Both store no identity and no time finer than a day. Keep it that way.

## 4. Proposed fixes (for owners to decide)

| # | Fix | Effect |
|---|---|---|
| F1 | Set a table expiration on `agent_usage_analytics_*`: a dataset default for new tables plus a one-off update for existing ones, e.g. 30 days, to match `audit_logs`. Or move user email and query into a restricted dataset. Stop logging `agent_response`, or apply the 4h rule to it. | Aligns Slack with the web UI policy |
| F2 | Narrow the sink filter: exclude `discoveryengine` `data_access` payloads, or keep only what audit requires. Lock or shorten the retention to what compliance actually needs. Restrict bucket access. | Removes the raw shadow copy |
| F3 | Store `TO_HEX(SHA256(salt ‖ user_email))` as the dashboard doc promises. The salt goes in Secret Manager; the dashboard needs counts, not emails. Or add an expiry. | Removes forever-identity |
| F4 | Same hashing, or aggregate to day level. Keep the 35-day expiry. | Removes the hour-level join path |
| F5, F6 | Expiry (e.g. 90 days) and hashed emails | Hygiene |
| F7 | No change. Document that feedback comments are user text kept for 30 days. | Transparency |

## 5. Owners (to confirm)

| Finding | Likely owner |
|---|---|
| F1, F5 | Bolek Slack backend and MCP server owners (log format), AIEL infrastructure (sink and dataset) |
| F2 | AIEL infrastructure (`audit-logs-sink`, bucket) |
| F3, F4, F6 | Owner of `user_activity_materialize` and the usage dashboard |
| F7 | none (Google export) |

## 6. Impact on the design (not applied)

- §10.3: replace the list with F1-F7, and add F1 (Slack logs with answers, no expiry), which `design.md` doesn't mention.
- §16 Q8: answered by F3 (who writes it: `user_activity_materialize`, line 117, raw lowercased principal).
- Phase 4 (Slack channel) must not build on F1 as it is: it would extend the analyzer onto data that violates the 4h rule.
