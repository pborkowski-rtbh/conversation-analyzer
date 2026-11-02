# 02 · Security approval for the assessor's access to conversation text in stage and prod

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 02 |
| Depends on | — |
| Plan | `deployment-plan.md` G1 |

### User story

As the Conversation Analyzer owner, before any judge call on real traffic, I want SECOPS to approve which accounts read conversation text and where it is sent so that the assessor runs within agreed security rules.

### Context

The assessor reads questions and answers from `rtbhouse-agentspace.analytics.audit_logs` inside the 4-hour window and sends them, without PII scrubbing, to Vertex AI on the `eu` multi-region. It also reads full document text from the content bucket `rtbhouse-agentspace-mcp-document-content` with the content secrets. Stage (`rtb-aiel-core-stage`) reads the same prod data with its own service accounts. §3.1 lists the `eu` multi-region as still open with the security team. Before launch we must check whether the cloud audit logs of our calls contain content, and possibly exclude our accounts from the 7-year log copy.

### Acceptance criteria

* Written SECOPS approval (link in the ticket) for `quality-assessor@rtbhouse-agentspace` and `stage-quality-assessor@rtb-aiel-core-stage` to read the `audit_logs` table (table-level grant, not the `analytics` dataset)
* Approval for sending conversation text to the judge without PII scrubbing (EU endpoint only, nothing stored)
* Approval for both assessor accounts to read the content bucket and the `mcp-content-encryption-*` secrets
* Decision on the `eu` multi-region for the judge recorded (accepted, or a named EU region instead)
* The audit-log content check procedure (§12.13) agreed: which logs are checked, by whom, in ticket 16
* Decision recorded on excluding our service accounts' entries from the 7-year log copy, if the check finds content
* G1 in `deployment-plan.md` is ticked with the date and link

### If something is not clear

Look at `design-doc.md` first, starting with §3.1, §6.10, §12.4, §12.13.
