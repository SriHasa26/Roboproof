"""Schema for the scenario generator's risky-region proposal (what the LLM is asked to return)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

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


# ---------------------------------------------------------------- lenient intake: partial acceptance + deterministic repair
REPAIR_TOLERANCE = 0.10  # values up to 10% of an axis's range outside its bounds are clamped in code; further out is invalid
MAX_REGIONS = 8


class RawProposal(BaseModel):
    """What the model's JSON is parsed into FIRST. Individual regions are triaged one by one by `triage`, so one bad region
    does not discard the others."""
    model_config = ConfigDict(extra="forbid")

    regions: list[dict[str, Any]] = Field(min_length=1, max_length=12)


@dataclass
class TriageResult:
    valid: list[Region] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)   # {"name", "reason"}
    clamped: list[dict] = field(default_factory=list)   # {"region", "axis", "end", "from", "to"}


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def repair_ranges(name: str, ranges: Any) -> tuple[Any, list[dict]]:
    """Clamp values slightly outside the frozen bounds into them (and log it). Does not fix lo > hi, wrong axes or wrong shapes."""
    if not isinstance(ranges, dict):
        return ranges, []
    out, log = {}, []
    for axis, rng in ranges.items():
        if axis in SCENARIO_BOUNDS and isinstance(rng, (list, tuple)) and len(rng) == 2 and all(_is_num(v) for v in rng):
            blo, bhi = SCENARIO_BOUNDS[axis]
            tol = REPAIR_TOLERANCE * (bhi - blo)
            lo, hi = float(rng[0]), float(rng[1])
            if lo < blo and blo - lo <= tol:
                log.append({"region": name, "axis": axis, "end": "lo", "from": lo, "to": blo})
                lo = float(blo)
            if hi > bhi and hi - bhi <= tol:
                log.append({"region": name, "axis": axis, "end": "hi", "from": hi, "to": bhi})
                hi = float(bhi)
            out[axis] = [lo, hi]
        else:
            out[axis] = rng
    return out, log


def _reason(e: Exception) -> str:
    if isinstance(e, ValidationError):
        errs = e.errors()
        msg = errs[0]["msg"] if errs else str(e)
        return msg.replace("Value error, ", "")
    return str(e)


def triage(raw_regions: list[dict]) -> TriageResult:
    """Validate each region on its own. Keep the valid ones, log every dropped region with its reason, log clamping.
    Needs at least one valid region to be useful (callers decide)."""
    res = TriageResult()
    for i, raw in enumerate(raw_regions):
        name = str(raw.get("name", f"region_{i}"))[:60] if isinstance(raw, dict) else f"region_{i}"
        if not isinstance(raw, dict):
            res.dropped.append({"name": name, "reason": "region is not a JSON object"})
            continue
        ranges, log = repair_ranges(name, raw.get("ranges"))
        try:
            region = Region.model_validate({**raw, "ranges": ranges})
        except (ValidationError, ValueError) as e:
            res.dropped.append({"name": name, "reason": _reason(e)})
            continue
        if len(res.valid) >= MAX_REGIONS:
            res.dropped.append({"name": name, "reason": f"beyond the {MAX_REGIONS}-region limit"})
            continue
        res.valid.append(region)
        res.clamped.extend(log)
    return res
