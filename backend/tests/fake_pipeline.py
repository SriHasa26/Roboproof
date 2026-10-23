"""Stand-in for scripts/run_reliability.py in the live-service tests: same arguments, same artifact files, no real calls.

FAKE_MODE: ok (default) | nosummary (exit without a result) | hang (never finishes) ; FAKE_DELAY: seconds between stages.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--seeds", type=int, nargs="+", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()
mode, delay = os.environ.get("FAKE_MODE", "ok"), float(os.environ.get("FAKE_DELAY", "0.05"))
d = Path(a.out) / f"run_01_seed{a.seeds[0]}"
d.mkdir(parents=True, exist_ok=True)


def w(name, obj):
    (d / name).write_text(json.dumps(obj), encoding="utf-8")
    time.sleep(delay)


print("MODE: REHEARSAL (fake)")
print("pybullet build time: x")
print("leaked key check:", os.environ.get("NEBIUS_API_KEY", ""))  # the service must scrub this before it reaches a client
sys.stdout.flush()
w("LABEL.json", {"rehearsal": True})
w("analysis_set.json", {"source": "llm", "model": "fake/nano", "n_coverage": 3, "n_targeted": 2, "dropped_regions": []})
w("baseline_results.json", {"runner_name": "fake", "wall_clock_s": 0.1, "results": [{"success": True}, {"success": False}, {"success": True}]})
w("evidence.json", {"items": []})
w("hypotheses.json", [{"id": "H1"}, {"id": "H2"}])
if mode == "hang":
    time.sleep(600)
if mode == "nosummary":
    sys.exit(3)
checks = [{"id": f"G{i}", "name": f"check {i}", "status": "pass", "observed": {}, "threshold": {}, "details": ""} for i in range(1, 7)]
w("gate_report.json", {"report": {"verdict": "VERIFIED", "checks": checks}})
cand = {"index": 0, "applied": {"grip_force": 40.0}, "fixed": 4, "targeted": 5, "regressions": 0, "pass_rate": 0.9, "selected": True, "complete": True}
w("summary.json", {"verdict": "VERIFIED", "estimated_cost_usd": 0.03, "master_seed": a.seeds[0], "metrics": {}, "strict_zero_budget": {},
                   "attempts": [{"attempt": 1, "candidates": [cand], "selected_index": 0, "regression_budget": 3, "selection_rule": "fixed", "dev_stage_passed": True, "patched_policy": {}}]})
