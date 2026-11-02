# 12 · Local check of the Grafana dashboard's SQL on the emulator

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 12 |
| Depends on | — |
| Plan | `deployment-plan.md` A7 |

### User story

As a dashboard author, when I change a panel, I want to run every panel's SQL against the emulator so that a broken query is caught before it reaches Central Grafana.

### Context

The dashboard's source lives in `infra-grafana-dashboards`; this repository only tests it. Panels query `bolek_quality_metrics` through the BigQuery datasource with Grafana macros.

### Acceptance criteria

* `make dashboard-check DASHBOARD=<path>` extracts every panel's SQL from a `dashboard.grafana.app/v1beta1` file
* Grafana macros (`$__timeFilter`, variables) are replaced with fixed values and the dataset name follows the environment prefix
* Each query runs on the emulator after `make demo`; the target fails on an error or on an empty panel marked as required
* A test covers the extraction with a small sample dashboard

### If something is not clear

Look at `design-doc.md` first, starting with §8.8. If it is still not clear, ask Paweł Borkowski. Don't assume.
