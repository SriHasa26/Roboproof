# What RoboProof does not show

Plain-language limits, each tied to something we measured. Nothing here is a hedge for its own sake.

## It is a simulation of a simplified robot
- The robot is a two-finger gripper on a palm that moves perfectly to wherever it is told. There is no real arm: no joint limits, no inverse kinematics, no vibration, no arm collisions. Grasps come from PyBullet contact friction, which is an approximation. See `docs/SIM_FIDELITY.md`.
- Perception is a cube position plus random noise. There is no camera, no occlusion and no latency in sensing.
- Nothing was run on a real robot. A VERIFIED verdict means "passed this gate in this simulator", not "safe on hardware".
- The starting policy is a hand-designed controller. Its default numbers were chosen, using development seeds only, so that it passes roughly 70% of a broad sweep and fails in physically meaningful regions. It is deliberately imperfect, so there is something to fix.
- Identical seeds give identical results on the machine and container image we used (tested in-process and across fresh processes). We do not claim bit-identical physics on other hardware.

## What the gate can and cannot say
- **Some failures cannot be fixed by the allowed numbers.** The fixer may only change five control parameters. In our development search, every failure left under the best parameters had sensor noise of about 0.018 m or more (axis range 0 to 0.03 m). The gate's G3 check counts targeted failures in such regions too, so a hypothesis about noise can make the 70% fix requirement hard to meet. In a rehearsal run, the best candidate fixed 19 of 38 noise-region targets while the two parameter-fixable regions reached about 72%.
- **The thresholds were calibrated on development data.** The 0.90 held-out target was set about 7 points under the best pass rate found by a 71-policy search on development scenarios (best 96.7%). The 2% regression budget was chosen so that VERIFIED is reachable. Neither was tuned on the held-out seeds, but they are judgments, not laws.
- **The strict zero-regression check is stricter, and it matters.** In the official batch, 2 of the 4 VERIFIED runs (seeds 3202 and 3505) had regressions (3 and 1 previously passing scenarios that now fail) and would not have passed a zero-regression budget. The dashboard shows this next to every G4 result.
- **Held-out results are noisy.** Each verification set has 400 scenarios. A patch whose true pass rate is near 0.90 passes G5 about half the time. In the rehearsal studies two patches missed the target by 6 and by 1 scenario (354/400 and 359/400 against the 360/400 required); in the official batch run 3 reached 348/400, 12 short. Near misses are reported as FAILED.
- **Five official runs are a small sample.** 4 of 5 VERIFIED has a Wilson 95% interval of roughly 38% to 96%. Pipeline v1 (1 of 5 in rehearsal) and v2 (4 of 8 in rehearsal) have intervals that overlap heavily with the official one. We report all of them, not just the best.
- **The verification sets are broad Latin-hypercube sweeps.** They are not the risk-weighted mix used to generate the analysis set, because the targets were calibrated on broad sweeps.

## What the AI parts are and are not
- The models propose scenarios, explain failures and propose parameter changes. They never decide pass or fail; the simulator and the gate do. Their explanations are labelled unverified, and every number shown comes from code.
- A model's reply can be wrong or malformed: in rehearsal the fast model's output failed validation in 3 of 8 pipeline-v2 runs (a second Nemotron model took over each time), and in v1 two runs of five were lost at that step. The analyst failed validation once in v2.
- `enable_thinking: false` (used to turn off hidden reasoning in the fast model) is passed through Token Factory but is not documented by Nebius, so it could change. The fast model's chat endpoint also hung for at least 39 minutes during development (observed on 2026-10-22); the pipeline now has a timeout and a fallback for that.
- The client does not record why a reply ended; a reply cut off by its token cap would only be rejected because it fails the schema. No capped reply was accepted in any recorded run.

## Where it ran
- Simulations ran on a local machine inside a Docker container, **not on Nebius Serverless Jobs**. The container was not tested on Nebius. Every run is labelled "local fallback, not Nebius".
- Language-model calls used Nebius Token Factory with NVIDIA Nemotron models.
- Cost figures are estimates (tokens times the per-token prices the API reports). Actual billing was not checked and is UNCONFIRMED.
