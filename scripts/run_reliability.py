"""Reliability study: run the FULL real-model pipeline several times, each with its own master seed and a fresh REHEARSAL seed
block (all < 900000), then summarise honestly. REHEARSAL, NOT AN OFFICIAL RESULT. Held-out seeds are never touched.

Rules (decided before running):
- Master seeds are fixed up front (v2 default: 611 622 633 644 655 666 677 688). No re-rolling to improve numbers.
- A run that dies from an INFRASTRUCTURE error (timeout / connection error) may be re-run once with a new run id; the original failed
  run and its artifacts stay in the study and in the summary. A verdict (including FAILED or UNVERIFIED) is never re-run.
- Stop early if the projected total cost exceeds $2, or on any 401 / 402 or a second 429.
- Real, uncached calls only (LLM_DEV_CACHE must be 0). LocalRunner (labelled fallback, not Nebius).

Usage (in the sim image): scripts/dock.sh python scripts/run_reliability.py [--seeds ...] [--out recorded_runs/reliability_002]
       python scripts/run_reliability.py --resummarize --out recorded_runs/reliability_002   (rebuild the summary from saved files)
"""
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import load_settings  # noqa: E402
from app.core.provenance import PIPELINE_VERSION  # noqa: E402
from app.core.stats import wilson  # noqa: E402
from app.pipeline import PipelineConfig, fetch_pricing, run_pipeline  # noqa: E402
from app.runner.local import LocalRunner  # noqa: E402
from app.store.db import Database  # noqa: E402
from app.store.ledger import SeedLedger  # noqa: E402

INFRA_MARKERS = ("APITimeoutError", "APIConnectionError", "LLMTransportError: APITimeout", "LLMTransportError: APIConnection")
COST_CAP_USD = 2.0
V2_SEEDS = [611, 622, 633, 644, 655, 666, 677, 688]
V1_SUMMARY = ROOT / "recorded_runs" / "reliability_001" / "summary.json"


def is_infra(err: str | None) -> bool:
    return bool(err) and any(m in err for m in INFRA_MARKERS)


def row(res: dict) -> dict:
    m = res.get("metrics", {})
    a, v = m.get("analysis", {}), m.get("verification", {})
    u = res.get("llm_usage", {})
    failed_by_attempt = [[cid for cid, ch in at["dev_checks"].items() if ch["status"] == "fail"] for at in res.get("attempts", [])]
    gen = res.get("generator") or {}
    last = res["attempts"][-1] if res.get("attempts") else None
    return {
        "run_id": res["run_id"], "master_seed": res["master_seed"], "verdict": res.get("verdict"), "error": res.get("error"),
        "pipeline_version": (res.get("provenance") or {}).get("pipeline_version"), "g5_executed": res.get("g5_executed"),
        "attempts": res.get("n_attempts"), "failed_checks_per_attempt": failed_by_attempt, "final_checks": res.get("checks"),
        "generator": {"source": gen.get("source"), "model": gen.get("model"), "regions_used": gen.get("n_regions_used"),
                      "dropped": len(gen.get("dropped_regions") or []), "clamped": len(gen.get("clamped_values") or []),
                      "trail": [f"{t.get('stage')}:{t.get('outcome')}" for t in gen.get("trail") or []]},
        "analysis_before": a.get("before"), "analysis_after": a.get("after"), "verification_before": v.get("before"), "verification_after": v.get("after"),
        "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"), "llm_calls": u.get("calls_real"),
        "llm_seconds": res.get("llm_seconds"), "wall_clock_total_s": res.get("wall_clock_total_s"), "timings_s": res.get("timings_s"),
        "gate_timings_s": res.get("gate_timings_s"), "estimated_cost_usd": res.get("estimated_cost_usd"),
        "generator_value": res.get("generator_value"), "n_hypotheses": res.get("n_hypotheses"), "n_targeted": res.get("n_targeted"),
        "candidate_tables": [{"attempt": at["attempt"], "selected_index": at.get("selected_index"), "regression_budget": at.get("regression_budget"),
                              "diversity_violations": at.get("diversity_violations"), "dropped": at.get("dropped_candidates"),
                              "candidates": at.get("candidates")} for at in res.get("attempts", [])],
        "final_patch": last["patched_policy"] if last else None,
    }


