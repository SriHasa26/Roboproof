"""Rehearsal: the whole P4 pipeline on NON-held-out seeds, saved under recorded_runs/<name>/.

REHEARSAL, NOT AN OFFICIAL RESULT. Verification sets come from the rehearsal seed block (800000-899999, single use per run via
the seed ledger). Held-out seeds (>= 900000) are never generated or run here.

1-4  gate runs for fixed patches on the same analysis set: best-found, scripted trap, no-op, injected crashed shard
5    the full pipeline with the real models: generator (fast) -> runner -> evidence -> analyst (reasoning) -> fixer
     (up to 3 attempts, dev-stage feedback only) -> gate with a rehearsal verification set

Requires NEBIUS_API_KEY and both model ids in .env and LLM_DEV_CACHE=0. Usage (in the sim image):
  scripts/dock.sh python scripts/run_rehearsal.py [--name rehearsal_001] [--n 250] [--master-seed 11]
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.analysis.analyst import analyze, targeted_failures  # noqa: E402
from app.analysis.evidence import compute_evidence  # noqa: E402
from app.analysis.fixer import MAX_ATTEMPTS, propose  # noqa: E402
from app.analysis.models import DevFeedback  # noqa: E402
from app.core import gate_config as cfg  # noqa: E402
from app.core.config import load_settings  # noqa: E402
from app.core.schemas import Policy, PolicyPatch  # noqa: E402
from app.gate.gate import ProofGate  # noqa: E402
from app.gate.verification import make_verification_set  # noqa: E402
from app.llm.client import LLMClient, LLMError, estimate_tokens  # noqa: E402
from app.runner.local import LocalRunner, run_shard_scenarios  # noqa: E402
from app.scenarios.generator import ScenarioGenerator, build_prompt as gen_prompt  # noqa: E402
from app.store.db import Database  # noqa: E402
from app.store.ledger import SeedLedger  # noqa: E402

LABEL = ("REHEARSAL, NOT AN OFFICIAL RESULT. Verification used the rehearsal seed block; held-out seeds (>= 900000) were "
         "not generated or run. Scripted patches are labelled 'scripted example, not model output'.")


def jdump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")


class Timer:
    def __init__(self):
        self.t: dict[str, float] = {}

    def __call__(self, name):
        outer = self

        class _C:
            def __enter__(s):
                s.t0 = time.perf_counter()

            def __exit__(s, *a):
                outer.t[name] = round(outer.t.get(name, 0.0) + time.perf_counter() - s.t0, 2)

        return _C()


def fetch_pricing(settings, model_ids):
    """Per-token prices as reported by the API itself (GET /models?verbose=true). None if unavailable (then UNCONFIRMED)."""
    try:
        import httpx
        r = httpx.get(settings.base_url.rstrip("/") + "/models", params={"verbose": "true"},
                      headers={"Authorization": f"Bearer {settings.api_key}"}, timeout=30)
        r.raise_for_status()
        out = {}
        for m in r.json().get("data", []):
            if m.get("id") in model_ids and m.get("pricing"):
                out[m["id"]] = {"prompt": float(m["pricing"]["prompt"]), "completion": float(m["pricing"]["completion"])}
        return out or None
    except Exception as e:  # never include the key in a message
        print("pricing lookup failed:", type(e).__name__)
        return None


def gate_summary(label, rep):
    rows = []
    for c in rep.checks:
        obs = {k: v for k, v in c.observed.items() if k in ("fix_rate", "regressions", "previously_passing", "mismatches", "not_reproduced",
                                                            "patched_pass_rate", "unpatched_pass_rate", "improvement", "patched_wilson95_lower", "incomplete_runs")}
        rows.append(f"{c.id}={c.status.value}{'(skipped)' if c.skipped_after_failure else ''} {obs if obs else ''}")
    print(f"\n[{label}] VERDICT {rep.verdict.value}  (rehearsal={rep.rehearsal}, strict zero-budget: {rep.strict_zero_budget})")
    for r in rows:
        print("   ", r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="rehearsal_001")
    ap.add_argument("--n", type=int, default=250)
    ap.add_argument("--master-seed", type=int, default=11)
    ap.add_argument("--skip-llm", action="store_true", help="only the fixed-patch gate runs (needs a key anyway for the generator)")
    a = ap.parse_args()

    settings = load_settings(dotenv_path=ROOT / ".env")
    if settings.dev_cache:
        sys.exit("LLM_DEV_CACHE must be 0 for a recorded rehearsal")
    for n, v in (("NEBIUS_API_KEY", settings.api_key), ("NEBIUS_MODEL_FAST", settings.model_fast), ("NEBIUS_MODEL_REASONING", settings.model_reasoning)):
        print(f"{n}: {'set' if v else 'MISSING'}")
    if not (settings.api_key and settings.model_fast and settings.model_reasoning):
        sys.exit(2)

    out = ROOT / "recorded_runs" / a.name
    out.mkdir(parents=True, exist_ok=True)
    jdump(out / "LABEL.json", {"label": LABEL, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "rehearsal": True})
    db = Database(str(ROOT / settings.db_path))
    ledger = SeedLedger(db)
    run_id = a.name
    client = LLMClient(settings, sink=lambda rec: db.log_llm_call(rec, run_id), keep_transcript=True)
    T = Timer()
    runner = LocalRunner()
    summary: dict = {"label": LABEL, "run_id": run_id, "gate_config": {k: getattr(cfg, k) for k in dir(cfg) if k.startswith("GATE_")},
                     "models": {"fast": settings.model_fast, "reasoning": settings.model_reasoning}, "cpu_count": os.cpu_count()}

    # ---- projected tokens before any multi-call pipeline starts (worst-case completion ceilings; prompts are estimates)
    g_sys, g_user = gen_prompt()
    proj = {"generator_prompt_tokens_est": estimate_tokens(g_sys + g_user), "max_llm_calls": settings.max_calls_per_run,
            "completion_token_ceilings": {"generator": "model default", "analyst": 6000, "fixer_per_call": 4000},
            "note": "ESTIMATE: ~4 characters per token; the analyst and fixer prompts are sized after evidence exists"}
    print("projected:", json.dumps(proj))
    summary["projection_before_run"] = proj

    # ---- analysis set from the REAL fast model, baseline, evidence
    with T("1_generate_scenarios_llm"):
        gen = ScenarioGenerator(llm=client).generate(a.n, a.master_seed)
    assert gen.source == "llm"
    jdump(out / "analysis_set.json", {"source": gen.source, "master_seed": gen.master_seed, "n_coverage": gen.n_coverage, "n_targeted": gen.n_targeted,
                                       "proposal_validated": gen.proposal.model_dump(), "scenarios": [s.model_dump() for s in gen.scenarios]})
    scns = gen.scenarios
    with T("2_baseline_run"):
        base = runner.run(Policy(), scns, shards=10)
    assert base.complete, "baseline run incomplete"
    jdump(out / "baseline_results.json", {"runner": base.runner_name, "wall_clock_s": base.wall_clock_s, "results": [r.model_dump(mode="json") for r in base.results]})
    with T("3_evidence"):
        evidence = compute_evidence(scns, base.results)
    jdump(out / "evidence.json", evidence.model_dump())
    base_pass = sum(r.success for r in base.results) / len(base.results)
    print(f"analysis set: {len(scns)} scenarios ({gen.n_coverage} coverage + {gen.n_targeted} model-proposed regions), baseline pass {base_pass:.1%}, "
          f"{len(evidence.items)} evidence items")

    # ---- 1-4: fixed patches through the gate (targeting by a fixed code rule: heavy and slippery baseline failures)
    scripted_targets = [s.id for s, r in zip(scns, base.results) if s.mass_kg > 0.5 and s.friction < 0.4 and not r.success]
    best = json.loads((ROOT / "docs" / "ceiling_search_results.json").read_text())["best_policy"]
    best_changes = {k: (int(v) if k in ("grasp_hold_steps", "retry_count") else v) for k, v in best.items()}
    trap = json.loads((ROOT / "backend" / "app" / "gate" / "scripted_trap.json").read_text())
    best_policy = PolicyPatch(changes=best_changes).apply(Policy())[0]
    crash_id = scns[len(scns) // 2].id

    def crash_patched(policy, chunk, held_out):  # injected failure: the patched analysis run loses one shard
        if abs(policy.grip_force - best_policy.grip_force) < 1e-9 and any(s.id == crash_id for s in chunk):
            os._exit(3)
        return run_shard_scenarios(policy, chunk, held_out)

    fixed = [
        ("best_found_patch", PolicyPatch(changes=best_changes).apply(Policy())[0], runner, "ceiling-search best (found on dev sets), scripted"),
        ("scripted_trap", PolicyPatch(changes=trap["changes"]).apply(Policy())[0], runner, trap["label"]),
        ("noop_patch", Policy(), runner, "identical to the default policy"),
        ("crashed_shard", best_policy, LocalRunner(shard_fn=crash_patched), "best-found patch with an injected crashed shard in the patched analysis run"),
    ]
    summary["fixed_patch_runs"] = {}
    for label, patched, rn, desc in fixed:
        with T(f"4_gate_{label}"):
            gate = ProofGate(rn, shards=10, rehearsal=True)
            gate.prepare(Policy(), scns, base, scripted_targets)
            dev = gate.dev_stage(patched)
            vset = None if label == "crashed_shard" else make_verification_set(ledger, f"{run_id}:{label}", rehearsal=True)
            rep = gate.finalize(dev, patched, vset, diagnostic_g5=vset is not None)
        jdump(out / f"gate_{label}.json", {"label": LABEL, "patch": desc, "changes": patched.model_dump(), "targeting": "scripted rule: baseline failures with mass>0.5 and friction<0.4",
                                           "report": rep.model_dump(mode="json")})
        gate_summary(label, rep)
        summary["fixed_patch_runs"][label] = {"verdict": rep.verdict.value, "checks": {c.id: c.status.value for c in rep.checks}}

    # ---- 5: the full pipeline with the real models
    full: dict = {"attempts": []}
    try:
        with T("5_analyst_llm"):
            hyps = analyze(client, evidence, scns, Policy())
        jdump(out / "hypotheses.json", [h.model_dump() for h in hyps])
        targets = targeted_failures(hyps, scns, base.results)
        jdump(out / "targeted_failures.json", targets)
        print(f"\nanalyst: {len(hyps)} hypotheses; targeted failures chosen by code: {len(targets['all'])}")
        if not targets["all"]:
            raise RuntimeError("no targeted failures: hypotheses matched no baseline failures")
        gate = ProofGate(runner, shards=10, rehearsal=True)
        with T("6_gate_prepare"):
            gate.prepare(Policy(), scns, base, targets["all"])
        feedback, dev, last_patch = [], None, None
        for k in range(1, MAX_ATTEMPTS + 1):
            with T(f"7_fixer_llm_attempt{k}"):
                fr = propose(client, hyps, Policy(), feedback, base_pass)[0]
            with T(f"8_dev_stage_attempt{k}"):
                dev = gate.dev_stage(fr.patched_policy)
            last_patch = fr.patched_policy
            c = dev.checks
            after = (sum(r.success for r in dev.patched_run.results) / len(dev.patched_run.results)) if dev.patched_run.complete else None
            fb = DevFeedback(attempt=k, patch=fr.output.changes, g3_target_fix_rate=c["G3"].observed.get("fix_rate"), g3_threshold=cfg.GATE_TARGET_FIX_RATE,
                             g4_regressions=c["G4"].observed.get("regressions"), g4_budget=c["G4"].threshold.get("budget", 0),
                             g2_all_reproduced=None if c["G2"].status.value == "not_run" else c["G2"].status.value == "pass",
                             g1_deterministic=None if c["G1"].status.value == "not_run" else c["G1"].status.value == "pass",
                             g6_complete=dev.complete, analysis_pass_rate_before=round(base_pass, 4), analysis_pass_rate_after=after)
            feedback.append(fb)
            full["attempts"].append({"attempt": k, "model_proposal": fr.output.model_dump(), "clamped": fr.clamped,
                                     "patched_policy": fr.patched_policy.model_dump(), "dev_checks": {i: ch.model_dump(mode="json") for i, ch in c.items()},
                                     "regressed_scenario_ids": dev.regressed_ids, "feedback_given_to_next_attempt": fb.model_dump()})
            print(f"attempt {k}: model proposed {fr.output.changes} (clamped: {fr.clamped}) -> G1..G4 = "
                  f"{[c[i].status.value for i in ('G1','G2','G3','G4')]}  fix_rate={c['G3'].observed.get('fix_rate')} regressions={c['G4'].observed.get('regressions')}")
            if dev.passed:
                break
        with T("9_verification_g5"):
            vset = make_verification_set(ledger, f"{run_id}:full", rehearsal=True) if dev.passed else None
            rep = gate.finalize(dev, last_patch, vset)
        jdump(out / "gate_full_pipeline.json", {"label": LABEL, "attempts": full["attempts"], "report": rep.model_dump(mode="json")})
        gate_summary("full pipeline (real models)", rep)
        full["verdict"] = rep.verdict.value
        full["checks"] = {c.id: c.status.value for c in rep.checks}
    except LLMError as e:
        full["error"] = f"{type(e).__name__}: {client.mask(str(e))}"
        print("\nFULL PIPELINE STOPPED:", full["error"])
    finally:
        jdump(out / "llm_transcript.json", client.transcript)
        usage = client.usage_summary()
        pricing = fetch_pricing(settings, {settings.model_fast, settings.model_reasoning})
        calls = [r.__dict__ for r in client.records]
        cost = None
        if pricing:
            cost = round(sum((r.prompt_tokens or 0) * pricing[r.model]["prompt"] + (r.completion_tokens or 0) * pricing[r.model]["completion"]
                             for r in client.records if not r.cached and r.model in pricing), 6)
        summary.update({"timings_s": T.t, "llm_usage": usage, "llm_calls": calls, "pricing_per_token_from_api": pricing,
                        "estimated_cost_usd": cost, "cost_note": "ESTIMATE = tokens x per-token prices reported by GET /models?verbose=true; "
                        "hidden reasoning tokens are included in completion tokens; actual billing UNCONFIRMED",
                        "full_pipeline": {k: v for k, v in full.items() if k != "attempts"},
                        "any_cached": usage["any_cached"], "seed_ledger": [list(r) for r in ledger.rows()]})
        jdump(out / "summary.json", summary)
        print("\nstage wall-clock (s):", T.t)
        print("llm usage:", usage, "| estimated cost USD:", cost)
        for r in client.records:
            print(f"  call {r.purpose:<20} {r.model.split('/')[-1]:<32} attempt={r.attempt} {r.latency_s:6.2f}s prompt={r.prompt_tokens} completion={r.completion_tokens} ok={r.ok} cached={r.cached}")
        print("artifacts:", out)


if __name__ == "__main__":
    main()
