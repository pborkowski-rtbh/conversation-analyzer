# Vertex AI quota and assessment cost (Q3, §12)

| | |
|---|---|
| Ticket | AIENGLAB-800 (epic AIENGLAB-543), `design.md` Q3 and §12 |
| Status | Findings, 2026-10-21. Aligned with `design.md` v4: all channels (D5), stage 1 per turn (D18), session grade by `gemini-4-argon` on flagged turns only (D19). **Update 2026-10-23:** `gemini-4-argon` price and terms accepted by the user; the "unknown price" items below no longer block. |
| Data | Service Usage consumer quotas for `aiplatform.googleapis.com` in `rtbhouse-agentspace` (read-only REST). Vertex AI public pricing page. `audit_logs` 4h window, Wed 2026-10-21 ~09:45-13:45 UTC, web UI prod: 526 turns, 183 sessions; only character counts were output. |

## 1. Summary

1. **There is no per-project quota to request for `gemini-3.8-flash` or `gemini-4-argon` on `eu`.**
   - The project's `aiplatform` quotas list no `eu` entries and no base-model limits for these models. The only `gemini-3.8` limits are for `gemini-3.8-live` in other regions.
   - These models run under Google's shared capacity (dynamic shared quota). The risk is occasional `429`s, not a hard cap.
   - The load is tiny: ~20 web turns per 10-min run (`design.md` §12). So retry with exponential backoff is enough, and no quota request is needed now.
   - Provisioned throughput is the fallback if 429s become frequent.
2. **The real volume is smaller than `design.md` §12 assumes.** A web turn is ~3.6k characters: question, answer and snippets, with a median of 2.9k. Snippets are short (median 0, p90 1.2k characters).
3. **Stage-1 cost is a few dollars per weekday.** With `gemini-3.8-flash` at the introductory $0.75 / $3.75 per 1M input / output tokens (until 2026-12-31; $1.50 / $7.50 from 2027-01-01):
   - per-turn assessment with the full session as context costs **~$9 per weekday (~$190 per month)**, or ~$18 per weekday from 2027;
   - with the previous 2 turns only, ~$7 per weekday;
   - Slack and MCP (~115 turns per day, D5) add ~8%;
   - the session grade (D19) runs on `gemini-4-argon` for flagged turns only, so its cost is part of the unknown stage-2 price. For scale: grading every session once on `gemini-3.8-flash` would cost ~$3.4 per weekday.
4. **`gemini-4-argon`: no public price or listing found** under that name. Its stage-2 cost and terms stay open (Q4, SECOPS). The §12 bound of ≤ 9M tokens per weekday stands.
5. **Size cap for D13:** no turn in the sample exceeded 100k characters, and the largest session was ~209k characters (~60k tokens). Proposed cap: **30k input tokens per turn bundle** and 120k per session grade. Above it, the item is `SKIPPED_TOO_LARGE`. Expected to hit well under 1% of turns.

## 2. Quotas

| Check | Result |
|---|---|
| `aiplatform` consumer quota metrics in the project | 372 metrics, none with region `eu` |
| Base-model limits for `gemini-3.8-flash` / `gemini-4-argon` | None. The only `gemini-3.8*` entries are `gemini-3.8-live` concurrency limits in `us-central1`, `asia-south1` and global. |
| Cloud Quotas API (`cloudquotas.googleapis.com`) | Not enabled in the project; not enabled here (read-only). |
| `design.md` §4.5 | Synthetic calls to both models on `eu` already succeeded on 2026-10-20 |

Interpretation: newer Gemini models on Vertex AI are served from shared capacity without a fixed per-project tokens-per-minute limit. What to do:
- retry `429`/`503` with exponential backoff and jitter, at most 5 attempts;
- the 3h30 window leaves room for many retries (`design.md` §8.2);
- track the `429` rate in `pipeline_runs`;
- consider provisioned throughput only if stage-1 coverage drops because of throttling.

## 3. Input size (characters, web UI prod)

| Per turn | p50 | p90 | p99 | max |
|---|---|---|---|---|
| Question | 88 | 1,045 | 13,082 | 44,463 |
| Answer | 2,244 | 4,098 | 11,270 | 30,715 |
| Snippets (all references) | 0 | 1,155 | 1,870 | 3,217 |
| Question + answer + snippets | 2,945 | 5,421 | 20,661 | 50,540 |

