"""FastAPI entry point (P3: health/version only; run, analysis and gate endpoints arrive in P4/P6)."""
from __future__ import annotations

import os

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import hosting
from ..live.api import install as install_live
from ..playground.api import install as install_playground
from ..sim import freeze

if os.environ.get("DATA_DIR") or hosting.host_mode():
    hosting.prepare_data_dir()  # runtime data (live runs, quota counters, the SQLite file) goes to DATA_DIR; local disk, lost on spin-down
app = FastAPI(title="RoboProof API", version="0.4.0")
_live = install_live(app)  # live rehearsal service (off unless LIVE_ENABLED=1)
install_playground(app, _live)  # simulator playground (no LLM spend except the guarded analyze endpoint)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/version")
def version() -> dict:
    try:
        import pybullet

        sim = {"pybullet_available": True, "pybullet_api": pybullet.getAPIVersion()}
    except ImportError:
        sim = {"pybullet_available": False}
    return {
        "runner_default": "local",  # LocalRunner fallback; Nebius runner is not implemented yet (PENDING_KEY)
        "freeze_hash": freeze.freeze_hash(),
        "cpu_count": os.cpu_count(),  # the host's visible cores
        "effective_cpus": round(hosting.effective_cpus(), 2),  # what this container may really use (cgroup limit)
        "workers": hosting.worker_count(),
        "memory_limit_bytes": hosting.memory_limit_bytes(),
        "host_mode": hosting.host_mode(),
        **sim,
    }


# Single-container hosting: when a built frontend is present, serve it (and only it) at "/" on the same port as /api.
# Registered last so every /api route wins; an unknown /api path stays a JSON 404 instead of falling through to the site.
FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIR") or Path(__file__).resolve().parents[3] / "frontend_dist")


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"], include_in_schema=False)
def _unknown_api(rest: str):
    return JSONResponse({"error": "not_found", "message": "No such API route."}, status_code=404)


if (FRONTEND_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="site")
