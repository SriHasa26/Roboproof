# RoboProof: submission pack

**Category:** Physical AI (simulation only, no physical hardware).

## Project description (about 250 words)

RoboProof is an AI test engineer for robot policies. Fixing a robot controller is easy; knowing the fix works is hard. RoboProof takes one built-in task (a simulated gripper picks a cube and places it in a target zone) and runs the full loop: a Nemotron model proposes risky parameter regions, code adds a Latin-hypercube coverage sweep, and PyBullet runs hundreds of seeded scenarios. Failure statistics are computed in code. A Nemotron reasoning model turns those statistics into testable hypotheses and proposes four bounded patches to the controller's numeric parameters (grip force, speeds, lift height, retries). Code measures every candidate and picks one by a fixed rule.

The differentiator is the Proof-of-Robustness Gate, pure deterministic code with no LLM. It checks determinism, that targeted failures reproduce and are fixed, that nothing that passed before now fails (within a stated 2% budget), and that the patch generalises to a fresh, single-use held-out set of 400 scenarios with a Wilson 95% confidence interval. The verdict is VERIFIED, FAILED or UNVERIFIED. The model never decides pass or fail.

Official pre-registered batch (5 runs, frozen pipeline): 4 of 5 VERIFIED, a small sample (Wilson 95% [37.6%, 96.4%]; the v2 rehearsal study was 4 of 8); the fifth was honestly FAILED at the held-out check (348/400 vs 360 needed). A hand-written overfit "trap" patch is rejected by the gate. A static dashboard shows checklists, candidates, hypotheses, heatmaps and same-seed before/after replays, plus a page of limits: this is a simplified simulated robot, thresholds were set on development data, and the sample is small.

## How Nebius and NVIDIA are used

NVIDIA Nemotron models run on Nebius Token Factory (OpenAI-compatible API): Nemotron-3-Nano-30B-A3B for scenario generation (fallback Nemotron-3-Super-120B-A12B), Nemotron-3-Ultra-550B-A55B for failure analysis and fix proposals. Model IDs come from environment variables. Simulations ran in a local Docker container, **not** on Nebius Serverless Jobs (not built or tested; labelled everywhere). Cost figures are estimates; billing is UNCONFIRMED. Feedback: [FEEDBACK.md](FEEDBACK.md).

## Demo video script (max 3:00; about 2:00 of real modules running)

Prepare before recording: backend running (`docker compose up`, `LIVE_ENABLED=1`), the site built with `VITE_API_BASE`, `docs/demo_scenarios.csv` on the desktop, one earlier live run recorded as a fallback. All numbers on screen are real; say "exploration, not a verdict" whenever the playground is on screen.

| Time | Screen | Say |
|---|---|---|
| 0:00-0:15 | Landing page: hero, the gate section | "Robot fixes you can trust. RoboProof proposes a fix with Nemotron, and a deterministic gate refuses to say verified unless it is proven." |
| 0:15-0:30 | Results page: 4 of 5 VERIFIED, the FAILED run, the live-runs panel | "Official batch: 4 of 5 verified, small sample, and one honestly failed. Everything here is recorded or live; nothing is staged." |
| 0:30-0:55 | Playground, single tab: click the chip "A 700 g cube on a wet tray with a noisy camera", press Interpret (about 3 s), show the filled sliders and the "model interpretation, unverified" reasons, press Run simulation | "I describe a situation in plain English. A Nemotron model proposes the numbers; I can edit them. The simulator, not the model, decides: fail, missed grasp, and here is the real trajectory in 3D." |
| 0:55-1:10 | Raise grip force to 40, Run simulation again | "Same scenario, same seed, stronger grip: pass." |
| 1:10-1:35 | Sweep tab: Test this policy on 100 scenarios (about 8 s); pass rate against the default with intervals; the 3D failure map; click a red point | "100 scenarios, my policy against the default on identical scenarios, with confidence intervals. I click a failing point and replay that exact failure." |
| 1:35-1:55 | Sweep tab, Upload CSV: choose `demo_scenarios.csv`, Run the table; show the results table and Download results | "Or bring your own scenarios as a CSV. Every row is validated against the frozen bounds before anything runs." |
| 1:55-2:45 | `/live`: Start live rehearsal, confirm; stage timeline, log, candidate table, gate checks G1 to G6, verdict (the real run takes about 2.5 to 3.5 min: speed up the waiting, keep the log readable) | "Now the full pipeline, live: the model proposes risky regions, PyBullet runs the scenarios, Ultra explains the failures and proposes four patches, code measures them, and the gate decides. A rehearsal, never an official result." |
| 2:45-3:00 | Limits page, then the scripted-trap page | "What we do not show: a simplified robot, one task, simulations ran locally not on Nebius Serverless Jobs. A hand-written overfit patch is rejected by the gate." |

**If a model call fails on camera** (the interpret and analyze calls can fail about 1 time in 8, for example the model returns an unusable answer): press the button again; if it fails twice, say "the model's answer failed validation, so nothing was used" (that is the designed behaviour) and click a preset chip or type the values by hand. Never fake a result. If the backend is down, use the recorded replay on `/live` and the three recorded playground examples, and say they are recordings. Keep one earlier successful live run recorded as a fallback take (the Nano endpoint hung once during development, see FEEDBACK.md).

CLI alternative for the pipeline segment: `scripts/dock.sh python scripts/run_reliability.py --seeds 701 --out recorded_runs/demo_live` (about 3.5 min, prints `MODE: REHEARSAL`).

## Hackathon checklist

Done:
- [x] Physical AI track, simulation only, one task
- [x] Nemotron models on Nebius Token Factory for every LLM call
- [x] Deterministic gate G1-G6 with unit tests for each failure path (314 tests pass in the image)
- [x] Pre-registered official batch, all runs reported (4/5 VERIFIED)
- [x] Scripted trap shown rejected, clearly labelled
- [x] Static dashboard with real recorded runs and replays; limits page
- [x] README, MIT LICENSE, FEEDBACK.md (measured notes only), secrets check passes

Not done:
- [ ] Simulations on Nebius Serverless Jobs (skipped; `LocalRunner` only)
- [ ] Hosted demo URL (you deploy the static build; commands below)
- [ ] Public GitHub repo (you create and push)
- [ ] Demo video (you record)
- [ ] Verified billing figures (UNCONFIRMED)

## Manual steps for you

Create the public repo and push (the repo is already created and empty: use the last two lines):

```bash
cd "C:/Users/Yagna Sri Hasa Telu/OneDrive/Desktop/react projects/nvdia"
git branch -M main
gh repo create roboproof --public --source=. --remote=origin --push
# without gh: create an empty public repo "roboproof" on github.com, then
#   git remote add origin https://github.com/SriHasa26/Roboproof.git
#   git push -u origin main --tags
```

Check `git status` is clean and `.env` is not tracked (`git ls-files .env` prints nothing) before pushing.

Deploy the static dashboard (free host; the build uses relative paths and a hash router, so it works from any sub-path). Build first:

```bash
cd frontend && npm install && npm run build
```

- Netlify: `npx netlify-cli deploy --prod --dir=dist` (log in when prompted), or drag the `frontend/dist` folder onto app.netlify.com/drop.
- Or Vercel: `cd dist && npx vercel --prod`.
- Or GitHub Pages: `npx gh-pages -d dist` (run in `frontend/`), then enable Pages from the `gh-pages` branch in repo settings.

Then open the URL, click through Overview, a run, Scripted trap and Limits, and put the URL in the submission form. Add the repo URL and the video link.