def fc(r) -> str:
    c = r.get("final_checks")
    return " ".join(f"{k}={v.replace('skipped_after_failure', 'skipped')}" for k, v in c.items()) if c else "n/a"


def coll(r) -> str:
    b, a = r.get('verification_before'), r.get('verification_after')
    return f"{b['collision_rate']:.1%} -> {a['collision_rate']:.1%}" if b and a else 'n/a'


def fmt_rate(m) -> str:
    return f"{m['pass_rate']:.1%} [{m['pass_rate_ci95'][0]:.1%}, {m['pass_rate_ci95'][1]:.1%}]" if m else "n/a"


def candidate_table_md(r: dict) -> list[str]:
    out = [f"### {r['run_id']} (seed {r['master_seed']}): generator `{r['generator']['source']}` / `{r['generator']['model']}`, verdict {r['verdict']}", ""]
    if not r["candidate_tables"]:
        return out + ["_no fixer attempts (the run ended before the fixer)_", ""]
    for t in r["candidate_tables"]:
        out.append(f"**Attempt {t['attempt']}** (regression budget {t['regression_budget']}, selected candidate {t['selected_index']}"
                   + (f", diversity violations: {t['diversity_violations']}" if t["diversity_violations"] else "") + ")")
        out += ["", "| # | Applied changes | Fixed | Regressions | Pass | Per hypothesis | Selected | Clamped / rounded |", "|---|---|---|---|---|---|---|---|"]
        for c in t["candidates"]:
            note = ", ".join([f"clamped {k}" for k, v in (c["clamped"] or {}).items() if v] + [f"{k} {v[0]}->{v[1]}" for k, v in (c["rounded"] or {}).items()]) or ""
            out.append(f"| {c['index']} | `{json.dumps(c['applied'])}` | {c['fixed']}/{c['targeted']} | {c['regressions']}/{c['previously_passing']} | "
                       f"{c['pass_rate']} | {c['per_hypothesis_fixed']} | {'**yes**' if c['selected'] else ''} | {note} |")
        if t["dropped"]:
            out.append(f"\n_Dropped by validation:_ {t['dropped']}")
        out.append("")
    return out


