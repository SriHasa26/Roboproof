"""POST /api/verify/{run_id}: recompute and re-simulate (analysis set only) one recorded official run. No LLM spend, no held-out seeds."""
from __future__ import annotations

import re
import time
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from ..live.api import client_ip
from ..playground.service import PlaygroundError, PlaygroundService
from . import core

ROOT = Path(__file__).resolve().parents[3]
RUN_RE = re.compile(r"^official_\d{2}_seed\d+$")


def official_ids(root: Path = ROOT) -> list[str]:
    base = root / "recorded_runs" / "official_001"
    return sorted(d.name for d in base.glob("official_*") if d.is_dir() and (d / "summary.json").exists()) if base.exists() else []


def make_router(svc: PlaygroundService, live, verify_fn=core.verify_all, root: Path = ROOT) -> APIRouter:
    r = APIRouter()

    @r.get("/api/verify")
    def list_runs() -> dict:
        return {"runs": official_ids(root), "note": "Recorded official runs that can be re-verified. Analysis sets only: held-out seeds are never simulated here."}

    @r.post("/api/verify/{run_id}")
    def verify(run_id: str, request: Request):
        if not RUN_RE.match(run_id) or run_id not in official_ids(root):  # whitelist: the id never becomes a path from the client
            return JSONResponse({"error": "not_found", "message": "No such recorded official run."}, status_code=404)
        try:
            svc._enabled()
            svc._rate(client_ip(request, live.cfg if live else _NoProxy), "verify", 6, 600)
            t0 = time.perf_counter()
            with svc._Slot(svc.slots):
                res = verify_fn(root, resim=True, only=run_id, timeout_s=svc.cfg.sweep_timeout_s * 0.9)
        except PlaygroundError as e:
            return JSONResponse({"error": e.code, "message": e.message}, status_code=e.status)
        except RuntimeError as e:
            return JSONResponse({"error": "timeout", "message": f"The re-simulation did not finish in time ({e})."}, status_code=504)
        rows = res["runs"][run_id]
        return {"run_id": run_id, "mode": "verification of a recorded official run (analysis set re-simulated; held-out seeds never used)", "rows": rows, "integrity": res["integrity"],
                "limits": res["limits"], "tally": core.tally(res), "elapsed_s": round(time.perf_counter() - t0, 1),
                "commands": [f"scripts/dock.sh python scripts/verify_official.py --run {run_id}", "scripts/dock.sh python scripts/verify_official.py"]}

    return r


class _NoProxy:
    trust_proxy = False


def install(app: FastAPI, svc: PlaygroundService, live=None, verify_fn=core.verify_all, root: Path = ROOT) -> None:
    app.include_router(make_router(svc, live, verify_fn, root))
