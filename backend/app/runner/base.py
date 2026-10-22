"""JobRunner interface and RunResult.

Integrity rules (they feed gate check G6):
- A shard counts as COMPLETED only if it exited cleanly AND returned exactly its scenarios (same ids, same order).
- A crashed / timed-out / short / malformed shard is FAILED or TIMEOUT. Its results are discarded, not partially used.
- Scenarios from non-completed shards are reported in `missing_scenario_ids`. They are never counted as passes or
  as failures. `complete` is True only if every shard completed.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict

from ..core.schemas import Policy, Result, Scenario, ShardResult
from ..core.seeds import check_seeds


class RunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runner_name: str  # "local" or "nebius"; the UI shows this badge
    shards: list[ShardResult]
    results: list[Result]  # only from COMPLETED shards, in scenario order
    missing_scenario_ids: list[str]
    shards_total: int
    shards_ok: int
    shards_failed: int
    wall_clock_s: float
    cpu_count: int | None = None
    image_build_id: str | None = None  # container image id/build id the runner executed in (env ROBOPROOF_IMAGE_ID); None if unknown
    complete: bool

    @classmethod
    def build(cls, runner_name: str, shards: list[ShardResult], scenario_ids_by_shard: list[list[str]],
              wall_clock_s: float, cpu_count: int | None = None, image_build_id: str | None = None) -> "RunResult":
        results: list[Result] = []
        missing: list[str] = []
        for sh, ids in zip(shards, scenario_ids_by_shard):
            if sh.complete:
                results.extend(sh.results)
            else:
                missing.extend(ids)
        ok = sum(1 for s in shards if s.complete)
        return cls(
            runner_name=runner_name, shards=shards, results=results, missing_scenario_ids=missing,
            shards_total=len(shards), shards_ok=ok, shards_failed=len(shards) - ok,
            wall_clock_s=wall_clock_s, cpu_count=cpu_count, image_build_id=image_build_id, complete=ok == len(shards),
        )

    def pass_rate(self) -> float | None:
        """Pass rate over scenarios that actually ran. None if nothing ran. Meaningless unless `complete`."""
        return sum(r.success for r in self.results) / len(self.results) if self.results else None


class JobRunner(ABC):
    name: str

    @abstractmethod
    def _run(self, policy: Policy, scenarios: list[Scenario], shards: int, held_out: bool) -> RunResult: ...

    def run(self, policy: Policy, scenarios: list[Scenario], shards: int = 10, held_out: bool = False) -> RunResult:
        """Run `scenarios` under `policy`, split into up to `shards` shards. Held-out seeds need held_out=True (gate only)."""
        if not scenarios:
            raise ValueError("no scenarios to run")
        if shards < 1:
            raise ValueError("shards must be >= 1")
        check_seeds((s.seed for s in scenarios), held_out)
        return self._run(policy, scenarios, min(shards, len(scenarios)), held_out)


def split_into_shards(scenarios: list[Scenario], shards: int) -> list[list[Scenario]]:
    """Contiguous, deterministic chunks whose sizes differ by at most one."""
    q, r = divmod(len(scenarios), shards)
    out, i = [], 0
    for k in range(shards):
        size = q + (1 if k < r else 0)
        out.append(scenarios[i:i + size])
        i += size
    return out
