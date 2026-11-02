# 04 · Slack app and channels for quality alerts and the digest

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 04 |
| Depends on | — |
| Plan | `deployment-plan.md` G3 |

### User story

As a team member, when the system finds a problem, I want its alerts and digest posted by an approved Slack app to agreed channels so that we hear about issues without opening the dashboard.

### Context

The jobs post alerts and the weekly digest through the Slack Web API and read ✅ reactions to acknowledge anomalies. There is no Cloud Run service, so the app needs no callback URL. Stage posts every message to its own channel; prod splits quality messages from pipeline health.

### Acceptance criteria

* A Slack app with `chat:write` and `reactions:read` (no other scopes) is approved and installed in the workspace
* Channels `#bolek-quality-stage`, `#bolek-quality` and `#aiel-alerts` exist and the app's bot is a member of each
* The bot token is stored in Secret Manager in `rtb-aiel-core-stage` and in `rtbhouse-agentspace`; the secret names are recorded in the ticket
* A test message posted with the token appears in `#bolek-quality-stage`
* G3 in `deployment-plan.md` is ticked with the date

### If something is not clear

Look at `design-doc.md` first, starting with §9.2, §12.8.
