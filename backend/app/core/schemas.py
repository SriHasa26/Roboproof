"""Pydantic v2 schemas shared by every stage."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .bounds import INT_POLICY_PARAMS, POLICY_BOUNDS, SCENARIO_BOUNDS


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Scenario(Strict):
    id: str
    mass_kg: float
    friction: float
    size_m: float
    pos_offset_x: float
    pos_offset_y: float
    sensor_noise_m: float
    gripper_delay_steps: int
    seed: int = Field(ge=0)
    tag: str = ""  # e.g. "llm", "sobol", "heldout"; informational only

    @model_validator(mode="after")
    def _bounds(self):
        for k, (lo, hi) in SCENARIO_BOUNDS.items():
            v = getattr(self, k)
            if not lo <= v <= hi:
                raise ValueError(f"{k}={v} outside [{lo}, {hi}]")
        return self


class FailureReason(str, Enum):
    DROPPED_IN_TRANSIT = "DROPPED_IN_TRANSIT"
    MISSED_GRASP = "MISSED_GRASP"
    SLIPPED_ON_LIFT = "SLIPPED_ON_LIFT"
    COLLISION = "COLLISION"
    PLACED_OUTSIDE_ZONE = "PLACED_OUTSIDE_ZONE"
    TIMEOUT = "TIMEOUT"


def _f(name: str) -> Field:
    lo, hi, d = POLICY_BOUNDS[name]
    if name in INT_POLICY_PARAMS:
        return Field(int(d), ge=int(lo), le=int(hi))
    return Field(d, ge=lo, le=hi)


class Policy(Strict):
    grip_force: float = _f("grip_force")
    approach_speed: float = _f("approach_speed")
    lift_height: float = _f("lift_height")
    lift_speed: float = _f("lift_speed")
    grasp_hold_steps: int = _f("grasp_hold_steps")
    place_slow_factor: float = _f("place_slow_factor")
    retry_count: int = _f("retry_count")


# The fixer may only touch these. approach_speed and place_slow_factor stay in Policy but are excluded because
# one-at-a-time sweeps measured no effect on pass rate (docs/SIM_FIDELITY.md).
PATCHABLE_PARAMS = ("grip_force", "grasp_hold_steps", "retry_count", "lift_speed", "lift_height")
MAX_PATCH_FIELDS = 5


class PolicyPatch(Strict):
    """Bounded diff over the five effective policy parameters.

    Unknown or excluded keys are rejected, values must be finite, at most MAX_PATCH_FIELDS fields.
    Out-of-range values are clamped to bounds by apply() (and reported).
    """

    changes: dict[str, float]
    justification: str = ""

    @field_validator("changes")
    @classmethod
    def _valid_changes(cls, v):
        if not v:
            raise ValueError("patch has no changes")
        unknown = set(v) - set(POLICY_BOUNDS)
        if unknown:
            raise ValueError(f"unknown policy parameters: {sorted(unknown)}")
        excluded = set(v) - set(PATCHABLE_PARAMS)
        if excluded:
            raise ValueError(
                f"parameters not patchable (measured no effect on pass rate): {sorted(excluded)}; "
                f"allowed: {list(PATCHABLE_PARAMS)}"
            )
        if len(v) > MAX_PATCH_FIELDS:
            raise ValueError(f"at most {MAX_PATCH_FIELDS} fields per patch")
        bad = [k for k, x in v.items() if not math.isfinite(x)]
        if bad:
            raise ValueError(f"non-finite values for: {bad}")
        return v

    def apply(self, policy: Policy) -> tuple[Policy, dict[str, bool]]:
        """Return (patched policy, {param: was_clamped})."""
        data = policy.model_dump()
        clamped: dict[str, bool] = {}
        for k, v in self.changes.items():
            lo, hi, _ = POLICY_BOUNDS[k]
            c = min(max(v, lo), hi)
            clamped[k] = c != v
            data[k] = int(round(c)) if k in INT_POLICY_PARAMS else float(c)
        return Policy(**data), clamped


class Result(Strict):
    scenario_id: str
    seed: int
    success: bool
    collision: bool
    completion_time_s: float
    final_place_error_m: float
    max_slip_m: float
    failure_reason: FailureReason | None = None
    trajectory_summary: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reason_iff_fail(self):
        if self.success and self.failure_reason is not None:
            raise ValueError("successful result must not have a failure_reason")
        if not self.success and self.failure_reason is None:
            raise ValueError("failed result needs a failure_reason")
        return self


class ShardResult(Strict):
    shard_id: str
    status: Literal["COMPLETED", "FAILED", "TIMEOUT", "MISSING"]
    runner: Literal["local", "nebius"]
    results: list[Result] = Field(default_factory=list)
    n_expected: int
    wall_clock_s: float | None = None
    error: str | None = None

    @property
    def complete(self) -> bool:
        return self.status == "COMPLETED" and len(self.results) == self.n_expected


class BinStat(Strict):
    axis: str
    lo: float
    hi: float
    n: int
    n_fail: int

    @property
    def fail_rate(self) -> float:
        return self.n_fail / self.n if self.n else 0.0


class EvidenceReport(Strict):
    n_scenarios: int
    n_fail: int
    pass_rate: float
    collision_rate: float
    mean_completion_time_s: float
    reason_counts: dict[str, int]
    axis_bins: list[BinStat]
    interactions: list[dict]  # computed in code; the LLM only interprets
    tree_rules: list[str] = Field(default_factory=list)


class Hypothesis(Strict):
    statement: str
    conditions: dict[str, list[float]] = Field(default_factory=dict)  # axis -> [lo, hi]
    prediction: str
    targeted_scenario_ids: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"


class GateCheck(Strict):
    id: Literal["G1", "G2", "G3", "G4", "G5", "G6"]
    name: str
    status: CheckStatus
    detail: str
    metrics: dict[str, float | int | str | None] = Field(default_factory=dict)


class Verdict(str, Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"


class GateReport(Strict):
    verdict: Verdict
    checks: list[GateCheck]
    regression_budget: int = 0
    heldout_target: float = 0.80


class Run(Strict):
    id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    mode: Literal["live", "recorded"] = "live"
    runner: Literal["local", "nebius"] = "local"
    baseline_policy: Policy = Field(default_factory=Policy)
    attempts: list[dict] = Field(default_factory=list)
    gate: GateReport | None = None
    status: Literal["PENDING", "RUNNING", "DONE", "ERROR"] = "PENDING"
    notes: str = ""
