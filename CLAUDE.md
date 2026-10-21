# RoboProof: an AI that fixes robot policies and must PROVE the fix works

## Scope rules (these override anything below that conflicts)
- ONE task only: a simulated arm picks a cube and places it in a target zone. Built-in task, no free-text task input in v1.
- Metrics per scenario: success, collision flag, completion time. Report all three before and after.
- The fixer only tunes bounded numeric control parameters. It never rewrites controller code.
- Order of work: (1) verify Nebius inference and PyBullet install, (2) verify a containerized sim can run as a Nebius Serverless Job (even one tiny test job), (3) local end-to-end loop, (4) gate, (5) dashboard, (6) scale-out and demo mode.
- Keep LocalRunner working at all times as the fallback.
- Full problem statement, gate thresholds and milestones live in PROJECT_BRIEF.md.

Hackathon: NVIDIA x Nebius Global AI Hackathon. Track: Physical AI (no physical hardware).
Rule: all inference runs on Nebius Token Factory with NVIDIA Nemotron models. Simulations run on Nebius Serverless Jobs (local runner is only a fallback and must be labeled as such in the UI and README).

## One-line pitch
RoboProof stress-tests a robot policy with hundreds of AI-generated adversarial scenarios in parallel, diagnoses why it fails, proposes a fix, and only certifies the fix through a deterministic Proof-of-Robustness Gate. If it cannot prove the fix, it says UNVERIFIED.

## The pipeline (keep exactly this shape)
1. TASK SPEC: user writes a plain-English task ("pick up a cup and place it on the shelf") or picks a built-in task.
2. SCENARIO GENERATOR (Nemotron Nano/Super): outputs scenarios as JSON validated against a strict schema. Axes: object mass, friction, size, position offset, sensor noise, gripper delay, camera noise flag. Each scenario has a fixed integer seed. Code (not the LLM) guarantees coverage: the LLM proposes risky regions, code adds a Sobol/grid sweep so the heatmap has no holes.
3. SIMULATION FLEET (Nebius Serverless Jobs): the simulator is containerized. Scenarios are sharded across jobs (e.g. 10 shards x 20 scenarios). Each shard writes results.json (per-scenario pass/fail, metrics, failure reason code, trajectory summary) and a few replay clips.
4. FAILURE ANALYST (Nemotron Ultra): receives DETERMINISTIC statistics computed in code (failure rate per axis bin, a shallow decision tree over parameters, top failure reason codes). It explains root causes as testable hypotheses, e.g. "fails when mass > 0.4 kg AND friction < 0.3 because grip force saturates". The LLM interprets evidence; it does not invent numbers.
5. FIXER (Nemotron Ultra): proposes a policy patch as a bounded JSON diff over the policy's tunable parameters (grip_force, approach_speed, lift_height, retry_count, etc.). Schema-validated, min/max clamped, one patch per attempt, max 3 attempts.
6. PROOF-OF-ROBUSTNESS GATE (pure deterministic code, no LLM): see below.
7. DASHBOARD: heatmap of pass/fail across parameter space, failure clusters, before/after bars, gate checklist, replay clips, run telemetry.

## Proof-of-Robustness Gate (the differentiator)
Final status is exactly one of VERIFIED, FAILED, UNVERIFIED. VERIFIED only if ALL hold:
- G1 Determinism: the baseline run is repeated on a sample and gives identical outcomes for the same seeds (proves failures are real, not flaky).
- G2 Reproduced: every failure the analyst targeted is reproduced on the unpatched policy before the fix.
- G3 Fixed: targeted failing scenarios now pass with the patch.
- G4 No regressions: every scenario that passed before still passes.
- G5 Held-out generalization: a FRESH scenario set (new seeds, generated AFTER the fix, never shown to the analyst or fixer) has pass rate >= threshold, reported with a Wilson 95% confidence interval. This blocks overfitting.
- G6 Complete execution: all shards finished, none timed out or crashed. Any missing shard means UNVERIFIED, never a pass.
FAILED = a check ran and did not pass. UNVERIFIED = a check could not run or data is incomplete.
The gate must be unit-tested, including cases for each failure path.

## Must-have demo moments
- The "naive fix" trap: a one-click mode where a deliberately overfit patch fixes the known failures but breaks other scenarios. The gate must reject it visibly (G4 or G5 red). This proves the gate is honest.
- Honest iteration: attempt 1 may fail the gate, attempt 2 passes. Show both.
- Scale line with MEASURED numbers: scenarios run, jobs used, wall-clock time, tokens, cost estimate.
- Replay clips of a failing and a fixed scenario side by side.

## Tech stack
- Simulator: PyBullet in DIRECT (headless) mode, deterministic with fixed seeds. Task: a scripted/parameterized pick-and-place controller on a simple arm or gripper. The "policy" is a parameterized controller (tunable JSON). If PyBullet gives trouble, fall back to a simple numpy 2D physics sim with the same interface. Do not spend more than 45 minutes fighting the simulator.
- Backend: Python 3.11+, FastAPI, Pydantic v2 for every schema, SQLite for runs.
- LLM client: OpenAI-compatible SDK pointed at Nebius Token Factory. Config from env: NEBIUS_API_KEY, NEBIUS_BASE_URL, NEBIUS_MODEL_FAST, NEBIUS_MODEL_REASONING. Never hardcode model IDs. Provide `scripts/list_models.py` that lists models available to the key so the user can fill in the env vars.
- Fleet: Nebius Serverless Jobs behind a `JobRunner` interface with two implementations: `NebiusJobRunner` and `LocalRunner`. UI badge shows which one ran. Read the official Nebius docs for the real CLI/API. Do not invent commands.
- Frontend: React + TypeScript + Vite + Tailwind, dark theme, charts via Recharts or plain SVG. Replays as small MP4/GIF or canvas playback of trajectory data.
- Deployment: a single container serving API + built frontend; deploy with Nebius Serverless Endpoints if feasible, otherwise any host, and say so.
- License: MIT. Public GitHub repo.

## Engineering rules for Claude Code
- Never fabricate results, model outputs, run times, or Nebius capabilities. If something is not verified, say so in code comments, README, and UI.
- Never hardcode API keys. `.env` in `.gitignore`, `.env.example` with placeholders only.
- Every LLM output is parsed with Pydantic; on failure retry once with the validation error, then fail loudly. Log requests (no secrets), latency, and token counts to the DB.
- All randomness uses explicit seeds. Same seed means same outcome.
- LLM never decides pass/fail. The simulator and the gate decide.
- Build in milestones. After each: run tests, fix failures, commit. Do not start the next milestone with red tests.
- Keep a `DEMO_MODE` that replays a previously recorded REAL run from disk so judges can use the hosted demo instantly without spending credits. Label it clearly as "recorded real run" in the UI.
- Keep a running `FEEDBACK.md` of friction/bugs/praise about Nebius Token Factory, Serverless Jobs, and NVIDIA models while building (the submission requires feedback).
- README sections: overview, architecture (Mermaid), exactly where Nemotron is used per stage and why that model size, where Nebius Token Factory and Serverless Jobs are used, setup, run, gate rules, limitations, measured results (only real numbers), license.

## Definition of done
Real end-to-end run on Nebius: generate scenarios, fan out jobs, analyze, patch, gate verdict, dashboard, recorded for DEMO_MODE; the naive-fix trap works; tests pass; README and FEEDBACK.md complete; public repo with MIT license; hosted demo URL works.
