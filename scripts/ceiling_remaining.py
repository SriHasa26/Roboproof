"""Describe the failures that remain under the best searched policy (the 'unfixable by parameters' set). Dev seeds only."""
import json
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from devlib import JOBS, SET_A, SET_B, Policy, dev_set, evaluate  # noqa: E402

d = json.load(open(Path(__file__).resolve().parents[1] / "docs" / "ceiling_search_results.json"))
bp = d["best_policy"]
best = Policy(**{**bp, "grasp_hold_steps": int(bp["grasp_hold_steps"]), "retry_count": int(bp["retry_count"])})
with Pool(JOBS) as pool:
    for name, spec in (("A", SET_A), ("B", SET_B)):
        sc = dev_set(spec)
        res = evaluate(pool, best, sc)
        print(f"set {name}: {sum(r.success for r in res)}/{len(res)} pass; remaining failures:")
        for s, r in zip(sc, res):
            if not r.success:
                print(f"  {r.failure_reason.value:<20} noise={s.sensor_noise_m:.3f} size={s.size_m:.3f} mass={s.mass_kg:.2f} mu={s.friction:.2f} delay={s.gripper_delay_steps:2d} off=({s.pos_offset_x:+.3f},{s.pos_offset_y:+.3f}) err={r.final_place_error_m:.3f}")
