# STATUS (lean plan; pipeline v2 frozen, nothing in it may change)

| Part | State |
|---|---|
| 1. Official batch (K=5, per docs/OFFICIAL_PROTOCOL.md) | DONE: 4 of 5 VERIFIED, recorded in recorded_runs/official_001 |
| 2. Export data for the static dashboard | DONE (frontend/public/data, 677 KiB) |
| 3. Static dashboard (frontend/) | DONE (build passes; Overview, Run, Trap, Limits pages checked visually via headless Edge screenshots; Runs list page not screenshotted) |
| 4. Submission pack (README, SUBMISSION.md, LIMITATIONS.md) | next |

Notes
- During the batch, artifacts are written to `backend/data/official_001_work` (gitignored) because the official-run guard needs a clean tree before every run; they are copied to `recorded_runs/official_001` afterwards.
- Out of scope: P5 (Nebius Serverless Jobs). Simulations run on the local container.
