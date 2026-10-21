# RoboProof

[MIT License](LICENSE)

An AI test engineer for robot policies. It stress-tests a simulated pick-and-place arm, diagnoses failures, proposes a bounded parameter fix, and returns VERIFIED / FAILED / UNVERIFIED from a deterministic Proof-of-Robustness Gate. Built for the NVIDIA x Nebius Global AI Hackathon (Physical AI track).

**This is a simulation, not a real robot.** Nothing here has been validated on hardware. See `docs/SIM_FIDELITY.md` for simulator limits.

**Status: work in progress.** P1 (foundations) done. Everything that needs a real Nebius call is marked `PENDING_KEY` in [docs/NEBIUS_NOTES.md](docs/NEBIUS_NOTES.md). No measured results exist yet, so none are claimed.

## Setup

```bash
cp .env.example .env        # fill in NEBIUS_API_KEY
pip install -r backend/requirements.txt
cd backend && python -m pytest
python scripts/list_models.py --filter nemotron   # then set NEBIUS_MODEL_FAST / NEBIUS_MODEL_REASONING
```

Model IDs and keys come only from environment variables.

## Layout

`backend/app/{api,core,llm,sim,scenarios,runner,analysis,gate,store}`, `backend/tests`, `frontend/`, `scripts/`, `docker/`, `docs/`, `recorded_runs/`.

See [CLAUDE.md](CLAUDE.md) and [PROJECT_BRIEF.md](PROJECT_BRIEF.md) for scope and gate rules.
