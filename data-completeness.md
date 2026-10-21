# The 2026-09-30..10-04 data gap and `audit_logs` completeness (Q10)

| | |
|---|---|
| Ticket | AIENGLAB-799 (epic AIENGLAB-543), `design.md` Q10 |
| Status | Findings, 2026-10-21 |
| Data | `audit_logs` daily and hourly row counts per method (2026-09-22..10-21), table metadata, log sinks, GCS object counts per day. Read-only. No log content was read. |

## 1. Summary

1. **The gap affected only `StreamAssist`.** No `StreamAssist` rows exist from **2026-09-29 22:01 UTC to 2026-10-05 15:10 UTC** (~5.7 days). `Search` and `WriteUserEvent` kept arriving at normal volume, e.g. Wed 09-30: 7,224 `Search` and 1,221 `WriteUserEvent` rows.
2. **The most likely cause is a schema mismatch.** The Gemini Enterprise export started sending the new top-level field `assistToken` on `StreamAssist` events (the column description says "since 2026-09-29"). The table had no such column, so those rows were rejected. The other methods don't carry the field and were unaffected.
   - The **first row after the gap already has `assistToken`** (10-05 15:10 UTC).
   - The column was added with AIENGLAB-668. The terraform commit `3322ada` is from 10-06 07:26 UTC, so the column was probably added by hand on 10-05 and codified the next day.
3. **It can recur.** `audit_logs` is written by the Gemini Enterprise BigQuery export itself, not by a log sink or our code (§3). Any new field Google adds to an event can silently drop that method's rows until the schema is updated. Nothing alerts today.
4. **No other holes.** Over 30 days, outside the known gap, no weekday hour between 07:00 and 16:00 UTC has fewer than 5 rows for any of `StreamAssist`, `Search` or `WriteUserEvent`.
5. **The lost turns are probably in the raw Cloud Audit logs in GCS.** `cloudaudit.googleapis.com/data_access` has a normal number of objects every day of the gap. Recovering them means reading raw logs with identities (a SECOPS decision). For quality analysis the answers would be useless anyway: answers and identities are only usable within 4h.

## 2. Daily row counts around the gap

| Day | `StreamAssist` | `Search` | `WriteUserEvent` |
|---|---|---|---|
| Mon 09-28 | 1,156 | 5,302 | 1,213 |
| Tue 09-29 | 1,692 (last row 22:01) | 10,365 | 1,324 |
| Wed 09-30 | **0** | 7,224 | 1,221 |
| Thu 10-01 | **0** | 6,142 | 1,139 |
| Fri 10-02 | **0** | 6,425 | 1,239 |
| Sat 10-03 | **0** | 307 | 46 |
| Sun 10-04 | **0** | 161 | 35 |
| Mon 10-05 | 193 (from 15:10) | 6,355 | 1,124 |
| Tue 10-06 | 2,285 | 14,356 | 1,430 |

All rows land in the partition of their own day (ingestion lag under 1 day), so the gap isn't late data.

`StreamAssist` volume after the gap varies strongly with evaluator runs: 6,066 on Thu 10-15, but ~1,000-1,600 web UI turns per weekday (`design.md` §4.4). Volume checks must therefore be done per client (web UI / API / evaluator), not on the total.

## 3. Who writes `audit_logs`

- Log Router sinks in `rtbhouse-agentspace` are:
  - `agent-usage-sink` and `mcp-usage-sink`, which write other `analytics` tables;
  - `audit-logs-sink`, which writes to GCS with an empty filter;
  - `_Required` and `_Default`.
- None of them writes `audit_logs`.
- No code in the local repos writes it. Only terraform defines it (`aiel-infrastructure/modules/agentspace-bigquery/main.tf`), and the anonymizer and cleanup DAGs modify it.
- So it is filled by the Gemini Enterprise export, as the `assistToken` column description says. We control the table schema, not what is sent.

## 4. Proposed completeness check

Run hourly. It can be part of the window job from `session-analysis.md` §5.3, or the daily aggregation in `design.md` §7.3.

| Check | Rule | Action |
|---|---|---|
| Method silence | A method with 0 rows for ≥ 2 consecutive weekday hours between 07:00 and 17:00 UTC while another method has rows | Immediate alert to `#ai-engineering-lab-alerts-prod`. This is the 09-30 failure mode, and it would have fired at ~07:00 on 09-30 instead of being found weeks later. |
| Web UI volume | Hourly web UI `StreamAssist` count < 30% of the median of the same hour over the last 4 same weekdays | Alert, and mark the hour `incomplete` |
| Ratio | `Search` rows per web UI turn outside the 28-day p1..p99 band for the day | Warning (a change in retrieval or logging) |
| Field presence | Share of web UI turns in the window with `response.answer.name`, `assistToken`, `serviceTextReply` < 99% | Alert: the export changed shape |
| Daily | A day with any `incomplete` hour is excluded from baselines (`design.md` §8.9) | Automatic |

The known gap stays as the positive test case: replaying the check on 09-29..10-06 must flag 09-30 07:00 UTC.

## 5. Preventing recurrence

- **Owner action:** ask Google whether the Gemini Enterprise export can write unknown fields (e.g. into a JSON overflow column) or announce schema changes. This is not verified; it is a question for Google support.
- **Fast reaction:** with the method-silence alert, a recurrence costs hours instead of days. The fix is the same as AIENGLAB-668: add the nullable column.
- **Backfill (only if needed):** raw entries for the gap are probably in GCS `cloudaudit.googleapis.com/data_access`. A backfill would copy raw content and identities older than 4h into BigQuery, which goes against the 4h policy. Not recommended for this project; only question text and counts would be usable.

## 6. Impact on the design (not applied)

- §4.4: gap cause and exact boundaries (09-29 22:01 to 10-05 15:10 UTC, `StreamAssist` only).
- §7.3 step 1 and §11 "Data completeness": use the checks in §4, per method and per client.
- §16 Q10: answered (probable cause, can recur, now detectable).
- §15 Risks: add "export schema change silently drops a method", mitigated by the method-silence alert.