| Per session (all turns) | p50 | p90 | p99 | max |
|---|---|---|---|---|
| Characters | 5,301 | 20,661 | 89,048 | 208,669 |

Total over the window: 1.88M characters for 526 turns (3.57k per turn).

Context policies, total input characters over the same 526 turns:

| Policy | Characters | Per turn |
|---|---|---|
| Current turn only | 1.88M | 3.6k |
| Current + previous 2 turns | 4.16M | 7.9k |
| Current + all previous turns of the session (cap 60k chars) | 7.40M | 14.1k |

## 4. Cost estimate per weekday

Assumptions:
- 1,454 web turns per weekday (the high end of `design.md` §4.4), ~506 sessions (183 per 526 turns);
- ~3.5 characters per token (mixed Polish/English; not measured);
- rubric and instructions ~2k tokens per call; output ~400 tokens per turn and ~600 per session pass.

| Item | Input tokens / weekday | Output tokens / weekday | Cost now ($0.75 / $3.75) | Cost from 2027 ($1.50 / $7.50) |
|---|---|---|---|---|
| Stage 1, per turn, full session context | ~8.8M | ~0.6M | ~$8.8 | ~$17.6 |
| Stage 1, per turn, previous 2 turns | ~6.2M | ~0.6M | ~$6.8 | ~$13.6 |
| Session grade (D19), `gemini-4-argon`, flagged turns only (≤ 20%), whole segment | ≤ ~0.8M | small | unknown price | unknown price |
| For scale: every session graded once on `gemini-3.8-flash` | ~3.0M | ~0.3M | ~$3.4 | ~$6.8 |
| Slack + MCP stage 1 (~115 turns/day, not measured: assumed like web) | ~0.7M | ~0.05M | ~$0.7 | ~$1.4 |
| Calibration (canary + 5% cross-model) | small | small | < $1 | < $2 |
| Stage 2 (`gemini-4-argon`, ≤ 20% of turns, capped documents) | ≤ 9M | ? | unknown price | unknown price |

- Monthly (21 weekdays; weekends are ~5% of a weekday): stage 1 on all channels with full context is **~$200 now, ~$400 from 2027**, excluding stage 2 and session grades (unknown `gemini-4-argon` price).
- §12 estimated "up to ~15M input tokens per weekday" for stage 1. The measured size gives ~9M at most, with the richer context policy.
- **Cheaper option:** the 2k-token rubric is the same in every call. With Vertex context caching (explicit or implicit), it costs a fraction after the first call. That saves up to ~30% of stage-1 input. Prices for cached tokens were not checked.

## 5. Recommendation

- **Context policy (proposal against `design.md` §8.3, which says up to 2 prior turns):** per-turn assessment with the full session context (cap 60k characters, oldest turns dropped first). The extra ~$2 per weekday over "previous 2 turns" buys correct `relation_to_previous` and contradiction checks on long sessions (`conversation-heuristics.md`). Otherwise keep §8.3 as it is.
- **Size caps (D13, Q11):** 30k input tokens per turn bundle, 120k per session grade.
- **No quota request now.** Add backoff and 429 tracking. Revisit if stage-1 coverage drops below 98% because of throttling.
- **Budget alert:** a Cloud Billing budget on the assessor's service account or label, e.g. $50 per week. That guards against a loop bug or traffic spikes.

## 6. Impact on the design (not applied)

- §12: replace the estimates with §4 here (measured input size, current price). The session grade estimate is still missing there; it needs the `gemini-4-argon` price.
- §16 Q3: answered (no fixed quota, shared capacity, backoff). Q4 keeps the `gemini-4-argon` price, launch stage and terms.
- D13 / Q11: caps from §5.
- §11: add the 429 rate to `pipeline_runs` and a budget alert.

## 7. Open points

- `gemini-4-argon`: price, launch stage, data-use terms (SECOPS, Q4).
- Measure the tokenizer ratio on canary (evaluator) text instead of assuming 3.5 characters per token.
- Price of cached input tokens for `gemini-3.8-flash`.

Sources: [Vertex AI generative AI pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing) (introductory and standard `gemini-3.8-flash` rates, checked 2026-10-21).
