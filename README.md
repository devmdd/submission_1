# Northern Coast lead scorer

- **Endpoint:** `POST https://submission-1-seven.vercel.app/api/score`
- **Repo:** https://github.com/devmdd/submission_1
- **Time spent:** ~1.5 hours
- Design and trade-offs: [`DESIGN.md`](DESIGN.md)

```
curl -X POST https://submission-1-seven.vercel.app/api/score -H 'Content-Type: application/json' --data @samples/L001.json
```

## What model and why

`gemini-3.5-flash-lite`. I only ask the model to **read** the conversation and fill in a fixed list of facts: license status, FCL per month, brands, market, business signals and risk flags. Plain Python turns those facts into the score, tier and routing. That keeps scoring predictable, testable and safe from "ignore your instructions" messages. Reading is an easy job, so I picked the fast, cheap model to stay well under 30 s. My AI assistant suggested `gemini-2.5-flash`; I didn't use it because it's deprecated. If Gemini fails, a keyword reader fills in the same facts. The `X-Scoring-Mode` header shows which path was used.

## The rules I chose

- Points: license 30, volume 30, product/market fit 20, business signals 20. Hot is 85 or more, Warm 40–84, Cold below 40.
- **License in process → Warm at most.** The lead can't buy today.
- **License not mentioned → half points.** The KAM checks it on the first call.
- **A Warm lead scoring 70+ with no license problem still goes to a KAM.** The brief's own example (L001: Warm, `kam_handoff`) works this way, and it stops a big lead being lost in nurture.

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
