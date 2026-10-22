# RoboProof: submission pack

**Category:** Physical AI (simulation only, no physical hardware).

## Project description (about 250 words)

RoboProof is an AI test engineer for robot policies. Fixing a robot controller is easy; knowing the fix works is hard. RoboProof takes one built-in task (a simulated gripper picks a cube and places it in a target zone) and runs the full loop: a Nemotron model proposes risky parameter regions, code adds a Latin-hypercube coverage sweep, and PyBullet runs hundreds of seeded scenarios. Failure statistics are computed in code. A Nemotron reasoning model turns those statistics into testable hypotheses and proposes four bounded patches to the controller's numeric parameters (grip force, speeds, lift height, retries). Code measures every candidate and picks one by a fixed rule.

The differentiator is the Proof-of-Robustness Gate, pure deterministic code with no LLM. It checks determinism, that targeted failures reproduce and are fixed, that nothing that passed before now fails (within a stated 2% budget), and that the patch generalises to a fresh, single-use held-out set of 400 scenarios with a Wilson 95% confidence interval. The verdict is VERIFIED, FAILED or UNVERIFIED. The model never decides pass or fail.

Official pre-registered batch (5 runs, frozen pipeline): 4 of 5 VERIFIED, a small sample (Wilson 95% [37.6%, 96.4%]; the v2 rehearsal study was 4 of 8); the fifth was honestly FAILED at the held-out check (348/400 vs 360 needed). A hand-written overfit "trap" patch is rejected by the gate. A static dashboard shows checklists, candidates, hypotheses, heatmaps and same-seed before/after replays, plus a page of limits: this is a simplified simulated robot, thresholds were set on development data, and the sample is small.

## How Nebius and NVIDIA are used

NVIDIA Nemotron models run on Nebius Token Factory (OpenAI-compatible API): Nemotron-3-Nano-30B-A3B for scenario generation (fallback Nemotron-3-Super-120B-A12B), Nemotron-3-Ultra-550B-A55B for failure analysis and fix proposals. Model IDs come from environment variables. Simulations ran in a local Docker container, **not** on Nebius Serverless Jobs (not built or tested; labelled everywhere). Cost figures are estimates; billing is UNCONFIRMED. Feedback: [FEEDBACK.md](FEEDBACK.md).

## Demo video script (max 3:00; at least 1:00 of modules running)

| Time | Screen | Say |
|---|---|---|
| 0:00-0:20 | Title card, then the dashboard Overview top | "Robot policies fail in ways nobody listed. An AI can propose a fix, but how do you know it works? RoboProof makes the fix prove itself, or says it can't." |
| 0:20-1:40 | Screen-record the terminal: `scripts/dock.sh python scripts/run_rehearsal.py --name demo_live --master-seed 11` running live (about 2-3 min real time: speed up the idle waits, keep the log readable) | "This is the real pipeline: Nemotron Nano proposes regions, PyBullet runs the scenarios, Ultra explains the failures and proposes four patches, code measures them, then the gate." End on the printed gate verdict, whatever it is. |
| 1:40-2:30 | Dashboard: Overview official table, open official_01: gate checklist, candidates table, hypotheses, heatmaps, same-seed replay GIFs | "Official batch: 4 of 5 verified, one honestly failed. Here is attempt 1 failing G3, attempt 2 passing. Same scenario, same seed, before and after." |
| 2:30-3:00 | Scripted trap page, then Limits page | "A deliberately overfit patch, hand-written, is rejected by G4 and G5. And what we do not show: simplified robot, small sample, simulations ran locally, not on Nebius Serverless Jobs." |

Record a live run beforehand as a fallback in case Token Factory is slow (the Nano endpoint hung once during development, see FEEDBACK.md).

## Hackathon checklist

Done:
- [x] Physical AI track, simulation only, one task
- [x] Nemotron models on Nebius Token Factory for every LLM call
- [x] Deterministic gate G1-G6 with unit tests for each failure path (209 tests pass in the image)
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

Create the public repo and push (replace `YOUR_USER`; needs the `gh` CLI logged in, or create the repo on github.com and use the last two lines):

```bash
cd "C:/Users/Yagna Sri Hasa Telu/OneDrive/Desktop/react projects/nvdia"
git branch -M main
gh repo create roboproof --public --source=. --remote=origin --push
# without gh: create an empty public repo "roboproof" on github.com, then
#   git remote add origin https://github.com/YOUR_USER/roboproof.git
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
