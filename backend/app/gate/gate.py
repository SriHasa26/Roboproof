"""Proof-of-Robustness Gate: PURE CODE, no LLM. Decides VERIFIED / FAILED / UNVERIFIED from measured simulator results.

Checks (PROJECT_BRIEF.md 3.3, thresholds in core/gate_config.py):
  G1 determinism      a fixed, evenly spaced sample of the baseline is re-run (fresh processes); outcomes must be identical
  G2 reproduced       every targeted failure fails again on the unpatched policy
  G3 fixed            at least GATE_TARGET_FIX_RATE of the targeted failures now pass
  G4 no regressions   previously passing analysis-set scenarios that now fail <= floor(GATE_REGRESSION_BUDGET_FRAC x passing);
                      the strict zero-budget result is always reported next to it
  G5 generalisation   on a fresh code-only verification set: patched pass rate >= GATE_HELDOUT_TARGET, improvement over the
                      unpatched policy on the SAME set >= GATE_MIN_IMPROVEMENT, and the patched Wilson 95% lower bound >
                      the unpatched pass rate
  G6 complete         every run the gate relied on finished with no failed or timed-out shard
Verdict: UNVERIFIED if G6 is not PASS or any check could not run (not_run, other than a deliberate skip after an earlier
failure); otherwise FAILED if any check failed; otherwise VERIFIED. A crash, timeout or missing result is never a pass.

Two stages so the fixer can iterate without ever touching verification data: prepare() + dev_stage() compute G1 to G4 on the
ANALYSIS set; finalize() runs G5 (once) and assembles the report. This module lives under app/gate/, the only place allowed to
pass held_out=True.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..core import gate_config as cfg
from ..core.schemas import (CheckStatus, GateCheck, GateReport, Policy, Result, Scenario, SetMetrics, Verdict)
from ..core.stats import wilson
from ..runner.base import JobRunner, RunResult
from ..store.ledger import SeedBlockReusedError
from .verification import VerificationSet

PASS, FAIL, NOT_RUN = CheckStatus.PASS, CheckStatus.FAIL, CheckStatus.NOT_RUN


def metrics_of(results: list[Result]) -> SetMetrics:
    n = len(results)
    ok = [r for r in results if r.success]
    lo, hi = wilson(len(ok), n)
    return SetMetrics(
        n=n, pass_rate=round(len(ok) / n, 4) if n else 0.0, pass_rate_ci95=[round(lo, 4), round(hi, 4)],
        collision_rate=round(sum(r.collision for r in results) / n, 4) if n else 0.0,
        mean_completion_time_s=round(sum(r.completion_time_s for r in ok) / len(ok), 3) if ok else None)


def _check(id_: str, name: str, status: CheckStatus, observed=None, threshold=None, details="", skipped=False) -> GateCheck:
    return GateCheck(id=id_, name=name, status=status, observed=observed or {}, threshold=threshold or {}, details=details,
                     skipped_after_failure=skipped)


def decide_verdict(checks: list[GateCheck]) -> Verdict:
    by = {c.id: c for c in checks}
    g6 = by.get("G6")
    if g6 is None or g6.status != PASS:
        return Verdict.UNVERIFIED
    if any(c.status == NOT_RUN and not c.skipped_after_failure for c in checks):
        return Verdict.UNVERIFIED
    if any(c.status == FAIL for c in checks):
        return Verdict.FAILED
    return Verdict.VERIFIED


@dataclass
class DevStage:
    """Result of G1 to G4 (+ the completeness of the runs so far) for one patch, on the analysis set only."""
    checks: dict[str, GateCheck]
    patched_run: RunResult
    regressed_ids: list[str]
    strict_zero_budget: dict
    complete: bool

    @property
    def any_failed(self) -> bool:
        return any(c.status == FAIL for c in self.checks.values())

    @property
    def passed(self) -> bool:
        return self.complete and all(self.checks[k].status == PASS for k in ("G1", "G2", "G3", "G4"))


@dataclass
class ProofGate:
    runner: JobRunner
    shards: int = 10
    rehearsal: bool = False
    _prepared: dict = field(default_factory=dict)
    _runs: list = field(default_factory=list)  # (label, RunResult) of every run the verdict relies on

    # ------------------------------------------------------------------ stage 1 (patch independent)
    def prepare(self, baseline_policy: Policy, scenarios: list[Scenario], baseline_run: RunResult, targeted_ids: list[str]) -> None:
        """Runs G1 (determinism) and G2 (targeted failures reproduce) once, on the UNPATCHED policy."""
        self._runs = [("baseline", baseline_run)]
        by_id = {s.id: s for s in scenarios}
        base = {r.scenario_id: r for r in baseline_run.results}
        p: dict = {"policy": baseline_policy, "scenarios": scenarios, "base": base, "targeted": list(targeted_ids)}

        # G1
        k = min(cfg.GATE_DETERMINISM_SAMPLE, len(scenarios))
        step = max(1, len(scenarios) // max(k, 1))
        sample = [s for s in scenarios[::step]][:k] if k else []
        g1 = None
        if not baseline_run.complete or not sample:
            g1 = _check("G1", "Determinism", NOT_RUN, details="baseline incomplete or empty sample")
        else:
            rr = self.runner.run(baseline_policy, sample, shards=min(self.shards, len(sample)))
            self._runs.append(("g1_rerun", rr))
            if not rr.complete:
                g1 = _check("G1", "Determinism", NOT_RUN, details="re-run incomplete", threshold={"sample": len(sample)})
            else:
                diff = [r.scenario_id for r in rr.results if r.model_dump() != base[r.scenario_id].model_dump()]
                g1 = _check("G1", "Determinism", FAIL if diff else PASS, observed={"sample": len(sample), "mismatches": len(diff)},
                            threshold={"mismatches": 0}, details=f"differing scenarios: {diff[:10]}" if diff else "all outcomes identical")
        p["G1"] = g1

        # G2
        if not p["targeted"]:
            g2 = _check("G2", "Targeted failures reproduced", NOT_RUN, details="no targeted failures were defined")
        elif not baseline_run.complete:
            g2 = _check("G2", "Targeted failures reproduced", NOT_RUN, details="baseline incomplete")
        else:
            rr = self.runner.run(baseline_policy, [by_id[i] for i in p["targeted"]], shards=min(self.shards, len(p["targeted"])))
            self._runs.append(("g2_rerun", rr))
            if not rr.complete:
                g2 = _check("G2", "Targeted failures reproduced", NOT_RUN, details="re-run incomplete")
            else:
                not_repro = [r.scenario_id for r in rr.results if r.success]
                g2 = _check("G2", "Targeted failures reproduced", FAIL if not_repro else PASS,
                            observed={"targeted": len(p["targeted"]), "not_reproduced": len(not_repro)},
                            threshold={"not_reproduced": 0}, details=f"did not fail again: {not_repro[:10]}" if not_repro else "all reproduced")
        p["G2"] = g2
        self._prepared = p

    # ------------------------------------------------------------------ stage 1 (per patch)
    def dev_stage(self, patched_policy: Policy) -> DevStage:
        """G3 and G4 for one patch, on the analysis set (G1/G2 come from prepare())."""
        p = self._prepared
        if not p:
            raise RuntimeError("call prepare() first")
        scenarios, base = p["scenarios"], p["base"]
        run = self.runner.run(patched_policy, scenarios, shards=self.shards)
        self._runs = [r for r in self._runs if r[0] != "patched_analysis"] + [("patched_analysis", run)]
        passing_before = [i for i, r in base.items() if r.success]
        strict = {"regressions": None, "pass": None}
        regressed: list[str] = []
        if not run.complete or not p["targeted"] or len(base) != len(scenarios):
            g3 = _check("G3", "Targeted failures fixed", NOT_RUN, details="patched run incomplete or no targeted failures")
            g4 = _check("G4", "No regressions", NOT_RUN, details="patched run incomplete")
        else:
            now = {r.scenario_id: r for r in run.results}
            fixed = [i for i in p["targeted"] if now[i].success]
            rate = len(fixed) / len(p["targeted"])
            g3 = _check("G3", "Targeted failures fixed", PASS if rate >= cfg.GATE_TARGET_FIX_RATE else FAIL,
                        observed={"fixed": len(fixed), "targeted": len(p["targeted"]), "fix_rate": round(rate, 4)},
                        threshold={"min_fix_rate": cfg.GATE_TARGET_FIX_RATE})
            regressed = sorted(i for i in passing_before if not now[i].success)
            budget = math.floor(cfg.GATE_REGRESSION_BUDGET_FRAC * len(passing_before))
            strict = {"regressions": len(regressed), "pass": len(regressed) == 0}
            g4 = _check("G4", "No regressions", PASS if len(regressed) <= budget else FAIL,
                        observed={"regressions": len(regressed), "previously_passing": len(passing_before), "strict_zero_budget_pass": strict["pass"]},
                        threshold={"budget": budget, "budget_frac": cfg.GATE_REGRESSION_BUDGET_FRAC},
                        details=f"regressed: {regressed}" if regressed else "none")
        checks = {"G1": p["G1"], "G2": p["G2"], "G3": g3, "G4": g4}
        complete = all(r.complete for _, r in self._runs)
        return DevStage(checks=checks, patched_run=run, regressed_ids=regressed, strict_zero_budget=strict, complete=complete)

    # ------------------------------------------------------------------ stage 2 (terminal)
    def finalize(self, dev: DevStage, patched_policy: Policy, vset: VerificationSet | None,
                 diagnostic_g5: bool = False) -> GateReport:
        """Run G5 (only if the dev stage passed and there is a verification set), then G6 and the verdict.

        diagnostic_g5=True runs G5 even though an earlier check failed, to show what it would have said. It is refused for
        held-out blocks (it would spend a single-use block on a rejected patch) and never changes a FAILED verdict.
        """
        p = self._prepared
        verification_metrics: dict[str, SetMetrics] = {}
        dev_ok = dev.complete and all(dev.checks[k].status == PASS for k in ("G1", "G2", "G3", "G4"))
        dev_failed = dev.any_failed
        if diagnostic_g5 and vset is not None and vset.held_out:
            raise ValueError("diagnostic G5 is only allowed on rehearsal blocks, never on a held-out block")
        run_anyway = diagnostic_g5 and vset is not None and dev.complete
        if vset is None and dev_failed:
            g5 = _check("G5", "Held-out generalization", NOT_RUN, skipped=True,
                        details="skipped: an earlier check failed, so the single-use verification block was not spent")
        elif vset is None:
            g5 = _check("G5", "Held-out generalization", NOT_RUN, details="no verification set provided")
        elif dev_failed and not dev_ok and not run_anyway:
            g5 = _check("G5", "Held-out generalization", NOT_RUN, skipped=True,
                        details="skipped: an earlier check failed, so the single-use verification block was not spent")
        elif not dev_ok and not run_anyway:
            g5 = _check("G5", "Held-out generalization", NOT_RUN, details="earlier checks could not run or runs were incomplete")
        else:
            if vset.consumed:
                raise SeedBlockReusedError(f"verification set [{vset.start}, {vset.start + vset.count}) was already used for G5")
            vset.consumed = True
            held = vset.held_out
            base_run = self.runner.run(p["policy"], vset.scenarios, shards=self.shards, held_out=held)
            new_run = self.runner.run(patched_policy, vset.scenarios, shards=self.shards, held_out=held)
            self._runs += [("verify_unpatched", base_run), ("verify_patched", new_run)]
            if not (base_run.complete and new_run.complete):
                g5 = _check("G5", "Held-out generalization", NOT_RUN, details="verification run incomplete")
            else:
                mb, mp = metrics_of(base_run.results), metrics_of(new_run.results)
                verification_metrics = {"before": mb, "after": mp}
                lo = mp.pass_rate_ci95[0]
                conds = {"target": mp.pass_rate >= cfg.GATE_HELDOUT_TARGET,
                         "improvement": mp.pass_rate - mb.pass_rate >= cfg.GATE_MIN_IMPROVEMENT - 1e-9,
                         "wilson_lower_above_baseline": lo > mb.pass_rate}
                g5 = _check("G5", "Held-out generalization", PASS if all(conds.values()) else FAIL,
                            observed={"patched_pass_rate": mp.pass_rate, "patched_wilson95_lower": lo, "unpatched_pass_rate": mb.pass_rate,
                                      "improvement": round(mp.pass_rate - mb.pass_rate, 4), "n": mp.n, "conditions": conds},
                            threshold={"min_pass_rate": cfg.GATE_HELDOUT_TARGET, "min_improvement": cfg.GATE_MIN_IMPROVEMENT,
                                       "wilson_lower_must_exceed_unpatched_pass_rate": True},
                            details=(("DIAGNOSTIC (an earlier check had already failed). " if run_anyway and not dev_ok else "")
                                     + (("failed: " + ", ".join(k for k, v in conds.items() if not v)) if not all(conds.values()) else "all conditions met")))

        bad = [(label, r) for label, r in self._runs if not r.complete]
        g6 = _check("G6", "Complete execution", FAIL if bad else PASS,
                    observed={"runs": len(self._runs), "incomplete_runs": [label for label, _ in bad],
                              "failed_shards": sum(r.shards_failed for _, r in self._runs),
                              "missing_scenarios": sum(len(r.missing_scenario_ids) for _, r in self._runs)},
                    details="; ".join(f"{label}: {r.shards_failed}/{r.shards_total} shards failed" for label, r in bad) or "all shards finished")
        checks = [dev.checks["G1"], dev.checks["G2"], dev.checks["G3"], dev.checks["G4"], g5, g6]
        base_results = list(p["base"].values())
        analysis = {"before": metrics_of(base_results)}
        if dev.patched_run.complete:
            analysis["after"] = metrics_of(dev.patched_run.results)
        metrics = {"analysis": analysis}
        if verification_metrics:
            metrics["verification"] = verification_metrics
        return GateReport(
            verdict=decide_verdict(checks), rehearsal=self.rehearsal if vset is None else vset.rehearsal, checks=checks,
            regressed_scenario_ids=dev.regressed_ids, strict_zero_budget=dev.strict_zero_budget, metrics=metrics,
            verification_set=({"block": vset.block_name, "start": vset.start, "count": vset.count, "sampler": vset.sampler,
                               "rehearsal": vset.rehearsal} if vset else {}),
            config={"heldout_target": cfg.GATE_HELDOUT_TARGET, "min_improvement": cfg.GATE_MIN_IMPROVEMENT, "target_fix_rate": cfg.GATE_TARGET_FIX_RATE,
                    "regression_budget_frac": cfg.GATE_REGRESSION_BUDGET_FRAC, "determinism_sample": cfg.GATE_DETERMINISM_SAMPLE,
                    "heldout_size": cfg.GATE_HELDOUT_SIZE})
