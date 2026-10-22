"""Fixer (Nemotron reasoning model): proposes a bounded patch over the five tunable policy parameters.

No leakage by construction: the only feedback type it accepts is DevFeedback (analysis-set results of dev-stage checks
G1 to G4 and G6). That model has no field for G5 or for any verification-set number, and the prompt builder takes nothing else.
At most MAX_ATTEMPTS attempts per run. The interface returns a list so several candidates per attempt can be added later
(n_candidates); only n_candidates=1 is implemented.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import ValidationError

from ..core.bounds import POLICY_BOUNDS
from ..core.schemas import PATCHABLE_PARAMS, Policy
from ..llm.client import LLMClient
from ..llm.controls import FIXER_MAX_TOKENS
from .analyst import PARAM_DOCS
from .models import DevFeedback, FixerOutput, Hypothesis

MAX_ATTEMPTS = 3


class FixerExhausted(RuntimeError):
    pass


@dataclass
class FixerResult:
    output: FixerOutput            # exactly what the model proposed
    patched_policy: Policy         # after validation and clamping
    clamped: dict[str, bool]       # which proposed values had to be clamped to bounds
    attempt: int


def build_prompt(hypotheses: list[Hypothesis], policy: Policy, attempts: list[DevFeedback],
                 pass_rate_before: float) -> tuple[str, str]:
    system = (
        "You tune a robot pick-and-place controller by changing numeric parameters only. Propose ONE patch: a JSON object "
        "'changes' mapping parameter names to new values, within the stated min/max, using only these parameters: "
        + ", ".join(PATCHABLE_PARAMS) + ". Add a short 'rationale' and an 'expected_effect'. A good patch fixes the failing "
        "regions described by the hypotheses WITHOUT breaking scenarios that already pass, so prefer the smallest change that "
        "addresses the cause, and use earlier attempts' feedback if given. You do not decide pass or fail."
    )
    user = json.dumps({
        "tunable_policy_parameters": {k: {"doc": PARAM_DOCS[k], "min": POLICY_BOUNDS[k][0], "max": POLICY_BOUNDS[k][1],
                                           "current": getattr(policy, k)} for k in PATCHABLE_PARAMS},
        "baseline_pass_rate_on_analysis_scenarios": pass_rate_before,
        "hypotheses": [h.model_dump(exclude={"evidence_refs"}) for h in hypotheses],
        "previous_attempts": [a.model_dump() for a in attempts],
    }, separators=(",", ":"))
    return system, user


def propose(client: LLMClient, hypotheses: list[Hypothesis], policy: Policy, attempts: list[DevFeedback],
            pass_rate_before: float, n_candidates: int = 1) -> list[FixerResult]:
    if n_candidates != 1:
        raise NotImplementedError("only n_candidates=1 is implemented")
    if len(attempts) >= MAX_ATTEMPTS:
        raise FixerExhausted(f"at most {MAX_ATTEMPTS} attempts per run")
    system, user = build_prompt(hypotheses, policy, attempts, pass_rate_before)
    box: dict = {}

    def check(out: FixerOutput) -> None:
        try:
            patched, clamped = out.to_patch().apply(policy)  # unknown/excluded/non-finite keys raise here
        except ValidationError as e:
            raise ValueError(str(e)) from e
        if patched == policy:
            raise ValueError("the patch changes nothing (every value equals the current policy)")
        box["patched"], box["clamped"] = patched, clamped

    out = client.complete_json("fixer", "reasoning", system, user, FixerOutput, validator=check, max_tokens=FIXER_MAX_TOKENS)
    return [FixerResult(output=out, patched_policy=box["patched"], clamped=box["clamped"], attempt=len(attempts) + 1)]
