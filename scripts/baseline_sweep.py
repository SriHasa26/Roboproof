"""Dev baseline: run the default policy over a seeded Latin-hypercube sweep (DEV seeds only) and print a summary.

Usage: python scripts/baseline_sweep.py [--n 200] [--sweep-seed 7] [--out path.json] [--jobs 4]
"""
import argparse, json, sys, time
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.bounds import SCENARIO_BOUNDS  # noqa: E402
from app.core.schemas import Policy, Scenario  # noqa: E402
from app.scenarios.sweep import DEV_SEED_BASE, HELDOUT_SEED_BASE, latin_hypercube  # noqa: E402
from app.sim.pickplace import run_scenario  # noqa: E402


def _run(args):
    pol, scn = args
    return run_scenario(pol, scn)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--sweep-seed", type=int, default=7)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out")
    ap.add_argument("--set", nargs="*", default=[], help="policy overrides, e.g. grip_force=12")
    a = ap.parse_args()
    scns = latin_hypercube(a.n, a.sweep_seed)
    assert all(s.seed < HELDOUT_SEED_BASE for s in scns) and scns[0].seed >= DEV_SEED_BASE
    pol = Policy(**{k: float(v) for k, v in (x.split('=') for x in a.set)})
    t = time.time()
    with Pool(a.jobs) as pool:
        res = pool.map(_run, [(pol, s) for s in scns], chunksize=4)
    wall = time.time() - t
    ok = sum(r.success for r in res)
    print(f"policy={pol.model_dump()}\nN={a.n} pass={ok}/{a.n} = {ok/a.n:.1%}  collisions={sum(r.collision for r in res)}  wall={wall:.1f}s (jobs={a.jobs})")
    print("failure reasons:", dict(Counter(r.failure_reason.value for r in res if r.failure_reason)))
    ts = [r.completion_time_s for r in res if r.success]
    print(f"mean completion time (successes): {sum(ts)/max(len(ts),1):.2f}s")
    print(f"\n{'axis':<22}{'bin range':<22}{'n':>4}{'pass%':>8}")
    for ax, (lo, hi) in SCENARIO_BOUNDS.items():
        for b in range(4):
            blo, bhi = lo + (hi - lo) * b / 4, lo + (hi - lo) * (b + 1) / 4
            idx = [i for i, s in enumerate(scns) if blo <= getattr(s, ax) <= bhi and (b == 3 or getattr(s, ax) < bhi)]
            if idx:
                p = sum(res[i].success for i in idx) / len(idx)
                print(f"{ax:<22}{f'[{blo:.3f}, {bhi:.3f}]':<22}{len(idx):>4}{p:>8.0%}")
    if a.out:
        Path(a.out).write_text(json.dumps([{"scenario": s.model_dump(), "result": r.model_dump(mode="json")} for s, r in zip(scns, res)]))


if __name__ == "__main__":
    main()
