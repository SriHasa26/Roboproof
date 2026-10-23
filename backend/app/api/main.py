"""FastAPI entry point (P3: health/version only; run, analysis and gate endpoints arrive in P4/P6)."""
from __future__ import annotations

import os

from fastapi import FastAPI

from ..live.api import install as install_live
from ..sim import freeze

app = FastAPI(title="RoboProof API", version="0.4.0")
install_live(app)  # live rehearsal service (off unless LIVE_ENABLED=1)


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
        "cpu_count": os.cpu_count(),
        **sim,
    }
