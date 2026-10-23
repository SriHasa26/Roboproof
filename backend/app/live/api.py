"""HTTP surface of the live service. The client can send an access code and nothing else: no seed, no flag, no pipeline parameter."""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

from fastapi import APIRouter, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from .config import LiveConfig
from .manager import SERVED_FILES, LiveError, RunManager

ROOT = Path(__file__).resolve().parents[3]


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # any other field (seed, official, held_out, ...) is a 422
    access_code: str | None = None


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cancel_token: str


def client_ip(request: Request, cfg: LiveConfig) -> str:
    if cfg.trust_proxy:
        xf = request.headers.get("x-forwarded-for", "")
        if xf:
            return xf.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _err(e: LiveError) -> JSONResponse:
    return JSONResponse({"error": e.code, "message": e.message, **e.extra}, status_code=e.status)


def _export_module():
    spec = importlib.util.spec_from_file_location("export_demo_data", ROOT / "scripts" / "export_demo_data.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def make_router(mgr: RunManager) -> APIRouter:
    r = APIRouter()
    cfg = mgr.cfg

    @r.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "live_enabled": cfg.enabled}

    @r.get("/api/live/status")
    def live_status() -> dict:
        return mgr.status()

    @r.post("/api/runs", status_code=201)
    def start(body: StartRequest, request: Request):
        try:
            st = mgr.start(client_ip(request, cfg), body.access_code)
        except LiveError as e:
            return _err(e)
        return {"id": st.id, "cancel_token": st.cancel_token, "status": st.status, "mode": "rehearsal", "official": False}

    @r.get("/api/runs/{rid}")
    def get_run(rid: str):
        st = mgr.get(rid)
        if st is None:
            return JSONResponse({"error": "not_found", "message": "No such run."}, status_code=404)
        return st.meta()

    @r.post("/api/runs/{rid}/cancel")
    def cancel(rid: str, body: CancelRequest):
        try:
            st = mgr.cancel(rid, body.cancel_token)
        except LiveError as e:
            return _err(e)
        return {"id": st.id, "cancel_requested": True}

    @r.get("/api/runs/{rid}/events")
    async def events(rid: str, request: Request, last_event_id: str | None = Header(default=None), start: int = Query(default=0, ge=0)):
        st = mgr.get(rid)
        if st is None:
            return JSONResponse({"error": "not_found", "message": "No such run."}, status_code=404)
        # always replayable from the first event; Last-Event-ID resumes after that event
        i = start
        if last_event_id and last_event_id.isdigit():
            i = int(last_event_id) + 1

        async def gen():
            nonlocal i
            idle = 0
            while True:
                if await request.is_disconnected():
                    return
                batch = st.events[i:]
                for ev in batch:
                    yield f"id: {ev['seq']}\nevent: {'end' if ev['stage'] == 'end' else 'message'}\ndata: {json.dumps(ev)}\n\n"
                    i = ev["seq"] + 1
                    if ev["stage"] == "end":
                        return
                if not batch:
                    idle += 1
                    if st.done and i >= len(st.events):
                        return
                    if idle % 40 == 0:
                        yield ": keep-alive\n\n"
                await asyncio.sleep(0.25)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @r.get("/api/runs/{rid}/files/{name}")
    def files(rid: str, name: str):
        st = mgr.get(rid)
        if st is None or name not in SERVED_FILES:  # whitelist: no path from the client is ever joined to a directory
            return JSONResponse({"error": "not_found", "message": "No such file."}, status_code=404)
        p = st.dir / name if name in ("events.jsonl", "meta.json") else st.rid_dir / name
        try:
            p = p.resolve(strict=True)
            p.relative_to(cfg.runs_dir.resolve())
        except (OSError, ValueError):
            return JSONResponse({"error": "not_found", "message": "No such file."}, status_code=404)
        return FileResponse(p, media_type="application/json" if name.endswith(".json") else "text/plain")

    @r.get("/api/runs/{rid}/scenarios")
    def scenarios(rid: str):
        """Per-scenario outcomes of the unpatched policy on the run's analysis set (for the 3D failure map)."""
        st = mgr.get(rid)
        if st is None or not st.done or not (st.rid_dir / "baseline_results.json").exists():
            return JSONResponse({"error": "not_found", "message": "No scenario results for this run."}, status_code=404)
        try:
            return _export_module().scenario_points(st.rid_dir)
        except Exception as e:
            return JSONResponse({"error": "failed", "message": f"Could not read scenario results: {type(e).__name__}"}, status_code=500)

    @r.get("/api/runs/{rid}/report")
    def report(rid: str):
        """The same JSON shape the static dashboard's run page reads, built from this run's artifacts by the export script's own code."""
        st = mgr.get(rid)
        if st is None or not st.done or not (st.rid_dir / "summary.json").exists():
            return JSONResponse({"error": "not_found", "message": "No finished report for this run."}, status_code=404)
        mod = _export_module()
        try:
            run = mod.build_run(st.rid_dir, "rehearsal", "v2")
        except Exception as e:  # a half-written run must not crash the service
            return JSONResponse({"error": "report_failed", "message": f"Could not build the report: {type(e).__name__}"}, status_code=500)
        run["id"] = st.id
        run["badges"] = {**run.get("badges", {}), "mode": "rehearsal", "recorded": False}
        return run

    return r


def install(app: FastAPI, cfg: LiveConfig | None = None) -> RunManager:
    cfg = cfg or LiveConfig.from_env()
    mgr = RunManager(cfg)
    app.include_router(make_router(mgr))
    if cfg.allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=cfg.allowed_origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Last-Event-ID"])
    app.state.live = mgr
    return mgr
