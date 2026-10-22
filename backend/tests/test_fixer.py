"""Fixer tests with a mocked LLM."""
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.analysis.fixer import MAX_ATTEMPTS, FixerExhausted, build_prompt, propose
from app.analysis.models import DevFeedback, Hypothesis
from app.core.config import load_settings
from app.core.schemas import Policy
from app.llm.client import LLMClient, LLMValidationError


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


def out(changes, rationale="because", effect="fewer failures"):
    return json.dumps({"changes": changes, "rationale": rationale, "expected_effect": effect})


def fb(n=1, **over):
    d = dict(attempt=n, patch={"grip_force": 40.0}, g3_target_fix_rate=0.5, g3_threshold=0.7, g4_regressions=7, g4_budget=4,
             g2_all_reproduced=True, g1_deterministic=True, g6_complete=True, analysis_pass_rate_before=0.72,
             analysis_pass_rate_after=0.8)
    d.update(over)
    return DevFeedback(**d)


def test_valid_patch_is_applied_to_the_policy():
    c, fake = client([out({"grip_force": 45, "grasp_hold_steps": 40})])
    (r,) = propose(c, H, Policy(), [], 0.72)
    assert r.patched_policy.grip_force == 45.0 and r.patched_policy.grasp_hold_steps == 40
    assert r.patched_policy.lift_height == Policy().lift_height and r.attempt == 1 and not any(r.clamped.values())
    assert fake.calls[0]["model"] == "r"


def test_out_of_bound_values_are_clamped_and_reported():
    c, _ = client([out({"grip_force": 500, "retry_count": 9})])
    (r,) = propose(c, H, Policy(), [], 0.72)
    assert r.patched_policy.grip_force == 80.0 and r.patched_policy.retry_count == 3
    assert r.clamped == {"grip_force": True, "retry_count": True}
    assert r.output.changes["grip_force"] == 500  # the raw proposal is preserved for the record


def test_unknown_or_excluded_fields_rejected_with_one_retry():
    c, fake = client([out({"approach_speed": 0.1}), out({"controller_code": 1})])
    with pytest.raises(LLMValidationError, match="not patchable|unknown"):
        propose(c, H, Policy(), [], 0.72)
    assert len(fake.calls) == 2
    c, _ = client([out({"approach_speed": 0.1}), out({"grip_force": 50})])  # corrected on retry
    assert propose(c, H, Policy(), [], 0.72)[0].patched_policy.grip_force == 50.0


def test_noop_patch_is_rejected():
    c, _ = client([out({"grip_force": 15}), out({"grip_force": 15.0})])  # equals the default policy
    with pytest.raises(LLMValidationError, match="changes nothing"):
        propose(c, H, Policy(), [], 0.72)


def test_attempt_one_feedback_appears_in_attempt_two_prompt():
    _, user = build_prompt(H, Policy(), [], 0.72)
    assert json.loads(user)["previous_attempts"] == []
    feedback = fb(1, g4_regressions=7, patch={"grip_force": 40.0})
    c, fake = client([out({"grip_force": 50})])
    propose(c, H, Policy(), [feedback], 0.72)
    prompt = json.dumps(fake.calls[0]["messages"])
    assert '\\"g4_regressions\\":7' in prompt and '\\"attempt\\":1' in prompt and "40.0" in prompt


def test_at_most_three_attempts_and_only_one_candidate():
    c, _ = client([])
    with pytest.raises(FixerExhausted):
        propose(c, H, Policy(), [fb(1), fb(2), fb(3)], 0.72)
    assert MAX_ATTEMPTS == 3
    with pytest.raises(NotImplementedError):
        propose(c, H, Policy(), [], 0.72, n_candidates=2)


def test_no_leakage_feedback_model_has_no_g5_or_verification_fields():
    names = set(DevFeedback.model_fields)
    assert not [n for n in names if any(t in n.lower() for t in ("g5", "held", "verif", "rehears", "seed"))]
    with pytest.raises(ValidationError):  # cannot smuggle extra fields in
        DevFeedback(**{**fb().model_dump(), "g5_pass_rate": 0.9})
    with pytest.raises(ValidationError):
        DevFeedback(**{**fb().model_dump(), "verification_pass_rate": 0.9})


def test_prompt_never_mentions_verification_data_even_with_feedback():
    system, user = build_prompt(H, Policy(), [fb(1), fb(2)], 0.72)
    text = (system + user).lower()
    for banned in ("g5", "held-out", "held_out", "heldout", "verification", "rehearsal", "800000", "900000"):
        assert banned not in text
