# 10 · Department family on every turn and in the AQR strata

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 10 |
| Depends on | 03 (values only; code can start with placeholder families) |
| Plan | `deployment-plan.md` A5 |

### User story

As a team member reading AQR, when the mix of departments using Bolek changes, I want the strata to include the user's department so that the shift does not look like a change in quality.

### Context

Stratum = intent family × data-store family × department family. The department comes from `base_function` in the HR table, mapped to 3-5 families plus `OTHER` and `UNKNOWN`. Data-store families collapse to 3 (`ENGINEERING`, `COMPANY`, `NONE` incl. Drive), so there are at most 72 strata (4 families plus `OTHER` and `UNKNOWN`). Stored: the family code (families under 30 active associates fold into `OTHER`), the `base_function` as is, and a keyed hash of the email. Work happens in the private repository.

### Acceptance criteria

* `strata.department_families` and `strata.department_min_associates: 30` in settings; data-store families reduced to 3
* `vocab.DepartmentFamily` closed list and `SliceKind.DEPARTMENT`; `closed_lists_version()` changes
* `people/directory.py` reads the associates indexer's `email → base_function` map from its state bucket once per run; a missing, malformed or stale map sets `UNKNOWN` for all and counts `DIRECTORY_UNAVAILABLE`
* `department` column (leak-guard kind `department`: family codes only) on `quality_turns` and `quality_segments`; the principal is stored only as `user_key` (keyed hash); `base_function` as is when listed in settings, else `OTHER`
* Daily metrics produce `intent__datastore__department` strata and a department slice; small strata fall back as today
* The emulator has the department map in fake GCS; synthetic principals cover every family
* Tests: the leak guard rejects anything but a family code; a family below the floor is folded; e2e stratum rows
* Families filled from the real `base_function` list (read from the stage associates indexer's map)
* `make coverage` ≥ 90 %

### If something is not clear

Look at `design-doc.md` first, starting with §2.1, §3.1, §5.4, §8.4, §8.5, §12.6.
