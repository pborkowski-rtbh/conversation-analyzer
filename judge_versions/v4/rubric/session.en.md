# Session grade rubric (English)

You grade a whole session segment: did the user get what they needed, and if not, where did it go wrong. You see
the text of all turns of the segment with their stage 1 and stage 2 results. The user's need is what they were
trying to get from the segment as a whole, not from one turn.

| Outcome | Meaning |
|---|---|
| `RESOLVED` | By the end of the segment the user got what they needed: the last answer on their need is relevant and has no `MEDIUM` or `HIGH` problem, and the user did not correct it or show frustration afterwards. Earlier bad answers are allowed if a later one fixed them. |
| `PARTIALLY_RESOLVED` | The user had several needs, or a need with several parts, and only some were met by the end. |
| `UNRESOLVED` | The need was not met by the end: the last answer on it has a `MEDIUM` or `HIGH` problem, or the user corrected that answer or showed frustration after it. |
| `UNCLEAR` | You cannot tell what the user needed, or whether it was met, for example when the segment ends right after an answer that cannot be checked. |

| Field | How to set it |
|---|---|
| First bad turn | The position of the first turn with an identified problem of `MEDIUM` or `HIGH` severity, or the first one the user corrected. Null when nothing went wrong. |
| Recovered after correction | `NO_CORRECTION` when the user never corrected an answer. Otherwise `YES` when, after the user's first correction, a later answer gave what was asked without an identified problem; else `NO`. |
| Confidence | 0 to 1, informational only. |

## Example segments (made up)

| Segment | Outcome | First bad turn | Recovered |
|---|---|---|---|
| 1: "How many days of on-demand leave?" answer 6 (contradicted). 2: "That's wrong, it's 4." answer: "You're right, 4 days." | `RESOLVED` | 1 | `YES` |
| 1: "How do I book a trip and who approves it?" answer covers booking only. 2: "And the approval?" answer off target. 3: "Forget it." | `UNRESOLVED` | 1 | `NO_CORRECTION` |
| 1: "Leave policy and expense limits?" good answer on leave only. | `PARTIALLY_RESOLVED` | 1 | `NO_CORRECTION` |
