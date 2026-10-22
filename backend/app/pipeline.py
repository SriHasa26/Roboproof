"""The full RoboProof pipeline for one run: generator -> runner -> evidence -> analyst -> fixer (<=3 attempts, dev-stage
feedback only) -> gate. Part of the frozen pipeline (see core/provenance.py).

A run is either a REHEARSAL (verification set from the rehearsal seed block, flagged everywhere) or OFFICIAL (verification set
from a fresh held-out block; refused unless the pipeline freeze checks pass). Official runs and recorded rehearsals must use real,
uncached model calls. Every run writes its artifacts under <out_dir>/<run_id>/ including per-stage timers and provenance.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .analysis.analyst import analyze, targeted_failures
from .analysis.evidence import compute_evidence
from .analysis.fixer import MAX_ATTEMPTS, propose
from .analysis.models import CandidateRow, DevFeedback
from .analysis.selection import CandidateEval, select_candidate
from .core import gate_config as cfg_gate
from .core.config import Settings
from .core.provenance import describe_unofficial, official_preflight
from .core.schemas import Policy, Result, Scenario
from .core.stats import wilson
from .gate.gate import ProofGate, regression_budget
from .gate.verification import make_verification_set
from .llm.client import LLMClient, LLMError
from .runner.base import JobRunner
from .scenarios.generator import ScenarioGenerator
from .store.db import Database
from .store.ledger import SeedLedger

REHEARSAL_LABEL = "REHEARSAL, NOT AN OFFICIAL RESULT. Verification used the rehearsal seed block; held-out seeds were not run."
OFFICIAL_LABEL = "OFFICIAL RUN. Verification used a fresh single-use held-out seed block."


@dataclass
class PipelineConfig:
    run_id: str
    out_dir: Path
    master_seed: int
    n: int = 250
    shards: int = 10
    rehearsal: bool = True
    official: bool = False


class Timer:
    def __init__(self):
        self.t: dict[str, float] = {}

    def __call__(self, name: str):
        outer = self

        class _C:
            def __enter__(s):
                s.t0 = time.perf_counter()

            def __exit__(s, *a):
                outer.t[name] = round(outer.t.get(name, 0.0) + time.perf_counter() - s.t0, 2)

        return _C()


def fetch_pricing(settings: Settings, model_ids: set[str]) -> dict | None:
    """Per-token prices as reported by the API itself (GET /models?verbose=true). None if unavailable (then UNCONFIRMED)."""
    try:
        import httpx

        r = httpx.get(settings.base_url.rstrip("/") + "/models", params={"verbose": "true"},
                      headers={"Authorization": f"Bearer {settings.api_key}"}, timeout=30)
        r.raise_for_status()
        out = {m["id"]: {"prompt": float(m["pricing"]["prompt"]), "completion": float(m["pricing"]["completion"])}
               for m in r.json().get("data", []) if m.get("id") in model_ids and m.get("pricing")}
        return out or None
    except Exception:  # never include the key in a message
        return None


def estimate_cost(records, pricing: dict | None) -> float | None:
    if not pricing:
        return None
    return round(sum((r.prompt_tokens or 0) * pricing[r.model]["prompt"] + (r.completion_tokens or 0) * pricing[r.model]["completion"]
                     for r in records if not r.cached and r.model in pricing), 6)


def generator_value(scenarios: list[Scenario], results: list[Result]) -> dict:
    """Does the model add value? Baseline failure rate of model-targeted vs coverage scenarios, with Wilson 95% intervals.
    Reported as measured; the mix is never tuned."""
    by_id = {r.scenario_id: r for r in results}
    out = {}
    for group in ("cov", "tgt"):
        ids = [s.id for s in scenarios if s.tag.split(":")[0] == group]
        nf = sum(not by_id[i].success for i in ids)
        lo, hi = wilson(nf, len(ids))
        out[group] = {"n": len(ids), "n_fail": nf, "fail_rate": round(nf / len(ids), 4) if ids else None, "wilson95": [round(lo, 4), round(hi, 4)]}
    per_region: dict[str, list[int]] = {}
    for s in scenarios:
        if s.tag.startswith("tgt:"):
            c = per_region.setdefault(s.tag[4:], [0, 0])
            c[0] += 1
            c[1] += not by_id[s.id].success
    out["per_region_fail"] = {k: f"{v[1]}/{v[0]}" for k, v in per_region.items()}
    return out


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")


def run_pipeline(settings: Settings, runner: JobRunner, db: Database, ledger: SeedLedger, cfg: PipelineConfig,
                 env: dict | None = None, pricing: dict | None = None, openai_client=None) -> dict:
    env = dict(os.environ) if env is None else env
    if cfg.official and cfg.rehearsal:
        raise ValueError("an official run cannot be a rehearsal")
    if settings.dev_cache:
        raise ValueError("LLM_DEV_CACHE must be 0 for a recorded run (rehearsal or official): cached responses are not real calls")
    prov = (official_preflight(env, model_fast=settings.model_fast, model_reasoning=settings.model_reasoning, runner_name=runner.name).as_dict()
            if cfg.official else describe_unofficial(env, settings.model_fast, settings.model_reasoning, runner.name))
    settings.require_llm("fast"), settings.require_llm("reasoning")
    out = Path(cfg.out_dir) / cfg.run_id
    out.mkdir(parents=True, exist_ok=True)
    label = OFFICIAL_LABEL if cfg.official else REHEARSAL_LABEL
    _dump(out / "LABEL.json", {"label": label, "official": cfg.official, "rehearsal": cfg.rehearsal, "master_seed": cfg.master_seed,
                               "started": time.strftime("%Y-%m-%d %H:%M:%S"), "provenance": prov})
    client = LLMClient(settings, openai_client=openai_client, sink=lambda rec: db.log_llm_call(rec, cfg.run_id), keep_transcript=True)
    T = Timer()
    res: dict = {"run_id": cfg.run_id, "label": label, "official": cfg.official, "rehearsal": cfg.rehearsal, "master_seed": cfg.master_seed,
                 "provenance": prov, "verdict": None, "error": None, "attempts": [], "n_attempts": 0}
    t_start = time.perf_counter()
    try:
        with T("generate_scenarios_llm"):
            gen = ScenarioGenerator(llm=client).generate(cfg.n, cfg.master_seed)
        scns = gen.scenarios
        res["generator"] = {"source": gen.source, "model": gen.model, "n_regions_used": len(gen.proposal.regions) if gen.proposal else 0,
                            "dropped_regions": gen.dropped_regions, "clamped_values": gen.clamped_values, "trail": gen.generator_trail}
        _dump(out / "analysis_set.json", {"source": gen.source, "model": gen.model, "master_seed": gen.master_seed, "n_coverage": gen.n_coverage,
                                           "n_targeted": gen.n_targeted, "proposal_validated": gen.proposal.model_dump() if gen.proposal else None,
                                           "dropped_regions": gen.dropped_regions, "clamped_values": gen.clamped_values,
                                           "generator_trail": gen.generator_trail, "scenarios": [s.model_dump() for s in scns]})
        with T("baseline_run"):
            base = runner.run(Policy(), scns, shards=cfg.shards)
        _dump(out / "baseline_results.json", {"runner_name": base.runner_name, "image_build_id": base.image_build_id, "complete": base.complete,
                                               "wall_clock_s": base.wall_clock_s, "cpu_count": base.cpu_count,
                                               "results": [r.model_dump(mode="json") for r in base.results]})
        if not base.complete:
            raise RuntimeError("baseline run incomplete: " + str([s.error for s in base.shards if s.error]))
        res["generator_value"] = generator_value(scns, base.results)
        with T("evidence"):
            evidence = compute_evidence(scns, base.results)
        _dump(out / "evidence.json", evidence.model_dump())
        base_pass = sum(r.success for r in base.results) / len(base.results)
        with T("analyst_llm"):
            hyps = analyze(client, evidence, scns, Policy())
        _dump(out / "hypotheses.json", [h.model_dump() for h in hyps])
        targets = targeted_failures(hyps, scns, base.results)
        _dump(out / "targeted_failures.json", targets)
        res["n_hypotheses"], res["n_targeted"] = len(hyps), len(targets["all"])
        if not targets["all"]:
            raise RuntimeError("NO_TARGETS: the hypotheses matched no baseline failures")
        gate = ProofGate(runner, shards=cfg.shards, rehearsal=cfg.rehearsal)
        with T("gate_prepare_g1_g2"):
            gate.prepare(Policy(), scns, base, targets["all"])
        feedback: list[DevFeedback] = []
        dev = last = None
        for k in range(1, MAX_ATTEMPTS + 1):
            with T(f"fixer_llm_attempt{k}"):
                cs = propose(client, hyps, Policy(), feedback, base_pass)
            with T(f"candidate_evals_attempt{k}"):  # every candidate is measured on the ANALYSIS set only
                meas = [gate.evaluate_candidate(c.patched_policy, targets["by_hypothesis"], label=f"attempt{k}_cand{c.index}") for c in cs.candidates]
            done = [m for m in meas if m.complete]
            if not done:
                raise RuntimeError(f"attempt {k}: no candidate evaluation completed")
            budget = regression_budget(done[0].previously_passing)
            evals = [CandidateEval(index=c.index, fixed=m.fixed, targeted=m.targeted, regressions=m.regressions, n_changed=len(c.changed),
                                   grip_force=c.patched_policy.grip_force, complete=m.complete) for c, m in zip(cs.candidates, meas)]
            sel = select_candidate(evals, budget)  # deterministic rule in code; the model does not choose
            chosen, chosen_m = cs.candidates[sel], meas[sel]
            with T(f"dev_stage_attempt{k}"):  # only the selected candidate goes through the gate (reuses its measured run)
                dev = gate.dev_stage(chosen.patched_policy, run=chosen_m.run)
            last = chosen.patched_policy
            c_ = dev.checks
            rows, cand_records = [], []
            for c, m in zip(cs.candidates, meas):
                applied = {q: float(getattr(c.patched_policy, q)) for q in c.changed}
                if m.complete:
                    rows.append(CandidateRow(index=c.index, changes=applied, n_changed=len(c.changed), fixed=m.fixed, targeted=m.targeted,
                                             fix_rate=round(m.fixed / m.targeted, 4), per_hypothesis_fixed={h: f"{a}/{b}" for h, (a, b) in m.per_hypothesis.items()},
                                             regressions=m.regressions, previously_passing=m.previously_passing, budget=budget,
                                             pass_rate=round(m.passes / m.total, 4), collision_rate=round(m.collisions / m.total, 4), selected=c.index == sel))
                cand_records.append({"index": c.index, "model_proposal": c.output.model_dump(), "applied": applied, "clamped": c.clamped, "rounded": c.rounded,
                                     "complete": m.complete, "fixed": m.fixed, "targeted": m.targeted, "regressions": m.regressions,
                                     "previously_passing": m.previously_passing, "pass_rate": round(m.passes / m.total, 4) if m.complete else None,
                                     "collision_rate": round(m.collisions / m.total, 4) if m.complete else None,
                                     "per_hypothesis_fixed": {h: f"{a}/{b}" for h, (a, b) in m.per_hypothesis.items()}, "selected": c.index == sel})
            feedback.append(DevFeedback(
                attempt=k, candidates=rows, selected_index=sel, g3_threshold=cfg_gate.GATE_TARGET_FIX_RATE, g4_budget=budget,
                g2_all_reproduced=None if c_["G2"].status.value == "not_run" else c_["G2"].status.value == "pass",
                g1_deterministic=None if c_["G1"].status.value == "not_run" else c_["G1"].status.value == "pass",
                g6_complete=dev.complete, analysis_pass_rate_before=round(base_pass, 4),
                note=f"{len(cs.dropped)} candidate(s) dropped by validation" if cs.dropped else ""))
            res["attempts"].append({
                "attempt": k, "candidates": cand_records, "dropped_candidates": cs.dropped, "diversity_violations": cs.diversity_violations,
                "selection_rule": "highest targeted fix among candidates within the regression budget; ties: fewer changed params, lower grip; "
                                  "none within budget: fewest regressions", "selected_index": sel, "regression_budget": budget,
                "model_proposal": chosen.output.model_dump(), "clamped": chosen.clamped, "rounded": chosen.rounded,
                "patched_policy": chosen.patched_policy.model_dump(),
                "dev_checks": {i: ch.model_dump(mode="json") for i, ch in c_.items()}, "regressed_scenario_ids": dev.regressed_ids,
                "dev_stage_passed": dev.passed})
            if dev.passed:
                break
        res["n_attempts"] = len(res["attempts"])
        with T("verification_g5"):
            vset = make_verification_set(ledger, cfg.run_id, rehearsal=cfg.rehearsal) if dev.passed else None
            report = gate.finalize(dev, last, vset)
        _dump(out / "gate_report.json", {"label": label, "attempts": res["attempts"], "report": report.model_dump(mode="json")})
        res["verdict"] = report.verdict.value
        res["checks"] = {c.id: c.status.value for c in report.checks}
        res["strict_zero_budget"] = report.strict_zero_budget
        res["metrics"] = {k: {kk: vv.model_dump() for kk, vv in v.items()} for k, v in report.metrics.items()}
        res["gate_timings_s"] = report.timings_s
        res["verification_set"] = report.verification_set
    except (LLMError, RuntimeError, ValueError) as e:
        res["error"] = f"{type(e).__name__}: {client.mask(str(e))}"
    finally:
        usage = client.usage_summary()
        pricing = pricing if pricing is not None else fetch_pricing(settings, {settings.model_fast, settings.model_reasoning})
        res.update({"timings_s": T.t, "wall_clock_total_s": round(time.perf_counter() - t_start, 2), "llm_usage": usage,
                    "llm_calls": [r.__dict__ for r in client.records], "pricing_per_token_from_api": pricing,
                    "estimated_cost_usd": estimate_cost(client.records, pricing),
                    "llm_seconds": round(sum(r.latency_s for r in client.records if not r.cached), 2),
                    "cost_note": "ESTIMATE = tokens x per-token prices from GET /models?verbose=true; hidden reasoning tokens are included "
                                 "in completion tokens; actual billing UNCONFIRMED"})
        _dump(out / "llm_transcript.json", client.transcript)
        _dump(out / "summary.json", res)
    return res
