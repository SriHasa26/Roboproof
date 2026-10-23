# STATUS (lean plan; pipeline v2 frozen, nothing in it may change)

| Part | State |
|---|---|
| 1. Official batch (K=5, per docs/OFFICIAL_PROTOCOL.md) | DONE: 4 of 5 VERIFIED, recorded in recorded_runs/official_001 |
| 2. Export data for the static dashboard | DONE (frontend/public/data, 677 KiB) |
| 3. Static dashboard (frontend/) | DONE (build passes; Overview, Run, Trap, Limits pages checked visually via headless Edge screenshots; Runs list page not screenshotted) |
| 4. Submission pack (README, SUBMISSION.md, LIMITATIONS.md) | DONE (tests: 209 passed in image, 183 passed + 15 skipped on host; check_secrets OK). Not pushed or deployed; manual steps in SUBMISSION.md |
| Pre-submission audit | DONE: display fixes, wording, live-run command fixed (run_reliability.py), clean-clone test passed |

Notes
- During the batch, artifacts are written to `backend/data/official_001_work` (gitignored) because the official-run guard needs a clean tree before every run; they are copied to `recorded_runs/official_001` afterwards.
- Out of scope: P5 (Nebius Serverless Jobs). Simulations run on the local container.

## UI overhaul plan (second master prompt)
| Part | State |
|---|---|
| A. Design system + landing + routing | DONE (landing, nav/footer, 404, meta, motion toggle) |
| B1. Procedural 3D hero (lazy chunk, fallback) | DONE |
| B2. 3D failure map, B3 motion language | next |
| C. Restyle old pages | next |
| D. Live backend (backend/app/live, docker-compose) | DONE: 20 tests with a fake pipeline |
| E. Live console UI + recorded replay | DONE: one real live run recorded (VERIFIED, 153.5 s, est. $0.031) |
| B2 3D failure map, B3 motion, C restyle | DONE (results page, run page, shared UI; trap/about restyled via the shared system) |
| F. QA/docs | DONE: 229 tests pass in image (203 + 15 skipped on host); README and SUBMISSION updated |

## Typography fix + Playground (third master prompt)
| Part | State |
|---|---|
| 1. Typography (Sora, DM Sans, JetBrains Mono, variable fonts) | DONE |
| 2. Playground (backend, UI, offline examples, tests) | DONE |
| 3. QA and docs | DONE: 273 tests pass in the image |
