# 23 · Step 9: Slack health alerts, HIGH cluster alerts and acknowledgements

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 23 |
| Depends on | 04, 19, 22 |
| Plan | `deployment-plan.md` Step 9 |

### User story

As a team member, when something needs attention now, I want an alert in Slack that I can acknowledge with ✅ so that problems reach us the same day.

### Context

Moves: `reporting/lookup.py`, HIGH cluster alerts, ✅ acknowledgements; Slack switched on. Stage posts everything to `#bolek-quality-stage`; prod posts health to `#aiel-alerts` and quality to `#bolek-quality`.

### Acceptance criteria

* Infra: Slack token secret per project; `slack.enabled: true` on stage first
* A forced health condition posts one message; the next run does not repeat it
* A HIGH cluster alert on stage holds only codes, counts, hours and the alert ID; `ca quality-alert-lookup --alert <id>` shows the segments' grades
* ✅ on an alert is recorded as an acknowledgement and answered in the thread
* Prod switched on with the channels above; step 9 ticked

### If something is not clear

Look at `design-doc.md` first, starting with §7.7, §9.2, §12.8.
