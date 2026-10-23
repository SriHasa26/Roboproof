# RoboProof

[MIT License](LICENSE) · NVIDIA x Nebius Global AI Hackathon · Track: Physical AI (simulation only, no hardware)

Source: <https://github.com/SriHasa26/Roboproof>

RoboProof stress-tests a robot policy in simulation, asks NVIDIA Nemotron models to explain the failures and propose a bounded parameter fix, and only certifies the fix through a deterministic Proof-of-Robustness Gate. If the gate cannot prove the fix, the answer is FAILED or UNVERIFIED, never a quiet pass.

**This is a simulation of a simplified robot (a two-finger gripper in PyBullet), not a real robot. Nothing was validated on hardware.** One built-in task: pick a cube and place it in a target zone. Read [docs/LIMITATIONS.md](docs/LIMITATIONS.md) before trusting any number here.

**Where it ran (honest):** language-model calls used Nebius Token Factory with NVIDIA Nemotron models. Simulations ran in a local Docker container (`LocalRunner`), **not on Nebius Serverless Jobs**; the container was never tested on Nebius. Every run is labelled "local fallback, not Nebius". Cost figures are estimates (tokens x API-reported prices); actual billing is UNCONFIRMED.

## Official result (pre-registered batch, pipeline v2 frozen, LocalRunner)

Protocol: [docs/OFFICIAL_PROTOCOL.md](docs/OFFICIAL_PROTOCOL.md). 5 runs, fixed master seeds, each with its own single-use held-out block; all reported, none repeated or discarded. Full table with candidates: `recorded_runs/official_001/official_summary.md`.

| Run (master seed) | Verdict | Attempts | Held-out pass, before -> after (n=400) |
|---|---|---|---|
| official_01 (3101) | VERIFIED | 2 | 71.2% -> 96.8% |
| official_02 (3202) | VERIFIED | 2 | 68.8% -> 95.5% |
| official_03 (3303) | FAILED (G5: 348/400, needed 360) | 1 | 69.0% -> 87.0% |
| official_04 (3404) | VERIFIED | 1 | 69.2% -> 97.5% |
| official_05 (3505) | VERIFIED | 1 | 71.2% -> 96.8% |

**4 of 5 VERIFIED (small sample), Wilson 95% interval [37.6%, 96.4%].** For comparison, the v2 rehearsal study on rehearsal seeds was **4 of 8 VERIFIED** (Wilson 95% [21.5%, 78.5%]) and v1 was 1 of 5; the intervals overlap heavily, so this is not a reliability claim. Two of the four VERIFIED runs had 3 and 1 regressions on the analysis set, within the 2% budget but not zero. Measured per run: 109 to 193 s wall clock, 15k to 26k tokens, estimated cost $0.026 to $0.055 (total $0.181, estimate). All three studies are in the dashboard.

## Architecture

```mermaid
flowchart LR
  T[Built-in task] --> G[Scenario generator<br/>Nemotron Nano]
  C[Code: Latin-hypercube coverage] --> S
  G --> S[Scenario set, fixed seeds]
  S --> R[Fleet: LocalRunner<br/>PyBullet, container]
  R --> E[Evidence in code:<br/>failure rates, bins]
  E --> A[Failure analyst<br/>Nemotron Ultra]
  A --> F[Fixer: 4 candidate patches<br/>Nemotron Ultra]
  F --> M[Code measures every candidate,<br/>picks one by fixed rule]
  M --> P[Proof-of-Robustness Gate G1-G6<br/>pure code, no LLM]
  H[Fresh held-out set, single-use seeds] --> P
  P --> V{VERIFIED / FAILED / UNVERIFIED}
  V --> D[Static dashboard]
```

## Where each Nemotron model is used, and why that size

All inference goes through Nebius Token Factory (OpenAI-compatible API). Model IDs come only from env vars, never hardcoded.

| Stage | Model | Why this size |
|---|---|---|
| Scenario generator | Nemotron-3-Nano-30B-A3B (`NEBIUS_MODEL_FAST`), reasoning off. Fallback: Nemotron-3-Super-120B-A12B, then a code-only coverage set | Cheap, quick structured JSON: it proposes risky parameter regions. Code validates each region and adds the coverage sweep. |
| Failure analyst | Nemotron-3-Ultra-550B-A55B (`NEBIUS_MODEL_REASONING`) | Needs reasoning over code-computed statistics to write testable hypotheses. It never invents numbers; the dashboard looks numbers up by evidence id and marks the model's wording as unverified. |
| Fixer | Nemotron-3-Ultra | Proposes 4 bounded patches (schema-validated, clamped). Code measures all of them and selects one. |
| Gate | none | Pass/fail is decided by simulator results and deterministic code only. |

