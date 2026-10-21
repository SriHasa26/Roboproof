# RoboProof: Project Brief

Autonomous stress testing for robot policies, with a fix that must be proven before it is trusted.
Hackathon: NVIDIA x Nebius Global AI Hackathon. Track: Physical AI (simulation, no hardware).

---

## 1. Problem statement

Robot control policies, whether hand-tuned or learned, are usually validated against a small set of hand-picked test cases. That is not enough, for three reasons.

**Failures hide in combinations.** A pick-and-place policy may work on light, grippy objects and nominal sensors, and still fail whenever an object is heavy AND slippery AND the sensor is noisy. Hand-written tests rarely sample those corners. On real hardware, discovering them costs broken equipment, wasted lab time, and sometimes safety incidents.

**Diagnosis is slow and manual.** Even when a failure is found, an engineer must dig through logs to work out which physical conditions cause it and why.

**AI-proposed fixes cannot be trusted by default.** If we let an AI tune a policy, it will tend to fix the failures it was shown and quietly break other cases (regressions), or overfit to the exact scenarios it saw. A claim like "the fix works" is worthless without proof against cases the AI never saw.

Software engineering solved the equivalent problem with continuous integration: automated tests, regression suites, and gates that block bad changes. Robotics has no equally accessible, rigorous equivalent for policy changes.

**The problem RoboProof addresses:** there is no fast, reproducible way to (a) discover where a robot policy breaks, (b) understand why, (c) propose a fix, and (d) rigorously prove that the fix generalizes without breaking anything else, all before the policy goes near real hardware.

---

## 2. The challenge

### 2.1 Hackathon requirements (from the hackathon page)
- Must run on Nebius Token Factory or Nebius AI Cloud, and use at least one NVIDIA open source model.
- Track: Physical AI. Embodied/edge agents powered by Nemotron (and optionally GR00T, Cosmos, Sonic), coordinated through an agent runtime. Use Nebius Serverless Jobs for simulations, synthetic data, policy evaluation, or sensor processing at scale; Serverless Endpoints for real-time inference when needed.
- Demo video: 3 minutes or less, public on YouTube. For Physical AI it must include at least 1 minute showing the hardware operating, or, with no hardware, the key application modules in action.
- Public code repository with an open-source license visible at the top (MIT chosen), plus a README with setup and run instructions.
- Submission must highlight how Nemotron was used, where Token Factory helped, and any other Nebius tools used; include written feedback on Nebius and NVIDIA tools.
- A working demo URL is listed but appears marked "not required" for Physical AI. Hosting one is still recommended. Confirm against the Official Rules and the deadline on the hackathon page yourself.

### 2.2 The engineering challenge (what makes this hard)
1. **Coverage of rare failures.** Random scenarios mostly pass. We must deliberately probe risky regions while still guaranteeing coverage of the whole parameter space.
2. **Trustworthy diagnosis.** An LLM must explain failures without inventing evidence. Solution: code computes the statistics; the model only interprets them.
3. **Trustworthy verification.** The system must refuse to certify a fix unless machine-checked evidence says so, including on scenarios created after the fix.
4. **Scale and reproducibility.** Hundreds of simulations must finish quickly (Nebius Serverless Jobs) and give identical results for identical seeds.
5. **Honesty.** Every number shown must be measured. Simulation is not reality, and the product must say so.

---

## 3. What we are building

**RoboProof** is an AI test engineer for robot policies. You point it at a robot task and policy; it finds where the policy breaks, explains why, proposes a bounded fix, and returns a verdict (VERIFIED, FAILED or UNVERIFIED) from a deterministic Proof-of-Robustness Gate.

### 3.1 The demo task (one task, done well)
A simulated robotic arm (PyBullet, headless, deterministic) picks up a cube and places it in a target zone. The policy is a parameterized controller with a small set of tunable numbers.

