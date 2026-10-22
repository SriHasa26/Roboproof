"""Reliability study: run the FULL real-model pipeline several times, each with its own master seed and a fresh REHEARSAL seed
block (all < 900000), then summarise honestly. REHEARSAL, NOT AN OFFICIAL RESULT. Held-out seeds are never touched.

Rules (decided before running):
- Master seeds are fixed up front (default 101 202 303 404 505). No re-rolling to improve numbers.
- A run that dies from an INFRASTRUCTURE error (timeout / connection error) may be re-run once with a new run id; the original failed
  run and its artifacts stay in the study and in the summary. A verdict (including FAILED or UNVERIFIED) is never re-run.
- Stop early if the projected total cost exceeds $1, or on any 401 / 402 or a second 429.
- Real, uncached calls only (LLM_DEV_CACHE must be 0). LocalRunner (labelled fallback, not Nebius).

Usage (in the sim image): scripts/dock.sh python scripts/run_reliability.py [--seeds 101 202 303 404 505] [--out recorded_runs/reliability_001]
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
from app.core.stats import wilson  # noqa: E402
from app.pipeline import PipelineConfig, fetch_pricing, run_pipeline  # noqa: E402
from app.runner.local import LocalRunner  # noqa: E402
from app.store.db import Database  # noqa: E402
from app.store.ledger import SeedLedger  # noqa: E402

INFRA_MARKERS = ("APITimeoutError", "APIConnectionError", "LLMTransportError: APITimeout", "LLMTransportError: APIConnection")
COST_CAP_USD = 1.0


def is_infra(err: str | None) -> bool:
    return bool(err) and any(m in err for m in INFRA_MARKERS)


def row(res: dict) -> dict:
    m = res.get("metrics", {})
    a, v = m.get("analysis", {}), m.get("verification", {})
    u = res.get("llm_usage", {})
    failed_by_attempt = [[cid for cid, ch in at["dev_checks"].items() if ch["status"] == "fail"] for at in res.get("attempts", [])]
    return {
        "run_id": res["run_id"], "master_seed": res["master_seed"], "verdict": res.get("verdict"), "error": res.get("error"),
        "attempts": res.get("n_attempts"), "failed_checks_per_attempt": failed_by_attempt, "final_checks": res.get("checks"),
        "analysis_before": a.get("before"), "analysis_after": a.get("after"), "verification_before": v.get("before"), "verification_after": v.get("after"),
        "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"), "llm_calls": u.get("calls_real"),
        "llm_seconds": res.get("llm_seconds"), "wall_clock_total_s": res.get("wall_clock_total_s"), "timings_s": res.get("timings_s"),
        "gate_timings_s": res.get("gate_timings_s"), "estimated_cost_usd": res.get("estimated_cost_usd"),
        "generator_value": res.get("generator_value"), "n_hypotheses": res.get("n_hypotheses"), "n_targeted": res.get("n_targeted"),
        "final_patch": res["attempts"][-1]["model_proposal"]["changes"] if res.get("attempts") else None,
    }


def fc(r) -> str:
    c = r.get('final_checks')
    return ' '.join(f"{k}={v.replace('skipped_after_failure', 'skipped')}" for k, v in c.items()) if c else 'n/a'


def fmt_rate(m) -> str:
    return f"{m['pass_rate']:.1%} [{m['pass_rate_ci95'][0]:.1%}, {m['pass_rate_ci95'][1]:.1%}]" if m else "n/a"


def summarize(rows: list[dict], out: Path, note: str) -> None:
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
    agg = {"runs": len(rows), "verdict_counts": verdicts, "attempts_distribution_for_runs_with_a_verdict": att,
           "total_tokens": mmm("total_tokens", rows), "wall_clock_total_s": mmm("wall_clock_total_s", rows),
           "estimated_cost_usd": mmm("estimated_cost_usd", rows), "llm_seconds": mmm("llm_seconds", rows)}
    gv = {}
    for g in ("cov", "tgt"):
        n = sum(r["generator_value"][g]["n"] for r in rows if r.get("generator_value"))
        f = sum(r["generator_value"][g]["n_fail"] for r in rows if r.get("generator_value"))
        lo, hi = wilson(f, n)
        gv[g] = {"n": n, "n_fail": f, "fail_rate": round(f / n, 4) if n else None, "wilson95": [round(lo, 4), round(hi, 4)]}
    agg["generator_value_pooled"] = gv
    (out / "summary.json").write_text(json.dumps({"note": note, "aggregate": agg, "runs": rows}, indent=1, default=str), encoding="utf-8")

    L = ["# reliability_001: REHEARSAL STUDY, NOT AN OFFICIAL RESULT", "", note, "",
         f"Runs: {len(rows)}. Verdicts: {verdicts}. Attempts needed (runs with a verdict): {att}.", "",
         "| Run | Seed | Verdict | Attempts | Dev-stage checks failed, per attempt | Final G1-G6 | Analysis pass before -> after | Verification pass before -> after | Tokens (p/c) | Wall s (LLM s) | Est. cost |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['run_id']} | {r['master_seed']} | {r['verdict'] or 'ERROR: ' + str(r['error'])[:80]} | {r['attempts']} | {r['failed_checks_per_attempt']} | {fc(r)} | "
                 f"{fmt_rate(r['analysis_before'])} -> {fmt_rate(r['analysis_after'])} | {fmt_rate(r['verification_before'])} -> {fmt_rate(r['verification_after'])} | "
                 f"{r['prompt_tokens']}/{r['completion_tokens']} | {r['wall_clock_total_s']} ({r['llm_seconds']}) | {r['estimated_cost_usd']} |")
    L += ["", "Pass rates are shown with Wilson 95% intervals. Cost is an ESTIMATE (tokens x the per-token prices the API reports); actual billing UNCONFIRMED.", "",
          "## Min / median / max", ""]
    for k in ("total_tokens", "wall_clock_total_s", "llm_seconds", "estimated_cost_usd"):
        L.append(f"- {k}: {agg[k]}")
    L += ["", "## Does the model add value in scenario generation? (baseline failure rate, default policy)", "",
          f"- coverage scenarios: {gv['cov']['n_fail']}/{gv['cov']['n']} fail = {gv['cov']['fail_rate']} (Wilson95 {gv['cov']['wilson95']})",
          f"- model-targeted scenarios: {gv['tgt']['n_fail']}/{gv['tgt']['n']} fail = {gv['tgt']['fail_rate']} (Wilson95 {gv['tgt']['wilson95']})",
          "- Pooled over the runs above. Region rationales from the model are unverified opinions; only these code-computed rates are evidence.", ""]
    (out / "summary.md").write_text("\n".join(L), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[101, 202, 303, 404, 505])
    ap.add_argument("--out", default=str(ROOT / "recorded_runs" / "reliability_001"))
    ap.add_argument("--n", type=int, default=250)
    ap.add_argument("--resummarize", action="store_true", help="rebuild summary.md/json from the saved run_*/summary.json files; runs nothing")
    a = ap.parse_args()
    if a.resummarize:
        out = Path(a.out)
        rows = [row(json.loads(f.read_text(encoding="utf-8"))) for f in sorted(out.glob("run_*/summary.json"))]
        summarize(rows, out, "Rebuilt from the saved run files (nothing re-run). Master seeds fixed in advance (101 202 303 404 505); no run was re-rolled for its verdict. "
                  "Runs with no verdict failed in the scenario generator (validation failed after its single retry): that is not an infrastructure error, so they were not re-run. "
                  "LocalRunner (labelled fallback, not Nebius). Rehearsal seed blocks only; held-out seeds were never run.")
        print("rebuilt", out)
        return
    settings = load_settings(dotenv_path=ROOT / ".env")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    db = Database(str(ROOT / settings.db_path))
    ledger = SeedLedger(db)
    pricing = fetch_pricing(settings, {settings.model_fast, settings.model_reasoning})
    print("pricing from API:", pricing)
    rows, n429, stop = [], 0, None
    for i, seed in enumerate(a.seeds, 1):
        rid = f"run_{i:02d}_seed{seed}"
        res = run_pipeline(settings, LocalRunner(), db, ledger, PipelineConfig(rid, out, seed, n=a.n, rehearsal=True), env=dict(os.environ), pricing=pricing)
        rows.append(row(res))
        print(f"{rid}: verdict={res.get('verdict')} attempts={res.get('n_attempts')} error={res.get('error')} cost={res.get('estimated_cost_usd')} wall={res.get('wall_clock_total_s')}s", flush=True)
        if is_infra(res.get("error")):  # infrastructure failure: one re-run allowed, the original stays in the study
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
    summarize(rows, out, f"Completed {time.strftime('%Y-%m-%d %H:%M')}. " + (stop or "All planned runs executed.") +
              " Master seeds fixed in advance; no run re-rolled for its verdict. LocalRunner (labelled fallback, not Nebius). Rehearsal seed blocks only.")
    print("summary written to", out)


if __name__ == "__main__":
    main()
