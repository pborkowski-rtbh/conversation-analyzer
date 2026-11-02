# 05 · BigQuery datasource in Central Grafana for the quality dashboard

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 05 |
| Depends on | — |
| Plan | `deployment-plan.md` G4 |

### User story

As a team member, when I read the quality dashboard every morning, I want Central Grafana to query our metrics dataset through a read-only account so that the dashboard shows aggregates and nothing else.

### Context

Dashboards live in `RTBHouse-Platform-Engineering/infra-grafana-dashboards` (Central Grafana, Git Sync; folders `test/`, `stage/`, `prod/`; `AI-Engineering-Lab` exists in `test` and `prod`). The existing dashboards use Cloud Monitoring datasources; no BigQuery datasource is known. Our stage maps to the test instance, prod to the prod instance.

### Acceptance criteria

* The `grafana-bigquery-datasource` plugin is available on the test and prod instances
* Service account `grafana-bolek-quality` exists in both projects (Terraform in `RTBHouse-OEET/infrastructure`) with only `bigquery.dataViewer` on `stage_bolek_quality_metrics` / `bolek_quality_metrics` and `bigquery.jobUser`
* One BigQuery datasource per instance authenticates as that account; datasource UIDs are recorded in `deployment-plan.md`
* Folder `AI-Engineering-Lab/Conversation-Analyzer/` with `_folder.json` and `README.md` exists in `test/` and `prod/`
* `SELECT 1` runs from Explore on both instances through the new datasource
* G4 in `deployment-plan.md` is ticked with the date

### If something is not clear

Look at `design-doc.md` first, starting with §8.8, §12.4.
