# reliability_001: REHEARSAL STUDY, NOT AN OFFICIAL RESULT

Rebuilt from the saved run files (nothing re-run). Master seeds fixed in advance (101 202 303 404 505); no run was re-rolled for its verdict. Runs with no verdict failed in the scenario generator (validation failed after its single retry): that is not an infrastructure error, so they were not re-run. LocalRunner (labelled fallback, not Nebius). Rehearsal seed blocks only; held-out seeds were never run.

Runs: 5. Verdicts: {'VERIFIED': 1, 'FAILED': 2, 'UNVERIFIED': 0, 'ERROR (no verdict)': 2}. Attempts needed (runs with a verdict): {3: 2, 2: 1}.

| Run | Seed | Verdict | Attempts | Dev-stage checks failed, per attempt | Final G1-G6 | Analysis pass before -> after | Verification pass before -> after | Tokens (p/c) | Wall s (LLM s) | Est. cost |
|---|---|---|---|---|---|---|---|---|---|---|
| run_01_seed101 | 101 | ERROR: LLMValidationError: scenario_generation: output failed validation after retry: 1 | 0 | [] | n/a | n/a -> n/a | n/a -> n/a | 2297/492 | 7.63 (7.58) | 0.000256 |
| run_02_seed202 | 202 | FAILED | 3 | [['G3'], ['G3'], []] | G1=pass G2=pass G3=pass G4=pass G5=fail G6=pass | 70.4% [64.5%, 75.7%] -> 82.8% [77.6%, 87.0%] | 69.2% [64.6%, 73.6%] -> 84.2% [80.4%, 87.5%] | 19471/15083 | 159.34 (52.09) | 0.06304 |
| run_03_seed303 | 303 | VERIFIED | 2 | [['G3'], []] | G1=pass G2=pass G3=pass G4=pass G5=pass G6=pass | 61.6% [55.4%, 67.4%] -> 93.2% [89.4%, 95.7%] | 70.8% [66.1%, 75.0%] -> 95.0% [92.4%, 96.7%] | 10139/6820 | 133.47 (23.21) | 0.028883 |
| run_04_seed404 | 404 | FAILED | 3 | [['G3'], ['G3'], ['G3', 'G4']] | G1=pass G2=pass G3=fail G4=fail G5=skipped G6=pass | 62.0% [55.8%, 67.8%] -> 74.4% [68.7%, 79.4%] | n/a -> n/a | 13032/13871 | 105.01 (48.8) | 0.050789 |
| run_05_seed505 | 505 | ERROR: LLMValidationError: scenario_generation: output failed validation after retry: 1 | 0 | [] | n/a | n/a -> n/a | n/a -> n/a | 2366/628 | 10.06 (10.01) | 0.000293 |

Pass rates are shown with Wilson 95% intervals. Cost is an ESTIMATE (tokens x the per-token prices the API reports); actual billing UNCONFIRMED.

## Min / median / max

- total_tokens: {'min': 2789, 'median': 16959, 'max': 34554, 'n': 5}
- wall_clock_total_s: {'min': 7.63, 'median': 105.01, 'max': 159.34, 'n': 5}
- llm_seconds: {'min': 7.58, 'median': 23.21, 'max': 52.09, 'n': 5}
- estimated_cost_usd: {'min': 0.000256, 'median': 0.028883, 'max': 0.06304, 'n': 5}

## Does the model add value in scenario generation? (baseline failure rate, default policy)

- coverage scenarios: 126/450 fail = 0.28 (Wilson95 [0.2405, 0.3232])
- model-targeted scenarios: 139/300 fail = 0.4633 (Wilson95 [0.4077, 0.5199])
- Pooled over the runs above. Region rationales from the model are unverified opinions; only these code-computed rates are evidence.

## Observations (n = 5, rehearsal; not a statistical claim)

- **1 of 5 runs was VERIFIED (run_03), 2 were FAILED (run_02 at G5, run_04 at G3/G4), 2 produced no verdict** because the scenario generator's output failed validation after its single retry (run_01, run_05: a region under the 2% volume floor). That is 2 of 5 runs lost to the generator step, in line with the 1-in-5 per-call failure seen when the fast model was probed (docs/NEBIUS_NOTES.md section 8). These two were not infrastructure errors, so they were not re-run.
- **No run passed on the first fixer attempt.** Attempt-1 G3 fix rates were 0.675 (run_02), 0.551 (run_03) and 0.211 (run_04); the threshold is 0.70.
- **run_02:** the third patch (grip_force 30, grasp_hold_steps 40) cleared G3 at exactly 0.70 with no regressions, then did not generalise: 84.2% on the fresh verification set against the 0.90 target, an improvement of 15 points over the unpatched 69.2%. The gate rejected a patch that was better than nothing but not good enough.
- **run_04:** after two weak patches (fix rates 0.211 and 0.620) the third (grip_force 60 alone) was *worse* on G3 (0.352) and added 4 regressions (budget 3), so G4 failed too; G5 was skipped. The fixer did not use the earlier, better direction (attempt 2 combined more levers) and never proposed the multi-lever combination found by the ceiling search (grip ~59, hold 86, retries 3, lift speed ~0.59). Whether this is the model, the prompt or the information it gets is not established by this study.
- **run_03:** attempt 2 (grip_force 40, retry_count 2, lift_speed 0.15) fixed 87% of targets with no regressions and reached 95.0% on the verification set (unpatched 70.8%).
- **Unpatched verification pass rates** were 69.2% and 70.8% in the two runs that reached G5, consistent with the roughly 72% of the earlier broad-sweep baselines.
- **Model-targeted scenarios failed more than coverage scenarios** with the constrained prompt (46.3% against 28.0%, non-overlapping Wilson intervals, from the three runs that got a baseline). With the old, unconstrained prompt in rehearsal_001 they did not (22.0% against 26.7%). The mix was not tuned. Note that this also lowers the analysis-set baseline pass rate (about 62% to 70%) compared with a pure coverage sweep.
- **Totals:** 84,199 tokens and an estimated $0.143 for all five runs (ESTIMATE from API prices; actual billing UNCONFIRMED). Wall-clock per run with a verdict was 105 to 159 s, of which 23 to 52 s was LLM time.
