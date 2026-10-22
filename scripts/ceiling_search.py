"""Find the achievable pass-rate ceiling for the five effective policy parameters (DEV seeds only).

Random search + coordinate refinement, scored on dev set A (sweep seed 11, n=300, seeds from 1000);
the winner and the default are then cross-checked on dev set B (sweep seed 23, n=300, seeds from 50000).
Selection uses set A only. Nothing here touches held-out seeds. Writes docs/ceiling_search_results.json.
"""
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from devlib import JOBS, SET_A, SET_B, Policy, dev_set, evaluate, summarize  # noqa: E402
from app.core.bounds import INT_POLICY_PARAMS, POLICY_BOUNDS  # noqa: E402

PARAMS = ["grip_force", "grasp_hold_steps", "retry_count", "lift_speed", "lift_height"]
N_RANDOM = int(sys.argv[1]) if len(sys.argv) > 1 else 40
OUT = Path(__file__).resolve().parents[1] / "docs" / "ceiling_search_results.json"


def make(vals: dict) -> Policy:
    d = {}
    for k, v in vals.items():
        lo, hi, _ = POLICY_BOUNDS[k]
        v = min(max(v, lo), hi)
        d[k] = int(round(v)) if k in INT_POLICY_PARAMS else float(v)
    return Policy(**d)


def key(p: Policy) -> tuple:
    return tuple(getattr(p, k) for k in PARAMS)


def main():
    rng = np.random.default_rng(2026)
    A, B = dev_set(SET_A), dev_set(SET_B)
    log, cache = [], {}
    t0 = time.time()

    with Pool(JOBS) as pool:
        def score(p: Policy, tag: str):
            k = key(p)
            if k in cache:
                return cache[k]
            s = summarize(evaluate(pool, p, A))
            cache[k] = (s["pass_rate"], -s["mean_time_s_success"])  # higher pass first, then faster
            log.append({"tag": tag, "policy": {q: getattr(p, q) for q in PARAMS}, **s})
            print(f"[{len(log):3d}] {tag:<8} pass={s['pass_rate']:.3f} t={s['mean_time_s_success']:.2f}s "
                  f"{[getattr(p, q) for q in PARAMS]}", flush=True)
            return cache[k]

        default = Policy()
        best, best_s = default, score(default, "default")
        # structured anchors, then uniform random
        anchors = [dict(grip_force=40), dict(grasp_hold_steps=60), dict(retry_count=3), dict(lift_speed=0.1),
                   dict(grip_force=40, grasp_hold_steps=60, retry_count=3, lift_speed=0.1),
                   dict(grip_force=80, grasp_hold_steps=120, retry_count=3, lift_speed=0.05, lift_height=0.2)]
        cands = [make({**{q: getattr(default, q) for q in PARAMS}, **a}) for a in anchors]
        for _ in range(N_RANDOM):
            cands.append(make({q: (rng.uniform(POLICY_BOUNDS[q][0], POLICY_BOUNDS[q][1])) for q in PARAMS}))
        for i, c in enumerate(cands):
            s = score(c, "anchor" if i < len(anchors) else "random")
            if s > best_s:
                best, best_s = c, s
        # coordinate refinement around the best
        grids = {"grip_force": [10, 20, 30, 45, 60, 80], "grasp_hold_steps": [0, 10, 20, 40, 70, 120],
                 "retry_count": [0, 1, 2, 3], "lift_speed": [0.05, 0.1, 0.15, 0.2, 0.3], "lift_height": [0.1, 0.15, 0.2, 0.3]}
        for rnd in range(2):
            improved = False
            for q in PARAMS:
                for v in grids[q]:
                    c = make({**{k: getattr(best, k) for k in PARAMS}, q: v})
                    s = score(c, f"coord{rnd}")
                    if s > best_s:
                        best, best_s, improved = c, s, True
            if not improved:
                break

        # cross-check on set B: default, best, and the top-5 by set-A score
        top = sorted(cache.items(), key=lambda kv: kv[1], reverse=True)[:5]
        cross = {}
        for name, p in [("default", default), ("best", best)] + [(f"top{i+1}", make(dict(zip(PARAMS, k)))) for i, (k, _) in enumerate(top)]:
            cross[name] = {"policy": {q: getattr(p, q) for q in PARAMS}, "A": summarize(evaluate(pool, p, A)), "B": summarize(evaluate(pool, p, B))}

    res = {"n_policy_evaluations": len(log), "n_scenarios_per_eval": 300, "total_simulations": len(log) * 300 + len(cross) * 600,
           "wall_clock_s": round(time.time() - t0, 1), "jobs": JOBS, "search_set": SET_A, "crosscheck_set": SET_B,
           "best_policy": {q: getattr(best, q) for q in PARAMS}, "cross": cross, "log": log}
    OUT.write_text(json.dumps(res, indent=1))
    print(f"\nevaluations={len(log)} wall={res['wall_clock_s']}s jobs={JOBS}")
    for name in ("default", "best"):
        c = cross[name]
        print(f"{name:8} A pass={c['A']['pass_rate']:.3f}  B pass={c['B']['pass_rate']:.3f}  policy={c['policy']}")
        print(f"         A reasons={c['A']['reasons']}  B reasons={c['B']['reasons']}")


if __name__ == "__main__":
    main()
