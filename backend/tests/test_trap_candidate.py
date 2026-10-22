"""Provisional scripted-trap candidate (see docs/SIM_FIDELITY.md, 'Scripted trap').

The ORIGINAL bar was: fix >= 80% of heavy-and-slippery failures AND regress >= 10 previously passing scenarios.
No searched patch met it (docs/trap_search_results.json, docs/trap_search_random_partial.json). This test therefore
checks the candidate against its own RECORDED numbers on dev set A, and states plainly what it does not show.
Sim image only (needs PyBullet). Dev seeds only.
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("pybullet")

from app.core.gate_config import GATE_HELDOUT_TARGET  # noqa: E402
from app.core.schemas import Policy, PolicyPatch  # noqa: E402
from app.runner.local import LocalRunner  # noqa: E402
from app.scenarios.sweep import latin_hypercube  # noqa: E402

FILE = Path(__file__).resolve().parents[1] / "app" / "gate" / "scripted_trap_candidate.json"


def test_candidate_is_labelled_and_valid():
    j = json.loads(FILE.read_text())
    assert j["label"] == "scripted example, not model output"
    assert "PROVISIONAL" in j["status"] and "Does NOT meet" in j["status"]
    PolicyPatch(changes=j["changes"])  # must be a legal patch (five effective parameters only)


def test_candidate_behaviour_on_dev_set_A_matches_record():
    j = json.loads(FILE.read_text())
    rec = j["measured_on_dev_sets"]["A"]
    scns = latin_hypercube(300, 11, seed_base=1000)  # dev set A
    patched = PolicyPatch(changes=j["changes"]).apply(Policy())[0]
    runner = LocalRunner()
    base = runner.run(Policy(), scns, shards=12)
    new = runner.run(patched, scns, shards=12)
    assert base.complete and new.complete
    b = {r.scenario_id: r for r in base.results}
    n = {r.scenario_id: r for r in new.results}
    targeted = [s.id for s in scns if s.mass_kg > 0.5 and s.friction < 0.4 and not b[s.id].success]
    passing = [s.id for s in scns if b[s.id].success]
    fixed = sum(n[i].success for i in targeted) / len(targeted)
    regressions = sum(not n[i].success for i in passing)
    overall = sum(r.success for r in new.results) / len(scns)

    assert len(targeted) == rec["targeted_n"] and len(passing) == rec["previously_passing"]
    assert fixed == pytest.approx(rec["fix_rate_targeted"]) and regressions == rec["regressions"]
    assert regressions >= 1                      # the user's weakest requirement: it does regress something
    assert fixed >= 0.70                         # fixes most targeted failures (but NOT >= 0.80 on set A)
    assert fixed < 0.80, "if this now fixes >= 80%, re-evaluate the trap bar in docs/SIM_FIDELITY.md"
    assert overall < GATE_HELDOUT_TARGET         # would still miss the held-out target: G5 red
