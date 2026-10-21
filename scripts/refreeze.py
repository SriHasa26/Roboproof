"""Deliberately re-freeze the simulator: rewrites backend/app/sim/FROZEN_HASH.txt and the golden results.

Changing the simulator, parameter ranges or default policy invalidates every baseline and held-out
comparison made so far. Only run this after deciding that on purpose, and record why in docs/SIM_FIDELITY.md.

Usage: python scripts/refreeze.py --i-understand-this-invalidates-results
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.schemas import Policy, Scenario  # noqa: E402
from app.sim import freeze  # noqa: E402
from app.sim.pickplace import run_scenario  # noqa: E402

GOLDEN = ROOT / "backend" / "tests" / "fixtures" / "golden_results.json"
GOLDEN_SCENARIOS = [
    dict(id="g1", mass_kg=0.2, friction=0.8, size_m=0.05, pos_offset_x=0.0, pos_offset_y=0.0, sensor_noise_m=0.0, gripper_delay_steps=0, seed=1),
    dict(id="g2", mass_kg=0.9, friction=0.15, size_m=0.05, pos_offset_x=0.03, pos_offset_y=-0.02, sensor_noise_m=0.005, gripper_delay_steps=4, seed=2),
    dict(id="g3", mass_kg=0.4, friction=0.6, size_m=0.03, pos_offset_x=-0.05, pos_offset_y=0.04, sensor_noise_m=0.02, gripper_delay_steps=18, seed=3),
    dict(id="g4", mass_kg=0.6, friction=1.0, size_m=0.08, pos_offset_x=0.0, pos_offset_y=0.06, sensor_noise_m=0.03, gripper_delay_steps=10, seed=4),
    dict(id="g5", mass_kg=0.1, friction=0.3, size_m=0.06, pos_offset_x=0.07, pos_offset_y=0.0, sensor_noise_m=0.01, gripper_delay_steps=0, seed=5),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--i-understand-this-invalidates-results", action="store_true", required=True)
    ap.parse_args()
    golden = []
    for sd in GOLDEN_SCENARIOS:
        scn = Scenario(**sd)
        golden.append({"scenario": sd, "policy": Policy().model_dump(),
                       "result": run_scenario(Policy(), scn)[0].model_dump(mode="json")})
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(golden, indent=1), encoding="utf-8")
    freeze.HASH_FILE.write_text(freeze.render(), encoding="utf-8")
    print("re-frozen:\n" + freeze.render())


if __name__ == "__main__":
    main()
