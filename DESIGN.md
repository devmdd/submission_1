# Lead-scoring endpoint — design

Date: 2026-11-07. Status: draft for candidate approval (builder check done; fixes applied).

## Intent

Northern Coast gets inbound wholesale leads from 60+ countries. Four KAMs can't call all of them. This endpoint reads one lead conversation and decides: is this worth a KAM's call now (Hot), worth keeping warm (Warm), or not a buyer (Cold) — and routes it.

The scoring intuition from the brief: **import license + product fit + volume (≥1 FCL/month) + real-business signals.**

Two failure modes matter most:
1. **Wasting a KAM's call** on a non-buyer (office-party orders, price fishers, brokers without a license).
2. **Losing a whale in nurture** — the L009 incident: a lead scored Warm at first touch that became a $500K deal.

## Goals / non-goals / anti-goals

- **Goals:** public Vercel URL; POST JSON in, contract JSON out, < 30 s; deterministic, defensible scoring; always returns valid JSON for valid input, even when the LLM fails.
- **Non-goals:** persistence, re-scoring over time, auth, a UI, CRM integration, multi-turn agent behaviour. (README "more time" section covers these.)
- **Anti-goals:** the LLM decides the score (non-deterministic, injectable, indefensible); a response that violates the output contract; a 500 for anything a client sent.

## Contract

Input and output exactly as in `../BRIEF.md`. Output contains **only** `lead_id, score, tier, routing, reasoning` — no extra fields (a strict grader might reject them). Diagnostic signals go in response headers.

## Architecture

```
POST → validate input → [no lead turns? → Cold, skip LLM]
     → extract facts (Gemini, structured output)  ──fail──→ extract facts (keyword fallback)
     → score facts (pure code) → tier → routing → reasoning → JSON
```

The LLM's only job is **reading**: turn a messy, possibly multilingual transcript into a fixed set of facts. Everything that is a business rule — weights, caps, tiers, routing — is plain code. Reasons: deterministic, unit-testable, prompt injection can't set the score, and every rule can be defended line by line in the README.

The keyword fallback produces the **same facts structure**, so scoring code has one path.

## Stack (candidate's decisions)

- **Python** on Vercel's Python runtime.
- **Gemini** via Google's official `google-genai` SDK, using its structured-output (response schema) feature. Candidate has a Gemini key, not a Claude key.
- **Model: `gemini-3.5-flash-lite`** (my call; candidate may override). Stable, fastest/cheapest current model; extraction is a simple task and the 30 s budget favours speed. Verified 2026-11-07 at https://aistudio.google.com/docs/models — note `gemini-2.5-flash` is deprecated and auto-routes to another model from 2026-12-01; do not use it.
- API key in Vercel env var `GEMINI_API_KEY`; never committed.
- Model name in env var `GEMINI_MODEL` with the above as default (so a deprecation is a config change, not a deploy).

## Facts the extractor returns

Only statements made in **lead** turns count as evidence. Agent turns give context (e.g. what question was answered) but an agent asking "are you licensed?" is not the lead being licensed.

