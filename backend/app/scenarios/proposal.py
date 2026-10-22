"""Schema for the scenario generator's risky-region proposal (what the LLM is asked to return)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.bounds import SCENARIO_BOUNDS


class Region(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    rationale: str = Field(min_length=1, max_length=600)
    # axis -> [lo, hi]; axes not listed span their full frozen range
    ranges: dict[str, list[float]]

    @field_validator("ranges")
    @classmethod
    def _within_bounds(cls, v):
        if not v:
            raise ValueError("region needs at least one parameter range")
        for axis, rng in v.items():
            if axis not in SCENARIO_BOUNDS:
                raise ValueError(f"unknown scenario parameter {axis!r}; allowed: {list(SCENARIO_BOUNDS)}")
            if len(rng) != 2:
                raise ValueError(f"{axis}: range must be [lo, hi]")
            lo, hi = rng
            blo, bhi = SCENARIO_BOUNDS[axis]
            if not (lo <= hi):
                raise ValueError(f"{axis}: lo {lo} > hi {hi}")
            if lo < blo or hi > bhi:
                raise ValueError(f"{axis}: [{lo}, {hi}] outside allowed [{blo}, {bhi}]")
        return v


class ScenarioProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regions: list[Region] = Field(min_length=1, max_length=8)
