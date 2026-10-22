"""P1 unit tests. The network is always mocked here; no real Nebius call is made."""
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

from app.core.config import ConfigError, load_settings
from app.core.schemas import (CheckStatus, FailureReason, GateCheck, GateReport, Policy, PolicyPatch,
                              Result, Run, Scenario, ShardResult, Verdict)
from app.llm.client import LLMClient, LLMTransportError, LLMValidationError, extract_json
from app.store.db import Database

ENV = {"NEBIUS_API_KEY": "secret-key-xyz", "NEBIUS_MODEL_FAST": "fast-model", "NEBIUS_MODEL_REASONING": "reason-model"}


def settings(**over):
    return load_settings({**ENV, **over})


class Fake:
    """Stands in for openai.OpenAI. Each item in `replies` is a str (content) or an Exception to raise."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=r))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
        )


class Out(BaseModel):
    x: int


# ---- config
def test_config_defaults_and_missing():
    s = load_settings({})
    assert s.base_url.startswith("https://api.tokenfactory.nebius.com")
    with pytest.raises(ConfigError, match="NEBIUS_API_KEY"):
        s.require_llm("fast")
    with pytest.raises(ConfigError, match="NEBIUS_MODEL_REASONING"):
        load_settings({"NEBIUS_API_KEY": "k"}).require_llm("reasoning")


def test_config_redacts_key():
    assert "secret-key-xyz" not in str(settings().redacted())


# ---- schemas
def good_scenario(**kw):
    d = dict(id="s1", mass_kg=0.5, friction=0.5, size_m=0.05, pos_offset_x=0, pos_offset_y=0,
             sensor_noise_m=0.01, gripper_delay_steps=3, seed=1)
    return Scenario(**{**d, **kw})


def test_scenario_bounds_enforced():
    good_scenario()
    for bad in ({"mass_kg": 5.0}, {"friction": 0.0}, {"gripper_delay_steps": 21}, {"seed": -1}):
        with pytest.raises(ValidationError):
            good_scenario(**bad)
    with pytest.raises(ValidationError):
        good_scenario(extra_field=1)


def test_patch_clamps_and_rejects_unknown():
    p, clamped = PolicyPatch(changes={"grip_force": 999, "retry_count": 2.4, "lift_height": 0.2}).apply(Policy())
    assert p.grip_force == 80.0 and clamped["grip_force"]
    assert p.retry_count == 2 and not clamped["retry_count"]
    assert p.lift_height == 0.2 and p.approach_speed == Policy().approach_speed
    with pytest.raises(ValidationError):
        PolicyPatch(changes={"controller_code": 1})
    with pytest.raises(ValidationError):
        PolicyPatch(changes={})


def test_patch_only_five_effective_params_and_finite():
    from app.core.schemas import PATCHABLE_PARAMS
    assert set(PATCHABLE_PARAMS) == {"grip_force", "grasp_hold_steps", "retry_count", "lift_speed", "lift_height"}
    for excluded in ("approach_speed", "place_slow_factor"):
        Policy(**{excluded: Policy().model_dump()[excluded]})  # still valid Policy fields
        with pytest.raises(ValidationError, match="not patchable"):
            PolicyPatch(changes={excluded: 0.2})
    PolicyPatch(changes={k: Policy().model_dump()[k] for k in PATCHABLE_PARAMS})  # all five at once is fine
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValidationError, match="non-finite"):
            PolicyPatch(changes={"grip_force": bad})
    with pytest.raises(ValidationError):
        PolicyPatch(changes={"grip_force": 20}, justification="ok", extra=1)


def test_result_reason_consistency():
    ok = dict(scenario_id="a", seed=1, collision=False, completion_time_s=1.0, final_place_error_m=0.01, max_slip_m=0.0)
    Result(success=True, **ok)
    Result(success=False, failure_reason=FailureReason.TIMEOUT, **ok)
    with pytest.raises(ValidationError):
        Result(success=False, **ok)
    with pytest.raises(ValidationError):
        Result(success=True, failure_reason=FailureReason.TIMEOUT, **ok)


def test_shard_complete_property():
    assert not ShardResult(shard_id="a", status="TIMEOUT", runner="local", n_expected=2).complete
    assert ShardResult(shard_id="a", status="COMPLETED", runner="local", n_expected=0).complete


def test_run_roundtrip_through_sqlite():
    db = Database(":memory:")
    gate = GateReport(verdict=Verdict.UNVERIFIED, checks=[GateCheck(id="G6", name="x", status=CheckStatus.NOT_RUN, details="d")])
    db.save_run(Run(id="r1", gate=gate))
    assert db.load_run("r1").gate.verdict == Verdict.UNVERIFIED
    assert db.load_run("nope") is None


# ---- extract_json
def test_extract_json_variants():
    assert extract_json('{"x": 1}') == {"x": 1}
    assert extract_json('```json\n{"x": 2}\n```') == {"x": 2}
    assert extract_json('<think>hmm {"x": 9}</think>\n{"x": 3}') == {"x": 3}
    assert extract_json('Sure! Here: {"x": 4} done') == {"x": 4}
    with pytest.raises(ValueError):
        extract_json("no json here")


# ---- LLM client
def test_complete_json_ok_and_logs_tokens_without_secrets():
    fake = Fake(['{"x": 5}'])
    seen = []
    c = LLMClient(settings(), fake, sink=seen.append)
    assert c.complete_json("t", "fast", "sys", "usr", Out).x == 5
    assert fake.calls[0]["model"] == "fast-model"
    rec = seen[0]
    assert (rec.prompt_tokens, rec.completion_tokens, rec.ok) == (11, 7, True) and rec.latency_s >= 0
    assert "secret-key-xyz" not in repr(rec)


def test_validation_failure_retries_once_with_error_then_succeeds():
    fake = Fake(['{"x": "nope"}', '{"x": 6}'])
    c = LLMClient(settings(), fake)
    assert c.complete_json("t", "reasoning", "s", "u", Out).x == 6
    assert len(fake.calls) == 2 and fake.calls[0]["model"] == "reason-model"
    assert "failed validation" in fake.calls[1]["messages"][-1]["content"]
    assert c.records[0].ok is False and c.records[1].ok is True


def test_validation_failure_twice_fails_loudly():
    c = LLMClient(settings(), Fake(["garbage", '{"x": "still bad"}']))
    with pytest.raises(LLMValidationError):
        c.complete_json("t", "fast", "s", "u", Out)


def test_transport_error_retried_once_then_raised():
    ok = LLMClient(settings(), Fake([TimeoutError("slow"), '{"x": 1}']))
    assert ok.complete_json("t", "fast", "s", "u", Out).x == 1
    bad = LLMClient(settings(), Fake([TimeoutError("a"), TimeoutError("b")]))
    with pytest.raises(LLMTransportError):
        bad.complete_json("t", "fast", "s", "u", Out)


def test_json_schema_flag_only_when_enabled():
    f1 = Fake(['{"x": 1}'])
    LLMClient(settings(), f1).complete_json("t", "fast", "s", "u", Out)
    assert "response_format" not in f1.calls[0]
    f2 = Fake(['{"x": 1}'])
    LLMClient(settings(NEBIUS_USE_JSON_SCHEMA="1"), f2).complete_json("t", "fast", "s", "u", Out)
    assert f2.calls[0]["response_format"]["type"] == "json_schema"


def test_missing_model_config_fails_before_network():
    fake = Fake([])
    with pytest.raises(ConfigError):
        LLMClient(load_settings({"NEBIUS_API_KEY": "k"}), fake).complete_json("t", "fast", "s", "u", Out)
    assert fake.calls == []


def test_calls_persist_to_db():
    db = Database(":memory:")
    c = LLMClient(settings(), Fake(['{"x": 1}']), sink=db.log_llm_call)
    c.complete_json("scenario_gen", "fast", "s", "u", Out)
    assert db.llm_calls() == [("scenario_gen", "fast-model", 1, 1, 11, 7)]
