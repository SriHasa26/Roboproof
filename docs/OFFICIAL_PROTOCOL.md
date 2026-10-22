# Official evaluation protocol (pre-registered)

Written and committed on 2026-10-22, **before any official run** and before the pipeline-v2 reliability study (reliability_002). It is part of the frozen pipeline (its hash is in `backend/app/core/FROZEN_PIPELINE_HASH.txt`), so changing it requires a deliberate re-freeze and a new tag. The commit that last changed this file is recorded in every official run's artifacts (`provenance.protocol_commit`).

## 1. What is evaluated

- **Pipeline v2**, git tag `pipeline-frozen-v2`. An official run refuses to start unless the working tree is clean, the frozen files equal their content at that tag, this document is committed, the image build id is known, and no threshold override is set in the environment.
- **Models** (ids are recorded in each run's artifacts): scenario generator = `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` with hidden reasoning off, falling back to `nvidia/nemotron-3-super-120b-a12b`, then to a coverage-only analysis set labelled `coverage_only_fallback`; analyst and fixer = `nvidia/Nemotron-3-Ultra-550b-a55b` with reasoning on. All via Nebius Token Factory.
- **Runner:** `LocalRunner`, the local fallback. It is labelled "local fallback, not Nebius" in every artifact. If simulations later run on Nebius Serverless Jobs, that is a separate batch under an amended protocol, never a silent change.
- **Simulation only.** The simulator is frozen (tag `sim-frozen`); nothing here has been validated on a real robot.

## 2. Fixed thresholds (`backend/app/core/gate_config.py`)

| Check | Rule |
|---|---|
| G1 determinism | 30 evenly spaced baseline scenarios re-run in fresh processes; every result identical |
| G2 reproduced | every targeted failure fails again on the unpatched policy |
| G3 fixed | targeted failures now passing / targeted >= 0.70 (exact fraction, inclusive) |
| G4 no regressions | regressions <= floor(0.02 x previously passing) (exact, inclusive); the strict zero-budget result is reported next to it |
| G5 held-out | on a fresh code-only verification set of **400** scenarios from a single-use held-out block: patched pass rate >= 0.90 (exact, inclusive); improvement over the unpatched policy on the same set >= 0.10 (exact, inclusive); and the patched Wilson 95% lower bound > the unpatched pass rate |
| G6 complete | every run the verdict relies on finished with no failed or timed-out shard |

Verdict: UNVERIFIED if G6 fails or a check could not run; otherwise FAILED if a check that ran failed; otherwise VERIFIED. These values are fixed by this document. They will not be changed after seeing any official result, and no official run may override them through environment variables.

## 3. Procedure of one official run

1. Analysis set: 250 scenarios, about 60% Latin-hypercube coverage and 40% from model-proposed regions (dev seed block), from the run's master seed.
2. Baseline run of the default policy; evidence computed in code; the analyst proposes hypotheses (grounded in evidence ids); targeted failures are chosen by code.
3. Up to **3 attempts**. Each attempt: the fixer proposes **4 diverse candidate patches**; code measures **every** candidate on the analysis set; the candidate is chosen by the deterministic rule in `backend/app/analysis/selection.py` (highest targeted fix among candidates within the regression budget; ties: fewer changed parameters, then lower grip force, then lower index; none within budget: fewest regressions). Only the selected candidate goes through G1 to G4. The fixer never sees any verification-set number.
4. If G1 to G4 pass: G5 runs **once** on a fresh held-out block of 400 seeds allocated by the ledger (`seed_ledger`, single use). If G3 or G4 failed on all three attempts, the verdict is FAILED and G5 is `skipped_after_failure`. G5 is terminal: a failed G5 is final and the fixer is not given a second chance on the same seeds.

## 4. The batch

- **K = 5 official runs**, each with a different master seed and its own fresh held-out block.
- **Master seeds, in order:** 3101, 3202, 3303, 3404, 3505. Run ids `official_01_seed3101` to `official_05_seed3505`; artifacts in `recorded_runs/official_001/`.
- All five are run unless a stop condition below applies. They are reported together.

## 5. Reporting rules (fixed in advance)

- **Every run is reported.** No best-of selection, no discarded runs, no re-rolls for a better verdict.
- Report: verdict counts; the **VERIFIED rate with its Wilson 95% interval**; attempts per run; for each run the analysis-set and verification-set pass rates before and after with Wilson intervals; collision rate; mean completion time of successes; the generator source and model per run (including any `coverage_only_fallback`); the candidate tables; tokens, per-stage time (LLM versus simulation) and an estimated cost (marked as an estimate).
- A run that ends without a verdict for a reason other than infrastructure (for example the generator and every fallback failing validation and no targeted failures existing) is reported as such and counts as a run.
- **Headline rule: the demo video and the README headline show run 1** (`official_01_seed3101`), side by side with the table of all five runs. It is never replaced by a better-looking run.

## 6. When a run may be repeated

- An **infrastructure error** is a timeout, connection error or HTTP 5xx from the model API, or a failure of the container or machine, that occurs **before G5 executed** ("executed" means both verification runs completed and G5 produced pass or fail).
- Such a run may be repeated **once** with a new run id (`..._repeat1`). The original failure stays in the log and in the report. The original run's held-out block, if one was allocated, is marked `retired_unused` in the ledger: it is **never reused**; the repeat gets a fresh block.
- **A run where G5 executed is final**, whatever its verdict.
- Validation failures, FAILED and UNVERIFIED verdicts caused by the gate, and runs lost to the generator are **not** infrastructure errors and are never repeated.
- Stop the batch and report if the API returns 401 or 402, or repeated 429.

## 7. Context disclosed in advance

- Pipeline v1 reliability study (rehearsal blocks, `recorded_runs/reliability_001`): 1 of 5 runs VERIFIED, 2 FAILED, 2 without a verdict (generator validation).
- The pipeline-v2 rehearsal study (8 runs, `recorded_runs/reliability_002`) is run after this document is committed and is reported honestly whatever it shows. The official batch is a separate decision made by the project owner.
- The thresholds were derived from a dev-seed ceiling search (`docs/CEILING_SEARCH.md`); held-out seeds were not used for any choice.
- There is a real chance that few or no official runs are VERIFIED. That result will be reported as it is.
