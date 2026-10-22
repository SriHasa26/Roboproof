"""Run the default policy on N generated dev scenarios with LocalRunner, store the baseline in SQLite, print a summary.

Scenario regions come from the Nebius model when NEBIUS_API_KEY/NEBIUS_MODEL_FAST are set (PENDING_KEY), otherwise
from the hand-written FIXTURE (clearly labelled in the output and in the database). Dev seeds only.

Usage: python scripts/run_baseline.py [--n 200] [--shards 10] [--master-seed 1] [--db path] [--label baseline]
"""
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import load_settings  # noqa: E402
from app.core.schemas import Policy  # noqa: E402
from app.runner.local import LocalRunner  # noqa: E402
from app.scenarios.generator import ScenarioGenerator  # noqa: E402
from app.store.db import Database  # noqa: E402

FIXTURE = ROOT / "backend" / "tests" / "fixtures" / "scenario_proposal.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--shards", type=int, default=10)
    ap.add_argument("--master-seed", type=int, default=1)
    ap.add_argument("--db")
    ap.add_argument("--label", default="baseline-default-policy")
    ap.add_argument("--summary-out")
    a = ap.parse_args()

    settings = load_settings(dotenv_path=ROOT / ".env")
    gen = ScenarioGenerator.from_settings(settings, FIXTURE).generate(a.n, a.master_seed)
    policy = Policy()
    run = LocalRunner().run(policy, gen.scenarios, shards=a.shards)

    batch_id = f"{a.label}-{a.master_seed}-{a.n}"
    db = Database(a.db or str(ROOT / settings.db_path))
    db.save_batch(batch_id, a.label, policy, gen.scenarios, run, gen.source)

    res = run.results
    n = len(res)
    ok = sum(r.success for r in res)
    times = [r.completion_time_s for r in res if r.success]
    reasons = Counter(r.failure_reason.value for r in res if r.failure_reason)
    summary = {
        "batch_id": batch_id, "runner": run.runner_name + " (LOCAL FALLBACK, not Nebius)", "scenario_source": gen.source,
        "scenarios_requested": a.n, "scenarios_run": n, "complete": run.complete, "missing": len(run.missing_scenario_ids),
        "pass_rate": ok / n if n else None, "collision_rate": sum(r.collision for r in res) / n if n else None,
        "mean_completion_time_s_successes": sum(times) / len(times) if times else None,
        "failure_reasons": dict(reasons), "shards": run.shards_total, "shards_ok": run.shards_ok,
        "cpu_count": run.cpu_count, "workers": os.cpu_count(), "wall_clock_s": run.wall_clock_s,
        "n_coverage": gen.n_coverage, "n_targeted": gen.n_targeted, "policy": policy.model_dump(),
    }
    print(f"\nBaseline {batch_id}  [{summary['runner']}]  regions source: {gen.source.upper()}"
          + ("  (FIXTURE, not model output)" if gen.source == "fixture" else ""))
    print(f"  scenarios  {n}/{a.n} run ({gen.n_coverage} coverage + {gen.n_targeted} targeted), complete={run.complete}")
    if n:
        print(f"  pass rate  {ok}/{n} = {ok / n:.1%}")
        print(f"  collisions {summary['collision_rate']:.1%}")
        print(f"  mean completion time (successes) {summary['mean_completion_time_s_successes']:.2f} s")
        print("  failure reasons:", dict(reasons))
        by_tag = Counter(); by_tag_ok = Counter()
        sc = {s.id: s for s in gen.scenarios}
        for r in res:
            t = sc[r.scenario_id].tag.split(":")[0]
            by_tag[t] += 1; by_tag_ok[t] += r.success
        print("  by origin:", {t: f"{by_tag_ok[t]}/{by_tag[t]}" for t in by_tag})
    print(f"  measured wall-clock {run.wall_clock_s:.1f} s with {run.shards_total} shards, {run.cpu_count} CPUs")
    print(f"  stored in {db.conn.execute('PRAGMA database_list').fetchone()[2]}")
    if a.summary_out:
        Path(a.summary_out).write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
