"""LLM client controls: dev cache, call budget, secret masking, validator hook. Network is always mocked."""
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.core.config import load_settings
from app.llm.client import LLMBudgetExceeded, LLMClient, LLMTransportError, LLMValidationError, estimate_tokens

KEY = "secret-key-ABCDEF123456"


class Fake:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=r))],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


class Out(BaseModel):
    x: int


def settings(tmp_path=None, **env):
    base = {"NEBIUS_API_KEY": KEY, "NEBIUS_MODEL_FAST": "fast", "NEBIUS_MODEL_REASONING": "reason"}
    if tmp_path is not None:
        base["LLM_CACHE_DIR"] = str(tmp_path / "cache")
    return load_settings({**base, **env})


def test_defaults_cache_off_and_budget_12():
    s = load_settings({})
    assert s.dev_cache is False and s.max_calls_per_run == 12


def test_dev_cache_hit_is_flagged_cached_and_not_a_real_call(tmp_path):
    fake = Fake(['{"x": 1}'])
    c = LLMClient(settings(tmp_path, LLM_DEV_CACHE="1"), fake)
    assert c.complete_json("t", "fast", "s", "u", Out).x == 1
    assert c.complete_json("t", "fast", "s", "u", Out).x == 1  # served from disk
    assert len(fake.calls) == 1
    assert [r.cached for r in c.records] == [False, True]
    u = c.usage_summary()
    assert u["calls_real"] == 1 and u["calls_cached"] == 1 and u["any_cached"] is True
    # a different prompt is a miss
    fake.replies.append('{"x": 2}')
    assert c.complete_json("t", "fast", "s", "other", Out).x == 2 and len(fake.calls) == 2


def test_cache_off_by_default_never_flags_cached(tmp_path):
    fake = Fake(['{"x": 1}', '{"x": 1}'])
    c = LLMClient(settings(tmp_path), fake)
    c.complete_json("t", "fast", "s", "u", Out)
    c.complete_json("t", "fast", "s", "u", Out)
    assert len(fake.calls) == 2 and not any(r.cached for r in c.records) and c.usage_summary()["any_cached"] is False
    assert not (tmp_path / "cache").exists()


def test_call_budget_enforced_and_retries_count():
    fake = Fake(['{"x": 1}'] * 3)
    c = LLMClient(settings(MAX_LLM_CALLS_PER_RUN="2"), fake)
    c.complete_json("t", "fast", "s", "a", Out)
    c.complete_json("t", "fast", "s", "b", Out)
    with pytest.raises(LLMBudgetExceeded):
        c.complete_json("t", "fast", "s", "c", Out)
    assert len(fake.calls) == 2  # the third never reached the network


def test_cached_calls_do_not_consume_budget(tmp_path):
    fake = Fake(['{"x": 1}'])
    c = LLMClient(settings(tmp_path, LLM_DEV_CACHE="1", MAX_LLM_CALLS_PER_RUN="1"), fake)
    for _ in range(4):
        assert c.complete_json("t", "fast", "s", "same", Out).x == 1
    assert c.real_calls == 1


def test_api_key_is_masked_in_errors():
    fake = Fake([ConnectionError(f"failed with Authorization: Bearer {KEY}"), ConnectionError(f"again {KEY}")])
    c = LLMClient(settings(), fake)
    with pytest.raises(LLMTransportError) as ei:
        c.complete_json("t", "fast", "s", "u", Out)
    assert KEY not in str(ei.value) and "***" in str(ei.value)
    assert KEY not in repr(c.records)


def test_validator_hook_error_is_fed_back_once():
    fake = Fake(['{"x": 1}', '{"x": 99}'])

    def must_be_big(o):
        if o.x < 10:
            raise ValueError("x must be at least 10 (grounding check)")

    c = LLMClient(settings(), fake)
    assert c.complete_json("t", "fast", "s", "u", Out, validator=must_be_big).x == 99
    assert "grounding check" in fake.calls[1]["messages"][-1]["content"]
    fake2 = Fake(['{"x": 1}', '{"x": 2}'])
    with pytest.raises(LLMValidationError):
        LLMClient(settings(), fake2).complete_json("t", "fast", "s", "u", Out, validator=must_be_big)


def test_estimate_tokens_is_a_rough_positive_number():
    assert estimate_tokens("a" * 400) == 100 and estimate_tokens("") == 1
