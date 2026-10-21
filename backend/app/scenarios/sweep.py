"""Seeded Latin-hypercube sweep over the scenario space (numpy only).

Seed ranges (core/seeds.py): dev seeds start at DEV_SEED_BASE; seeds >= HELDOUT_SEED_BASE are gate-only.
"""
from __future__ import annotations

import numpy as np

from ..core.bounds import SCENARIO_BOUNDS
from ..core.schemas import Scenario
from ..core.seeds import DEV_SEED_BASE, HELDOUT_SEED_BASE, check_seed  # noqa: F401  (re-exported)
AXES = list(SCENARIO_BOUNDS)


def latin_hypercube(n: int, sweep_seed: int, tag: str = "lhs", seed_base: int = DEV_SEED_BASE) -> list[Scenario]:
    check_seed(seed_base)
    check_seed(seed_base + n - 1)
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
