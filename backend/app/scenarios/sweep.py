"""Seeded Latin-hypercube sweep over the scenario space (numpy only).

Seed ranges are reserved so development never touches held-out data:
  DEV_SEED_BASE     = 1_000      development / tuning sweeps
  HELDOUT_SEED_BASE = 900_000    gate G5 only; never used during development
"""
from __future__ import annotations

import numpy as np

from ..core.bounds import SCENARIO_BOUNDS
from ..core.schemas import Scenario

DEV_SEED_BASE = 1_000
HELDOUT_SEED_BASE = 900_000
AXES = list(SCENARIO_BOUNDS)


def latin_hypercube(n: int, sweep_seed: int, tag: str = "lhs", seed_base: int = DEV_SEED_BASE) -> list[Scenario]:
    rng = np.random.default_rng(sweep_seed)
    d = len(AXES)
    u = np.empty((n, d))
    for j in range(d):
        u[:, j] = (rng.permutation(n) + rng.random(n)) / n
    out = []
    for i in range(n):
        vals = {}
        for j, ax in enumerate(AXES):
            lo, hi = SCENARIO_BOUNDS[ax]
            v = lo + u[i, j] * (hi - lo)
            vals[ax] = int(round(v)) if ax == "gripper_delay_steps" else float(v)
        out.append(Scenario(id=f"{tag}-{seed_base + i}", seed=seed_base + i, tag=tag, **vals))
    return out
