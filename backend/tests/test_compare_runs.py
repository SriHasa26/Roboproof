"""scripts/compare_runs.py: per-scenario comparison of two result sets."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "compare_runs.py"
spec = importlib.util.spec_from_file_location("compare_runs", SCRIPT)
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)


def r(i, ok=True, reason=None, t=3.0, coll=False, seed=None):
    return {"scenario_id": f"s{i}", "seed": 1000 + i if seed is None else seed, "success": ok, "failure_reason": reason,
            "collision": coll, "completion_time_s": t, "final_place_error_m": 0.0, "max_slip_m": 0.0}


def index(rows):
    return {(x["scenario_id"], x["seed"]): x for x in rows}


def test_identical_sets():
    rows = [r(i) for i in range(5)]
    rep = cr.compare(index(rows), index(rows))
    assert rep["identical"] and rep["common"] == 5 and rep["mismatches"] == []


def test_outcome_reason_collision_and_time_mismatches_reported():
    a = [r(0), r(1), r(2, ok=False, reason="MISSED_GRASP"), r(3), r(4)]
    b = [r(0), r(1, ok=False, reason="TIMEOUT"), r(2, ok=False, reason="SLIPPED_ON_LIFT"), r(3, coll=True), r(4, t=3.5)]
    rep = cr.compare(index(a), index(b))
    by = {m["scenario_id"]: m["diffs"] for m in rep["mismatches"]}
    assert set(by) == {"s1", "s2", "s3", "s4"} and rep["outcome_mismatches"] == 1 and not rep["identical"]
    assert "success" in by["s1"] and by["s2"].keys() == {"failure_reason"} and by["s3"].keys() == {"collision"}
    assert by["s4"]["completion_time_s"][:2] == (3.0, 3.5)


def test_time_tolerance_and_seed_is_part_of_the_key():
    assert cr.compare(index([r(0, t=3.0)]), index([r(0, t=3.0000004)]))["identical"]
    rep = cr.compare(index([r(0)]), index([r(0, seed=999)]))  # same id, different seed = different scenario
    assert rep["only_in_a"] and rep["only_in_b"] and not rep["identical"]


def test_missing_scenarios_reported(tmp_path):
    rep = cr.compare(index([r(0), r(1)]), index([r(0)]))
    assert rep["only_in_a"] == [("s1", 1001)] and rep["only_in_b"] == []


def test_cli_exit_codes_and_both_file_formats(tmp_path, capsys, monkeypatch):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps({"runner_name": "local", "results": [r(0), r(1)]}))
    b.write_text(json.dumps([r(0), r(1)]))  # bare list
    monkeypatch.setattr("sys.argv", ["compare_runs.py", str(a), str(b)])
    assert cr.main() == 0 and "IDENTICAL" in capsys.readouterr().out
    b.write_text(json.dumps([r(0), r(1, ok=False, reason="TIMEOUT")]))
    assert cr.main() == 1 and "DIFFERENT" in capsys.readouterr().out
