# P4.6 findings: pipeline v2 rehearsal study (reliability_002)

Rehearsal blocks only; held-out seeds were never run; LocalRunner (local fallback, not Nebius). 8 runs, master seeds 611 622 633 644 655 666 677 688 fixed in advance, no run re-rolled. Raw data: `recorded_runs/reliability_002/` (summary.md has every run and the candidate tables). Pipeline v1 is the record in `recorded_runs/reliability_001/`.

## Result

| | v1 (5 runs) | v2 (8 runs) |
|---|---|---|
| VERIFIED | 1 (20%, Wilson 95% [4%, 62%]) | **4 (50%, [22%, 78%])** |
| FAILED | 2 | 3 (two at G5, one at G3) |
| no verdict | 2 (generator validation) | 1 (analyst validation) |
| runs that cleared G1-G4 on the first attempt | 0 of 3 with a verdict | 6 of 7 with a verdict |
| estimated cost | $0.143 for 5 runs | $0.298 for 8 runs (median $0.032 per run, max $0.070) |

The stop rule ("VERIFIED rate below 50%") was **not** triggered (it is exactly 50%), so nothing was changed after seeing the results. The two intervals overlap heavily: with these sample sizes the data are consistent with a real improvement and with chance. What is solid is the mechanism-level evidence below, not the headline rate.

## What the v2 changes did (evidence per change)

- **Generator chain and partial acceptance.** The fast model (Nano) failed validation after its retry in **3 of 8 runs** (633, 666, 677); the second Nemotron model (Super-120B) produced valid regions every time, so all 8 runs had an LLM-made analysis set. Under v1's rules, those 3 runs would have had no analysis set (v1 lost 2 of 5 runs this way). Partial acceptance kept the valid regions of a proposal in all 8 runs, dropping 0 to 4 regions each (reasons: below the 2% volume floor, or more than 3 axes). One Nano failure shape was new: in run_06 the reply used the key `region_name` instead of `name` (and German region names), so every region failed "Field required" on both tries; runs 03 and 07 show the same "Field required" error on both tries (their raw replies were not inspected).
- **Fixer candidates chosen by code.** In 6 of 7 runs that had a verdict the first selected candidate already passed G1-G4 (v1: none of 3 did). Candidate quality varies a lot within one attempt: in run 5, attempt 1, the four candidates fixed 16, 29, 22 and 11 of 67 targets, so the spread is what the selection rule exploits. Run 4 shows the rule's budget filter working: candidate 3 tied candidate 1 on fixes (55/69) but had 3 regressions against a budget of 2 and was excluded.
- **Model-targeted scenarios.** With the constrained prompt, scenarios from model-proposed regions fail more often under the default policy than coverage scenarios: 369/800 = 46.1% (Wilson 95% [42.7%, 49.6%]) against 337/1200 = 28.1% ([25.6%, 30.7%]). Intervals do not overlap. (With the unconstrained v1 prompt in rehearsal_001 they did not: 22.0% against 26.7%.) The mix was never tuned.

## Failures in v2, with the real reasons

1. **Two G5 near-misses, both patches had passed G1-G4.** run_03: 354/400 = 88.5% on the fresh set (unpatched 288/400); run_04: **359/400 = 89.75%** against the 360/400 the fixed 0.90 target requires, i.e. **one scenario short** (unpatched 290/400). Both improved the pass rate by 16 to 17 points and cleared the improvement and Wilson conditions; only the target failed. The target was not touched. These are what a 400-scenario test does near a threshold: a patch whose true rate is near 0.90 passes about half the time.
2. **run_05 never cleared the dev stage (G3 failed on all 3 attempts).** The best candidate overall fixed 44 of 67 targeted failures (0.66; needs 0.70). The hypotheses covered 4 regions: the two parameter-fixable ones (H1 heavy and slippery, H4 slippery and small) reached 73% and 72%, but H2 (sensor noise 0.02 to 0.03, 38 of the 67 targets) reached only 19/38 and H3 (gripper delay 12 to 16) 10/17. Noise-driven failures are the ones the dev-seed ceiling search found parameters cannot fix (`docs/CEILING_SEARCH.md`). When a hypothesis targets such a region, a 70% fix requirement over all targets becomes hard to meet. The model saw per-hypothesis results after attempt 1 and its later candidates still did not get past 0.66.
3. **run_06 had no verdict: the analyst failed validation twice.** The first reply cited an evidence id that does not exist (`E49`, rejected by the code-side grounding check); the retry used scenario axes (`sensor_noise_m`, `size_m`, `gripper_delay_steps`) as policy "levers" (4 errors). Both rejections are the validation working as designed; the run was lost because the analyst has one retry.

## Weaknesses noticed (not changed: the pipeline is frozen and you asked for one iteration)

- **The LLM client does not record `finish_reason`.** In v1 run_02 a fixer call used exactly its 6,000-token cap and returned 26,467 characters of reasoning prose in `content`, ending mid-sentence. The extractor pulled the first brace pair out of it (`{"grip_force": 20.0}`); that failed schema validation and the call was retried, so no wrong answer was accepted, but only because the snippet did not fit the schema. In v2 no call reached its cap (largest: fixer 5,150 of 6,000; analyst 7,271 of 10,000; generator 596 of 1,500), but the headroom is thin and the protection is accidental.
- **The gate checks only the last attempt's selected candidate**, not the best one across attempts. In run_05 attempt 2 had the best candidate (0.66) and attempt 3's (0.58) was gated. This would not have changed that run's verdict (0.66 < 0.70) but is a design limitation.
- **Aliases for near-miss keys are not tolerated** (`region_name`), and the analyst has a single retry.

## Decisions for the project owner (nothing below was implemented)

1. Record `finish_reason`, treat a truncated reply as invalid and never parse it (small, safe; needs a re-freeze and a new tag).
2. Carry the best candidate across attempts into the gate (changes which candidate is gated; needs a re-freeze).
3. Whether G3 should be computed over targets from parameter-fixable hypotheses only, or the analyst told which regions parameters can fix. This changes the meaning of G3 and so is a protocol decision, not a tuning one; I recommend against changing any threshold.
4. Nothing about the thresholds: G5 near-misses are the pre-registered outcome and must be reported as FAILED.
