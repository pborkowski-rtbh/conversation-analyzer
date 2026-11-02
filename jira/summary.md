# Jira issues: summary

26 issues, one file each in this directory, in execution order. Every file uses the Story template (user story,
context, acceptance criteria), starts with a field table (epic AIENGLAB-543, order, dependencies, plan section) and
ends with the rule: look at `design-doc.md` first; if still not clear, ask Paweł Borkowski; don't assume. The order
and dependencies come from `deployment-plan.md`.

| # | Issue | Kind | Depends on |
|---|---|---|---|
| 01 | Official repository and CI access | Approval / setup | — |
| 02 | Security approval for the assessor's access to conversation text | Approval | — |
| 03 | Access to the HR table and the department list | Approval | — |
| 04 | Slack app and channels | Approval | — |
| 05 | BigQuery data source in Central Grafana | Approval / setup | — |
| 06 | Agreement with the evaluator (AIENGLAB-519) | Approval | — |
| 07 | Drop the document index and search | Code (private repo) | — |
| 08 | Judge v3 and the suite without search (paid, ~7 USD) | Code (private repo) | 07 |
| 09 | Department group on every turn and in the strata | Code (private repo) | 03 (values only) |
| 10 | Per-environment settings, stage on/off switch, dry run, schema check, leak audit | Code (private repo) | — |
| 11 | Local check of the dashboard's SQL on the emulator | Code (private repo) | — |
| 12 | Step 1: foundations in the official repo, CI, first image | Deploy | 01, 10 |
| 13 | Step 2: datasets, service accounts, tables | Deploy | 12 |
| 14 | Step 3: assessor dry run on the real log | Deploy | 13 |
| 15 | Step 4: stage 1 in shadow | Deploy | 02, 08, 14 |
| 16 | Step 5: department on real traffic | Deploy | 03, 09, 15 |
| 17 | Step 6: evidence check, stage 2, session grades, then **go-live** | Deploy | 07, 08, 16 |
| 18 | Step 7: monitor and log views, alerts stored but not posted | Deploy | 15 |
| 19 | Feedback numbering check (optional) | Check | 18 |
| 20 | Step 8: daily metrics and the Grafana dashboard | Deploy | 05, 11, 17, 18 |
| 21 | Step 10: judge suite as a Cloud Run job | Deploy | 15 |
| 22 | Step 9: Slack alerts and ✅ acknowledgements | Deploy | 04, 18, 21 |
| 23 | Step 11: canary and second-model check | Deploy | 06, 17 |
| 24 | Step 12: weekly clusters, digest, anomalies, release impact | Deploy | 20, 22 |
| 25 | Step 13: eval documents and gate verdicts | Deploy | 06, 24 |
| 26 | Step 14: hand-over and archive of the private repo | Wrap-up | 25 |

## Notes

- **Order:** 01–06 come first because they wait on other people, so they should be raised right away. Plan step 10
  (judge suite job) comes before step 9 (Slack), because HIGH alerts need a suite run in the environment first.
- **Open input:** ticket 03 still has to deliver the `base_function` list. Until it does, ticket 09 can only use
  placeholder department groups.