**Scenario parameters (the physical conditions that vary):**
| Parameter | Meaning | Range (initial) |
|---|---|---|
| mass_kg | cube mass | 0.05 to 1.0 |
| friction | contact friction coefficient | 0.1 to 1.2 |
| size_m | cube edge length | 0.03 to 0.08 |
| pos_offset_m | (x, y) offset of cube from nominal position | +/- 0.08 |
| sensor_noise_m | std of noise on perceived cube position | 0.0 to 0.03 |
| gripper_delay_steps | actuation latency | 0 to 20 |
| seed | integer seed for all randomness | any |

**Policy parameters (what the fixer may tune, always clamped to bounds):**
grip_force, approach_speed, lift_height, lift_speed, grasp_hold_steps, place_slow_factor, retry_count.

**Per-scenario result:** success, collision flag, completion_time_s, final_place_error_m, max_slip_m, failure_reason (DROPPED_IN_TRANSIT, MISSED_GRASP, SLIPPED_ON_LIFT, COLLISION, PLACED_OUTSIDE_ZONE, TIMEOUT).

### 3.2 The pipeline
1. **Scenario generation (Nemotron fast model: Nano or Super).** Reads the task description and policy parameter docs, proposes risky regions of the scenario space as schema-validated JSON. Code then adds a grid/Sobol sweep so coverage has no holes. Output: a fixed list of scenarios with seeds.
2. **Simulation fleet.** Scenarios are sharded and executed headlessly. Primary runner: Nebius Serverless Jobs (containerized simulator). Fallback runner: local multiprocessing. Both implement one `JobRunner` interface, and the UI shows which one ran.
3. **Evidence computation (pure code).** Failure rate per parameter bin, top failure reasons, a simple interaction scan for combinations (e.g. heavy x slippery), and pass/collision/time metrics.
4. **Failure analysis (Nemotron Ultra, the reasoning model).** Receives the computed evidence, returns root-cause hypotheses as structured JSON, each with a testable prediction ("failures should fall sharply if grip_force rises above X for mass > Y").
5. **Fix proposal (Nemotron Ultra).** Returns a bounded parameter patch (JSON diff over policy parameters), with justification. Validated and clamped. At most 3 attempts; gate feedback is fed back into later attempts.
6. **Proof-of-Robustness Gate (pure code, no LLM).** See 3.3.
7. **Dashboard.** Failure heatmap over parameter space, failure clusters with hypotheses, before/after metrics with confidence intervals, gate checklist, side-by-side replay of a failing and a fixed scenario, telemetry (scenarios, shards, wall-clock, tokens, cost), and a downloadable JSON evidence report.

### 3.3 The Proof-of-Robustness Gate
Verdict is one of VERIFIED, FAILED, UNVERIFIED. VERIFIED only if every check passes:
- **G1 Determinism.** A sample of the baseline is re-run; outcomes must be identical for identical seeds.
- **G2 Reproduced.** Each failure the analyst targeted reproduces on the unpatched policy.
- **G3 Fixed.** The targeted failing scenarios now pass with the patch.
- **G4 No regressions.** Scenarios that passed before still pass (regression budget defaults to 0, configurable, and the UI shows it).
- **G5 Held-out generalization.** A fresh scenario set (new seeds, generated after the fix, never shown to the analyst or fixer). The patched policy's held-out pass rate must meet a configurable target (default 0.80) AND its Wilson 95% lower bound must exceed the unpatched policy's point estimate on the same held-out set.
- **G6 Complete execution.** Every shard finished; none timed out or crashed.

FAILED means a check ran and did not pass. UNVERIFIED means a check could not run or data is incomplete. A crash or timeout never counts as a pass.

### 3.4 The "naive fix" trap (key demo moment)
A one-click mode applies a deliberately overfit patch: it fixes the known failures but harms other conditions. The gate must visibly reject it (G4 and/or G5 red). This shows judges the gate is real and the system is honest. Alongside it, show an honest iteration where attempt 1 fails the gate and attempt 2 passes.

