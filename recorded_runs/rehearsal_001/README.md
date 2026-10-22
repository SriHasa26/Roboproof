# rehearsal_001: REHEARSAL, NOT AN OFFICIAL RESULT

Produced by `scripts/run_rehearsal.py` on 2026-10-22 with real Nemotron calls via Nebius Token Factory (no cache, `LLM_DEV_CACHE=0`) and the local fallback runner (**LocalRunner, not Nebius Serverless Jobs**). Verification sets came from the **rehearsal** seed block (800000 to 801599, four single-use blocks of 400). **Held-out seeds (>= 900000) were not generated or run.** One run, one seed: it shows the machinery works end to end, not how reliable it is.

| Run | Patch | Verdict | Checks |
|---|---|---|---|
| best-found patch | ceiling-search best (scripted; found on dev sets) | VERIFIED | G1-G6 pass; G4: 1 regression of 188 (budget 3), strict zero-budget FAILS |
| scripted trap | grip 80 + hold 60 (scripted example, not model output) | FAILED | G4 fail (6 regressions > budget 3); G5 fail (diagnostic: 0.83 < 0.90, improvement 0.0975 < 0.10) |
| no-op patch | identical to default | FAILED | G3 fail (0% fixed); G5 fail (diagnostic: improvement 0) |
| crashed shard | best-found patch, one shard killed | UNVERIFIED | G6 fail; G3/G4/G5 not_run |
| **full pipeline, real models** | model-proposed, attempt 2 | VERIFIED | attempt 1 failed G3 (fix rate 0.51 < 0.70); attempt 2 passed G1-G6, G5: 0.96 vs 0.69 unpatched |

Targeting for the first four runs is a fixed code rule (baseline failures with mass > 0.5 and friction < 0.4); only the last run uses analyst-chosen targets (45 failures inside 4 hypothesis regions). "Diagnostic" G5 means G5 was run although an earlier check had already failed, which the gate allows on rehearsal blocks only.

Files: `analysis_set.json` (scenarios + the validated model-proposed regions), `baseline_results.json`, `evidence.json`, `hypotheses.json`, `targeted_failures.json`, `gate_*.json` (full `GateReport`s), `llm_transcript.json` (verbatim prompts and replies), `summary.json` (timings, tokens, estimated cost, seed ledger), `run_console.log`.
