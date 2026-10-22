"""Seed ranges and the held-out guard.

Dev seeds are below HELDOUT_SEED_BASE. Seeds at or above it are reserved for gate check G5 and must
never be generated or simulated by development code (generator, runner, analyst, fixer, search scripts).
The only code allowed to pass `held_out=True` is app/gate/ (enforced by a static scan in
tests/test_seed_guard.py, plus runtime checks in run_scenario, the sweep sampler, the generator and runners).
"""
from __future__ import annotations

from typing import Iterable

DEV_SEED_BASE = 1_000
HELDOUT_SEED_BASE = 900_000

# Three disjoint seed blocks, [start, end). See docs/SEEDS_AND_SETS.md.
#   dev:       sweeps, searches, baselines, analysis sets, tests (so far: 1000-1299, 3000-3023, 50000-50299)
#   rehearsal: end-to-end gate rehearsals; no dev sweep uses it; each run allocates a fresh sub-block (store/ledger.py)
#   held_out:  official verification only; gate-only; each sub-block can be used once, ever
BLOCKS: dict[str, tuple[int, int]] = {
    "dev": (DEV_SEED_BASE, 100_000),
    "rehearsal": (800_000, HELDOUT_SEED_BASE),
    "held_out": (HELDOUT_SEED_BASE, 10_000_000),
}


class HeldOutSeedError(RuntimeError):
    pass


def check_seed(seed: int, held_out: bool = False) -> int:
    """Return `seed` if allowed in this context, else raise HeldOutSeedError.

    held_out=False: seed must be a dev seed (< HELDOUT_SEED_BASE).
    held_out=True:  seed must be a held-out seed (>= HELDOUT_SEED_BASE), so the two sets never mix.
    """
    if not held_out and seed >= HELDOUT_SEED_BASE:
        raise HeldOutSeedError(
            f"seed {seed} is in the held-out range (>= {HELDOUT_SEED_BASE}); only the gate may use it (held_out=True)"
        )
    if held_out and seed < HELDOUT_SEED_BASE:
        raise HeldOutSeedError(f"seed {seed} is a dev seed; held_out=True requires seeds >= {HELDOUT_SEED_BASE}")
    return seed


def check_seeds(seeds: Iterable[int], held_out: bool = False) -> None:
    for s in seeds:
        check_seed(s, held_out)