### 3.5 Where NVIDIA and Nebius are used
- **Nemotron Nano/Super via Token Factory:** high-volume, fast scenario generation.
- **Nemotron Ultra via Token Factory:** failure analysis and fix proposals (reasoning-heavy).
- **Nebius Serverless Jobs:** parallel simulation fleet (verify on day one, fallback to local).
- **Nebius Serverless Endpoints:** host the dashboard/API if feasible.
- Model IDs are never hardcoded; they come from environment variables after listing what the API key can see.
- Optional stretch, only if everything else is done: a Cosmos model to vary visual conditions. Not required.

### 3.6 Honesty rules
All numbers shown are measured from real runs. This is a simulation, not a real robot, and the README says so, including simulator fidelity limits. The simulator's default policy and parameter ranges are chosen once and then frozen; held-out seeds are never used during development tuning. The model never decides pass or fail.

---

## 4. Master plan (milestones with exit criteria, not dates)

| # | Milestone | Exit criteria |
|---|---|---|
| P0 | Discovery | docs/NEBIUS_NOTES.md written from official docs (UNCONFIRMED where not verified); model list obtained; PyBullet installs; one tiny containerized test job attempted on Serverless Jobs with the outcome recorded |
| P1 | Foundations | repo layout, config, Pydantic schemas, LLM client with real smoke call, tests green |
| P2 | Simulator and policy | deterministic sim, same seed gives same result (tested), default policy passes about 60 to 70 percent of a broad sweep with clear failure regions, replay recorder |
| P3 | Scenario generator and local runner | schema-validated Nemotron scenarios, plus sweep, sharded local run of 200 scenarios, baseline stored |
| P4 | Analysis, fixer, gate | evidence stats, analyst, bounded fixer, G1 to G6 gate with unit tests for every failure path, naive-fix trap rejected, full real loop run and recorded |
| P5 | Nebius scale-out | NebiusJobRunner behind same interface, same 200 scenarios on Nebius, measured wall-clock and cost; honest fallback if it cannot work |
| P6 | Dashboard | all screens working, every button functional, live vs recorded and runner badges |
| P7 | Demo mode and submission | DEMO_MODE replays a recorded real run, README, FEEDBACK.md, deploy, SUBMISSION.md with video script and checklist |

### Risk register
| Risk | Mitigation |
|---|---|
| PyBullet grasping is unstable | Cap effort at 45 minutes, then switch to a simpler contact/friction model or 2D numpy sim with the same interface; document the simplification |
| Serverless Jobs cannot run the sim | Test one tiny job in P0; keep LocalRunner; label honestly |
| Nemotron model IDs or names differ from expectation | List models via API; env-configured; never hardcode |
| LLM returns invalid JSON | Pydantic validation, one retry with the error, then fail loudly |
| Fix does not improve things | That is a valid, honest outcome: report FAILED/UNVERIFIED; widen the tunable parameters or adjust ranges before experiments, never after seeing held-out results |
| Credits run out | Fast model for volume, Ultra only for analysis/fix; DEMO_MODE for judges |

### Submission checklist
- [ ] Real end-to-end run using Nemotron via Token Factory
- [ ] Simulations run on Nebius Serverless Jobs (or honest local fallback labeled)
- [ ] Gate verdict plus naive-fix rejection demonstrated
- [ ] Measured before/after metrics with held-out results
- [ ] Public GitHub repo, MIT license visible at the top
- [ ] README: setup, run, architecture, Nemotron usage per stage, Nebius services used, limits
- [ ] FEEDBACK.md on Nebius and NVIDIA tools
- [ ] YouTube video of 3 minutes or less with at least 1 minute of the modules running
- [ ] Hosted demo URL (recommended)
- [ ] Project description (what, why, how); Physical AI category selected; city selected if you attended an IRL event
