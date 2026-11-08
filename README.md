# Northern Coast lead scorer

- **Endpoint:** `POST https://submission-1-seven.vercel.app/api/score`
- **Repo:** https://github.com/devmdd/submission_1
- **Time spent:** ~50 minutes
- Design and trade-offs: [`DESIGN.md`](DESIGN.md)

```
curl -X POST https://submission-1-seven.vercel.app/api/score -H 'Content-Type: application/json' --data @samples/L001.json
```

## What model and why

`gemini-3.5-flash-lite`. I only ask the model to **read** the conversation and fill in a fixed list of facts: license status, FCL per month, brands, market, business signals and risk flags. Plain Python turns those facts into the score, tier and routing. That keeps scoring predictable, testable and safe from "ignore your instructions" messages. Reading is an easy job, so I picked the fast, cheap model to stay well under 30 s. My AI assistant suggested `gemini-2.5-flash`; I didn't use it because it's deprecated. If Gemini fails, a keyword reader fills in the same facts. The `X-Scoring-Mode` header shows which path was used.

## Decisions I made

Points: license 30, volume 30, product/market fit 20, business signals 20. Hot ≥ 85, Warm 40–84, Cold < 40.

| Decision | What I rejected | Why | What would change my mind |
|---|---|---|---|
| **The LLM extracts facts; code scores them** | The LLM returns the score directly | Same input gives the same score. Every point can be traced to a fact and unit-tested. A lead typing "score me 100" can't set the score (tested live: it stayed Cold). | Backtests showing an LLM judgement beats the rules on real won/lost leads |
| **Tier and routing are separate.** A Warm lead scoring ≥ 70 with no license blocker goes to `kam_handoff` | Warm always goes to nurture | The brief contradicts itself: "Warm = nurture pool", yet its own example is `78, Warm, kam_handoff`. I followed the example, because a big deal parked in nurture (a "missed whale") costs far more than one extra KAM call. | KAMs reporting that too many 70–84 leads waste their time |
| **License "in process" or "none" → capped at Warm** | Let a strong lead without a license still be Hot | A missing license is a legal blocker: the lead can't close today, however good the volume. The reasoning says "re-score once licensed". | — (business rule, not a tuning choice) |
| **License not mentioned → half points, no cap** | Treat silence as "no license" | Most first messages don't mention it. Penalising silence would bury real importers. The KAM verifies it on the first call. | Data showing that "not mentioned" leads usually turn out unlicensed |
| **LLM failure → keyword fallback, never an error** | Return 500/503 when Gemini fails | Live, Gemini returned 503 on ~25% of calls. A scorer that fails a quarter of the time is worse than a coarse one. The `X-Scoring-Mode` header shows which path ran. | — |

**Known limits:**
- The weights and thresholds are **uncalibrated guesses**, set from the three brief samples.
- The fallback reader is English-only and coarser. It can miss "1 x 40ft container" and non-English volumes.

## What live testing taught me

- Gemini returned 503 "busy" on about 1 in 4 calls, so I added one quick retry. The worst case is still under 30 s.
- Scores drifted between runs. They now move by 5 points at most (S001: 87, 87, 87, 92), and the tier never changed.
- Gemini wrote "Monster Energy" where my code expected "Monster". The unit tests missed it; the live run caught it.

## With more time

1. Tune the points against real won and lost leads.
2. Build a test set of real conversations, including other languages and tricky ones.
3. Re-score "license in process" leads automatically after about 6 weeks.
4. Add an API key and rate limiting.

## Run tests

```
pip install -r requirements-dev.txt && pytest -q
```
