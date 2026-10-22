"""Proof-of-Robustness Gate thresholds. Derived from the dev-seed ceiling search (docs/CEILING_SEARCH.md), not guessed.

Evidence (dev sets only; 71 policies searched over the five patchable parameters, 25,500 simulations):
  default policy pass rate     72.0% (set A) / 71.7% (set B)
  best policy found            96.7% (set A, selected on) / 98.0% (set B, cross-check)
  median of searched policies  ~90% ; 34 of 71 reached >= 90%, 28 of 71 reached >= 95%
So a good fix can plausibly reach ~97%, and the target sits ~7 points below the best found: demanding, but with margin.
Values can be overridden by environment variables for experiments, but the defaults below are the frozen ones.
Held-out seeds were not used to choose any of these numbers.
"""
from __future__ import annotations

import os

# G5: patched policy's held-out pass rate must be >= this point value ...
GATE_HELDOUT_TARGET = float(os.environ.get("GATE_HELDOUT_TARGET", "0.90"))
# ... and must beat the unpatched policy's held-out pass rate on the same set by at least this absolute amount.
GATE_MIN_IMPROVEMENT = float(os.environ.get("GATE_MIN_IMPROVEMENT", "0.10"))
# G5 also requires: Wilson 95% lower bound of the patched held-out pass rate > unpatched held-out point estimate.
# Planned size of the fresh held-out set (Wilson half-width at p=0.9 is about 0.03 for n=400).
GATE_HELDOUT_SIZE = int(os.environ.get("GATE_HELDOUT_SIZE", "400"))
# G3: at least this fraction of the targeted failures must now pass. Set before the rehearsal and not tuned to suit
# the scripted trap.
GATE_TARGET_FIX_RATE = float(os.environ.get("GATE_TARGET_FIX_RATE", "0.70"))
# G4: budget = floor(GATE_REGRESSION_BUDGET_FRAC x previously_passing) analysis-set scenarios may regress (0.02 of 216 is 4).
# A zero budget would reject even the best-found patch (3 regressions), making VERIFIED unreachable. The strict
# zero-budget result is always computed and shown next to the budgeted one.
GATE_REGRESSION_BUDGET_FRAC = float(os.environ.get("GATE_REGRESSION_BUDGET_FRAC", "0.02"))
# G1: how many baseline scenarios are re-run (evenly spaced over the analysis set) to prove determinism.
GATE_DETERMINISM_SAMPLE = int(os.environ.get("GATE_DETERMINISM_SAMPLE", "30"))
