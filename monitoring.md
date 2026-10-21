# Monitoring algorithm (proposal, v2)

Goal: detect that something got worse (or changed) on the web channel, using only `rtbhouse-agentspace.analytics.audit_logs` metadata. No verdicts on individual answers.

v2 = v1 after verification against live data on 2026-10-16 (counts only). What changed and why is listed at the end.

Status: absorbed into `design.md` as the health layer (§14). Where the two differ, `design.md` is current. Counts here are as of 2026-10-16.

## Inputs and their limits (verified)
- Columns: `timestamp`, `methodName`, `serviceAttributionToken`, `assistToken`, `request`, `response`, `userIamPrincipal`, `userQuery`, `serviceLabel`, `serviceName`. No status/error column, no latency.
- Inside the window, `userIamPrincipal` and `response` are 100% filled. At 4h `audit_logs_annonymizer` NULLs them. Rows land ~4 min after the call. Rows are deleted after 30 days.
- (Corrected 2026-10-20: the session ID is in `response.answer.name` inside the window, see `session-analysis.md` and `design.md` §8.3. The note below checked `request` only.) No session key in the `StreamAssist` request: it carries only `name`, `query`, `agentsSpec`. `serviceAttributionToken` is unique per call. Conversations can only be rebuilt from the principal, inside the window.
- `Search` rows are internal retrieval calls the assistant fires per user turn (~6 per turn, per the `user_activity_materialize` DAG), not user searches. Not a per-user signal. (Corrected 2026-10-19: earlier guessed as search-as-you-type.)
- Data has gaps: no `StreamAssist` rows 2026-09-30 .. 2026-10-04, 2026-10-05 partial (193 calls).
- The web UI can be separated from Slack/MCP/evaluator structurally: web-UI `StreamAssist` requests carry `agentsSpec`, API clients send `query.text` (verified 2026-10-19).
- Real traffic: 831-1,590 non-eval `StreamAssist` calls per weekday, 32-237 per weekend day.

## Population
- `methodName = 'StreamAssist'`, non-eval only.
- Eval exclusion: `userQuery` starts with "Provide concise, focused answers that:", plus (inside the window) the evaluator's principals. Other automated callers are unknown, so counts are an upper bound on human traffic.
- Engines reported separately; the dev engine is treated as test traffic and not alerted on.

## Two stages
1. **Counter stage (inside the 4h window).** Every 30 min, for each 15-min bucket aged >= 30 min and < 3h, compute counters and write them to `monitoring_counters`. Re-run each bucket once more (idempotent overwrite) for late rows. Metrics that look at the next call look T seconds past the bucket end. Identity and response are used transiently and never written.
2. **Detection stage (daily, no deadline).** Reads counters only.

## Metrics
### v0: usable now
| Metric | Definition | Source |
|---|---|---|
| Data completeness | rows per hour vs same hour/weekday baseline; zero-row hours on weekdays | `audit_logs`, replayable |
| Volume | non-eval `StreamAssist` calls per day | `audit_logs`, replayable |
| Thumbs-down | `add-feedback` DISLIKE count and per-call rate | `audit_logs` (`WriteUserEvent`), replayable, informational only (37 events in a month as of 2026-10-16; 33 as of 2026-10-19) |
| Active users, retention | `daily_active_user_count`, `user_retention_ratio_for7d` | `ge_metrics` (3-day lag) |
| Change events | `UpdateEngine`, `UpdateAgent`, `UpdateDataConnector` | `audit_logs` |

### v1: needs a fix before it means anything
| Metric | Problem found | Fix needed |
|---|---|---|
| Re-ask rate | No cluster of fast rephrases: gaps to next call spread evenly 30 s - 10 min, none under 5 s. At T = 120 s ~26% of calls count, which is normal multi-turn use. | Separate rephrase from follow-up via `userQuery` similarity (needs the decision that question text is not fragile), computed in the counter stage. |
| Empty answer rate | 62% of answers have no `answer.replies`; most are agent calls (230 of 346). All states are `SUCCEEDED`. A missing field is a logging detail, not an empty answer. | Find where the real answer state is logged (raw GCS logs or `gen_ai.client.inference.operation.details`). |
| Error rate | No status column, `response.error` never set; failed calls may not be in this table at all. | Use the raw Cloud Audit logs in GCS (they carry `status`) or Cloud Logging metrics. |
| Distinct users per bucket | 15-min distinct counts do not add up to a daily distinct. | `ge_metrics` only, or mergeable HLL sketches (derived from identity, needs a decision). |
| Zero-result `Search` | ~6% of retrieval calls return no results; calls carry no turn ID. | Link to turns by principal and time inside the window (see `design.md` §8.4). |

