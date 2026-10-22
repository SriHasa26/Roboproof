"""Analysis only (dev seeds, simulator untouched): how do natural candidate patches behave on dev sets A and B?

For each patch: pass rate overall, fix rate on the targeted heavy-and-slippery failures, regressions among previously
passing scenarios, and pass rate IF a cycle-time deadline were part of "success" (computed from the recorded
completion_time_s; this does NOT change the simulator, it only asks what a deadline would do).
Writes docs/trap_alternatives.json.
"""
import json
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from devlib import JOBS, SET_A, SET_B, Policy, dev_set, evaluate  # noqa: E402
from app.core.schemas import PolicyPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEADLINES = [5.0, 6.0, 8.0]
PATCHES = {
    "default": {},
    "grip 80 only": {"grip_force": 80},
    "hold 60 only": {"grasp_hold_steps": 60},
    "retries 3 only": {"retry_count": 3},
    "grip 80 + hold 60": {"grip_force": 80, "grasp_hold_steps": 60},
    "grip 80 + hold 60 + retries 3": {"grip_force": 80, "grasp_hold_steps": 60, "retry_count": 3},
    "grip 40 + hold 30": {"grip_force": 40, "grasp_hold_steps": 30},
    "best found (ceiling search)": None,  # filled from docs/ceiling_search_results.json
}


def is_target(s):
    return s.mass_kg > 0.5 and s.friction < 0.4


def main():
    best = json.load(open(ROOT / "docs" / "ceiling_search_results.json"))["best_policy"]
    PATCHES["best found (ceiling search)"] = {k: (int(v) if k in ("grasp_hold_steps", "retry_count") else v) for k, v in best.items()}
    out = {"deadlines_s": DEADLINES, "patches": {}}
    with Pool(JOBS) as pool:
        for tag, spec in (("A", SET_A), ("B", SET_B)):
            sc = dev_set(spec)
            base = evaluate(pool, Policy(), sc)
            T = [i for i, (s, r) in enumerate(zip(sc, base)) if is_target(s) and not r.success]
            P = [i for i, r in enumerate(base) if r.success]
            for name, ch in PATCHES.items():
                pol = Policy() if not ch else PolicyPatch(changes=ch).apply(Policy())[0]
                res = base if not ch else evaluate(pool, pol, sc)
                row = out["patches"].setdefault(name, {"changes": ch})
                row[tag] = {
                    "pass": sum(r.success for r in res) / len(res),
                    "fix_rate_targeted": sum(res[i].success for i in T) / len(T),
                    "targeted_n": len(T),
                    "regressions": sum(not res[i].success for i in P), "previously_passing": len(P),
                    "mean_time_s": sum(r.completion_time_s for r in res if r.success) / max(sum(r.success for r in res), 1),
                    "pass_under_deadline": {str(d): sum(r.success and r.completion_time_s <= d for r in res) / len(res) for d in DEADLINES},
                }
                print(f"[{tag}] {name:<32} pass={row[tag]['pass']:.3f} fix={row[tag]['fix_rate_targeted']:.2f}/{len(T)} "
                      f"regress={row[tag]['regressions']}/{len(P)} t={row[tag]['mean_time_s']:.2f}s "
                      f"deadline5/6/8={[round(v, 3) for v in row[tag]['pass_under_deadline'].values()]}", flush=True)
    (ROOT / "docs" / "trap_alternatives.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
