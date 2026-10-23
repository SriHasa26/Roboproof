"""POST /api/verify/{run_id}: recompute and re-simulate (analysis set only) one recorded official run. No LLM spend, no held-out seeds."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field
from fastapi.responses import JSONResponse

from ..live.api import client_ip
from ..core.schemas import Policy, Scenario
from ..core.seeds import BLOCKS
from ..playground.service import EXPLAIN, PlaygroundError, PlaygroundService
from . import core

ROOT = Path(__file__).resolve().parents[3]
RUN_RE = re.compile(r"^official_\d{2}_seed\d+$")


class RerunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str = Field(pattern=r"^[A-Za-z0-9_\-]{1,40}$")


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

    def _run_dir(run_id: str) -> Path | None:
        if not RUN_RE.match(run_id) or run_id not in official_ids(root):
            return None
        return root / "recorded_runs" / "official_001" / run_id

    @r.get("/api/verify/{run_id}/scenarios")
    def failing(run_id: str):
        """Analysis-set scenarios that failed on the unpatched policy in the stored results, and the run's final patch (for 'Re-run in Playground')."""
        d = _run_dir(run_id)
        if d is None:
            return JSONResponse({"error": "not_found", "message": "No such recorded official run."}, status_code=404)
        base = json.loads((d / "baseline_results.json").read_text(encoding="utf-8"))["results"]
        s = json.loads((d / "summary.json").read_text(encoding="utf-8"))
        targeted = set(json.loads((d / "targeted_failures.json").read_text(encoding="utf-8"))["all"])
        fails = [{"id": b["scenario_id"], "reason": b.get("failure_reason"), "targeted": b["scenario_id"] in targeted} for b in base if not b["success"]]
        fails.sort(key=lambda f: (not f["targeted"], f["id"]))
        return {"run_id": run_id, "failing": fails[:60], "n_failing": len(fails), "final_patch": s["attempts"][-1]["patched_policy"]}

    @r.post("/api/verify/{run_id}/rerun")
    def rerun(run_id: str, body: RerunBody, request: Request):
        """Re-simulate ONE stored analysis-set scenario (its stored seed, a dev seed) with the default policy and with the run's final patch, and compare the default result with the stored one."""
        d = _run_dir(run_id)
        if d is None:
            return JSONResponse({"error": "not_found", "message": "No such recorded official run."}, status_code=404)
        aset = json.loads((d / "analysis_set.json").read_text(encoding="utf-8"))["scenarios"]
        scn = next((x for x in aset if x["id"] == body.scenario_id), None)
        if scn is None:
            return JSONResponse({"error": "not_found", "message": "That scenario is not in this run's analysis set."}, status_code=404)
        if scn["seed"] >= BLOCKS["rehearsal"][0]:  # the stored analysis set only holds dev seeds; refuse anything else
            return JSONResponse({"error": "refused", "message": "Only dev-seed scenarios can be re-run here."}, status_code=403)
        stored = next(b for b in json.loads((d / "baseline_results.json").read_text(encoding="utf-8"))["results"] if b["scenario_id"] == body.scenario_id)
        patched = json.loads((d / "summary.json").read_text(encoding="utf-8"))["attempts"][-1]["patched_policy"]
        try:
            svc._enabled()
            svc._rate(client_ip(request, live.cfg if live else _NoProxy), "rerun", 20, 60)
            with svc._Slot(svc.slots):
                t0 = time.perf_counter()
                a = svc.scenario_fn(Policy(), Scenario(**scn), svc.cfg.scenario_timeout_s)
                b = svc.scenario_fn(Policy(**patched), Scenario(**scn), svc.cfg.scenario_timeout_s)
        except PlaygroundError as e:
            return JSONResponse({"error": e.code, "message": e.message}, status_code=e.status)

        def pack(out, policy):
            res = out["result"]
            return {"policy": policy, "result": res, "trajectory": out["trajectory"], "world": out["world"],
                    "explanation": EXPLAIN.get(res.get("failure_reason")) if res.get("failure_reason") else "The cube was lifted, carried over the wall and placed upright inside the target zone.", "seed": scn["seed"], "scenario": scn}
        keys = ("success", "collision", "completion_time_s", "final_place_error_m", "max_slip_m", "failure_reason")
        same = all(a["result"].get(k) == stored.get(k) for k in keys)
        return {"run_id": run_id, "scenario_id": body.scenario_id, "seed": scn["seed"], "default": pack(a, Policy().model_dump()), "patched": pack(b, patched), "stored_default_result": {k: stored.get(k) for k in keys},
                "matches_stored": same, "wall_clock_s": round(time.perf_counter() - t0, 2),
                "note": "Recorded scenario and seed from the official run's analysis set (a dev seed), simulated now. Exploration, not part of the official evaluation."}

    return r


class _NoProxy:
    trust_proxy = False


def install(app: FastAPI, svc: PlaygroundService, live=None, verify_fn=core.verify_all, root: Path = ROOT) -> None:
    app.include_router(make_router(svc, live, verify_fn, root))
