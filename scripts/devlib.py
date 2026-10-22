"""Dev helpers for search scripts (dev seeds only: every path goes through check_seed via run_scenario)."""
import os
import sys
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.schemas import Policy, Result, Scenario  # noqa: E402
from app.scenarios.sweep import latin_hypercube  # noqa: E402
from app.sim.pickplace import run_scenario  # noqa: E402

JOBS = int(os.environ.get("JOBS", os.cpu_count() or 4))

# Fixed dev evaluation sets (never the held-out range). Set B uses a disjoint seed block for cross-checking.
SET_A = dict(n=300, sweep_seed=11, seed_base=1_000)
SET_B = dict(n=300, sweep_seed=23, seed_base=50_000)


def dev_set(spec: dict) -> list[Scenario]:
    return latin_hypercube(spec["n"], spec["sweep_seed"], seed_base=spec["seed_base"])


def _run(args):
    return run_scenario(args[0], args[1])[0]


def evaluate(pool: Pool, policy: Policy, scenarios: list[Scenario]) -> list[Result]:
    return pool.map(_run, [(policy, s) for s in scenarios], chunksize=4)


def summarize(results: list[Result]) -> dict:
    ok = [r for r in results if r.success]
    return {
        "n": len(results), "pass_rate": len(ok) / len(results),
        "mean_time_s_success": sum(r.completion_time_s for r in ok) / max(len(ok), 1),
        "reasons": dict(Counter(r.failure_reason.value for r in results if r.failure_reason)),
        "collisions": sum(r.collision for r in results),
    }
