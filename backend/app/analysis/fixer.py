"""Fixer (Nemotron reasoning model): proposes SEVERAL bounded candidate patches per attempt over the five tunable parameters.

CODE (not the model) evaluates every candidate on the analysis set and picks one with a deterministic rule (analysis/selection.py);
only the selected candidate goes through the gate. The model sees, for earlier attempts, a table of every candidate it proposed with
its analysis-set metrics and which one was selected. No verification-set number can reach it: DevFeedback has no field for one, and
the prompt builder accepts nothing else. The prompt contains no recommended values: only parameter documentation and the measured
one-at-a-time effects from dev seeds. At most MAX_ATTEMPTS attempts per run.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from pydantic import ValidationError

from ..core.bounds import INT_POLICY_PARAMS, POLICY_BOUNDS
from ..core.schemas import PATCHABLE_PARAMS, Policy
from ..llm.client import LLMClient
from ..llm.controls import FIXER_MAX_TOKENS
from .analyst import PARAM_DOCS
from .models import DevFeedback, FixerCandidates, FixerOutput, Hypothesis

MAX_ATTEMPTS = 3
N_CANDIDATES = int(os.environ.get("FIXER_N_CANDIDATES", "4"))
DIVERSITY_SPREAD = 0.20  # largest-step candidate must exceed the smallest-step one by this fraction of a parameter's range

# Measured one parameter at a time on DEV seeds (dev sweep seed 7, 200 scenarios, default policy 70.0%): docs/SIM_FIDELITY.md.
# Effects are on ALL scenarios, not on the targeted failures, and they combine in ways not measured here.
ONE_AT_A_TIME_EFFECTS = [
    "retry_count 0 -> 3: overall pass rate 70.0% -> 81.0% (costs time: each retry re-perceives and re-descends)",
    "lift_speed 0.3 -> 0.1: 70.0% -> 79.0%;  lift_speed 0.3 -> 0.6: 70.0% -> 50.5%",
    "grip_force 15 -> 40: 70.0% -> 78.5%",
    "grasp_hold_steps 10 -> 60: 70.0% -> 77.5%",
    "lift_height 0.15 -> 0.08: 70.0% -> 45.0% (53 collisions with the 6 cm wall);  lift_height 0.15 -> 0.30: no measurable change",
]


class FixerExhausted(RuntimeError):
    pass


@dataclass
class Candidate:
    index: int
    output: FixerOutput            # exactly what the model proposed
    patched_policy: Policy         # after validation, clamping and integer rounding
    changed: list[str]             # parameters that differ from the current policy
    step: float                    # largest change as a fraction of that parameter's allowed range
    clamped: dict[str, bool]       # proposed values that had to be moved into bounds
    rounded: dict[str, list[float]] = field(default_factory=dict)  # integer parameters: [proposed, applied] when they differ


@dataclass
class CandidateSet:
    candidates: list[Candidate]
    dropped: list[dict]                 # candidates rejected by validation, with the reason
    diversity_violations: list[str]     # empty if the diversity requirements hold
    n_requested: int


def normalized_step(policy: Policy, patched: Policy) -> float:
    steps = [abs(getattr(patched, k) - getattr(policy, k)) / (POLICY_BOUNDS[k][1] - POLICY_BOUNDS[k][0]) for k in PATCHABLE_PARAMS]
    return max(steps)


def diversity_violations(cands: list[Candidate]) -> list[str]:
    """Requirements: a single-lever patch, a patch moving three or more levers, and a spread between the largest and the smallest step."""
    v = []
    if not any(len(c.changed) == 1 for c in cands):
        v.append("no single-lever candidate (exactly one parameter changed)")
    if not any(len(c.changed) >= 3 for c in cands):
        v.append("no candidate that moves three or more levers")
    if len(cands) >= 2 and max(c.step for c in cands) - min(c.step for c in cands) < DIVERSITY_SPREAD:
        v.append(f"all candidates take similar step sizes (largest minus smallest is below {DIVERSITY_SPREAD:.0%} of a parameter's range): "
                 "include one larger-step and one smaller-step candidate")
    return v


def process_candidates(out: FixerCandidates, policy: Policy, n_requested: int) -> tuple[list[Candidate], list[dict]]:
    """Validate and clamp each candidate on its own. Invalid, no-op and duplicate candidates are dropped with a reason."""
    cands: list[Candidate] = []
    dropped: list[dict] = []
    for i, o in enumerate(out.candidates):
        try:
            patched, clamped = o.to_patch().apply(policy)
        except ValidationError as e:
            dropped.append({"index": i, "reason": str(e.errors()[0]["msg"]).replace("Value error, ", "")})
            continue
        if patched == policy:
            dropped.append({"index": i, "reason": "changes nothing (every value equals the current policy)"})
            continue
        dup = next((c for c in cands if c.patched_policy == patched), None)
        if dup is not None:
            dropped.append({"index": i, "reason": f"duplicate of candidate {dup.index}"})
            continue
        if len(cands) >= n_requested:
            dropped.append({"index": i, "reason": f"more than the {n_requested} requested candidates"})
            continue
        rounded = {k: [float(o.changes[k]), float(getattr(patched, k))] for k in INT_POLICY_PARAMS
                   if k in o.changes and float(o.changes[k]) != float(getattr(patched, k))}
        changed = [k for k in PATCHABLE_PARAMS if getattr(patched, k) != getattr(policy, k)]
        cands.append(Candidate(index=len(cands), output=o, patched_policy=patched, changed=changed,
                               step=normalized_step(policy, patched), clamped=clamped, rounded=rounded))
    return cands, dropped


def build_prompt(hypotheses: list[Hypothesis], policy: Policy, attempts: list[DevFeedback], pass_rate_before: float,
                 n_candidates: int) -> tuple[str, str]:
    system = (
        f"You tune a robot pick-and-place controller by changing numeric parameters only. Propose EXACTLY {n_candidates} different candidate "
        "patches in one reply: {\"candidates\": [ {\"changes\": {...}, \"rationale\": \"...\", \"expected_effect\": \"...\"}, ... ]}. "
        "Each 'changes' maps parameter names to new values within the stated min/max, using only these parameters: "
        + ", ".join(PATCHABLE_PARAMS) + ". Integer parameters (grasp_hold_steps, retry_count) are rounded to integers. "
        "The candidates must be DIVERSE: (a) at least one candidate changes exactly one parameter; (b) at least one candidate changes "
        "three or more parameters; (c) at least one candidate makes a larger step on some parameter and at least one makes only smaller "
        "steps. Every candidate will be tested by code on the analysis scenarios and the best one under a fixed rule is kept, so use the "
        "candidates to explore different ideas, not small variations of one idea. A good patch fixes the failing regions in the hypotheses "
        "WITHOUT breaking scenarios that already pass. Use the table of earlier candidates, if given: it shows what each tested candidate "
        "achieved overall and per hypothesis (fixed/total), so you can see which hypotheses still fail. You do not decide pass or fail."
    )
    user = json.dumps({
        "tunable_policy_parameters": {k: {"doc": PARAM_DOCS[k], "min": POLICY_BOUNDS[k][0], "max": POLICY_BOUNDS[k][1],
                                           "current": getattr(policy, k)} for k in PATCHABLE_PARAMS},
        "measured_one_at_a_time_effects": ONE_AT_A_TIME_EFFECTS,
        "baseline_pass_rate_on_analysis_scenarios": pass_rate_before,
        "hypotheses": [h.model_dump(exclude={"evidence_refs"}) for h in hypotheses],
        "earlier_attempts": [a.model_dump() for a in attempts],
        "n_candidates": n_candidates,
    }, separators=(",", ":"))
    return system, user


def propose(client: LLMClient, hypotheses: list[Hypothesis], policy: Policy, attempts: list[DevFeedback], pass_rate_before: float,
            n_candidates: int | None = None) -> CandidateSet:
    n = N_CANDIDATES if n_candidates is None else n_candidates
    if n < 1:
        raise ValueError("n_candidates must be >= 1")
    if len(attempts) >= MAX_ATTEMPTS:
        raise FixerExhausted(f"at most {MAX_ATTEMPTS} attempts per run")
    system, user = build_prompt(hypotheses, policy, attempts, pass_rate_before, n)
    box: dict = {"parses": 0}

    def check(out: FixerCandidates) -> None:
        box["parses"] += 1
        cands, dropped = process_candidates(out, policy, n)
        if not cands:
            raise ValueError("no usable candidate. Reasons: " + "; ".join(f"candidate {d['index']}: {d['reason']}" for d in dropped))
        viol = diversity_violations(cands) if n >= 3 else []
        if viol and box["parses"] == 1:  # ask once; on the retry accept and record the violation instead of failing the run
            raise ValueError("candidates are not diverse enough: " + "; ".join(viol))
        box["set"] = CandidateSet(candidates=cands, dropped=dropped, diversity_violations=viol, n_requested=n)

    client.complete_json("fixer", "reasoning", system, user, FixerCandidates, validator=check, max_tokens=FIXER_MAX_TOKENS)
    return box["set"]
