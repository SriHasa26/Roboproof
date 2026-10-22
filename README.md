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

**Check statuses:** `pass`, `fail`, `not_run` (the check could not run: missing or incomplete data) and `skipped_after_failure` (deliberately not run because an earlier check already failed).

**Verdict precedence** (each line has a test in `backend/tests/test_gate.py`):
1. **UNVERIFIED** if G6 fails (incomplete execution) or any required check is `not_run`.
2. Otherwise **FAILED** if any check that ran failed. Checks that are `skipped_after_failure` do not change this.
3. Otherwise **VERIFIED** (and only if nothing was skipped).

So an incomplete run is UNVERIFIED even if another check also failed, and a complete run with a failed G3 is FAILED with G5 `skipped_after_failure`. A crash, timeout or missing result never counts as a pass.

**Regression budget (G4), decided by the project owner: 2%.** The budget is `floor(0.02 x previously passing)` (about 4 of 200). The strict zero-budget result and every regressed scenario id are always shown next to it. The strict check would reject even the best patch found by the ceiling search (3 regressions of 216 on dev set A; 1 of 188 in rehearsal_001), which is why a zero budget would make VERIFIED practically unreachable. The budget is a documented compromise, not a physical law.

**Skipped after failure (approved):** if G3 or G4 already failed on the analysis set, G5 is `skipped_after_failure`, so the single-use verification block is not spent on a patch that is already rejected. G5 is terminal: its details are never fed back to the fixer, and a failed G5 means a new run with a fresh seed block is needed.

**Diagnostic G5:** `finalize(..., diagnostic_g5=True)` runs G5 even though an earlier check failed, to show what it would have said. It exists for rehearsal blocks only (it is refused for held-out blocks) and can never change a verdict: a FAILED verdict stays FAILED.

## Pipeline v2: what changed and why

Pipeline v1 (tag `pipeline-frozen`) was measured in `recorded_runs/reliability_001`: 1 of 5 runs VERIFIED, 2 FAILED, 2 without a verdict. The diagnosis (`docs/P46_DIAGNOSIS.md`) found that both dead runs were lost to **one invalid region out of three** (the other two were fine) and that the fixer saw only one number per attempt. Pipeline v2 (tag `pipeline-frozen-v2`) changes exactly that, and nothing about the gate:

- **Generator:** each region is validated on its own (valid ones are kept, dropped ones are logged with the reason; values up to 10% of an axis range outside the bounds are clamped and logged). Fallback chain, all NVIDIA Nemotron: fast model with reasoning off (60 s per-call timeout) -> `nemotron-3-super-120b-a12b` -> a code-made coverage-only analysis set labelled `coverage_only_fallback`. The source and model are recorded in every run.
- **Fixer:** one reasoning-model call returns 4 diverse candidate patches. **Code** measures every candidate on the analysis set and picks one with a fixed rule (highest targeted fix within the regression budget; ties: fewer changed parameters, lower grip force); only the selected candidate goes through the gate, and G5 still runs at most once per run. The model sees a table of every candidate it proposed, with per-hypothesis results, on later attempts (analysis-set numbers only).
- **Exact comparisons:** every gate threshold is compared on integers/exact fractions with inclusive boundaries (one run cleared G3 at exactly 0.70).
- Thresholds are unchanged: G3 0.70, G4 2%, G5 0.90 with minimum improvement 0.10, held-out size 400.

## Pipeline freeze and official runs

The prompts, generator, evidence, analyst, fixer, selection rule, gate, gate thresholds, seed guard, ledger, LLM client and controls, runner base, pipeline orchestrator and `docs/OFFICIAL_PROTOCOL.md` are fingerprinted (`backend/app/core/FROZEN_PIPELINE_HASH.txt`, list in `backend/app/core/provenance.py`) and marked by the git tag `pipeline-frozen-v2` (v1 stays as `pipeline-frozen`). `backend/tests/test_pipeline_frozen.py` fails with an explanation if any of them changes. Anything run before the tag is a **rehearsal**; changing a frozen file is a deliberate re-freeze (`scripts/refreeze_pipeline.py`, a new commit and a new tag) and makes every earlier run a rehearsal again.

An **official** run (`PipelineConfig(official=True, rehearsal=False)`) refuses to start unless the working tree is clean, the frozen files equal their content at the tag, the committed hash file agrees, the official protocol is committed, the container image build id is known, and no `GATE_*`/`FIXER_N_CANDIDATES` override is set in the environment. It refuses with `LLM_DEV_CACHE=1`. It records the commit, tag, pipeline hash, image build id, protocol commit, model ids and runner name in its artifacts. Line endings alone never count as a change.

The official evaluation is a **pre-registered batch of 5 runs** with fixed master seeds and a fresh held-out block each, all reported, with run 1 as the headline by rule: [docs/OFFICIAL_PROTOCOL.md](docs/OFFICIAL_PROTOCOL.md). `scripts/run_official.py` implements it and has not been run.

## Layout

`backend/app/{api,core,llm,sim,scenarios,runner,analysis,gate,store}`, `backend/tests`, `frontend/`, `scripts/`, `docker/`, `docs/`, `recorded_runs/`.

See [CLAUDE.md](CLAUDE.md) and [PROJECT_BRIEF.md](PROJECT_BRIEF.md) for scope and gate rules.
