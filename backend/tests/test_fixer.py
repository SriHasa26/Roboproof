"""Fixer tests with a mocked LLM: candidate generation, validation, diversity, prompt contents, no leakage."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.analysis.fixer import (DIVERSITY_SPREAD, MAX_ATTEMPTS, N_CANDIDATES, ONE_AT_A_TIME_EFFECTS, FixerExhausted, build_prompt,
                                diversity_violations, process_candidates, propose)
from app.analysis.models import CandidateRow, DevFeedback, FixerCandidates, Hypothesis
from app.core.config import load_settings
from app.core.schemas import Policy
from app.llm import controls
from app.llm.client import LLMClient, LLMValidationError

ROOT = Path(__file__).resolve().parents[2]


class Fake:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.replies.pop(0)))],
                               usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))


def client(replies):
    s = load_settings({"NEBIUS_API_KEY": "k", "NEBIUS_MODEL_FAST": "f", "NEBIUS_MODEL_REASONING": "r"})
    fake = Fake(replies)
    return LLMClient(s, fake), fake


H = [Hypothesis.model_validate({
    "id": "H1", "statement": "Heavy slippery cubes slip.", "region": {"mass_kg": [0.6, 1.0], "friction": [0.1, 0.4]},
    "mechanism": "weak grip", "levers": [{"param": "grip_force", "direction": "increase"}],
    "prediction": "fewer slips with more force", "evidence_refs": ["E38"]})]


def cand(changes, why="because", eff="fewer failures"):
    return {"changes": changes, "rationale": why, "expected_effect": eff}


def reply(*cs):
    return json.dumps({"candidates": list(cs)})


DIVERSE = [cand({"grip_force": 25}),                                                    # single lever, small step
           cand({"grip_force": 60, "grasp_hold_steps": 70, "retry_count": 2}),          # three levers, large step
           cand({"lift_speed": 0.2, "retry_count": 1}),
           cand({"grip_force": 40, "grasp_hold_steps": 30})]


def row(index, selected, fixed=10, **kw):
    d = dict(index=index, changes={"grip_force": 30.0}, n_changed=1, fixed=fixed, targeted=40, fix_rate=fixed / 40, per_hypothesis_fixed={"H1": f"{fixed}/40"},
             regressions=1, previously_passing=150, budget=3, pass_rate=0.8, collision_rate=0.0, selected=selected)
    d.update(kw)
    return CandidateRow(**d)


def fb(n=1, **over):
    d = dict(attempt=n, candidates=[row(0, False, 8), row(1, True, 20, changes={"grip_force": 60.0, "grasp_hold_steps": 70.0}, n_changed=2)],
             selected_index=1, g1_deterministic=True, g2_all_reproduced=True, g3_threshold=0.7, g4_budget=3, g6_complete=True,
             analysis_pass_rate_before=0.72)
    d.update(over)
    return DevFeedback(**d)


# ------------------------------------------------------------------ candidate generation and validation
def test_default_is_four_candidates_and_max_three_attempts():
    assert N_CANDIDATES == 4 and MAX_ATTEMPTS == 3


def test_diverse_candidates_are_accepted_in_one_call_with_the_reasoning_model():
    c, fake = client([reply(*DIVERSE)])
    cs = propose(c, H, Policy(), [], 0.72)
    assert len(cs.candidates) == 4 and cs.diversity_violations == [] and cs.dropped == [] and len(fake.calls) == 1
    assert fake.calls[0]["model"] == "r" and fake.calls[0]["max_tokens"] == controls.FIXER_MAX_TOKENS
    assert [c.index for c in cs.candidates] == [0, 1, 2, 3] and cs.candidates[1].changed == ["grip_force", "grasp_hold_steps", "retry_count"]


def test_bounds_are_clamped_and_integer_rounding_is_recorded():
    changes = cand({"grip_force": 500, "grasp_hold_steps": 20.6, "retry_count": 2.4, "lift_speed": 0.2})
    c, _ = client([reply(changes, *DIVERSE[:3])])
    cs = propose(c, H, Policy(), [], 0.72)
    k = cs.candidates[0]
    assert k.patched_policy.grip_force == 80.0 and k.clamped["grip_force"] is True
    assert k.patched_policy.grasp_hold_steps == 21 and k.patched_policy.retry_count == 2
    assert k.rounded == {"grasp_hold_steps": [20.6, 21.0], "retry_count": [2.4, 2.0]}
    assert k.output.changes["grip_force"] == 500  # the raw proposal is preserved
    assert cs.candidates[1].rounded == {}  # whole-number proposals record no rounding


def test_invalid_noop_and_duplicate_candidates_are_dropped_with_reasons_others_kept():
    cs_raw = [cand({"approach_speed": 0.1}),                      # excluded parameter
              cand({"grip_force": 15}),                            # equals the current policy: a no-op
              cand({"grip_force": 25}),
              cand({"grip_force": 25.0}),                          # duplicate of the previous one
              cand({"grip_force": 60, "grasp_hold_steps": 70, "retry_count": 2}),
              cand({"lift_speed": 0.2, "retry_count": 1})]
    out = FixerCandidates.model_validate({"candidates": cs_raw[:6]})
    cands, dropped = process_candidates(out, Policy(), 4)
    assert [c.index for c in cands] == [0, 1, 2]
    reasons = {d["index"]: d["reason"] for d in dropped}
    assert "not patchable" in reasons[0] and "changes nothing" in reasons[1] and "duplicate" in reasons[3]


def test_all_candidates_invalid_retries_once_then_fails_loudly():
    bad = reply(cand({"approach_speed": 0.1}), cand({"controller_code": 1}))
    c, fake = client([bad, bad])
    with pytest.raises(LLMValidationError, match="no usable candidate"):
        propose(c, H, Policy(), [], 0.72)
    assert len(fake.calls) == 2


def test_extra_candidates_beyond_the_requested_number_are_dropped():
    many = DIVERSE + [cand({"lift_height": 0.2}), cand({"lift_speed": 0.1})]
    c, _ = client([reply(*many)])
    cs = propose(c, H, Policy(), [], 0.72)
    assert len(cs.candidates) == 4 and len(cs.dropped) == 2 and "more than the 4 requested" in cs.dropped[0]["reason"]


# ------------------------------------------------------------------ diversity
def test_diversity_requirements_are_checked():
    cs, _ = process_candidates(FixerCandidates.model_validate({"candidates": DIVERSE}), Policy(), 4), None
    assert diversity_violations(cs[0]) == []
    same = FixerCandidates.model_validate({"candidates": [cand({"grip_force": 25}), cand({"grip_force": 26}), cand({"grip_force": 27})]})
    v = diversity_violations(process_candidates(same, Policy(), 4)[0])
    assert any("three or more levers" in x for x in v) and any("similar step sizes" in x for x in v) and not any("single-lever" in x for x in v)
    no_single = FixerCandidates.model_validate({"candidates": [cand({"grip_force": 25, "retry_count": 1}), cand({"grip_force": 70, "grasp_hold_steps": 90, "retry_count": 3})]})
    assert any("single-lever" in x for x in diversity_violations(process_candidates(no_single, Policy(), 4)[0]))
    assert DIVERSITY_SPREAD == 0.20


def test_non_diverse_first_reply_is_sent_back_once_and_a_diverse_retry_is_used():
    flat = reply(*[cand({"grip_force": g}) for g in (22, 24, 26, 28)])
    c, fake = client([flat, reply(*DIVERSE)])
    cs = propose(c, H, Policy(), [], 0.72)
    assert len(fake.calls) == 2 and cs.diversity_violations == []
    assert "not diverse enough" in fake.calls[1]["messages"][-1]["content"]


def test_still_not_diverse_after_the_retry_is_accepted_and_recorded_not_fatal():
    flat = reply(*[cand({"grip_force": g}) for g in (22, 24, 26, 28)])
    c, fake = client([flat, flat])
    cs = propose(c, H, Policy(), [], 0.72)
    assert len(fake.calls) == 2 and len(cs.candidates) == 4 and cs.diversity_violations  # recorded, the run continues


def test_single_candidate_mode_skips_the_diversity_requirement():
    c, fake = client([reply(cand({"grip_force": 25}))])
    cs = propose(c, H, Policy(), [], 0.72, n_candidates=1)
    assert len(cs.candidates) == 1 and cs.diversity_violations == [] and len(fake.calls) == 1


def test_exhausted_after_three_attempts():
    c, _ = client([])
    with pytest.raises(FixerExhausted):
        propose(c, H, Policy(), [fb(1), fb(2), fb(3)], 0.72)


# ------------------------------------------------------------------ prompt contents
def test_earlier_candidate_table_appears_in_the_next_prompt():
    _, user = build_prompt(H, Policy(), [], 0.72, 4)
    assert json.loads(user)["earlier_attempts"] == []
    c, fake = client([reply(*DIVERSE)])
    propose(c, H, Policy(), [fb(1)], 0.72)
    prompt = json.loads(fake.calls[0]["messages"][1]["content"])
    a = prompt["earlier_attempts"][0]
    assert a["selected_index"] == 1 and [r["selected"] for r in a["candidates"]] == [False, True]
    assert a["candidates"][1]["changes"] == {"grip_force": 60.0, "grasp_hold_steps": 70.0}
    assert a["candidates"][1]["per_hypothesis_fixed"] == {"H1": "20/40"} and a["candidates"][1]["fixed"] == 20 and a["g3_threshold"] == 0.7


def test_prompt_has_parameter_docs_and_dev_seed_effects_and_only_tunable_parameters():
    system, user = build_prompt(H, Policy(), [], 0.72, 4)
    d = json.loads(user)
    assert set(d["tunable_policy_parameters"]) == {"grip_force", "grasp_hold_steps", "retry_count", "lift_speed", "lift_height"}
    assert all("doc" in v and "min" in v and "max" in v and "current" in v for v in d["tunable_policy_parameters"].values())
    assert d["measured_one_at_a_time_effects"] == ONE_AT_A_TIME_EFFECTS and "approach_speed" not in user and "place_slow_factor" not in user
    assert "DIVERSE" in system and "exactly one parameter" in system and "three or more" in system


def test_prompt_contains_no_value_from_the_ceiling_search():
    best = json.loads((ROOT / "docs" / "ceiling_search_results.json").read_text())["best_policy"]
    system, user = build_prompt(H, Policy(), [fb(1)], 0.72, 4)
    text = system + user
    nums = [float(x) for x in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", text)]
    for name in ("grip_force", "grasp_hold_steps", "lift_speed", "lift_height"):  # retry_count's best value (3) is just the upper bound
        v = best[name]
        assert not any(abs(n - v) <= 0.005 * abs(v) for n in nums), f"{name}={v} (a ceiling-search value) appears in the fixer prompt"
    assert "ceiling" not in text.lower() and "best_policy" not in text and "recommended" not in text.lower()


# ------------------------------------------------------------------ no leakage by construction
def test_no_leakage_feedback_models_have_no_g5_or_verification_fields():
    for model in (DevFeedback, CandidateRow):
        names = set(model.model_fields)
        assert not [n for n in names if any(t in n.lower() for t in ("g5", "held", "verif", "rehears", "seed"))]
    with pytest.raises(ValidationError):
        DevFeedback(**{**fb().model_dump(), "g5_pass_rate": 0.9})
    with pytest.raises(ValidationError):
        CandidateRow(**{**row(0, True).model_dump(), "verification_pass_rate": 0.9})


def test_prompt_never_mentions_verification_data_even_with_feedback():
    system, user = build_prompt(H, Policy(), [fb(1), fb(2)], 0.72, 4)
    text = (system + user).lower()
    for banned in ("g5", "held-out", "held_out", "heldout", "verification", "rehearsal", "800000", "900000"):
        assert banned not in text
