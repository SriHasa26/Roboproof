"""Search (DEV seeds only) for a scripted "naive fix" that FIXES most heavy-and-slippery failures but REGRESSES
scenarios that passed under the default policy elsewhere. The simulator is never modified.

Targeted failures T: scenarios in dev set A with mass_kg > 0.5 and friction < 0.4 that fail under the default policy.
Regressions R: scenarios outside T's definition that PASS under the default but FAIL under the candidate patch.
Candidates: full grid over the five patchable parameters. Selection rule (decided before running):
  fix rate >= 0.80 and regressions >= MIN_REGRESSIONS, then prefer the patch with the fewest changed parameters
  (a plausible naive fix), then more fixes, then more regressions.
The chosen patch is re-checked on dev set B (reported, not used for selection).
Writes backend/app/gate/scripted_trap.json and docs/trap_search_results.json.
"""
import itertools
import json
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from devlib import JOBS, SET_A, SET_B, Policy, dev_set, evaluate  # noqa: E402
from app.core.schemas import PolicyPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MIN_REGRESSIONS = 10
FIX_TARGET = 0.80


PHRASE = {
    "grip_force": lambda a, b: f"grip force {b:g} -> {a:g} N",
    "grasp_hold_steps": lambda a, b: f"grasp hold {b:g} -> {a:g} steps",
    "lift_speed": lambda a, b: f"lift speed {b:g} -> {a:g} m/s",
    "lift_height": lambda a, b: f"lift height {b:g} -> {a:g} m",
    "retry_count": lambda a, b: f"retries {b:g} -> {a:g}",
}


def describe(changes, default):
    return "Changes: " + "; ".join(PHRASE[k](v, getattr(default, k)) for k, v in changes.items()) + "."


def is_target(s):
    return s.mass_kg > 0.5 and s.friction < 0.4


