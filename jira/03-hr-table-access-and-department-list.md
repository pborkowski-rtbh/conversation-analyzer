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

The department comes from `base_function` in `rtb-house-hr-reporting-data.IT.bolek_associates_active`, the table the people indexer already reads. The assessor gets `Email` and `base_function` from the map the associates indexer writes to its state bucket (AIENGLAB-853), not from the table. Stored per turn: the department family (a family under 30 active associates is merged into `OTHER`), the `base_function` as is, and a keyed hash of the email. On 2026-11-02 Paweł Borkowski's own account had no access to the table; on 2026-11-04 the values and counts were read from the stage associates indexer's map instead (45 values, 1536 associates; `deployment-plan.md` A5).

### Acceptance criteria

* No assessor access to the table: the associates indexer, which already reads it, writes an `email → base_function` map to its state bucket (AIENGLAB-853); the assessor reads that
* The HR data owner and SECOPS approve storing per turn a department family code, the `base_function` as is (some have 1 associate) and a keyed hash of the user's email (link in the ticket)
* The distinct `base_function` values with their associate counts are delivered (counts only, no names) and attached to the ticket (read from the stage map on 2026-11-04)
* The HR contact for future changes to `base_function` values is named in the ticket
* G2 in `deployment-plan.md` is ticked with the date

### If something is not clear

Look at `design-doc.md` first, starting with §2.1 (Department), §3.1, §8.4.
