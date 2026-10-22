# RoboProof

[MIT License](LICENSE)

An AI test engineer for robot policies. It stress-tests a simulated pick-and-place arm, diagnoses failures, proposes a bounded parameter fix, and returns VERIFIED / FAILED / UNVERIFIED from a deterministic Proof-of-Robustness Gate. Built for the NVIDIA x Nebius Global AI Hackathon (Physical AI track).

**This is a simulation, not a real robot.** Nothing here has been validated on hardware. See `docs/SIM_FIDELITY.md` for simulator limits.

**Status: work in progress.** P1 (foundations), P2 (simulator + policy) and P3 (freeze, ceiling search, scenario generator, LocalRunner) in progress. Everything that needs a real Nebius call is marked `PENDING_KEY` in [docs/NEBIUS_NOTES.md](docs/NEBIUS_NOTES.md). No measured results exist yet, so none are claimed.

## Setup and run

The whole backend (FastAPI + runner + PyBullet simulator) runs in one Docker image (Python 3.11). The Windows host has Python 3.13 where PyBullet has no wheel, so the host only runs the browser and, later, the frontend dev server. The same image is intended for Nebius Serverless Jobs (P5, not done yet: PENDING_KEY).

```bash
cp .env.example .env                  # fill in NEBIUS_API_KEY etc. (passed to containers at run time, never baked in)
scripts/dock.sh build                 # docker build -f docker/Dockerfile.sim -t roboproof-sim:dev .  (first build ~5 min)
scripts/dock.sh test                  # whole test suite, including the simulator
scripts/dock.sh api                   # backend on http://localhost:8000  (/health, /api/version)
scripts/dock.sh baseline              # 200 dev scenarios on the default policy with LocalRunner, stored in SQLite
scripts/dock.sh sweep --n 200         # dev baseline table by parameter bin
scripts/dock.sh python scripts/ceiling_search.py   # any other command inside the image
```

`scripts/dock.sh` mounts the repo at `/app`, so edits take effect without rebuilding. The database defaults to `backend/data/roboproof.sqlite` (gitignored). Without a Nebius key, scenario regions come from a labelled hand-written fixture, never from a model (PENDING_KEY); model IDs and keys come only from environment variables.

The non-simulator tests also run on the host (`cd backend && python -m pytest`); simulator tests skip there.

Simulator fidelity limits, the freeze and the tuning log: [docs/SIM_FIDELITY.md](docs/SIM_FIDELITY.md). Ceiling search and gate thresholds: [docs/CEILING_SEARCH.md](docs/CEILING_SEARCH.md).

## Gate rules (Proof-of-Robustness Gate, pure code)

The verdict is exactly one of VERIFIED, FAILED, UNVERIFIED, computed from simulator results only (`backend/app/gate/gate.py`; thresholds in `backend/app/core/gate_config.py`; derivation in [docs/CEILING_SEARCH.md](docs/CEILING_SEARCH.md)).

| Check | Rule |
|---|---|
| G1 determinism | 30 evenly spaced baseline scenarios are re-run in fresh processes; every `Result` must be identical |
| G2 reproduced | every targeted failure fails again on the unpatched policy |
| G3 fixed | at least 70% of the targeted failures now pass (`GATE_TARGET_FIX_RATE`, set before the rehearsal, not tuned to the trap) |
| G4 no regressions | previously passing analysis-set scenarios that now fail <= floor(2% x previously passing) (about 4 of 200). **The strict zero-budget result and every regressed scenario id are always shown next to it** |
| G5 held-out | on a fresh, code-only verification set of 400 scenarios from a single-use seed block: patched pass rate >= 0.90, improvement over the unpatched policy on the same set >= 0.10, **and** the patched Wilson 95% lower bound > the unpatched pass rate |
| G6 complete | every run the gate relied on finished with no failed or timed-out shard |

**Verdict:** UNVERIFIED if G6 is not a pass or any check could not run; otherwise FAILED if any check ran and failed; otherwise VERIFIED. A crash, timeout or missing result never counts as a pass.

**Why the regression budget is not zero:** with a budget of zero, even the best patch found by the ceiling search (3 regressions of 216 on dev set A) would be rejected, so VERIFIED would be practically unreachable. 2% is a documented compromise, not a physical law; the strict result is displayed so nobody has to take the budget on trust.

**Skipped after failure:** if G3 or G4 already failed on the analysis set, G5 is not run (`skipped_after_failure`), so the single-use verification block is not spent on a patch that is already rejected. That is a deliberate skip, not a check that "could not run": the verdict is FAILED, not UNVERIFIED. G5 is terminal: its details are never fed back to the fixer, and a failed G5 means a new run with a fresh seed block is needed.

## Layout

`backend/app/{api,core,llm,sim,scenarios,runner,analysis,gate,store}`, `backend/tests`, `frontend/`, `scripts/`, `docker/`, `docs/`, `recorded_runs/`.

See [CLAUDE.md](CLAUDE.md) and [PROJECT_BRIEF.md](PROJECT_BRIEF.md) for scope and gate rules.