def main():
    A, B = dev_set(SET_A), dev_set(SET_B)
    default = Policy()
    grid = {
        "grip_force": [15.0, 40.0, 80.0],
        "grasp_hold_steps": [10, 30, 60],
        "lift_speed": [0.3, 0.6],
        "lift_height": [0.065, 0.07, 0.08, 0.1, 0.15],
        "retry_count": [0, 3],
    }
    cands = []
    for vals in itertools.product(*grid.values()):
        ch = dict(zip(grid, vals))
        changes = {k: v for k, v in ch.items() if v != getattr(default, k)}
        if changes:
            cands.append(changes)

    import os
    import numpy as np
    n_random = int(os.environ.get("TRAP_RANDOM", "0"))
    if n_random:  # extra uniformly random patches over the whole patchable space (fixed seed)
        rng = np.random.default_rng(31)
        from app.core.bounds import POLICY_BOUNDS
        for _ in range(n_random):
            ch = {}
            for k in ("grip_force", "grasp_hold_steps", "retry_count", "lift_speed", "lift_height"):
                lo, hi, _d = POLICY_BOUNDS[k]
                v = rng.uniform(lo, hi)
                ch[k] = int(round(v)) if k in ("grasp_hold_steps", "retry_count") else round(float(v), 3)
            cands.append(ch)

    with Pool(JOBS) as pool:
        base = evaluate(pool, default, A)
        T = [i for i, (s, r) in enumerate(zip(A, base)) if is_target(s) and not r.success]
        P = [i for i, r in enumerate(base) if r.success]  # everything that passed (targets by definition failed)
        print(f"dev set A: {len(A)} scenarios, default pass {len(P)}/{len(A)}; targeted failures T={len(T)}", flush=True)
        rows = []
        for n, changes in enumerate(cands):
            pol, _ = PolicyPatch(changes=changes).apply(default)
            rt = evaluate(pool, pol, [A[i] for i in T])
            fix = sum(r.success for r in rt) / len(T)
            reg = None
            if fix >= 0.5:  # evaluate regressions for anything promising so near-misses are visible
                rp = evaluate(pool, pol, [A[i] for i in P])
                reg = sum(not r.success for r in rp)
            rows.append({"changes": changes, "fix_rate": fix, "regressions": reg})
            print(f"[{n+1}/{len(cands)}] fix={fix:.2f} regress={reg} {changes}", flush=True)

        ok = [r for r in rows if r["regressions"] is not None and r["fix_rate"] >= FIX_TARGET]
        near = sorted([r for r in rows if r["regressions"] is not None], key=lambda r: (-r["fix_rate"], -r["regressions"]))[:10]
        meets = [r for r in ok if r["regressions"] >= MIN_REGRESSIONS]
        print(f"\ncandidates={len(cands)} fixing>=80%: {len(ok)}  of which regress>={MIN_REGRESSIONS}: {len(meets)}")
        closest = sorted(ok, key=lambda r: -r["regressions"])[:8] or near
        out = {"all_candidates": rows, "n_candidates": len(cands), "targeted_n": len(T), "default_passing_n": len(P), "closest": closest,
               "selection_rule": f"fix>={FIX_TARGET}, regressions>={MIN_REGRESSIONS}, fewest changed params, then fix, then regressions"}
        if not meets:
            print("NO candidate meets the bar. Closest:")
            for r in closest:
                print("  ", r)
            (ROOT / "docs" / "trap_search_results.json").write_text(json.dumps(out, indent=1))
            return
        best = sorted(meets, key=lambda r: (len(r["changes"]), -r["fix_rate"], -r["regressions"]))[0]
        pol, _ = PolicyPatch(changes=best["changes"]).apply(default)
        # confirm on set B (not used for selection)
        baseB = evaluate(pool, default, B)
        polB = evaluate(pool, pol, B)
        TB = [i for i, s in enumerate(B) if is_target(s) and not baseB[i].success]
        PB = [i for i, r in enumerate(baseB) if r.success]
        fixB = sum(polB[i].success for i in TB) / max(len(TB), 1)
        regB = sum(not polB[i].success for i in PB)
        rp = evaluate(pool, pol, [A[i] for i in P])
        where = {}
        for i, r in zip(P, rp):
            if not r.success:
                s = A[i]
                key = r.failure_reason.value
                where[key] = where.get(key, 0) + 1
        print(f"\nCHOSEN {best}\n  set A: fixed {best['fix_rate']:.0%} of {len(T)} targeted; regressed {best['regressions']} of {len(P)} previously passing {where}")
        print(f"  set B (confirmation): fixed {fixB:.0%} of {len(TB)} targeted; regressed {regB} of {len(PB)} previously passing")
        j = {
            "label": "scripted example, not model output",
            "kind": "scripted_trap",
            "changes": best["changes"],
            "justification": "SCRIPTED EXAMPLE, NOT MODEL OUTPUT. " + describe(best["changes"], default) +
                             " Found by a dev-seed grid search for a patch that fixes the targeted heavy/slippery failures "
                             "while breaking other scenarios; it exists to show that the gate rejects overfit patches.",
            "found_on": {
                "dev_set_A": {**SET_A, "targeted_failures": len(T), "fixed_rate": best["fix_rate"],
                              "previously_passing": len(P), "regressions": best["regressions"], "regression_reasons": where},
                "dev_set_B_confirmation": {**SET_B, "targeted_failures": len(TB), "fixed_rate": fixB,
                                           "previously_passing": len(PB), "regressions": regB},
                "targeted_definition": "mass_kg > 0.5 and friction < 0.4 and failing under the default policy",
            },
        }
        (ROOT / "backend" / "app" / "gate").mkdir(parents=True, exist_ok=True)
        (ROOT / "backend" / "app" / "gate" / "scripted_trap.json").write_text(json.dumps(j, indent=1))
        out["chosen"] = j
        (ROOT / "docs" / "trap_search_results.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