## Where Nebius is used

- **Token Factory:** every model call above, with latency and token counts logged. See [FEEDBACK.md](FEEDBACK.md) (measured notes only).
- **Serverless Jobs:** NOT used. `LocalRunner` ran every simulation. A `NebiusJobRunner` was never validated.

## Gate rules (pure code, `backend/app/gate/gate.py`)

Verdict is exactly one of VERIFIED, FAILED, UNVERIFIED. Thresholds: `backend/app/core/gate_config.py`; derivation: [docs/CEILING_SEARCH.md](docs/CEILING_SEARCH.md).

| Check | Rule |
|---|---|
| G1 determinism | 30 evenly spaced baseline scenarios re-run in fresh processes give identical results |
| G2 reproduced | every targeted failure fails again on the unpatched policy |
| G3 fixed | at least 70% of targeted failures now pass |
| G4 no regressions | previously passing analysis scenarios that now fail <= floor(2% x previously passing); the strict zero-budget result is always shown |
| G5 held-out | fresh 400-scenario code-made set, single-use seeds: patched pass rate >= 0.90, improvement >= 0.10, and patched Wilson 95% lower bound > unpatched pass rate |
| G6 complete | all shards finished, none failed or timed out |

Statuses: `pass`, `fail`, `not_run` (could not run), `skipped_after_failure` (an earlier check already failed, so the single-use held-out set is not spent). Precedence: UNVERIFIED (G6 fails or a required check is not run) > FAILED (a check that ran failed) > VERIFIED. Each path is unit-tested in `backend/tests/test_gate.py`. The thresholds were set from development data, not tuned on held-out seeds; they are judgments, see the limits page.

**Scripted trap:** a hand-written overfit patch (not model output) that fixes most targeted failures but is rejected by G4 and G5. Its stored gate result is shown in the dashboard and labelled as such.

## Setup (Windows + Docker Desktop)

