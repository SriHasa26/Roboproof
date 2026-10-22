"""Schema for the scenario generator's risky-region proposal (what the LLM is asked to return)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.bounds import SCENARIO_BOUNDS


MAX_AXES_PER_REGION = 3
MIN_VOLUME_FRACTION = 0.02  # a region must cover at least 2% of the frozen parameter space


class Region(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    rationale: str = Field(min_length=1, max_length=600)
    # axis -> [lo, hi]; axes not listed span their full frozen range. At most MAX_AXES_PER_REGION axes.
    ranges: dict[str, list[float]]
    # The rationale is the model's unchecked opinion. It is kept for the record only and must never be shown as fact.
    unverified: Literal[True] = True

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
        if len(v) > MAX_AXES_PER_REGION:
            raise ValueError(f"a region may constrain at most {MAX_AXES_PER_REGION} axes (got {len(v)}: {sorted(v)}); "
                             f"leave the others unconstrained")
        return v

    def volume_fraction(self) -> float:
        """Fraction of the frozen parameter space covered (product of the constrained axes' relative widths)."""
        frac = 1.0
        for axis, (lo, hi) in self.ranges.items():
            blo, bhi = SCENARIO_BOUNDS[axis]
            frac *= (hi - lo) / (bhi - blo)
        return frac

    @model_validator(mode="after")
    def _volume_floor(self):
        if self.volume_fraction() < MIN_VOLUME_FRACTION:
            raise ValueError(f"region '{self.name}' covers only {self.volume_fraction():.2%} of the parameter space; "
                             f"at least {MIN_VOLUME_FRACTION:.0%} is required, widen it")
        return self


class ScenarioProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regions: list[Region] = Field(min_length=1, max_length=8)