| Field | Values |
|---|---|
| `license_status` | `stated` · `in_process` · `none` · `not_mentioned`. `stated` includes a clear import track record ("8 years importing energy drinks"). |
| `volume_fcl_per_month` | number or null. Normalise units: "3 containers a quarter" → 1; "40ft"/"20ft" both count as 1 FCL. Pallets/cases-only → below 1. A range ("2-3 FCL") takes the **low end** (conservative). |
| `volume_recurring` | true / false / null. A per-period volume ("1 FCL/month", "initial volume 1 FCL/month") counts as recurring unless the lead says it's a one-off/trial. |
| `brands` | list of brand names mentioned by the lead |
| `market` | destination country/region or null |
| `consumer_order` | true if it's a personal/office/event purchase, not trade |
| `business_signals` | subset of: `years_trading`, `existing_brands`, `retail_accounts`, `company_named`, `specific_answers` |
| `risk_flags` | subset of: `origin_request` (asks for stock of a specific origin, e.g. "original Austrian product" — normal for some markets, but a parallel-import signal the KAM should confirm), `re_export` (states goods go to a different market than where they're based), `too_good_to_be_true` |
| `summary` | ≤ 20-word neutral summary of the lead, English |

If the lead contradicts itself, the **latest** statement wins. Non-English input is read in the original language; `summary` is English.

## Scoring (candidate's rules; weights are my proposal)

Score 0–100 = sum of four parts:

| Part | Max | Points |
|---|---|---|
| License | 30 | `stated` 30 · `not_mentioned` 15 · `in_process` 15 · `none` 0 |
| Volume | 30 | ≥ 3 FCL/mo recurring 30 · ≥ 2 recurring 22 · ≥ 1 recurring 15 · ≥ 1 one-off 10 · not stated 5 · < 1 FCL 0 |
| Fit | 20 | brand we carry 15 (other beverage brand 5, none named 5) + market named 5 |
| Business signals | 20 | 5 per distinct signal, max 4 counted |

Catalog of brands we carry is a constant in code: Coca-Cola (incl. Coke, Sprite, Fanta), Monster, Red Bull. The brief says "etc." — the list is a known simplification.

**Hard rules (candidate's decisions):**
- License `in_process` or `none` → **capped at Warm** (score ≤ 84). Can't close today, however good the rest is.
- License `not_mentioned` → **neutral**: half points, no cap. Max total is 85, so Hot needs near-perfect everything else — but a strong lead (≥ 70) still routes to `kam_handoff` via the Warm band below, and the KAM verifies the license on call 1.
- `consumer_order` → **Cold**, score capped at 15.
- No lead turns at all → Cold / `auto_archive`, score 0, no LLM call.
- `risk_flags` **do not change the score**; they are named in `reasoning` for the KAM to judge.

**Tiers:** Hot ≥ 85 · Warm 40–84 · Cold < 40.

**Routing (Option B, candidate's decision):** tier and routing are separate decisions.
- Hot → `kam_handoff`
- Warm **and** score ≥ 70 **and** license `stated` or `not_mentioned` → `kam_handoff` (grey-zone lead with no known blocker: worth a KAM touch — the L009 lesson; KAM verifies an unmentioned license on call 1)
- other Warm → `nurture_pool`
- Cold → `auto_archive`

Why these numbers: they reproduce the brief's L001 example (score ~78–80, **Warm**, `kam_handoff`). Expected on the samples:

| Lead | License | Volume | Fit | Signals | Score | Tier | Routing |
|---|---|---|---|---|---|---|---|
| S001 UAE Red Bull | 30 | 22 ("2-3" → 2) | 20 | 15 | 87 | Hot | kam_handoff (+ origin_request note) |
| L001 Singapore Monster | 30 | 15 | 20 | 15 | 80 | Warm | kam_handoff |
| S003 Ghana Coca-Cola | 15 (in process → capped at Warm) | 15 | 20 | 0–5 | 50–55 | Warm | nurture_pool (+ "re-score once licensed ~6 wks") |
| S002 office party | — | — | — | — | ≤ 15 | Cold | auto_archive |

Thresholds are uncalibrated guesses; the README says so and lists calibration against historical conversions as the first "more time" item.

## Reasoning text

Built in code: `summary` + one clause explaining the tier/routing decision (e.g. "capped at Warm: license in process — re-score once licensed", "Warm but licensed with committed volume — KAM follow-up") + any risk flag. 1–2 sentences. Always consistent with the score, because code wrote both.

## Failure handling

| Case | Response |
|---|---|
| Method other than POST | 405 `{"error": "method_not_allowed"}` |
| Body not JSON | 400 `{"error": "invalid_json"}` |
| `lead_id` missing/not a non-empty string; `conversation` missing, not a list, or empty; a turn without string `text` | 400 `{"error": "invalid_input", "detail": "<field>"}` |
| Extra fields, missing `channel`, unknown `role` value | accepted, ignored (unknown roles treated as non-lead) |
| Body > 50 KB or > 100 turns | 413 `{"error": "payload_too_large"}` — bounds LLM cost per call |
| Gemini timeout (11 s per attempt), error, rate limit, or output failing schema | keyword fallback; 200 with valid contract; `reasoning` notes "scored by fallback rules"; header `X-Scoring-Mode: fallback` (else `llm`) |
| `GEMINI_API_KEY` unset | fallback (so the endpoint still answers), logged loudly |
| Anything unexpected in our code | 500 `{"error": "internal_error"}` with no stack trace |

One retry on the Gemini call, only for 429/503 and transient network errors/timeouts (added after live testing saw 503s on ~25% of calls). 11 s per attempt: worst case 2 × 11 s + ≤ 1.5 s wait ≈ 23.5 s, inside 30 s. Then the fallback.

**Prompt injection:** transcript is passed as delimited data with an instruction that it is untrusted content to extract from, not instructions. Even if the model is fooled, it can only misreport facts — it cannot set the score, tier, or routing directly.

**Logging:** one line per request: `lead_id`, mode (llm/fallback/skipped), latency, tier. No transcript text (it's customer data).

## Testing

- Unit checks on scoring + routing with hand-built facts (the four sample rows above, cap cases, consumer override, boundary scores 39/40/69/70/84/85).
- Fallback extractor run against the 3 samples + L001 — must give the same tiers as the table (fallback may be coarser on score).
- Input validation cases from the failure table.
- Live smoke test against the deployed URL with the 3 samples + L001 + one injection attempt + one non-English lead.

## Deliverables (in `test-1-build/submission/`)

Code, `README.md` (~200 words: model + why, scoring weights defended, Option B and the L001 discrepancy, the Warm cap tradeoff vs L009, what with more time), this `DESIGN.md`, and the deployed URL + repo URL.

## Left to the builder

File layout; whether to use a tiny ASGI/WSGI framework or the plain handler Vercel's Python runtime accepts (prefer fewest dependencies — `pydantic` already comes with `google-genai`); keyword lists for the fallback; exact prompt wording.

## Needs the candidate (at deploy time)

Vercel account, GitHub/GitLab repo, Gemini API key. `vercel` and `gh` CLIs are not installed locally.
