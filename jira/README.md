# Jira issues for the deployment

One file per issue, in execution order. Each follows the team's Story template (jira-describe). The order and the
dependencies come from `deployment-plan.md`; when the two disagree, the plan wins.

| # | Title | Depends on | Plan |
|---|---|---|---|
| 01 | [Official repository and CI access for the Conversation Analyzer](01-official-repo-and-ci-access.md) | — | G6 |
| 02 | [Security approval for the assessor's access to conversation text in stage and prod](02-secops-approval-text-access.md) | — | G1 |
| 03 | [Access to the HR active-associates table and the department list](03-hr-table-access-and-department-list.md) | — | G2, A4 input |
| 04 | [Slack app and channels for quality alerts and the digest](04-slack-app-and-channels.md) | — | G3 |
| 05 | [BigQuery datasource in Central Grafana for the quality dashboard](05-grafana-bigquery-datasource.md) | — | G4 |
| 06 | [Agreement with the evaluator (AIENGLAB-519) on canary runs and the aiel_evals contract](06-evaluator-agreement.md) | — | G5 |
| 07 | [Drop the document index and search from the assessor](07-drop-document-index.md) | — | A2 |
| 08 | [Judge v3 and the judge test suite without search](08-judge-v3-and-suite.md) | 07 | A3 |
| 09 | [Department family on every turn and in the AQR strata](09-department-in-strata.md) | 03 (values only; code can start with placeholder families) | A4 |
| 10 | [Environment settings, run gate and operational commands for real GCP](10-ready-for-real-gcp.md) | — | A5 |
| 11 | [Local check of the Grafana dashboard's SQL on the emulator](11-dashboard-sql-check.md) | — | A6 |
| 12 | [Step 1: foundations in the official repository, CI and the first image](12-step1-repo-ci-image.md) | 01, 10 | Step 1 |
| 13 | [Step 2: datasets, service accounts and tables in stage and prod](13-step2-datasets-and-accounts.md) | 12 | Step 2 |
| 14 | [Step 3: assessor dry run on the real log in stage and prod](14-step3-assessor-dry-run.md) | 13 | Step 3 |
| 15 | [Step 4: stage 1 in shadow on real traffic](15-step4-stage1-shadow.md) | 02, 08, 14 | Step 4 |
| 16 | [Step 5: department family on real traffic](16-step5-department.md) | 03, 09, 15 | Step 5 |
| 17 | [Step 6: evidence check, stage 2 and session grades, then go-live](17-step6-stage2-go-live.md) | 07, 08, 16 | Step 6 |
| 18 | [Step 7: monitor and authorized log views, alerts stored but not posted](18-step7-monitor-without-slack.md) | 15 | Step 7 |
| 19 | [Check that feedback numbering matches turn positions](19-feedback-numbering-check.md) | 18 | G7 (optional) |
| 20 | [Step 8: daily metrics and the Grafana dashboard](20-step8-daily-metrics-and-grafana.md) | 05, 11, 17, 18 | Step 8 |
| 21 | [Step 10: judge test suite as a Cloud Run job](21-step10-judge-suite-job.md) | 15 | Step 10 |
| 22 | [Step 9: Slack health alerts, HIGH cluster alerts and acknowledgements](22-step9-slack-alerts.md) | 04, 18, 21 | Step 9 |
| 23 | [Step 11: canary and second-model check on real traffic](23-step11-canary-and-second-model.md) | 06, 17 | Step 11 |
| 24 | [Step 12: weekly clusters, digest, anomalies, release impact and quality-record](24-step12-weekly-digest-anomalies.md) | 20, 22 | Step 12 |
| 25 | [Step 13: eval documents and gate verdicts (closed loop)](25-step13-closed-loop.md) | 06, 24 | Step 13 |
| 26 | [Step 14: hand-over and archive of the private repository](26-step14-handover.md) | 25 | Step 14 |
