# 01 · Official repository and CI access for the Conversation Analyzer

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 01 |
| Depends on | — |
| Plan | `deployment-plan.md` G6 |

### User story

As a Conversation Analyzer maintainer, when the code moves out of the private repository, I want an official repository with CI access to both GCP projects so that every migration step lands as a reviewed PR and builds an image.

### Context

The code lives in the private repository `pborkowski-rtbh/conversation-analyzer`. It moves piece by piece to `RTBHouse-OEET/aiel-conversation-analyzer` (agreed name). CI/CD follows `aiel-content-indexers`: GitHub Actions, Workload Identity Federation, Artifact Registry in `rtb-aiel-core-stage` (stage) and `rtbhouse-agentspace` (prod).

### Acceptance criteria

* `RTBHouse-OEET/aiel-conversation-analyzer` exists, with CODEOWNERS and branch protection on `main` (PR, at least 1 review, green CI required)
* A Workload Identity provider and a CI service account exist for both projects; their names are stored as repository secrets, like `GCP_RESTRICTED_PROVIDER_NAME` / `GCP_RESTRICTED_SA_EMAIL` in `aiel-content-indexers`
* A throwaway workflow run authenticates to both projects through WIF (log of the run linked in the ticket)
* The CI service account has no BigQuery, Secret Manager or Cloud Run admin rights; image push rights come with ticket 12
* G6 in `deployment-plan.md` is ticked with the date

### If something is not clear

Look at `design-doc.md` first, starting with §12.14. If it is still not clear, ask Paweł Borkowski. Don't assume.
