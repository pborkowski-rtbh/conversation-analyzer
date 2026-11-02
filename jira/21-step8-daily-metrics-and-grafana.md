# 21 · Step 8: daily metrics and the Grafana dashboard

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 21 |
| Depends on | 05, 12, 18, 19 |
| Plan | `deployment-plan.md` Step 8 |

### User story

As a team member, every morning, I want the daily metrics in a Grafana dashboard so that I can see pipeline health, AQR and failures at a glance.

### Context

Moves: `reporting/daily.py`, `metrics.py`, `changes.py`, `judge_quality.py`, `results.py`, `bq/views.py`. The dashboard file lives in `infra-grafana-dashboards` (`test/` reads stage, `prod/` reads prod). Row 7 of §8.8 waits for ticket 25.

### Acceptance criteria

* Infra: job `quality-daily` (05:00 UTC), read on `ge_metrics`, Cloud Run executions list for indexer events, GitHub read-only token secret
* `quality-daily --day <d>` run twice gives identical rows; a day's volume equals the log view's count
* Dashboard `bolek-quality.json` in `test/AI-Engineering-Lab/Conversation-Analyzer/` with rows 1-6 of §8.8 and a department filter; `make dashboard-check` green
* Every panel renders on the test instance; no slice under 20 turns shown; incomplete and paused days marked
* The Grafana account is denied on the turns dataset
* Prod copy with the prod datasource UID; the team reads it every morning (M5 exit)
* Step 8 ticked

### If something is not clear

Look at `design-doc.md` first, starting with §8, §12.9. If it is still not clear, ask Paweł Borkowski. Don't assume.