The simulator needs Python 3.11 (PyBullet has no wheel for the host's 3.13), so the backend runs in a container. Git Bash is needed for `scripts/dock.sh`.

```bash
cp .env.example .env            # fill NEBIUS_API_KEY, NEBIUS_BASE_URL, model ids (never commit .env)
scripts/dock.sh build           # first build ~5 min (a cached rebuild took 43 s)
scripts/dock.sh python scripts/list_models.py   # lists models for your key; fill NEBIUS_MODEL_* in .env
scripts/dock.sh test            # test suite inside the image
```

## Run the pipeline

A live run on rehearsal seeds (not held-out, so it can be repeated; it does spend Token Factory credits, about $0.03 estimated). Set `LLM_DEV_CACHE=0` in `.env`.

```bash
scripts/dock.sh python scripts/run_reliability.py --seeds 701 --out recorded_runs/my_run
```

It prints `MODE: REHEARSAL` and takes about 3.5 minutes (one measured run: 3m45s, $0.031 estimated). Artifacts land in `recorded_runs/my_run/run_01_seed701/` (including `gate_report.json`) with a `summary.md`. Official runs (`scripts/run_official.py`) refuse to start unless the tree is clean and the frozen pipeline hash matches tag `pipeline-frozen-v2`; they spend single-use held-out seeds and are not meant to be re-run.

## Dashboard and design

The site (`frontend/`: React, TypeScript, Vite, Tailwind, framer-motion, three.js via react-three-fiber) works on its own as a static site: it reads exported JSON from recorded real runs, and nothing on it is computed live unless the optional live backend is running.

```bash
scripts/dock.sh python scripts/export_demo_data.py   # optional: regenerate frontend/public/data from recorded_runs (keeps live_replay/)
cd frontend
npm install
npm run dev                          # http://localhost:5173
npm run build && npm run preview     # production build from frontend/dist
```

Routes: `/` landing, `/playground`, `/results` official batch, studies, the 3D failure map and a live panel listing runs created on this server (`GET /api/runs`; "backend offline" when there is none), `/runs` and `/runs/:id` run detail, `/live` live console, `/live/report/:id`, `/trap` (scripted example), `/about` (limits). Fonts are self-hosted (`@fontsource`). The hero scene is a procedural, purely illustrative animation (captioned as such); the failure map plots real scenarios from the recorded runs (the unpatched policy on each run's analysis set; per-scenario patched results were not stored, so none are shown). The 3D code is in lazy chunks, and a footer toggle ("Reduce motion and 3D", also set by `prefers-reduced-motion`) replaces it with static content. Nothing on the site is invented: counters come from the data, and the honesty labels (local runner, rehearsal vs official, unverified model opinion, scripted example) are kept on every page.

## Running live

A live run executes the real pipeline (`scripts/run_reliability.py` with one server-chosen rehearsal seed) as a subprocess of a small FastAPI service in the sim image. It is always a **rehearsal**: it can never be official, never uses held-out seeds (900000 and up), and the browser can send nothing but an access code. It makes real Nebius Token Factory calls, so it spends credits (about $0.03 estimated per run; billing is not checked).

```bash
cp .env.example .env          # fill the NEBIUS_* values, then set LIVE_ENABLED=1 (live runs are OFF by default)
docker compose up --build     # API on http://localhost:8000 (API_PORT=8010 docker compose up if 8000 is taken)
cd frontend && VITE_API_BASE=http://localhost:8000 npm run build   # point the site at the API (also set ALLOWED_ORIGINS in .env to the site's origin)
```

Endpoints: `GET /api/health`, `GET /api/live/status`, `POST /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/events` (server-sent events, replayable from the start), `POST /api/runs/{id}/cancel`, plus `/report`, `/scenarios` and whitelisted `/files/{name}`. Protections: one run at a time, per-IP rate limit, daily run cap (`LIVE_DAILY_RUN_CAP`) and daily estimated-spend cap (`LIVE_DAILY_USD_CAP`), optional `LIVE_ACCESS_CODE`, kill switch `LIVE_ENABLED`, CORS allowlist `ALLOWED_ORIGINS` (never `*`), a 10-minute timeout, cancel, secret scrubbing of every event and log. Progress events come from the subprocess output, artifact files as the pipeline writes them, and the pipeline's own LLM-call log; the pipeline writes candidate tables and gate results together at the end, so those appear together. Tests (`backend/tests/test_live.py`) use a fake pipeline and make no real calls.

**Static hosting:** a static host has no backend, so `/live` shows "Live runs are offline in this deployment" and offers **Replay a recorded live run**: a selector offers two real recorded live runs through the API, both 2026-10-23 and both rehearsals: one the gate called VERIFIED (153.5 s, about $0.031 estimated; recorded before response-id capture existed, so it has no model-call log) and one it called FAILED at G5 (158.6 s, about $0.034 estimated, with the model-call log and the provider's response ids). Each is clearly labelled as a recorded replay with its date and verdict. The live backend needs a host that can run a container (the sim image) with the `.env` secrets.

## Playground

`/playground` lets you enter your own scenario conditions (cube mass, friction, size, position offsets, sensor noise, gripper delay) and policy parameters, and get **real results from the frozen simulator**. Controls are built from `GET /api/sim/spec`, which reads the frozen bounds and defaults; the two parameters measured to have no effect are shown greyed out.

- **Single scenario** (`POST /api/sim/scenario`): success, collision, completion time, place error, slip, a plain-language failure reason, and a 3D playback of the real recorded trajectory (at most 300 frames).
- **Sweep** (`POST /api/sim/sweep`, up to 200 scenarios): a seeded Latin-hypercube sweep of your policy and, on the identical scenarios, the default policy (cached): pass rates with Wilson 95% intervals, failure reasons, per-axis failure rates (from the evidence code), and the 3D failure map. Clicking a point replays that scenario exactly.
- **Plain-English input** (`POST /api/sim/interpret`, optional): describe a situation in up to 300 characters ("A 700 g cube on a wet tray with a noisy camera"). The fast Nemotron model (thinking off, second Nemotron model as fallback) proposes the seven scenario values and a one-line reason each, as strict JSON validated against the frozen bounds (values up to 10% of the range outside are clamped and flagged, further out are rejected). Descriptions that are not about the cube task (a drone, a humanoid) come back as "unsupported". It only proposes: it never runs the simulation, the user edits and presses Run, and the result is labelled "model interpretation, unverified". The user's text is data (length-limited, delimited, after the instructions, with an instruction to ignore instructions inside it); only the schema output is used, the API key is never in a prompt, and model-written text is sanitised. It needs `LIVE_ENABLED=1`, the access code if set, a per-IP rate limit (`PLAYGROUND_RATE_INTERPRET_PER_HOUR`) and room under the daily spend cap; a call costs about $0.0001 (estimate).
- **CSV or pasted batch** (`POST /api/sim/batch`, Sweep tab, "Upload CSV or paste rows"): a table with a header row and exactly the seven scenario columns (a template is generated from the spec: `GET /api/sim/batch/template`), at most 200 rows and 100 KB. Every row is validated against the frozen bounds and problems come back per row and field; nothing runs if any row is invalid. Seeds are assigned by row (700000 + row index, deterministic, never held-out). The rows run with your policy and with the default policy; you get a per-row results table, pass rates with Wilson intervals, the comparison, the 3D failure map (click a row or point to replay it) and a results CSV whose text cells are neutralised against spreadsheet formula injection. No model is involved. A sample file is in `docs/demo_scenarios.csv`.
- **Analyze with Nemotron** (`POST /api/sim/analyze`, optional): grounded hypotheses for a finished sweep, labelled "model opinion, unverified". It spends credits, so it needs `LIVE_ENABLED=1`, the access code if set, room under the daily spend cap, and a confirmation; it is never automatic.

Safety: no LLM spend for scenario and sweep; every field validated against the frozen bounds (out-of-range, NaN and infinity rejected, unknown fields rejected); playground seeds are 100000 to 799999 only (held-out and rehearsal seeds are refused); per-IP rate limits, at most 2 simulations at once, 20 s and 60 s timeouts (the simulation runs in a killable process), `PLAYGROUND_ENABLED` kill switch. Results are **exploration, not a gate verdict** and are never part of the official evaluation.

**What it cannot do:** the simulator models one task (a gripper picks a cube and places it in a target zone). A different robot would need a new simulator and a recalibrated gate; that is future work. On a static host with no backend, the page shows three recorded real simulator runs, labelled as recorded examples.

## Evidence and reproducibility

Every important claim should be something you can re-check. Nothing below asks you to trust a screenshot.

| Claim | How to verify | Command or page |
|---|---|---|
| The official evaluation was pre-registered | The protocol (`docs/OFFICIAL_PROTOCOL.md`: K=5, fixed seeds, reporting and repeat rules) was committed at `8171c7d` (2026-10-22 19:13:55 +05:30 = 13:43:55 UTC), about 2 hours before the first official run started (15:42:58 UTC, `LABEL.json`). The verifier also checks that every official run's commit descends from the protocol commit and that the protocol file is unchanged. | `scripts/dock.sh python scripts/verify_official.py` (integrity section), `git show 8171c7d`, [docs/DEVELOPMENT_LOG.md](docs/DEVELOPMENT_LOG.md) |
| The pipeline was frozen before the official batch | Tag `pipeline-frozen-v2` (`f18ed6b`); each run records the frozen-file hash, and the verifier checks it equals the hash committed at the run's commit. A test fails if any frozen file changes. | `backend/tests/test_pipeline_frozen.py`, verifier integrity section |
| Held-out seeds were used once each | Five disjoint held-out blocks, one per run, each allocated once and marked used in the seed ledger (a snapshot of its rows is committed). | verifier ledger rows, `docs/evidence/seed_ledger_snapshot.json`, `backend/tests/test_ledger.py` |
| The numbers are what the gate computes | The verifier recomputes the Wilson intervals, G1 to G6 statuses and the verdict from the stored counts and compares them with the stored gate report, `official_summary.json` and the dashboard JSON. | **Verify this result** on any official run page, or `scripts/dock.sh python scripts/verify_official.py` (217 checks, 0 mismatches at the time of writing) |
| The simulator is deterministic and the results reproduce | The verifier **re-simulates each official run's analysis set now** (unpatched policy and selected patch) and compares every count with the stored candidate table. The Playground gives the same output for the same input, and "Re-run in Playground" replays a recorded scenario with its stored seed. | **Verify this result**, **Re-run in Playground** (official run pages), `backend/tests/test_verify.py` |
| The gate is pure code, no model | `backend/app/gate/` imports no model client, SDK or analysis module (enforced by a test); thresholds are in `backend/app/core/gate_config.py`. | [backend/app/gate/gate.py](backend/app/gate/gate.py), `backend/tests/test_gate.py`, `backend/tests/test_gate_pure.py` |
| Nemotron models were really called | The **Model calls** panel on each run: stage, model, latency, tokens, retry, cached flag and the raw replies. For live runs it also shows the provider's response id, the model id as returned, the finish reason and UTC timestamps, captured at call time (older recorded runs show "not recorded" for those fields, never a guess). | run pages, `GET /api/runs/{id}/model_calls`, `frontend/public/data/live_replay/failed/calls.json`, `backend/tests/test_capture.py` |
| What is live and what is recorded | Every panel carries a chip: LIVE (computed just now by this server), RECORDED (a stored artifact, with run id and date) or REPLAY (a recording played back). The navbar shows "Backend online" with the pipeline tag and server time, or "Backend offline, showing recorded data". | any page, `GET /api/health` |
| No secret is served | Exported data and committed evidence are scanned for the API key and token patterns; prompts are not exported; model-call and reply endpoints scrub secrets. | `backend/tests/test_exports_clean.py`, `scripts/check_secrets.py` |
| The tests pass | The full suite runs inside the simulator image. | `scripts/dock.sh test` (350 tests passed in the image at the time of writing) |
| The whole journey, including the failures | Pipeline v1 was 1 of 5 VERIFIED (rehearsal), v2 was 4 of 8 (rehearsal), the official batch was 4 of 5 with one honest FAILED run (official_03, G5: 348/400, needed 360). Intervals overlap heavily; they are reported together, not as a proven improvement. 51 commits with dates and hashes. | [docs/DEVELOPMENT_LOG.md](docs/DEVELOPMENT_LOG.md) (generated by `python scripts/make_dev_log.py`), `recorded_runs/`, [FEEDBACK.md](FEEDBACK.md) |

**What cannot be re-verified, and why** (the verifier lists these in the same words instead of faking them: `scripts/verify_official.py` and the **Verify this result** panel):
- **Held-out pass counts (G5: 400 fresh scenarios, unpatched and patched).** Held-out seeds are gate-only and single-use, and per-scenario held-out results were never stored, so they cannot be re-simulated. They are checked for internal consistency only (Wilson intervals, thresholds, verdict).
- **Model outputs (scenario regions, hypotheses, candidate patches).** A model's reply is not reproducible. What is checkable: the stored raw replies and call log (the Model calls panel), and that every number downstream of them was measured by the simulator and the gate.
- **How the analysis set was generated.** Regenerating it needs the model. The stored scenario list is what was simulated, and re-simulating it reproduces the stored results.
- **Billing.** Cost figures are estimates from token counts and a price table; billing was not checked. Nebius Serverless Jobs were not used.

**See the verifier catch a change:** `scripts/dock.sh python scripts/tamper_demo.py` copies one run's stored gate report and summary into a temporary folder, raises one number in the copy (official_03's held-out patched pass count, 348 to 361, which would turn its FAILED into VERIFIED), runs the same recomputation on the untouched and the tampered copy, and prints the seven checks that now mismatch. It never writes to the repository and checks afterwards that the stored files are byte-identical.

**Git facts inside the image:** the container has no `.git`, so the protocol-date, ancestry, tag and frozen-hash rows are answered from `docs/evidence/git_facts_snapshot.json`, taken from git with `python scripts/verify_official.py --export-git-snapshot` before the build. Those rows say "from build snapshot": evidence of what git said at export time, not a live check. From a checkout the verifier uses real git.

## Tests

`scripts/dock.sh test` (full suite incl. simulator and the live-service tests). On the host, `cd backend && python -m pytest -q` runs the non-simulator tests and skips the rest.

## Layout and further docs

`backend/app/{api,core,llm,sim,scenarios,runner,analysis,gate,store}`, `frontend/`, `scripts/`, `docker/`, `docs/`, `recorded_runs/`. Simulator limits: [docs/SIM_FIDELITY.md](docs/SIM_FIDELITY.md). Pipeline v1 vs v2 diagnosis: [docs/P46_DIAGNOSIS.md](docs/P46_DIAGNOSIS.md). Scope: [CLAUDE.md](CLAUDE.md), [PROJECT_BRIEF.md](PROJECT_BRIEF.md). Progress: [STATUS.md](STATUS.md).

## License

MIT, see [LICENSE](LICENSE).
