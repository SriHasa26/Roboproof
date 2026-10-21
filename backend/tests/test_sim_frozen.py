"""Freeze tests: the simulator, parameter ranges and default policy must not change silently.

The fingerprint check needs no PyBullet. The golden-results check does (runs in the sim image).
"""
import json
from pathlib import Path

import pytest

from app.sim import freeze

FIXTURES = Path(__file__).parent / "fixtures"

MESSAGE = (
    "\n\nThe simulator, parameter bounds or default policy changed ({what}).\n"
    "That invalidates the experiment: baselines, patches and held-out comparisons were all measured against the\n"
    "frozen version (git tag 'sim-frozen'). If this change is deliberate, re-freeze on purpose with\n"
    "  python scripts/refreeze.py --i-understand-this-invalidates-results\n"
    "re-run the dev baseline and ceiling search, and record the reason in docs/SIM_FIDELITY.md.\n"
)


def test_fingerprint_matches_committed_hash():
    committed = {l.split()[0]: l.split()[1] for l in freeze.read_committed().splitlines() if l.strip()}
    current = freeze.components()
    changed = [k for k, v in current.items() if committed.get(k) != v]
    assert not changed and committed.get("freeze_hash") == freeze.freeze_hash(), MESSAGE.format(what=", ".join(changed) or "hash")


def test_golden_results_reproduce_exactly():
    pytest.importorskip("pybullet")
    from app.core.schemas import Policy, Scenario
    from app.sim.pickplace import run_scenario

    golden = json.loads((FIXTURES / "golden_results.json").read_text(encoding="utf-8"))
    assert len(golden) >= 5
    for g in golden:
        res = run_scenario(Policy(**g["policy"]), Scenario(**g["scenario"]))[0]
        assert res.model_dump(mode="json") == g["result"], MESSAGE.format(what=f"golden scenario {g['scenario']['id']}")
