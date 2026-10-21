# Simulator fidelity and tuning log

The simulator is `backend/app/sim/pickplace.py` (PyBullet, DIRECT mode, 240 Hz). It is a simulation, not a real robot. Nothing here has been validated against hardware.

## What is modelled

- A two-finger parallel gripper. Each finger is a force-limited prismatic motor (velocity control, force = `grip_force`). The fingers are coupled by a gear constraint so they mirror each other, as a linkage would.
- Real PyBullet contact friction between the fingers and the cube (finger friction fixed at 1.0, cube friction = scenario `friction`). Grasp strength, slip and drops come from the contact solver, not from a formula.
- Cube mass and size from the scenario; a low wall (6 cm) between the pick and place positions; a circular target zone (radius 4.5 cm).
- Sensor noise: the policy perceives the cube position with Gaussian noise (`sensor_noise_m`), drawn from `numpy.default_rng(scenario.seed)`.
- Gripper latency: finger commands take effect `gripper_delay_steps` physics steps late.
- Speed ramps: the palm accelerates at `speed / 0.15 s`, so faster lifts and moves load the grasp more.
- Touch sensing during descent: if the fingers touch the cube while descending (they landed on top of it), the attempt stops as a stall. It counts as a missed grasp unless a retry is available (`retry_count`), in which case the policy backs off and re-perceives with fresh noise. Shoving the cube sideways by more than 5 mm before the grasp is a `COLLISION` instead.

## What is NOT modelled (simplifications and their limits)

- **No arm.** The palm is driven by a stiff world constraint (perfect Cartesian tracking, 2000 N limit). There is no inverse kinematics, joint limits, joint dynamics or arm collisions. A real arm would add tracking error, vibration and reach limits.
- **Idealised sensing.** Perception noise is white Gaussian position noise. There is no camera model, occlusion or latency in perception. The "camera noise" axis from CLAUDE.md is not implemented.
- **Gripper state is read from finger joint encoders** (gap and finger velocity) to decide whether an object is in hand. The policy never sees ground-truth cube pose after the initial noisy estimate, except for re-perception on retry, which also uses noise.
- **Cube is a rigid box;** contact uses PyBullet defaults (no deformation, no rolling friction, no compliance). PyBullet's friction is an approximate solver, not exact Coulomb friction at 240 Hz.
- **Single object, single table, flat zone.** No clutter.
- **Collision = abort.** Any contact between cube/gripper and the wall, or knocking the cube before the grasp, ends the episode as `COLLISION`. This is a safety-style rule, chosen once.
- **Failure-reason labels are heuristics** applied to ground truth: `MISSED_GRASP` (cube never lifted 1 cm), `SLIPPED_ON_LIFT` / `DROPPED_IN_TRANSIT` (cube moved more than 3 cm relative to the palm during that phase), `PLACED_OUTSIDE_ZONE`, `COLLISION`, `TIMEOUT` (25 s of simulated time).
- Heavy and slippery cases may behave differently on real hardware because grip force, finger compliance and surface properties differ.

## Environment note

PyBullet has no prebuilt Windows wheel for Python 3.13 and needs the MSVC build tools to compile (checked 2026-10-21: `pip install pybullet` fails with "Microsoft Visual C++ 14.0 or greater is required"). We therefore run the simulator in a Linux Docker image (`docker/Dockerfile.sim`, Python 3.11). Use `scripts/dock.sh <cmd>` to run commands in it with the repo mounted. This is also the image intended for Nebius Serverless Jobs (not yet pushed or run there: PENDING_KEY).

## Seeds and anti-rigging

- Dev seeds: 1000 and up (`DEV_SEED_BASE`). Held-out seeds: 900000 and up (`HELDOUT_SEED_BASE`), reserved for gate G5. The baseline sweep script asserts it never touches the held-out range. Held-out seeds were never run.
- Same `(policy, scenario)` gives the same `Result`: tested in-process and across fresh processes (`backend/tests/test_sim.py`). This is verified on one machine/image only; cross-platform bit-identity of PyBullet is not claimed.

## Tuning log (the one-time choice of defaults)

World constants and parameter ranges were fixed first (scenario ranges from PROJECT_BRIEF.md; policy bounds in `core/bounds.py`). Then the default policy values were chosen using DEV sweeps only (Latin hypercube, sweep seeds 7 and 11), because a first attempt was far off the 60-70% target. In order:

