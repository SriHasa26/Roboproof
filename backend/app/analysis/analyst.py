"""Failure analyst (Nemotron reasoning model).

The model interprets evidence computed in code; it must not invent numbers. Code enforces that:
- every hypothesis cites existing evidence ids,
- its region matches at least MIN_REGION_SUPPORT analysis-set scenarios,
- its levers are among the five tunable policy parameters (schema check),
- hypothesis ids are unique.
A violation is fed back to the model once; a second violation fails loudly (LLMValidationError).
Targeted failures are chosen by code: baseline failures inside any hypothesis region.
Numbers shown to users must be looked up from the EvidenceReport by id, never from model text.
"""
from __future__ import annotations

import json

from ..core.bounds import POLICY_BOUNDS, SCENARIO_BOUNDS
from ..core.schemas import PATCHABLE_PARAMS, Policy, Result, Scenario
from ..llm.client import LLMClient
from ..llm.controls import ANALYST_MAX_TOKENS
from .evidence import scenarios_in_region
from .models import EvidenceReport, Hypothesis, HypothesisList

MIN_REGION_SUPPORT = 10

PARAM_DOCS = {
    "grip_force": "Force limit (N) of each finger motor while closing; the squeeze that holds the cube by friction.",
    "grasp_hold_steps": "Physics steps (240 per second) the gripper waits after commanding close before it starts lifting. "
                        "The gripper command is delayed by the scenario's gripper_delay_steps.",
    "retry_count": "Extra grasp attempts allowed when the fingers land on the cube or no object is detected after lifting. "
                   "Each retry re-perceives the cube with fresh sensor noise and costs time.",
    "lift_speed": "Vertical lift speed (m/s); faster lifts add inertial load on the grasp.",
    "lift_height": "How far (m) the palm rises above the grasp height. A low wall (6 cm tall) lies between the pick and "
                   "place positions, so too little lift can hit it.",
}
REASON_DOCS = {
    "MISSED_GRASP": "the cube never left the table (or fingers landed on it and no retry was left)",
    "SLIPPED_ON_LIFT": "the cube slid in the grasp by more than 3 cm during the lift",
    "DROPPED_IN_TRANSIT": "the cube slid out during transit or lowering",
    "COLLISION": "the cube or gripper hit the wall, or the cube was shoved sideways before the grasp",
    "PLACED_OUTSIDE_ZONE": "the cube was released but ended outside the target zone",
    "TIMEOUT": "the episode exceeded 25 s of simulated time",
}


def build_prompt(evidence: EvidenceReport, policy: Policy) -> tuple[str, str]:
    system = (
        "You are a robotics test analyst. You are given EVIDENCE computed by code from simulated pick-and-place runs of a "
        "fixed controller. Explain WHY it fails as a few testable hypotheses. Rules: (1) cite evidence ids (like E7) in "
        "evidence_refs for every claim; use only ids that appear below. (2) Do NOT state statistics or counts in your own "
        "words: refer to evidence by id, because a person will see the numbers from the evidence table, not from you. "
        "(3) region is a machine-checkable predicate: scenario axes with [lo, hi] inside the allowed bounds. "
        "(4) levers may only be these tunable parameters: " + ", ".join(PATCHABLE_PARAMS) + ". "
        "(5) prediction must be testable, for example which failures should disappear if a lever moves. "
        "Return between 1 and 4 hypotheses with ids H1, H2, ... You do not decide pass or fail."
    )
    user = json.dumps({
        "scenario_axes_bounds": {a: list(b) for a, b in SCENARIO_BOUNDS.items()},
        "tunable_policy_parameters": {k: {"doc": PARAM_DOCS[k], "min": POLICY_BOUNDS[k][0], "max": POLICY_BOUNDS[k][1],
                                           "current": getattr(policy, k)} for k in PATCHABLE_PARAMS},
        "failure_reason_codes": REASON_DOCS,
        "evidence": [{"id": i.id, "kind": i.kind, "title": i.title, "data": i.data} for i in evidence.items],
    }, separators=(",", ":"))
    return system, user


def ground(hyps: HypothesisList, evidence: EvidenceReport, scenarios: list[Scenario]) -> None:
    """Code-side grounding check. Raises ValueError (fed back to the model) on the first problem."""
    ids = evidence.ids()
    seen: set[str] = set()
    for h in hyps.hypotheses:
        if h.id in seen:
            raise ValueError(f"duplicate hypothesis id {h.id}")
        seen.add(h.id)
        unknown = [r for r in h.evidence_refs if r not in ids]
        if unknown:
            raise ValueError(f"{h.id}: evidence_refs {unknown} do not exist; valid ids are {sorted(ids, key=lambda x: int(x[1:]))[:3]}... (see the evidence list)")
        support = len(scenarios_in_region(h.region, scenarios))
        if support < MIN_REGION_SUPPORT:
            raise ValueError(f"{h.id}: region matches only {support} analysis-set scenarios; at least {MIN_REGION_SUPPORT} required, widen it")


def analyze(client: LLMClient, evidence: EvidenceReport, scenarios: list[Scenario], policy: Policy) -> list[Hypothesis]:
    system, user = build_prompt(evidence, policy)
    out = client.complete_json("analyst", "reasoning", system, user, HypothesisList,
                               validator=lambda h: ground(h, evidence, scenarios), max_tokens=ANALYST_MAX_TOKENS)
    return out.hypotheses


def targeted_failures(hyps: list[Hypothesis], scenarios: list[Scenario], results: list[Result]) -> dict:
    """Baseline failures inside any hypothesis region (chosen by code). Returns per-hypothesis ids and the sorted union."""
    failed = {r.scenario_id for r in results if not r.success}
    by_h = {h.id: sorted(s.id for s in scenarios_in_region(h.region, scenarios) if s.id in failed) for h in hyps}
    return {"by_hypothesis": by_h, "all": sorted({i for ids in by_h.values() for i in ids})}
