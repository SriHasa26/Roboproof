"""P2 simulator tests. PyBullet is only installed in the simulator image (no Windows wheel for py3.13);
run with: scripts/dock.sh python -m pytest backend/tests/test_sim.py"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pybullet")

from app.core.schemas import FailureReason, Policy, PolicyPatch, Scenario  # noqa: E402
from app.scenarios.sweep import DEV_SEED_BASE, HELDOUT_SEED_BASE, latin_hypercube  # noqa: E402
from app.sim.pickplace import run_scenario  # noqa: E402
from app.sim.recorder import record_scenario  # noqa: E402

BASE = dict(id="t", mass_kg=0.2, friction=0.8, size_m=0.05, pos_offset_x=0.0, pos_offset_y=0.0,
            sensor_noise_m=0.0, gripper_delay_steps=0, seed=1)


def scn(**kw):
    return Scenario(**{**BASE, **kw})


def run(policy=None, **kw):
    return run_scenario(policy or Policy(), scn(**kw))[0]


def test_nominal_passes_and_metrics_present():
    r = run()
    assert r.success and not r.collision and r.failure_reason is None
    assert r.final_place_error_m < 0.01 and 1.0 < r.completion_time_s < 10


def test_same_seed_same_result_even_with_noise():
    kw = dict(sensor_noise_m=0.02, seed=42, mass_kg=0.7, friction=0.3, gripper_delay_steps=8)
    a, b = run(**kw), run(**kw)
    assert a == b


def test_same_result_across_fresh_processes():
    code = ("import sys; sys.path.insert(0,'backend');"
            "from app.core.schemas import *; from app.sim.pickplace import run_scenario;"
            "s=Scenario(id='t',mass_kg=0.7,friction=0.3,size_m=0.05,pos_offset_x=0.03,pos_offset_y=-0.02,"
            "sensor_noise_m=0.02,gripper_delay_steps=8,seed=42);"
            "print(run_scenario(Policy(), s)[0].model_dump_json())")
    root = Path(__file__).resolve().parents[2]
    outs = {subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True).stdout.strip().splitlines()[-1]
            for _ in range(2)}
    assert len(outs) == 1


def test_different_noise_seeds_can_differ():
    rs = {run(sensor_noise_m=0.03, seed=s).final_place_error_m for s in range(5, 10)}
    assert len(rs) > 1


def test_recording_does_not_change_result(tmp_path):
    s = scn(sensor_noise_m=0.01, seed=3)
    plain = run_scenario(Policy(), s)[0]
    rec, traj, gif = record_scenario(Policy(), s, tmp_path, gif=True)
    assert plain == rec
    data = json.loads(traj.read_text())
    assert data["frames"] and data["result"]["success"] == plain.success
    assert gif is not None and gif.stat().st_size > 1000


def test_heavy_slippery_fails_and_fix_direction_helps():
    r = run(mass_kg=0.9, friction=0.15)
    assert not r.success and r.failure_reason in (FailureReason.SLIPPED_ON_LIFT, FailureReason.MISSED_GRASP,
                                                  FailureReason.DROPPED_IN_TRANSIT)
    stronger, _ = PolicyPatch(changes={"grip_force": 60}).apply(Policy())
    assert run(stronger, mass_kg=0.9, friction=0.15).success


def test_high_delay_small_cube_fails_and_longer_hold_fixes():
    kw = dict(gripper_delay_steps=20, size_m=0.03)
    assert not run(**kw).success
    patched, _ = PolicyPatch(changes={"grasp_hold_steps": 80}).apply(Policy())
    assert run(patched, **kw).success


def test_low_lift_height_hits_wall():
    low, _ = PolicyPatch(changes={"lift_height": 0.05}).apply(Policy())
    r = run(low)
    assert not r.success and r.failure_reason == FailureReason.COLLISION and r.collision


def test_retry_recovers_from_noisy_blocked_descent():
    kw = dict(sensor_noise_m=0.03, size_m=0.08)
    fails = [s for s in range(20) if not run(seed=s, **kw).success]
    assert fails, "expected some noisy failures with no retries"
    retry, _ = PolicyPatch(changes={"retry_count": 3}).apply(Policy())
    fixed = [s for s in fails if run(retry, seed=s, **kw).success]
    assert len(fixed) >= len(fails) // 2


def test_dev_baseline_pass_rate_in_band_and_no_heldout_seeds():
    scns = latin_hypercube(60, sweep_seed=7)
    assert all(DEV_SEED_BASE <= s.seed < HELDOUT_SEED_BASE for s in scns)
    rate = sum(run_scenario(Policy(), s)[0].success for s in scns) / len(scns)
    assert 0.55 <= rate <= 0.80, rate
