# rehearsal_001: per-stage wall-clock (REHEARSAL, not an official result)

Measured with stage timers in `scripts/run_rehearsal.py` on a 12-CPU machine, LocalRunner. Source: `summary.json` (`timings_s`, `llm_calls`).

| Stage | Seconds | Kind |
|---|---:|---|
| 1 generator call (Nano) | 32.53 | LLM |
| 2 baseline run (250 scenarios) | 8.59 | simulation |
| 3 evidence | 0.03 | code |
| 5 analyst call (Ultra) | 13.03 | LLM |
| 6 gate prepare (G1 re-run + G2 re-run, **not timed separately in this run**) | 2.17 | simulation |
| 7 fixer call, attempt 1 | 4.70 | LLM |
| 8 dev stage, attempt 1 (patched analysis run, G3/G4) | 9.92 | simulation |
| 7 fixer call, attempt 2 | 9.16 | LLM |
| 8 dev stage, attempt 2 | 12.54 | simulation |
| 9 G5 verification (unpatched + patched, 400 scenarios each; **not split in this run**) | 34.61 | simulation |
| **Pipeline subtotal** | **127.3** | LLM 59.4 s (47%), simulation/gate 67.9 s (53%) |
| 4 four fixed-patch gate runs (best-found 40.4, trap 42.6, no-op 40.8, crashed shard 14.2) | 137.9 | simulation |
| **Whole script** | **265.2** | LLM 59.4 s (22%), simulation/gate 205.8 s (78%) |

The sum of the four per-call LLM latencies is 58.8 s, consistent with the LLM stage timers.

## Correction

The P4 report said the run took "about 5 minutes of wall-clock, mostly simulation". More precisely: the whole script took 4.4 minutes, 78% of it simulation, but most of that simulation was the four fixed-patch gate runs (138 s) that are not part of the model pipeline. For the pipeline alone (2.1 minutes) LLM calls were **47%** of the time, so it was not "mostly simulation". A single 250-scenario run is only about 9 s; the cost of a gate run comes from repeating runs (baseline, G1 and G2 re-runs, one patched run per attempt, and G5 on 800 scenarios).

From the next run on, `GateReport.timings_s` records G1 re-run, G2 re-run, each patched analysis run and the two G5 runs separately, and every pipeline artifact records all stage timers.
