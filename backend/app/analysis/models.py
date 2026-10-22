"""Models shared by the evidence computation, the analyst and the fixer."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.bounds import SCENARIO_BOUNDS
from ..core.schemas import PATCHABLE_PARAMS, PolicyPatch


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceItem(Strict):
    id: str  # E1, E2, ... stable for a given input
    kind: Literal["metrics", "reasons", "bin", "interaction", "tree_leaf"]
    title: str
    data: dict[str, Any]  # machine-readable; ALL numbers shown to users come from here


class EvidenceReport(Strict):
    n_scenarios: int
    items: list[EvidenceItem]

    def get(self, item_id: str) -> EvidenceItem | None:
        return next((i for i in self.items if i.id == item_id), None)

    def ids(self) -> set[str]:
        return {i.id for i in self.items}


class Lever(Strict):
    param: str
    direction: Literal["increase", "decrease"]

    @field_validator("param")
    @classmethod
    def _tunable(cls, v):
        if v not in PATCHABLE_PARAMS:
            raise ValueError(f"lever {v!r} is not a tunable parameter; allowed: {list(PATCHABLE_PARAMS)}")
        return v


class Hypothesis(Strict):
    id: str
    statement: str = Field(min_length=1)
    region: dict[str, list[float]]  # scenario axis -> [lo, hi]; inclusive
    mechanism: str = Field(min_length=1)
    levers: list[Lever] = Field(min_length=1)
    prediction: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)

    @field_validator("region")
    @classmethod
    def _region_ok(cls, v):
        if not v:
            raise ValueError("region needs at least one axis")
        for axis, rng in v.items():
            if axis not in SCENARIO_BOUNDS:
                raise ValueError(f"unknown scenario axis {axis!r}; allowed: {list(SCENARIO_BOUNDS)}")
            if len(rng) != 2 or rng[0] > rng[1]:
                raise ValueError(f"{axis}: range must be [lo, hi] with lo <= hi")
            lo, hi = SCENARIO_BOUNDS[axis]
            if rng[0] < lo or rng[1] > hi:
                raise ValueError(f"{axis}: [{rng[0]}, {rng[1]}] outside allowed [{lo}, {hi}]")
        return v


class HypothesisList(Strict):
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=5)


class CandidateRow(Strict):
    """One evaluated candidate, as shown to the fixer on the next attempt. ANALYSIS-SET numbers only."""

    index: int
    changes: dict[str, float]            # as applied (after clamping and integer rounding)
    n_changed: int
    fixed: int                           # targeted failures that now pass
    targeted: int
    fix_rate: float
    per_hypothesis_fixed: dict[str, str]  # hypothesis id -> "fixed/total" (which targets are still failing)
    regressions: int
    previously_passing: int
    budget: int
    pass_rate: float
    collision_rate: float
    selected: bool


class DevFeedback(Strict):
    """What the fixer may learn about an earlier attempt: every candidate evaluated on the ANALYSIS set, which one the selection rule
    chose, and the dev-stage checks (G1, G2, G6) of the chosen one. There is deliberately no field for G5 or any verification-set number."""

    attempt: int
    candidates: list[CandidateRow]
    selected_index: int
    g1_deterministic: bool | None
    g2_all_reproduced: bool | None
    g3_threshold: float
    g4_budget: int
    g6_complete: bool
    analysis_pass_rate_before: float
    note: str = ""


class FixerOutput(Strict):
    changes: dict[str, float]
    rationale: str = Field(min_length=1)
    expected_effect: str = Field(min_length=1)

    def to_patch(self) -> PolicyPatch:
        return PolicyPatch(changes=self.changes, justification=self.rationale)


class FixerCandidates(Strict):
    candidates: list[FixerOutput] = Field(min_length=1, max_length=8)
