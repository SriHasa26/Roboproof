"""Compare two run result files scenario by scenario (id + seed): outcome, failure reason, collision, completion time.

Intended use: LocalRunner vs NebiusJobRunner on the same scenarios and policy (P5), but it works on any two result files.
Accepted formats: a JSON object with a "results" list (RunResult dump, recorded baseline_results.json) or a bare list of Results.

Usage: python scripts/compare_runs.py A.json B.json [--time-tol 1e-6] [--max-print 20]
Exit code 0 if every scenario matches, 1 otherwise.
"""
import argparse
import json
import sys
from pathlib import Path


def load(path: str) -> tuple[dict, dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    results = data["results"] if isinstance(data, dict) else data
    meta = {k: data.get(k) for k in ("runner_name", "image_build_id", "wall_clock_s", "cpu_count")} if isinstance(data, dict) else {}
    return {(r["scenario_id"], r["seed"]): r for r in results}, meta


def compare(a: dict, b: dict, time_tol: float = 1e-6) -> dict:
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    mismatches = []
    for key in sorted(set(a) & set(b)):
        x, y = a[key], b[key]
        diffs = {}
        for f in ("success", "failure_reason", "collision"):
            if x.get(f) != y.get(f):
                diffs[f] = (x.get(f), y.get(f))
        dt = abs(x["completion_time_s"] - y["completion_time_s"])
        if dt > time_tol:
            diffs["completion_time_s"] = (x["completion_time_s"], y["completion_time_s"], f"diff {dt:.6f}")
        if diffs:
            mismatches.append({"scenario_id": key[0], "seed": key[1], "diffs": diffs})
    common = len(set(a) & set(b))
    return {"n_a": len(a), "n_b": len(b), "common": common, "only_in_a": only_a, "only_in_b": only_b, "mismatches": mismatches,
            "outcome_mismatches": sum("success" in m["diffs"] for m in mismatches), "identical": not (only_a or only_b or mismatches)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--time-tol", type=float, default=1e-6)
    ap.add_argument("--max-print", type=int, default=20)
    args = ap.parse_args()
    (ra, ma), (rb, mb) = load(args.a), load(args.b)
    rep = compare(ra, rb, args.time_tol)
    print(f"A: {args.a}  {ma}\nB: {args.b}  {mb}")
    print(f"scenarios: A={rep['n_a']} B={rep['n_b']} common={rep['common']}; only in A: {len(rep['only_in_a'])}, only in B: {len(rep['only_in_b'])}")
    print(f"mismatching scenarios: {len(rep['mismatches'])} (outcome differs in {rep['outcome_mismatches']}), time tolerance {args.time_tol}")
    for m in rep["mismatches"][: args.max_print]:
        print(f"  {m['scenario_id']} seed={m['seed']}: {m['diffs']}")
    if len(rep["mismatches"]) > args.max_print:
        print(f"  ... and {len(rep['mismatches']) - args.max_print} more")
    print("RESULT:", "IDENTICAL" if rep["identical"] else "DIFFERENT")
    return 0 if rep["identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