| Step | Finding | Change |
|---|---|---|
| 1 | 2.5% pass (200 scenarios). Palm landed on cubes of 6.5 cm and larger. | Fingers lengthened to 9 cm; fixed palm grasp height. (Geometry bug.) |
| 2 | Fingers drifted asymmetrically when the cube was offset in y (equal and opposite motor forces have no preferred position). | Added gear constraint between fingers. (Model bug.) |
| 3 | 80.5% pass but failures were almost only sensor-noise collisions; mass/friction/delay had no effect. | Descent onto the cube is now a stall that can be retried instead of an instant collision; open gap widened 5.5 to 6 cm. |
| 3b | (Found while writing tests, after step 4 below was chosen.) Retries recovered 1 of 12 noisy failures because contact registered as a 5 mm displacement before the lag-based stall check fired. | Contact during descent is now an immediate stall (tactile sensing). Dev sweeps were re-run: 70.0% (seed 7, n=200) and 72.0% (seed 11, n=300); defaults unchanged. |
| 4 | Default policy too strong. Tried `grip_force`/`grasp_hold_steps` of 30/30 (80%), 12/10 (66%), 15/10 (70.5%), 10/8 (60.5%). | Chose **grip_force 15, grasp_hold_steps 10**. Other defaults (approach_speed 0.3, lift_height 0.15, lift_speed 0.3, place_slow_factor 1.0, retry_count 0) were never changed. |

Result on dev seeds with the frozen default: 70.5% (n=200, sweep seed 7) and 72.3% (n=300, sweep seed 11). The target was "roughly 60 to 70"; this is slightly above. The defaults were not tuned further.

Failure structure on sweep seed 11 (n=300, dev seeds), default policy:

| Slice | n | pass |
|---|---|---|
| heavy (>0.5 kg) and slippery (friction <0.4) | 48 | 29% |
| heavy only (friction >=0.4) | 110 | 82% |
| slippery only (mass <=0.5 kg) | 34 | 82% |
| delay >=12 steps and cube <4.5 cm | 46 | 48% |
| sensor noise >0.022 m | 80 | 53% |
| benign (friction >=0.5, delay <=8, noise <0.015, size >=4.5 cm) | 29 | 100% |

These are small slices; treat them as indicative, not precise. Exact outputs depend on this PyBullet build.

Single-parameter sensitivity, measured on dev sweep seed 7 (n=200, default policy 70.0%, one parameter changed at a time):

| Change | Pass rate | Note |
|---|---|---|
| `retry_count` 0 to 3 | 81.0% | helps noise-induced misses; costs time |
| `lift_speed` 0.3 to 0.1 | 79.0% | slower lift, less inertial load |
| `lift_speed` 0.3 to 0.6 | 50.5% | |
| `grip_force` 15 to 40 | 78.5% | |
| `grasp_hold_steps` 10 to 60 | 77.5% | |
| `lift_height` 0.15 to 0.08 | 45.0% | 53 wall collisions: the wall is 6 cm, so low lifts hit it |
| `lift_height` 0.15 to 0.30 | 70.5% | no effect |
| `approach_speed` 0.1 / 0.6 | 71.0% / 70.0% | no meaningful effect |
| `place_slow_factor` 1.0 to 0.3 | 70.0% | no measurable effect |

So the fixer has five parameters with real influence (`grip_force`, `grasp_hold_steps`, `retry_count`, `lift_speed`, and `lift_height` in the harmful direction) and two that do nothing in this simulator (`approach_speed`, `place_slow_factor`). They stay in the policy schema because the brief lists them; do not describe them as effective. Lowering `lift_height` is a ready-made trap for the naive-fix demo.

Some failures cannot be fixed by these parameters. For example with sensor noise at 0.03 m, a grasp that succeeds off-centre in x ends up displaced from the target; retries do not correct that. The gate should report such cases honestly rather than the system claiming a fix.

## Freeze (from P3 Part A)

From this point the simulator, parameter bounds and default policy are frozen. Changing them invalidates every baseline, patch and held-out comparison.

- **Fingerprint:** `backend/app/sim/FROZEN_HASH.txt` holds SHA-256 hashes of `sim/pickplace.py` (line endings normalised) and of the scenario ranges, policy bounds and default policy values. `tests/test_sim_frozen.py` fails with an explanatory message if either changes.
- **Golden results:** `tests/fixtures/golden_results.json` holds exact `Result`s for 5 fixed scenarios; the test re-runs them and requires exact equality. This also catches a changed PyBullet version or platform. It is run on the same image/machine as it was generated, so a failure on a different host (for example on Nebius) means bit-identical physics is not guaranteed there; it would not necessarily be a bug in the code.
- **Deliberate re-freeze:** `python scripts/refreeze.py --i-understand-this-invalidates-results`, then re-run the dev baseline and ceiling search and note the reason here.
- **Git tag `sim-frozen`:** marks the commit that introduced the fingerprint. The P2 commit (`007bec9`) differs from it only by the held-out seed guard in `run_scenario`; the dev baseline was re-run after adding the guard and was unchanged (70.0%, sweep seed 7, n=200).
- **Seed guard:** `backend/app/core/seeds.py`. Seeds >= 900000 raise `HeldOutSeedError` in `run_scenario`, the sweep sampler, the scenario generator and the runners unless `held_out=True`, and `held_out=True` requires seeds >= 900000 (the two sets never mix). `tests/test_seed_guard.py` includes a static scan proving no code outside `backend/app/gate/` (and the forwarding parameters in the sim/runner/generator) passes the flag, including everything in `scripts/`.
