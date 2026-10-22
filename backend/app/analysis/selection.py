"""Deterministic candidate selection, written down before any v2 run. PURE CODE: the model never chooses.

Inputs are analysis-set measurements of each candidate (integers, so there is no float ambiguity):
  fixed       targeted failures that now pass            regressions   previously passing scenarios that now fail
  n_changed   parameters that differ from the current policy      grip_force   the candidate's grip force

Rule:
  1. Candidates within the regression budget (regressions <= budget) are eligible. Among them pick the highest `fixed`
     (all candidates share the same number of targets, so this is the highest targeted fix rate); ties: fewer changed parameters,
     then lower grip force, then lower candidate index.
  2. If none is within budget, pick the fewest regressions; ties: highest `fixed`, then fewer changed parameters, then lower grip
     force, then lower index. (That candidate will then be gated and will fail G4; that is the honest outcome.)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateEval:
    index: int
    fixed: int
    targeted: int
    regressions: int
    n_changed: int
    grip_force: float
    complete: bool = True  # the candidate's analysis-set run finished; incomplete candidates are never selected


def select_candidate(evals: list[CandidateEval], budget: int) -> int:
    """Return the `index` of the chosen candidate. Raises ValueError if there is no complete candidate."""
    usable = [e for e in evals if e.complete]
    if not usable:
        raise ValueError("no candidate has a complete evaluation")
    within = [e for e in usable if e.regressions <= budget]
    if within:
        return min(within, key=lambda e: (-e.fixed, e.n_changed, e.grip_force, e.index)).index
    return min(usable, key=lambda e: (e.regressions, -e.fixed, e.n_changed, e.grip_force, e.index)).index