## Detection
Applied per metric, per engine, weekdays and weekends modeled separately.

1. **Completeness first.** If the day (or hour) fails the completeness check, mark it `incomplete`, do not test other metrics on it, and exclude it from baselines. Alert on the gap itself.
2. **Minimum size.** Skip a day if `n_t < 100`. Any breakdown is reported only if `n >= 20`, otherwise merged into "other".
3. **Baseline.** Pooled rate `p0` over the last 28 complete same-type days (14 while history is short), excluding days in an open alert.
4. **Noise level.** `sigma_t = max(sqrt(p0(1-p0)/n_t), sigma_emp)`, `sigma_emp` = 1.4826 * MAD of baseline daily rates. The empirical floor accounts for clustering (one person, many calls).
5. **Sudden shift (Shewhart).** `z = (x_t - p0) / sigma_t`, flag if `|z| > 3`.
6. **Gradual drift (CUSUM).** On standardized values `u_t = (x_t - p0) / sigma_t`: `S+_t = max(0, S+_{t-1} + u_t - 0.5)`, `S-_t = max(0, S-_{t-1} - u_t - 0.5)`, flag if either > 4. Reset to 0 after an alert.
7. **Acknowledge and rebase.** An alert stays open until acknowledged. On acknowledgement, the baseline restarts from the acknowledged date, so a lasting change does not alert forever.
8. **Change annotation.** Attach change events from the previous 48h. A flag with a nearby change is "likely caused by", without one it is "unexplained".

## Sensitivity
- Per-day standard error at ~1,300 calls: ~0.8 pp at a 10% rate, ~1.2 pp at 26%. So a daily 3-sigma test sees shifts of ~2.5-3.6 pp. A weekly pool (~6,500 calls) sees ~1-1.6 pp.
- Hourly rates (~50-100 calls) are too noisy for anything but completeness.
- With ~20 tests per day at `|z| > 3`, expect roughly one false alarm a month (more with clustering).

## Output
`monitoring_daily(date, metric, engine, n, successes, rate, p0, z, cusum_pos, cusum_neg, status[ok|flag|incomplete], alert_id, nearby_changes, analyzer_version)`. No identities, no text, no per-person rows. Slack gets flags and completeness alerts only: metric, value vs baseline, nearby changes.

## Validation
- Replay is possible only for v0 metrics (completeness, volume, thumbs, change events). Use the 2026-09-30 .. 2026-10-05 gap as a known positive for completeness.
- Window metrics (v1) have no history: principal and response are gone after 4h. The counter stage must run for several weeks before their detection is trustworthy.
- Synthetic shifts (inject re-asks or empty answers at a known rate into counters) to measure detection delay.
- Window health: lag from bucket end to counter write, share of buckets with missing counters. A missed bucket cannot be recovered.

## Changes from v1 and why
- **Dropped "error rate from `status`"**: the BigQuery table has no status field.
- **Moved empty answer rate to v1**: `replies` is missing on 62% of answers, mostly agent calls; not a quality signal as defined.
- **Re-ask rate moved to v1**: gap distribution shows no rephrase cluster, ~26% base rate is mostly normal follow-ups. Text similarity is required, not optional.
- **Replaced "replay 25 days" validation**: impossible for window metrics.
- **Added completeness check**: real 5-day gap found, would read as a usage drop and poison baselines.
- **Added**: look-ahead past bucket end, evaluator principal exclusion, dev engine not alerted, CUSUM on standardized values with reset, acknowledge-and-rebase, HLL note for distinct users.
- **Corrected**: re-ask base rate ~26% (not 10%); `ge_metrics` has no `original_search_query` / `document_name` values, only aggregate counts and retention.

## Open points
- Is question text fragile? Decides whether re-ask can be fixed.
- Where are the real answer state and errors logged? Decides empty-answer and error rate.
- Any change to the anonymizer's cadence or delay silently shrinks the counter stage's budget.
- Department breakdown needs an email-to-department lookup inside the window.