def summarize(rows: list[dict], out: Path, note: str, title: str = "reliability_002", kind: str = "REHEARSAL STUDY, NOT AN OFFICIAL RESULT",
              stem: str = "summary", sidebyside: bool = True) -> None:
    done = [r for r in rows if r["verdict"]]
    verdicts = {k: sum(r["verdict"] == k for r in rows) for k in ("VERIFIED", "FAILED", "UNVERIFIED")}
    verdicts["ERROR (no verdict)"] = sum(r["verdict"] is None for r in rows)
    att = {}
    for r in done:
        att[r["attempts"]] = att.get(r["attempts"], 0) + 1

    def mmm(key, rs):
        xs = [r[key] for r in rs if r.get(key) is not None]
        return {"min": min(xs), "median": statistics.median(xs), "max": max(xs), "n": len(xs)} if xs else None

    for r in rows:
        r["total_tokens"] = (r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0)
    n, k = len(rows), verdicts["VERIFIED"]
    lo, hi = wilson(k, n)
    gsrc = {}
    for r in rows:
        s = (r.get("generator") or {}).get("source") or "none"
        gsrc[s] = gsrc.get(s, 0) + 1
    agg = {"runs": n, "verdict_counts": verdicts, "verified_rate": {"verified": k, "of_runs": n, "rate": round(k / n, 4) if n else None, "wilson95": [round(lo, 4), round(hi, 4)]},
           "attempts_distribution_for_runs_with_a_verdict": att, "generator_sources": gsrc, "total_tokens": mmm("total_tokens", rows),
           "wall_clock_total_s": mmm("wall_clock_total_s", rows), "estimated_cost_usd": mmm("estimated_cost_usd", rows), "llm_seconds": mmm("llm_seconds", rows),
           "total_estimated_cost_usd": round(sum(r["estimated_cost_usd"] or 0 for r in rows), 4)}
    gv = {}
    for g in ("cov", "tgt"):
        nn = sum(r["generator_value"][g]["n"] for r in rows if r.get("generator_value"))
        f = sum(r["generator_value"][g]["n_fail"] for r in rows if r.get("generator_value"))
        l2, h2 = wilson(f, nn)
        gv[g] = {"n": nn, "n_fail": f, "fail_rate": round(f / nn, 4) if nn else None, "wilson95": [round(l2, 4), round(h2, 4)]}
    agg["generator_value_pooled"] = gv
    v1 = json.loads(V1_SUMMARY.read_text(encoding="utf-8"))["aggregate"] if V1_SUMMARY.exists() else None
    (out / f"{stem}.json").write_text(json.dumps({"pipeline_version": PIPELINE_VERSION, "note": note, "aggregate": agg, "v1_aggregate": v1, "runs": rows}, indent=1, default=str), encoding="utf-8")

    L = [f"# {title}: {kind} (pipeline {PIPELINE_VERSION})", "", note, "",
         f"Runs: {n}. Verdicts: {verdicts}. **VERIFIED rate: {k}/{n} = {k / n:.1%} (Wilson 95% [{lo:.1%}, {hi:.1%}])**. "
         f"Attempts needed (runs with a verdict): {att}. Generator sources: {gsrc}.", ""]
    if v1 and sidebyside:
        v1c, v1n = v1["verdict_counts"], v1["runs"]
        l1, h1 = wilson(v1c["VERIFIED"], v1n)
        L += ["## Side by side with pipeline v1 (reliability_001)", "", "| | v1 (5 runs) | v2 (" + str(n) + " runs) |", "|---|---|---|",
              f"| VERIFIED | {v1c['VERIFIED']}/{v1n} = {v1c['VERIFIED'] / v1n:.0%} (Wilson 95% [{l1:.0%}, {h1:.0%}]) | {k}/{n} = {k / n:.0%} ([{lo:.0%}, {hi:.0%}]) |",
              f"| FAILED | {v1c['FAILED']} | {verdicts['FAILED']} |", f"| UNVERIFIED | {v1c['UNVERIFIED']} | {verdicts['UNVERIFIED']} |",
              f"| no verdict (error) | {v1c['ERROR (no verdict)']} | {verdicts['ERROR (no verdict)']} |",
              f"| median est. cost per run | ${v1['estimated_cost_usd']['median']:.3f} | ${agg['estimated_cost_usd']['median']:.3f} |" if agg["estimated_cost_usd"] else "",
              "", "Small samples: the intervals overlap heavily unless the difference is large. Different master seeds and rehearsal blocks in each study.", ""]
    L += ["## Runs", "", "| Run | Seed | Verdict | Attempts | Dev-stage checks failed, per attempt | Final G1-G6 | Generator | Analysis pass before -> after | Verification pass before -> after | Collision rate on verification set before -> after | Tokens (p/c) | Wall s (LLM s) | Est. cost |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        g = r["generator"]
        L.append(f"| {r['run_id']} | {r['master_seed']} | {r['verdict'] or 'ERROR: ' + str(r['error'])[:70]} | {r['attempts']} | {r['failed_checks_per_attempt']} | {fc(r)} | "
                 f"{g['source']} `{(g['model'] or '-').split('/')[-1]}` ({g['dropped']} dropped, {g['clamped']} clamped) | "
                 f"{fmt_rate(r['analysis_before'])} -> {fmt_rate(r['analysis_after'])} | {fmt_rate(r['verification_before'])} -> {fmt_rate(r['verification_after'])} | "
                 f"{coll(r)} | {r['prompt_tokens']}/{r['completion_tokens']} | {r['wall_clock_total_s']} ({r['llm_seconds']}) | {r['estimated_cost_usd']} |")
    L += ["", "Pass rates are shown with Wilson 95% intervals. Cost is an ESTIMATE (tokens x the per-token prices the API reports); actual billing UNCONFIRMED.", "",
          "## Min / median / max", ""]
    for key in ("total_tokens", "wall_clock_total_s", "llm_seconds", "estimated_cost_usd"):
        L.append(f"- {key}: {agg[key]}")
    L.append(f"- total estimated cost of the study: ${agg['total_estimated_cost_usd']}")
    L += ["", "## Does the model add value in scenario generation? (baseline failure rate, default policy)", "",
          f"- coverage scenarios: {gv['cov']['n_fail']}/{gv['cov']['n']} fail = {gv['cov']['fail_rate']} (Wilson95 {gv['cov']['wilson95']})",
          f"- model-targeted scenarios: {gv['tgt']['n_fail']}/{gv['tgt']['n']} fail = {gv['tgt']['fail_rate']} (Wilson95 {gv['tgt']['wilson95']})",
          "- Pooled over the runs that produced a baseline. Region rationales from the model are unverified opinions; only these code-computed rates are evidence.", "",
          "## Appendix: candidate tables (what the model proposed and what code measured)", ""]
    for r in rows:
        L += candidate_table_md(r)
    (out / f"{stem}.md").write_text("\n".join(L), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=V2_SEEDS)
    ap.add_argument("--out", default=str(ROOT / "recorded_runs" / "reliability_002"))
    ap.add_argument("--n", type=int, default=250)
    ap.add_argument("--resummarize", action="store_true", help="rebuild summary.md/json from the saved run_*/summary.json files; runs nothing")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.resummarize:
        rows = [row(json.loads(f.read_text(encoding="utf-8"))) for f in sorted(out.glob("run_*/summary.json"))]
        summarize(rows, out, "Rebuilt from the saved run files (nothing re-run). Master seeds fixed in advance; no run was re-rolled for its verdict. "
                  "LocalRunner (labelled fallback, not Nebius). Rehearsal seed blocks only; held-out seeds were never run.", out.name)
        print("rebuilt", out)
        return
    settings = load_settings(dotenv_path=ROOT / ".env")
    db = Database(str(ROOT / settings.db_path))
    ledger = SeedLedger(db)
    pricing = fetch_pricing(settings, {settings.model_fast, settings.model_reasoning, settings.model_fallback} - {None})
    print("pricing from API:", pricing)
    rows, n429, stop = [], 0, None
    for i, seed in enumerate(a.seeds, 1):
        rid = f"run_{i:02d}_seed{seed}"
        res = run_pipeline(settings, LocalRunner(), db, ledger, PipelineConfig(rid, out, seed, n=a.n, rehearsal=True), env=dict(os.environ), pricing=pricing)
        rows.append(row(res))
        print(f"{rid}: verdict={res.get('verdict')} attempts={res.get('n_attempts')} gen={(res.get('generator') or {}).get('source')} error={res.get('error')} "
              f"cost={res.get('estimated_cost_usd')} wall={res.get('wall_clock_total_s')}s", flush=True)
        if is_infra(res.get("error")) and not res.get("g5_executed"):  # infrastructure failure: one re-run allowed, the original stays in the study
            rid2 = rid + "_infra_retry1"
            res2 = run_pipeline(settings, LocalRunner(), db, ledger, PipelineConfig(rid2, out, seed, n=a.n, rehearsal=True), env=dict(os.environ), pricing=pricing)
            rows.append(row(res2))
            print(f"{rid2}: verdict={res2.get('verdict')} error={res2.get('error')}", flush=True)
            res = res2
        err = res.get("error") or ""
        if " 401" in err or " 402" in err or "AuthenticationError" in err:
            stop = f"stopped after {rid}: authentication/payment error ({err[:120]})"
        n429 += " 429" in err or "RateLimitError" in err
        if n429 >= 2:
            stop = f"stopped after {rid}: repeated 429"
        costs = [r["estimated_cost_usd"] for r in rows if r["estimated_cost_usd"] is not None]
        if costs and sum(costs) / len(costs) * len(a.seeds) > COST_CAP_USD:
            stop = f"stopped after {rid}: projected total cost {sum(costs) / len(costs) * len(a.seeds):.2f} USD exceeds {COST_CAP_USD}"
        if stop:
            print(stop)
            break
        summarize(rows, out, "Study in progress (rebuilt after each run).", out.name)  # keeps a readable summary even if interrupted
    summarize(rows, out, f"Completed {time.strftime('%Y-%m-%d %H:%M')}. " + (stop or "All planned runs executed.") +
              " Master seeds fixed in advance; no run re-rolled for its verdict. LocalRunner (labelled fallback, not Nebius). Rehearsal seed blocks only; "
              "held-out seeds were never run.", out.name)
    print("summary written to", out)


if __name__ == "__main__":
    main()
