"""Held-out seed guard: dev code paths must not be able to generate or simulate seeds >= 900000."""
import ast
from pathlib import Path

import pytest

from app.core.schemas import Scenario
from app.core.seeds import DEV_SEED_BASE, HELDOUT_SEED_BASE, HeldOutSeedError, check_seed, check_seeds
from app.scenarios.sweep import latin_hypercube

ROOT = Path(__file__).resolve().parents[2]
ALLOWED_DIRS = [ROOT / "backend" / "app" / "gate", ROOT / "backend" / "tests"]
ALLOWED_FILES = [ROOT / "backend" / "app" / "core" / "seeds.py"]


def scn(seed):
    return Scenario(id="x", mass_kg=0.2, friction=0.8, size_m=0.05, pos_offset_x=0, pos_offset_y=0,
                    sensor_noise_m=0.0, gripper_delay_steps=0, seed=seed)


def test_check_seed_rules():
    assert check_seed(DEV_SEED_BASE) == DEV_SEED_BASE
    assert check_seed(HELDOUT_SEED_BASE - 1) == HELDOUT_SEED_BASE - 1
    with pytest.raises(HeldOutSeedError):
        check_seed(HELDOUT_SEED_BASE)
    assert check_seed(HELDOUT_SEED_BASE, held_out=True) == HELDOUT_SEED_BASE
    with pytest.raises(HeldOutSeedError):  # the two sets never mix
        check_seed(5, held_out=True)
    with pytest.raises(HeldOutSeedError):
        check_seeds([1, 2, HELDOUT_SEED_BASE + 3])


def test_sweep_sampler_refuses_heldout_range():
    with pytest.raises(HeldOutSeedError):
        latin_hypercube(10, 1, seed_base=HELDOUT_SEED_BASE)
    with pytest.raises(HeldOutSeedError):
        latin_hypercube(10, 1, seed_base=HELDOUT_SEED_BASE - 5)  # would spill over the boundary


def test_simulator_refuses_heldout_seed_without_flag():
    pytest.importorskip("pybullet")
    from app.core.schemas import Policy
    from app.sim.pickplace import run_scenario

    with pytest.raises(HeldOutSeedError):
        run_scenario(Policy(), scn(HELDOUT_SEED_BASE + 1))


def _held_out_true_uses(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "held_out" and not (
            isinstance(node.value, ast.Constant) and node.value.value is False
        ):
            yield node.lineno


def test_only_the_gate_passes_held_out_flag():
    """Static scan of backend/app and scripts: `held_out=<anything but False>` is only allowed under app/gate/."""
    offenders = []
    for base in (ROOT / "backend" / "app", ROOT / "scripts"):
        for f in base.rglob("*.py"):
            if any(d in f.parents for d in ALLOWED_DIRS) or f in ALLOWED_FILES:
                continue
            offenders += [f"{f.relative_to(ROOT)}:{ln}" for ln in _held_out_true_uses(f)]
    # run_scenario/check_seed forward their own `held_out` parameter; forwarding is allowed only in these:
    forwarding_ok = {"backend/app/sim/pickplace.py", "backend/app/runner/base.py", "backend/app/runner/local.py",
                     "backend/app/scenarios/generator.py"}
    offenders = [o for o in offenders if o.split(":")[0].replace("\\", "/") not in forwarding_ok]
    assert not offenders, f"held_out flag used outside the gate: {offenders}"
