# 03 · Access to the HR active-associates table and the department list

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 03 |
| Depends on | — |
| Plan | `deployment-plan.md` G2, A5 input |

### User story

As the Conversation Analyzer owner, when standardized AQR is split by department, I want the list of departments in the HR table of active associates so that every turn can carry its department family.

### Context

The department comes from `base_function` in `rtb-house-hr-reporting-data.IT.bolek_associates_active`, the table the people indexer already reads. The assessor gets `Email` and `base_function` from the map the associates indexer writes to its state bucket (AIENGLAB-853), not from the table. Only a department family code is stored; a family with fewer than 30 active associates is merged into `OTHER`. On 2026-11-02 Paweł Borkowski's own account had no access to the table, so the list of `base_function` values is still unknown.

### Acceptance criteria

* No assessor access to the table: the associates indexer, which already reads it, writes an `email → base_function` map to its state bucket (AIENGLAB-853); the assessor reads that
* The HR data owner and SECOPS approve storing a department family code per turn with the 30-associate floor (link in the ticket)
* The distinct `base_function` values with their associate counts are delivered (counts only, no names) and attached to the ticket
* The HR contact for future changes to `base_function` values is named in the ticket
* G2 in `deployment-plan.md` is ticked with the date

### If something is not clear

Look at `design-doc.md` first, starting with §2.1 (Department), §3.1, §8.4.
