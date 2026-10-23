"""Build frontend/public/data/ for the STATIC dashboard from recorded_runs/. No model calls, no live computation in the dashboard.

Everything numeric is copied or derived in code from stored artifacts (hypothesis numbers are looked up from evidence.json by id,
never taken from model text). Replay GIFs are recorded from the frozen simulator for one failing and one fixed scenario of the SAME
seed (needs PyBullet: run inside the sim image). Usage:
  scripts/dock.sh python scripts/export_demo_data.py [--no-replays]
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.bounds import SCENARIO_BOUNDS  # noqa: E402
from app.core.stats import wilson  # noqa: E402

REC = ROOT / "recorded_runs"
OUT = ROOT / "frontend" / "public" / "data"
RUNNER_BADGE = "LOCAL FALLBACK, not Nebius"
TRAP_LABEL = "scripted example, not model output"


def jl(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def put(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")


def norm_check(c: dict) -> dict:
    st = c["status"]
    if c.get("skipped_after_failure"):  # records written before skipped_after_failure became its own status
        st = "skipped_after_failure"
    return {"id": c["id"], "name": c["name"], "status": st, "observed": c.get("observed", {}), "threshold": c.get("threshold", {}), "details": c.get("details", "")}


def heatmap(scenarios: list[dict], results: dict, ax_x: str, ax_y: str, nb: int = 5) -> dict:
    def b(v, ax):
        lo, hi = SCENARIO_BOUNDS[ax]
        return max(0, min(int((v - lo) / (hi - lo) * nb), nb - 1))

    cells = [[{"n": 0, "n_fail": 0} for _ in range(nb)] for _ in range(nb)]
    for s in scenarios:
        r = results.get(s["id"])
        if r is None:
            continue
        c = cells[b(s[ax_y], ax_y)][b(s[ax_x], ax_x)]
        c["n"] += 1
        c["n_fail"] += 0 if r["success"] else 1
    edges = lambda ax: [round(SCENARIO_BOUNDS[ax][0] + (SCENARIO_BOUNDS[ax][1] - SCENARIO_BOUNDS[ax][0]) * i / nb, 4) for i in range(nb + 1)]  # noqa: E731
    return {"x": ax_x, "y": ax_y, "x_edges": edges(ax_x), "y_edges": edges(ax_y), "cells": cells}


def v1_candidate_table(att: dict) -> dict:
    c = att["dev_checks"]
    g3, g4 = c["G3"]["observed"], c["G4"]["observed"]
    return {"attempt": att["attempt"], "selected_index": 0, "regression_budget": c["G4"]["threshold"].get("budget"), "v1_single_patch": True,
            "diversity_violations": [], "dropped": [], "candidates": [{
                "index": 0, "applied": att["model_proposal"]["changes"], "fixed": g3.get("fixed"), "targeted": g3.get("targeted"),
                "regressions": g4.get("regressions"), "previously_passing": g4.get("previously_passing"), "pass_rate": None,
                "per_hypothesis_fixed": {}, "selected": True, "complete": True, "clamped": {}, "rounded": {}}]}


def build_run(d: Path, mode: str, pv: str) -> dict:
    summ = jl(d / "summary.json")
    gf = d / "gate_report.json" if (d / "gate_report.json").exists() else d / "gate_full_pipeline.json"
    gate = jl(gf)
    rep = gate["report"]
    ev = jl(d / "evidence.json")
    ev_by_id = {i["id"]: i for i in ev["items"]}
    aset = jl(d / "analysis_set.json")
    base = jl(d / "baseline_results.json")
    results = {r["scenario_id"]: r for r in base["results"]}
    hyps = jl(d / "hypotheses.json") if (d / "hypotheses.json").exists() else []
    tf = jl(d / "targeted_failures.json") if (d / "targeted_failures.json").exists() else {"by_hypothesis": {}}
    attempts = gate.get("attempts", [])
    tables = [a.get("candidates") and {
        "attempt": a["attempt"], "selected_index": a["selected_index"], "regression_budget": a["regression_budget"], "v1_single_patch": False,
        "diversity_violations": a.get("diversity_violations", []), "dropped": a.get("dropped_candidates", []),
        "candidates": [{k: c[k] for k in ("index", "applied", "fixed", "targeted", "regressions", "previously_passing", "pass_rate", "per_hypothesis_fixed",
                                          "selected", "complete", "clamped", "rounded")} for c in a["candidates"]]} or v1_candidate_table(a)
              for a in attempts]
    tables = [t if t else v1_candidate_table(a) for t, a in zip(tables, attempts)]
    # hypotheses: model text is shown as unverified opinion; every NUMBER comes from the evidence item looked up by id
    hyp_out = []
    for h in hyps:
        hyp_out.append({"id": h["id"], "model_text_unverified": {"statement": h["statement"], "mechanism": h["mechanism"], "prediction": h["prediction"]},
                        "region": h["region"], "levers": h["levers"], "targeted_failures": len(tf["by_hypothesis"].get(h["id"], [])),
                        "evidence": [{"id": r, "kind": ev_by_id[r]["kind"], "title": ev_by_id[r]["title"], "data": ev_by_id[r]["data"]} for r in h["evidence_refs"] if r in ev_by_id]})
    gen = summ.get("generator") or {"source": aset.get("source"), "model": (summ.get("models") or {}).get("fast"), "dropped_regions": [], "clamped_values": [], "trail": []}
    llm_s = summ.get("llm_seconds")
    if llm_s is None:
        llm_s = round(sum(c["latency_s"] for c in summ.get("llm_calls", [])), 2)
    wall = summ.get("wall_clock_total_s") or round(sum((summ.get("timings_s") or {}).values()), 2)
    cand_s = (summ.get("gate_timings_s") or rep.get("timings_s") or {}).get("candidate_evals_total_s", 0.0)
    usage = summ.get("llm_usage", {})
    prov = summ.get("provenance") or {}
    rid = d.name
    return {
        "id": rid, "badges": {"pipeline_version": pv, "mode": mode, "runner": RUNNER_BADGE, "recorded": True},
        "recorded_at": (jl(d / "LABEL.json").get("started") if (d / "LABEL.json").exists() else None),  # container clock, UTC
        "label": summ.get("label"), "master_seed": summ.get("master_seed"), "verdict": rep["verdict"], "error": summ.get("error"),
        "attempts_used": len(attempts), "g5_executed": summ.get("g5_executed", rep["verdict"] != "UNVERIFIED"),
        "gate": {"checks": [norm_check(c) for c in rep["checks"]], "regressed_scenario_ids": rep.get("regressed_scenario_ids", []),
                 "strict_zero_budget": rep.get("strict_zero_budget"), "config": rep.get("config"), "verification_set": rep.get("verification_set")},
        "metrics": rep["metrics"], "candidate_tables": tables, "hypotheses": hyp_out,
        "generator": {"source": gen.get("source"), "model": gen.get("model"), "dropped_regions": gen.get("dropped_regions", []),
                      "clamped_values": gen.get("clamped_values", []), "trail": gen.get("trail", []),
                      "regions_used": [{"name": r["name"], "ranges": r["ranges"], "rationale_unverified": r["rationale"]}
                                       for r in ((aset.get("proposal_validated") or {}).get("regions") or [])]},
        "heatmaps": [heatmap(aset["scenarios"], results, "friction", "mass_kg"), heatmap(aset["scenarios"], results, "gripper_delay_steps", "sensor_noise_m")],
        "analysis_set": {"n": len(aset["scenarios"]), "n_coverage": aset.get("n_coverage"), "n_targeted": aset.get("n_targeted")},
        "timing": {"wall_clock_s": wall, "llm_s": llm_s, "candidate_evals_s": cand_s, "other_simulation_s": round(max(wall - llm_s - cand_s, 0), 2),
                   "stages_s": summ.get("timings_s"), "gate_stages_s": summ.get("gate_timings_s") or rep.get("timings_s")},
        "tokens": {"prompt": usage.get("prompt_tokens"), "completion": usage.get("completion_tokens"), "llm_calls": usage.get("calls_real")},
        "cost": {"estimated_usd": summ.get("estimated_cost_usd"), "note": "ESTIMATE from API prices; actual billing UNCONFIRMED"},
        "provenance": {k: prov.get(k) for k in ("commit", "tag", "pipeline_version", "image_build_id", "protocol_commit", "model_fast", "model_reasoning", "runner_name", "official")},
        "final_patch": attempts[-1].get("patched_policy") if attempts else None,
    }


def study(dirname: str, pv: str) -> dict:
    s = jl(REC / dirname / "summary.json")
    rows = [{k: r.get(k) for k in ("run_id", "master_seed", "verdict", "attempts", "analysis_before", "analysis_after", "verification_before", "verification_after",
                                   "estimated_cost_usd", "wall_clock_total_s", "final_checks", "error")} | {"generator": r.get("generator")} for r in s["runs"]]
    agg = s["aggregate"]
    if "verified_rate" not in agg:  # studies summarised by an older script version lack it: derive it from the stored verdict counts
        n, k = agg["runs"], agg["verdict_counts"]["VERIFIED"]
        lo, hi = wilson(k, n)
        agg["verified_rate"] = {"verified": k, "of_runs": n, "rate": round(k / n, 4), "wilson95": [round(lo, 4), round(hi, 4)]}
    return {"name": dirname, "pipeline_version": pv, "note": s.get("note"), "aggregate": agg, "runs": rows}


def make_replays(run_dir: Path, run: dict, n_try: int = 25) -> dict | None:
    from app.core.schemas import Policy, Scenario
    from app.sim.pickplace import run_scenario
    from app.sim.recorder import record_scenario

    aset, base = jl(run_dir / "analysis_set.json"), jl(run_dir / "baseline_results.json")
    tf = jl(run_dir / "targeted_failures.json")
    if not run["final_patch"]:
        return None
    patched = Policy(**run["final_patch"])
    scn = {s["id"]: s for s in aset["scenarios"]}
    failing = [i for i in tf["all"] if not next(r for r in base["results"] if r["scenario_id"] == i)["success"]]
    for sid in failing[:n_try]:
        s = Scenario(**scn[sid])
        rb = run_scenario(Policy(), s)[0]
        rp = run_scenario(patched, s)[0]
        if not rb.success and rp.success:
            out = OUT / "replays"
            res_b, tj_b, gif_b = record_scenario(Policy(), s, out, gif=True, label="baseline")
            res_p, tj_p, gif_p = record_scenario(patched, s, out, gif=True, label="patched")
            assert res_b.model_dump() == rb.model_dump() and res_p.model_dump() == rp.model_dump()  # recording does not change results
            tj_b.unlink(); tj_p.unlink()  # keep the bundle small: the dashboard plays the GIFs, not raw trajectories
            return {"run": run["id"], "scenario": scn[sid], "seed": s.seed,
                    "baseline": {"gif": f"replays/{gif_b.name}", "result": res_b.model_dump(mode="json"), "policy": Policy().model_dump()},
                    "patched": {"gif": f"replays/{gif_p.name}", "result": res_p.model_dump(mode="json"), "policy": patched.model_dump()},
                    "note": "Same scenario and seed; frozen simulator; the default policy fails and the final patch of this run passes."}
    return None


def calls_bundle(d: Path) -> dict:
    """The run's model calls and raw replies for the dashboard's "Model calls" panel. Built from the stored artifacts only; fields the pipeline did not
    record (the API's response ids, finish reasons, timestamps) stay null and are shown as 'not recorded'. Prompts are not exported; replies are scrubbed."""
    from app.live.capture import merge_calls
    from app.live.scrub import scrub_obj
    summ = jl(d / "summary.json")
    calls = merge_calls(summ.get("llm_calls", []), [])
    tpath = d / "llm_transcript.json"
    replies = [{"index": i + 1, "purpose": t.get("purpose"), "model": t.get("model"), "attempt": t.get("attempt"), "cached": t.get("cached"), "reply": t.get("reply", "")}
               for i, t in enumerate(jl(tpath))] if tpath.exists() else []
    return scrub_obj({
        "calls": calls, "replies": replies, "in_progress": False, "response_metadata_captured": False,
        "source": "summary.json (the pipeline's own call records) and llm_transcript.json; recorded before response-metadata capture existed",
        "totals": {"calls": len(calls), "prompt_tokens": sum(c["prompt_tokens"] or 0 for c in calls), "completion_tokens": sum(c["completion_tokens"] or 0 for c in calls),
                   "estimated_cost_usd": summ.get("estimated_cost_usd"), "cost_note": summ.get("cost_note") or "ESTIMATE: tokens x the per-token prices the API reports; billing is not checked"},
        "note": "Not recorded for this run: the provider response id, the model id as returned by the API, the finish reason and per-call timestamps. They are shown as 'not recorded', never filled in. "
                "Live runs record them from now on."})


def scenario_points(d: Path) -> dict:
    """Per-scenario outcomes of the UNPATCHED default policy on the run's analysis set, as column arrays (for the 3D failure map).
    Patched per-scenario outcomes were not stored by the pipeline, so none are exported."""
    aset, base = jl(d / "analysis_set.json"), jl(d / "baseline_results.json")
    res = {r["scenario_id"]: r for r in base["results"]}
    sc = [x for x in aset["scenarios"] if x["id"] in res]
    cols = ["mass_kg", "friction", "size_m", "sensor_noise_m", "gripper_delay_steps", "pos_offset_x", "pos_offset_y"]
    out = {"set": "analysis set", "policy": "unpatched default policy", "n": len(sc), "ids": [x["id"] for x in sc], "tag": [x.get("tag") for x in sc],
           "ok": [1 if res[x["id"]]["success"] else 0 for x in sc], "reason": [res[x["id"]].get("failure_reason") for x in sc]}
    for c in cols:
        out[c] = [round(float(x[c]), 5) for x in sc]
    return out


def playground_examples() -> list[dict]:
    """Three REAL simulator runs (frozen simulator, same code path as the playground endpoint) for the offline playground."""
    import tempfile
    from app.core.schemas import Policy
    from app.playground.service import EXPLAIN, _scenario_job
    from app.playground.spec import DEFAULT_SEED, PRESETS
    pre = {p["id"]: p for p in PRESETS}
    benign, heavy = pre["benign"]["scenario"], pre["heavy_slippery"]["scenario"]
    cases = [("Benign cube, default policy", "An easy cube and the default policy.", benign, {}),
             ("Heavy and slippery cube, default policy", "The default policy on a heavy, slippery cube with a little noise and delay.", heavy, {}),
             ("Same cube, stronger grip", "Same scenario and seed as the previous example; only the grip force is raised to 40.", heavy, {"grip_force": 40.0})]
    out = []
    for label, why, scn, over in cases:
        pol = Policy(**over)
        scenario = {"id": f"pg-{DEFAULT_SEED}", "seed": DEFAULT_SEED, "tag": "playground", **scn}
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "o.json"
            _scenario_job(pol.model_dump(), scenario, str(f))
            data = json.loads(f.read_text())
        reason = data["result"].get("failure_reason")
        out.append({"label": label, "why": why, "scenario": scenario, "policy": pol.model_dump(), "seed": DEFAULT_SEED, "result": data["result"],
                    "explanation": EXPLAIN.get(reason) if reason else "The cube was lifted, carried over the wall and placed upright inside the target zone.",
                    "trajectory": data["trajectory"], "world": data["world"]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-replays", action="store_true")
    a = ap.parse_args()
    keep = {}  # live_replay/ is recorded by a separate step (a real live run) and must survive a re-export
    if (OUT / "live_replay").exists():
        keep = {f.relative_to(OUT / "live_replay"): f.read_bytes() for f in (OUT / "live_replay").rglob("*") if f.is_file()}
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    if keep:
        (OUT / "live_replay").mkdir()
        for name, data in keep.items():
            (OUT / "live_replay" / name).parent.mkdir(parents=True, exist_ok=True)
            (OUT / "live_replay" / name).write_bytes(data)
    runs = []
    off_root = REC / "official_001"
    for d in sorted(off_root.glob("official_*")):
        if d.is_dir() and (d / "summary.json").exists():
            runs.append((build_run(d, "official", "v2"), d))
    runs.append((build_run(REC / "rehearsal_001", "rehearsal", "v1"), REC / "rehearsal_001"))
    for r, d in runs:
        put(OUT / "runs" / f"{r['id']}.json", r)
        put(OUT / "scenarios" / f"{r['id']}.json", scenario_points(d))
        put(OUT / "calls" / f"{r['id']}.json", calls_bundle(d))
    index = [{"id": r["id"], "badges": r["badges"], "verdict": r["verdict"], "master_seed": r["master_seed"], "attempts_used": r["attempts_used"],
              "generator_source": r["generator"]["source"], "analysis": r["metrics"].get("analysis"), "verification": r["metrics"].get("verification")} for r, _ in runs]
    put(OUT / "index.json", index)
    if (off_root / "official_summary.json").exists():
        put(OUT / "official.json", jl(off_root / "official_summary.json"))
    put(OUT / "studies.json", [study("reliability_001", "v1"), study("reliability_002", "v2")])
    trap = jl(REC / "rehearsal_001" / "gate_scripted_trap.json")
    rep = trap["report"]
    put(OUT / "trap.json", {"label": TRAP_LABEL, "patch": trap["changes"], "patch_description": trap["patch"], "targeting": trap["targeting"],
                            "verdict": rep["verdict"], "checks": [norm_check(c) for c in rep["checks"]], "metrics": rep["metrics"],
                            "regressed_scenario_ids": rep["regressed_scenario_ids"], "strict_zero_budget": rep["strict_zero_budget"],
                            "note": "Stored gate result from rehearsal_001 (rehearsal seed block, not a held-out result). G5 was run as a diagnostic after G4 failed. Not recomputed here."})
    if (ROOT / "docs" / "LIMITATIONS.md").exists():
        shutil.copy(ROOT / "docs" / "LIMITATIONS.md", OUT / "LIMITATIONS.md")
    if not a.no_replays:
        first = runs[0][0] if runs[0][0]["badges"]["mode"] == "official" else None
        rp = make_replays(runs[0][1], runs[0][0]) if first else None
        put(OUT / "replays.json", rp)
        print("replays:", "recorded for " + rp["scenario"]["id"] if rp else "none found")
        put(OUT / "playground_examples.json", playground_examples())
    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"exported {len(runs)} runs; bundle size {total / 1024:.0f} KiB")


if __name__ == "__main__":
    main()
