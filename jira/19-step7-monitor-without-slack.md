# 19 · Step 7: monitor and authorized log views, alerts stored but not posted

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 19 |
| Depends on | 16 |
| Plan | `deployment-plan.md` Step 7 |

### User story

As a Conversation Analyzer maintainer, when a run fails or the log has a gap, I want pipeline health computed and stored every 10 minutes so that problems are visible before Slack is switched on.

### Context

Moves: `reporting/monitor.py`, `reporting/completeness.py`, `reporting/messages.py` (health only), `reporting/slack.py` with posting off. The reporting account reads the log only through authorized views; stage's views read the prod log.

### Acceptance criteria

* Infra: job `quality-monitor` (reporter account, every 10 min at +5 min), `slack.enabled: false`
* Authorized views created by `db-init` and authorized on prod `analytics` (`google_bigquery_dataset_access`) for stage and prod
* `quality_pipeline_health` has a row per run and per log hour; stage marks paused periods
* The reporter account can query the views and is denied on `analytics.audit_logs`
* A forced health condition on stage writes one alert row with a deterministic ID and no duplicate on the next run
* The same in prod; step 7 ticked

### If something is not clear

Look at `design-doc.md` first, starting with §8.2, §9.2, §12.4, §12.8, §12.12.
