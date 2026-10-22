"""Scenario generator: LLM proposes risky regions, CODE guarantees coverage.

Final list = Latin-hypercube coverage sweep over the whole space (default 60%) + samples drawn from the
proposed regions (default 40%). Every scenario gets a deterministic dev seed; the list is a pure function of
(n, master_seed, mix, seed_base, proposal).

PENDING_KEY: the LLM path has only been exercised with a mocked client. Without a key the generator uses a
hand-written FIXTURE proposal, and the output says source="fixture" so it can never pass for model output.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict

from ..core.bounds import SCENARIO_BOUNDS
from ..core.config import Settings
from ..core.schemas import Scenario
from ..core.seeds import DEV_SEED_BASE, check_seed
import time

from ..llm.client import LLMBudgetExceeded, LLMClient, LLMTransportError, LLMValidationError
from ..llm.controls import (GENERATOR_EXTRA, GENERATOR_FALLBACK_MAX_TOKENS, GENERATOR_FALLBACK_TIMEOUT_S, GENERATOR_MAX_TOKENS,
                            GENERATOR_TIMEOUT_S)
from .proposal import RawProposal, ScenarioProposal, triage
from .sweep import AXES, latin_hypercube

log = logging.getLogger(__name__)

TASK_DESCRIPTION = (
    "A simulated parallel-jaw gripper picks up a cube from a table and places it in a circular target zone "
    "30 cm away, passing over a 6 cm low wall. The policy is a fixed controller with a few tunable numbers."
)
AXIS_DOCS = {
    "mass_kg": "cube mass in kg",
    "friction": "contact friction coefficient of the cube",
    "size_m": "cube edge length in metres",
    "pos_offset_x": "cube x offset from nominal position, metres",
    "pos_offset_y": "cube y offset from nominal position, metres",
    "sensor_noise_m": "std of Gaussian noise on the perceived cube position, metres",
    "gripper_delay_steps": "gripper actuation latency in 240 Hz physics steps (integer)",
}


class ScenarioGenError(RuntimeError):
    pass


class GeneratedScenarios(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenarios: list[Scenario]
    # who produced the risky regions; never conflate them. "coverage_only_fallback": every model failed, so the whole set is code-made coverage.
    source: Literal["llm", "fixture", "coverage_only_fallback"]
    model: str | None = None            # the model whose proposal was used (None for fixture / coverage-only)
    proposal: ScenarioProposal | None
    dropped_regions: list[dict] = []    # regions rejected by validation, with the reason
    clamped_values: list[dict] = []     # values moved into bounds by code (within 10% of the axis range)
    generator_trail: list[dict] = []    # every model attempted, in order: outcome, seconds, error
    master_seed: int
    n_coverage: int
    n_targeted: int


def build_prompt() -> tuple[str, str]:
    system = (
        "You are a test engineer for a robot pick-and-place policy. Propose RISKY regions of the scenario "
        "parameter space where the policy is most likely to fail, so they can be tested. You do not decide "
        "pass or fail and you do not know the results. Use only the listed parameters and stay inside their bounds."
    )
    params = {a: {"doc": AXIS_DOCS[a], "min": SCENARIO_BOUNDS[a][0], "max": SCENARIO_BOUNDS[a][1]} for a in AXES}
    user = json.dumps({
        "task": TASK_DESCRIPTION,
        "scenario_parameters": params,
        "request": "Return 3 to 6 regions. Each: a short name, a one-sentence physical rationale, and ranges "
                   "[lo, hi] for the parameters that define the region (omitted parameters span their full range).",
        "valid_parameter_names": AXES,
        "rules": [
            "In 'ranges' use ONLY the names in valid_parameter_names as keys. Nothing else is a valid key (the robot's own control settings are NOT scenario parameters).",
            "Constrain AT MOST 3 parameters per region; leave all others out.",
            "Each range is [lo, hi] with lo <= hi, inside that parameter's min and max.",
            "Each constrained range should span at least 30% of that parameter's min-max width, so that the region covers at least 2% of the "
            "whole parameter space (the product of the constrained parameters' relative widths). Do not use tiny ranges.",
            "Your rationale is treated as an unverified opinion and is only a hint for people reading the test plan.",
        ],
    }, indent=1)
    return system, user


class ScenarioGenerator:
    def __init__(self, llm: LLMClient | None = None, fixture_path: str | Path | None = None):
        self.llm = llm
        self.fixture_path = Path(fixture_path) if fixture_path else None

    @classmethod
    def from_settings(cls, settings: Settings, fixture_path: str | Path | None = None) -> "ScenarioGenerator":
        """Use the real LLM when configured; otherwise the labelled fixture (never silently mixed)."""
        if settings.api_key and settings.model_fast:
            return cls(llm=LLMClient(settings), fixture_path=None)
        log.warning("No Nebius key/model configured: scenario regions come from a FIXTURE, not a model (PENDING_KEY)")
        return cls(llm=None, fixture_path=fixture_path)

    def _attempt(self, model_id: str, label: str, max_tokens: int, timeout_s: float, trail: list[dict]):
        """One model, with validation + one retry. Returns a TriageResult with >= 1 valid region, or None (and a trail entry)."""
        system, user = build_prompt()
        t0 = time.perf_counter()
        entry = {"stage": label, "model": model_id}

        def need_valid(raw: RawProposal) -> None:
            tri = triage(raw.regions)
            if not tri.valid:
                raise ValueError("no region is valid, so nothing can be used. Reasons: " + "; ".join(f"{d['name']}: {d['reason']}" for d in tri.dropped))

        try:
            raw = self.llm.complete_json("scenario_generation", "fast", system, user, RawProposal, validator=need_valid, model=model_id,
                                         transport_retries=0, max_tokens=max_tokens, timeout=timeout_s, **GENERATOR_EXTRA)
        except LLMBudgetExceeded:
            raise  # a budget stop is loud, not a reason to fall back
        except LLMTransportError as e:
            trail.append({**entry, "outcome": "transport_error_or_timeout", "seconds": round(time.perf_counter() - t0, 2), "error": str(e)[:200]})
            return None
        except LLMValidationError as e:
            trail.append({**entry, "outcome": "validation_failed_after_retry", "seconds": round(time.perf_counter() - t0, 2), "error": str(e)[:300]})
            return None
        tri = triage(raw.regions)
        trail.append({**entry, "outcome": "ok", "seconds": round(time.perf_counter() - t0, 2), "regions_valid": len(tri.valid),
                      "regions_dropped": len(tri.dropped)})
        return tri

    def propose(self) -> tuple[ScenarioProposal | None, str, str | None, list[dict], list[dict], list[dict]]:
        """Returns (proposal, source, model, dropped, clamped, trail). Chain: primary fast model (thinking off) -> second Nemotron model
        (NEBIUS_MODEL_FALLBACK) -> None, which the caller turns into a coverage-only set labelled source='coverage_only_fallback'."""
        trail: list[dict] = []
        if self.llm is not None:
            st = self.llm.settings
            chain = [("primary", st.model_fast, GENERATOR_MAX_TOKENS, GENERATOR_TIMEOUT_S)]
            if st.model_fallback and st.model_fallback != st.model_fast:
                chain.append(("fallback_model", st.model_fallback, GENERATOR_FALLBACK_MAX_TOKENS, GENERATOR_FALLBACK_TIMEOUT_S))
            if not st.model_fast:
                from ..core.config import ConfigError
                raise ConfigError("NEBIUS_MODEL_FAST is not set; run scripts/list_models.py")
            for label, model_id, mx, to in chain:
                tri = self._attempt(model_id, label, mx, to, trail)
                if tri is not None:
                    return ScenarioProposal(regions=tri.valid), "llm", model_id, tri.dropped, tri.clamped, trail
            trail.append({"stage": "coverage_only_fallback", "model": None, "outcome": "all models failed; using code-made coverage only"})
            return None, "coverage_only_fallback", None, [], [], trail
        if self.fixture_path is None:
            raise ScenarioGenError("no LLM client and no fixture proposal configured")
        raw = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        return ScenarioProposal.model_validate(raw["proposal"]), "fixture", None, [], [], trail

    def generate(self, n: int, master_seed: int, targeted_fraction: float = 0.4,
                 seed_base: int = DEV_SEED_BASE, held_out: bool = False) -> GeneratedScenarios:
        if n < 1 or not 0.0 <= targeted_fraction <= 1.0:
            raise ValueError("need n >= 1 and 0 <= targeted_fraction <= 1")
        check_seed(seed_base, held_out)
        check_seed(seed_base + n - 1, held_out)
        n_tgt = round(n * targeted_fraction)
        n_cov = n - n_tgt
        proposal, source, model, dropped, clamped, trail = None, "fixture", None, [], [], []
        if n_tgt > 0:
            proposal, source, model, dropped, clamped, trail = self.propose()
            if proposal is None:  # coverage-only fallback: the whole set is code-made coverage
                n_tgt, n_cov = 0, n

        scenarios: list[Scenario] = []
        if n_cov:
            scenarios += latin_hypercube(n_cov, master_seed, tag="cov", seed_base=seed_base, held_out=held_out)
        if n_tgt:
            rng = np.random.default_rng([master_seed, 1])
            regions = proposal.regions
            for j in range(n_tgt):
                region = regions[j % len(regions)]
                vals = {}
                for ax in AXES:
                    lo, hi = region.ranges.get(ax, list(SCENARIO_BOUNDS[ax]))
                    v = rng.uniform(lo, hi)
                    vals[ax] = int(round(v)) if ax == "gripper_delay_steps" else float(v)
                seed = seed_base + n_cov + j
                scenarios.append(Scenario(id=f"tgt-{seed}", seed=seed, tag=f"tgt:{region.name}", **vals))
        return GeneratedScenarios(scenarios=scenarios, source=source, model=model, proposal=proposal, dropped_regions=dropped, clamped_values=clamped,
                                  generator_trail=trail, master_seed=master_seed, n_coverage=n_cov, n_targeted=n_tgt)
