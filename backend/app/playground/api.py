"""HTTP surface of the playground. Every field is validated against the frozen bounds; nothing from the client reaches a command line."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..live.api import client_ip
from ..live.manager import LiveError, RunManager
from .service import AnalyzeRequest, PlaygroundConfig, PlaygroundError, PlaygroundService, ScenarioRequest, SweepRequest
from .spec import build_spec

MIN_FAILURES_TO_ANALYZE = 5


def _err(e: PlaygroundError | LiveError) -> JSONResponse:
    return JSONResponse({"error": e.code, "message": e.message}, status_code=e.status)


def make_router(svc: PlaygroundService, live: RunManager | None) -> APIRouter:
    r = APIRouter()

    @r.get("/api/sim/spec")
    def spec() -> dict:
        s = build_spec(svc.cfg.max_sweep_n)
        s["enabled"] = svc.cfg.enabled
        s["analyze_available"] = bool(live and live.cfg.enabled)
        s["analyze_access_code_required"] = bool(live and live.cfg.access_code)
        s["analyze_est_usd"] = svc.cfg.analyze_usd_est
        return s

    @r.post("/api/sim/scenario")
    def scenario(body: ScenarioRequest, request: Request):
        try:
            return svc.scenario(body, client_ip(request, live.cfg if live else _NoProxy))
        except PlaygroundError as e:
            return _err(e)

    @r.post("/api/sim/sweep")
    def sweep(body: SweepRequest, request: Request):
        try:
            return svc.sweep(body, client_ip(request, live.cfg if live else _NoProxy))
        except PlaygroundError as e:
            return _err(e)

    @r.post("/api/sim/analyze")
    def analyze_sweep(body: AnalyzeRequest, request: Request):
        """Optional: Nemotron hypotheses for a finished sweep. Spends credits, so it needs LIVE_ENABLED, the access code, and room under the daily spend cap."""
        if live is None or not live.cfg.enabled:
            return JSONResponse({"error": "disabled", "message": "Analysis needs the live backend to be enabled (it spends credits)."}, status_code=503)
        if live.cfg.access_code and not secrets.compare_digest((body.access_code or "").encode(), live.cfg.access_code.encode()):
            return JSONResponse({"error": "access_code", "message": "A valid access code is required for the analysis."}, status_code=401)
        try:
            svc._rate(client_ip(request, live.cfg), "analyze", 3, 3600)
            sw = svc.get_sweep(body.sweep_id)
            n_fail = sum(1 for x in sw["results"] if not x.success)
            if n_fail < MIN_FAILURES_TO_ANALYZE:
                return JSONResponse({"error": "too_few_failures", "message": f"Only {n_fail} scenarios failed; at least {MIN_FAILURES_TO_ANALYZE} are needed for an analysis."}, status_code=422)
            live.reserve_spend(svc.cfg.analyze_usd_est)
        except (PlaygroundError, LiveError) as e:
            return _err(e)
        return _run_analysis(svc, live, sw)

    return r


class _NoProxy:
    trust_proxy = False


def _run_analysis(svc: PlaygroundService, live: RunManager, sw: dict):
    from ..analysis.analyst import analyze, targeted_failures
    from ..analysis.evidence import compute_evidence
    from ..core.config import load_settings
    from ..llm.client import LLMClient, LLMError
    from ..pipeline import estimate_cost, fetch_pricing
    settings = load_settings()
    if not (settings.api_key and settings.model_reasoning):
        live.adjust_spend(-svc.cfg.analyze_usd_est)
        return JSONResponse({"error": "not_configured", "message": "The server has no model configured for the analysis."}, status_code=503)
    client = LLMClient(settings)
    scns, results = sw["scenarios"], sw["results"]
    ev = compute_evidence(scns, results)
    try:
        hyps = analyze(client, ev, scns, sw["policy"])
    except LLMError as e:
        live.adjust_spend(-svc.cfg.analyze_usd_est)
        return JSONResponse({"error": "model_failed", "message": f"The model's answer could not be used ({type(e).__name__}). Nothing was charged to the daily cap."}, status_code=502)
    tf = targeted_failures(hyps, scns, results)
    est = estimate_cost(client.records, fetch_pricing(settings, {settings.model_reasoning}))
    if est is not None:
        live.adjust_spend(est - svc.cfg.analyze_usd_est)
    by_id = {i.id: i for i in ev.items}
    out = [{"id": h.id, "model_text_unverified": {"statement": h.statement, "mechanism": h.mechanism, "prediction": h.prediction},
            "region": h.region, "levers": [lv.model_dump() for lv in h.levers], "targeted_failures": len(tf["by_hypothesis"].get(h.id, [])),
            "evidence": [{"id": rf, "kind": by_id[rf].kind, "title": by_id[rf].title, "data": by_id[rf].data} for rf in h.evidence_refs if rf in by_id]} for h in hyps]
    return {"sweep_id": sw.get("id"), "hypotheses": out, "model": settings.model_reasoning, "estimated_cost_usd": est,
            "label": "Model opinion, unverified. Every number comes from the sweep's evidence, looked up by id; the wording is the model's.",
            "cost_note": "ESTIMATE from token counts and API prices; billing is not checked."}


async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 without echoing the offending input: a NaN or Infinity in the request cannot be serialised back, and echoing user text is not needed."""
    errs = [{"field": ".".join(str(x) for x in e.get("loc", ()) if x != "body"), "message": str(e.get("msg", "invalid"))} for e in exc.errors()]
    return JSONResponse({"error": "invalid_input", "message": "; ".join(f"{e['field']}: {e['message']}" for e in errs)[:500], "details": errs}, status_code=422)


def install(app: FastAPI, live: RunManager | None = None, cfg: PlaygroundConfig | None = None) -> PlaygroundService:
    app.add_exception_handler(RequestValidationError, _validation_error)
    svc = PlaygroundService(cfg or PlaygroundConfig.from_env())
    app.include_router(make_router(svc, live))
    app.state.playground = svc
    return svc
