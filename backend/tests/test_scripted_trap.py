"""The scripted trap (grip 80 + hold 60), finalized with its MEASURED behaviour on dev sets A and B.

It is "scripted example, not model output". The original bar (>= 80% fixed AND >= 10 regressions) was not met by any
searched patch; the user chose this patch anyway (option 1) and the bar was relaxed after the search (docs/SIM_FIDELITY.md).
These tests therefore assert the exact recorded numbers, not the old bar. Sim image only. Dev seeds only.
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("pybullet")

from app.core.gate_config import GATE_HELDOUT_TARGET  # noqa: E402
from app.core.schemas import Policy, PolicyPatch  # noqa: E402
from app.runner.local import LocalRunner  # noqa: E402
from app.scenarios.sweep import latin_hypercube  # noqa: E402

FILE = Path(__file__).resolve().parents[1] / "app" / "gate" / "scripted_trap.json"
SETS = {"A": dict(n=300, sweep_seed=11, seed_base=1000), "B": dict(n=300, sweep_seed=23, seed_base=50000)}


def test_trap_file_is_labelled_final_and_valid():
    j = json.loads(FILE.read_text())
    assert j["label"] == "scripted example, not model output"
    assert j["kind"] == "scripted_trap" and "FINAL" in j["status"] and "relaxed" in j["status"]
    assert j["changes"] == {"grip_force": 80.0, "grasp_hold_steps": 60}
    PolicyPatch(changes=j["changes"])


@pytest.mark.parametrize("name", ["A", "B"])
def test_trap_measured_numbers_match_record(name):
    j = json.loads(FILE.read_text())
    rec = j["measured_on_dev_sets"][name]
    scns = latin_hypercube(**SETS[name])
    patched = PolicyPatch(changes=j["changes"]).apply(Policy())[0]
    runner = LocalRunner()
    base, new = runner.run(Policy(), scns, shards=12), runner.run(patched, scns, shards=12)
    assert base.complete and new.complete
    b = {r.scenario_id: r for r in base.results}
    n = {r.scenario_id: r for r in new.results}
    targeted = [s.id for s in scns if s.mass_kg > 0.5 and s.friction < 0.4 and not b[s.id].success]
    passing = [s.id for s in scns if b[s.id].success]
    assert (len(targeted), len(passing)) == (rec["targeted_n"], rec["previously_passing"])
    assert sum(n[i].success for i in targeted) / len(targeted) == pytest.approx(rec["fix_rate_targeted"])
    assert sum(not n[i].success for i in passing) == rec["regressions"]
    assert sum(r.success for r in new.results) / len(scns) == pytest.approx(rec["pass"])
    # what the numbers mean: it regresses some scenarios and stays below the held-out target
    assert rec["regressions"] >= 8 and rec["pass"] < GATE_HELDOUT_TARGET
