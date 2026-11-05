# Jira issues for the deployment

One file per issue, in execution order. Each follows the team's Story template (jira-describe). The order and the
dependencies come from `deployment-plan.md`; when the two disagree, the plan wins.

| # | Title | Depends on | Plan |
|---|---|---|---|
| 01 | [Official repository and CI access for the Conversation Analyzer](01-official-repo-and-ci-access.md) | — | G6 |
| 02 | [Security approval for the assessor's access to conversation text in stage and prod](02-secops-approval-text-access.md) | — | G1 |
| 03 | [Access to the HR active-associates table and the department list](03-hr-table-access-and-department-list.md) | — | G2, A5 input |
| 04 | [Slack app and channels for quality alerts and the digest](04-slack-app-and-channels.md) | — | G3 |
| 05 | [BigQuery datasource in Central Grafana for the quality dashboard](05-grafana-bigquery-datasource.md) | — | G4 |
| 06 | [Agreement with the evaluator (AIENGLAB-519) on canary runs and the aiel_evals contract](06-evaluator-agreement.md) | — | G5 |
| 07 | [Drop the document index and search from the assessor](07-drop-document-index.md) | — | A2 |
| 08 | [Drop PII scrubbing from the assessor](08-no-pii-scrubbing.md) | — | A3 |
| 09 | [Judge v3 and the judge test suite without search](09-judge-v3-and-suite.md) | 07, 08 | A4 |
| 10 | [Department family on every turn and in the AQR strata](10-department-in-strata.md) | 03 (values only; code can start with placeholder families) | A5 |
| 11 | [One code for stage and prod, run gate and operational commands for real GCP](11-ready-for-real-gcp.md) | — | A6 |
| 12 | [Local check of the Grafana dashboard's SQL on the emulator](12-dashboard-sql-check.md) | — | A7 |
| 13 | [Step 1: foundations in the official repository, CI and the first image](13-step1-repo-ci-image.md) | 01, 11 | Step 1 |
| 14 | [Step 2: datasets, service accounts and tables in stage and prod](14-step2-datasets-and-accounts.md) | 13 | Step 2 |
| 15 | [Step 3: assessor dry run on the real log in stage and prod](15-step3-assessor-dry-run.md) | 14 | Step 3 |
| 16 | [Step 4: stage 1 in shadow on real traffic](16-step4-stage1-shadow.md) | 02, 09, 15 | Step 4 |
| 17 | [Step 5: department family on real traffic](17-step5-department.md) | 03, 10, 16 | Step 5 |
| 18 | [Step 6: evidence check, stage 2 and session grades, then go-live](18-step6-stage2-go-live.md) | 07, 09, 17 | Step 6 |
| 19 | [Step 7: monitor and authorized log views, alerts stored but not posted](19-step7-monitor-without-slack.md) | 16 | Step 7 |
| 20 | [Check that feedback numbering matches turn positions](20-feedback-numbering-check.md) | 19 | G7 (optional) |
| 21 | [Step 8: daily metrics and the Grafana dashboard](21-step8-daily-metrics-and-grafana.md) | 05, 12, 18, 19 | Step 8 |
| 22 | [Step 10: judge test suite as a Cloud Run job](22-step10-judge-suite-job.md) | 16 | Step 10 |
| 23 | [Step 9: Slack health alerts, HIGH cluster alerts and acknowledgements](23-step9-slack-alerts.md) | 04, 19, 22 | Step 9 |
| 24 | [Step 11: canary and second-model check on real traffic](24-step11-canary-and-second-model.md) | 06, 18 | Step 11 |
| 25 | [Step 12: weekly clusters, digest, anomalies, release impact and quality-record](25-step12-weekly-digest-anomalies.md) | 21, 23 | Step 12 |
| 26 | [Step 13: eval documents and gate verdicts (closed loop)](26-step13-closed-loop.md) | 06, 25 | Step 13 |
| 27 | [Step 14: hand-over and archive of the private repository](27-step14-handover.md) | 26 | Step 14 |
