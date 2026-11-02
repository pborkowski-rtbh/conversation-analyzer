# 20 · Check that feedback numbering matches turn positions

| Field | Value |
|---|---|
| Type | Story |
| Epic | AIENGLAB-543 (Bolek RAG - Conversation Analyzer) |
| Order | 20 |
| Depends on | 19 |
| Plan | `deployment-plan.md` G7 (optional) |

### User story

As a Conversation Analyzer maintainer, when feedback arrives after the window, I want proof that the feedback record's question index matches our turn position so that the fallback match can be switched on.

### Context

Feedback after the window is matched by session key and position (`questionIndex` + 1), behind `feedback_after_window_fallback`, off by default. It stays off until synthetic chats confirm the numbering. Optional for go-live.

### Acceptance criteria

* Synthetic chats of known lengths with feedback on known turns are created on the stage engine (who and how recorded)
* Each feedback record's position matches the turn's stored position (results attached, counts only)
* Decision recorded: switch the fallback on in stage and prod, or keep it off with the reason
* G7 in `deployment-plan.md` ticked

### If something is not clear

Look at `design-doc.md` first, starting with §12.5, §12.17. If it is still not clear, ask Paweł Borkowski. Don't assume.
