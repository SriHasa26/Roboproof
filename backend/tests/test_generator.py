"""Scenario generator tests. The LLM client is mocked; the fixture path is exercised separately."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.bounds import SCENARIO_BOUNDS
from app.core.config import load_settings
from app.core.seeds import HELDOUT_SEED_BASE, HeldOutSeedError
from app.llm.client import LLMClient, LLMValidationError
from app.scenarios.generator import ScenarioGenerator
from app.scenarios.proposal import ScenarioProposal

FIX = Path(__file__).parent / "fixtures" / "scenario_proposal.json"
GOOD = {"regions": [
    {"name": "heavy_slippery", "rationale": "r", "ranges": {"mass_kg": [0.6, 1.0], "friction": [0.1, 0.3]}},
    {"name": "delay", "rationale": "r", "ranges": {"gripper_delay_steps": [14, 20]}},
]}


class Fake:
    def __init__(self, replies):
        self.replies, self.calls, self.sent, self.kws = list(replies), 0, [], []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls += 1
        self.sent.append(kw.get("messages"))
        self.kws.append(kw)
        r = self.replies.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=r))],
                               usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))


def gen_with(replies):
    s = load_settings({"NEBIUS_API_KEY": "k", "NEBIUS_MODEL_FAST": "m", "NEBIUS_MODEL_REASONING": "r"})
    fake = Fake(replies)
    return ScenarioGenerator(llm=LLMClient(s, fake)), fake


def test_valid_proposal_accepted_and_labelled_llm():
    g, _ = gen_with([json.dumps(GOOD)])
    out = g.generate(100, master_seed=5)
    assert out.source == "llm" and len(out.scenarios) == 100
    assert (out.n_coverage, out.n_targeted) == (60, 40)
    tgt = [s for s in out.scenarios if s.tag.startswith("tgt:heavy")]
    assert tgt and all(s.mass_kg >= 0.6 and s.friction <= 0.3 for s in tgt)


def test_out_of_range_proposal_rejected_by_schema():
    bad_cases = [
        {"regions": [{"name": "a", "rationale": "r", "ranges": {"mass_kg": [0.5, 5.0]}}]},          # above max
        {"regions": [{"name": "a", "rationale": "r", "ranges": {"friction": [0.9, 0.2]}}]},         # lo > hi
        {"regions": [{"name": "a", "rationale": "r", "ranges": {"approach_speed": [0.1, 0.2]}}]},   # unknown axis
        {"regions": [{"name": "a", "rationale": "r", "ranges": {}}]},
        {"regions": []},
    ]
    for b in bad_cases:
        with pytest.raises(ValidationError):
            ScenarioProposal.model_validate(b)


def test_malformed_json_retries_once_then_falls_back_to_coverage_only_and_says_so():
    g, fake = gen_with(["not json at all", "{still bad"])
    out = g.generate(50, master_seed=1)
    assert fake.calls == 2  # one call + the single validation retry on the only configured model
    assert out.source == "coverage_only_fallback" and out.model is None and out.proposal is None
    assert (out.n_coverage, out.n_targeted) == (50, 0) and len(out.scenarios) == 50 and all(s.tag == "cov" for s in out.scenarios)
    assert out.generator_trail[0]["outcome"] == "validation_failed_after_retry" and out.generator_trail[-1]["stage"] == "coverage_only_fallback"


def test_malformed_then_valid_recovers_with_one_retry():
    g, fake = gen_with(["oops", json.dumps(GOOD)])
    assert g.generate(50, master_seed=1).source == "llm" and fake.calls == 2


def test_out_of_range_llm_output_goes_through_retry_path():
    bad = {"regions": [{"name": "a", "rationale": "r", "ranges": {"mass_kg": [0.5, 5.0]}}]}
    g, fake = gen_with([json.dumps(bad), json.dumps(GOOD)])
    assert g.generate(50, master_seed=1).source == "llm" and fake.calls == 2


def test_same_master_seed_gives_identical_list_and_different_seed_differs():
    a = ScenarioGenerator(fixture_path=FIX).generate(120, master_seed=7)
    b = ScenarioGenerator(fixture_path=FIX).generate(120, master_seed=7)
    c = ScenarioGenerator(fixture_path=FIX).generate(120, master_seed=8)
    assert a.scenarios == b.scenarios
    assert a.scenarios != c.scenarios


def test_all_seeds_are_dev_seeds_unique_and_params_in_bounds():
    out = ScenarioGenerator(fixture_path=FIX).generate(300, master_seed=3)
    seeds = [s.seed for s in out.scenarios]
    assert len(set(seeds)) == 300 and max(seeds) < HELDOUT_SEED_BASE
    for s in out.scenarios:
        for ax, (lo, hi) in SCENARIO_BOUNDS.items():
            assert lo <= getattr(s, ax) <= hi


def test_generator_refuses_heldout_range_without_flag():
    g = ScenarioGenerator(fixture_path=FIX)
    with pytest.raises(HeldOutSeedError):
        g.generate(10, master_seed=1, seed_base=HELDOUT_SEED_BASE)
    with pytest.raises(HeldOutSeedError):
        g.generate(10, master_seed=1, seed_base=HELDOUT_SEED_BASE - 3)


def test_fixture_output_is_labelled_fixture_never_llm():
    out = ScenarioGenerator(fixture_path=FIX).generate(50, master_seed=1)
    assert out.source == "fixture"
    assert "NOT model output" in json.loads(FIX.read_text())["_label"]
    # without a key, from_settings must pick the fixture rather than pretend
    g = ScenarioGenerator.from_settings(load_settings({}), FIX)
    assert g.llm is None and g.generate(50, master_seed=1).source == "fixture"


def test_coverage_part_spans_the_space():
    out = ScenarioGenerator(fixture_path=FIX).generate(200, master_seed=2, targeted_fraction=0.0)
    assert out.n_targeted == 0 and out.proposal is None
    for ax, (lo, hi) in SCENARIO_BOUNDS.items():
        vals = [getattr(s, ax) for s in out.scenarios]
        assert min(vals) < lo + 0.1 * (hi - lo) and max(vals) > hi - 0.1 * (hi - lo)


# ---------------------------------------------------------------- P4.5: region constraints
from app.scenarios.proposal import MAX_AXES_PER_REGION, MIN_VOLUME_FRACTION, Region  # noqa: E402


def region(**ranges):
    return {"name": "r", "rationale": "r", "ranges": ranges}


def test_at_most_three_axes_enforced():
    Region.model_validate(region(mass_kg=[0.2, 1.0], friction=[0.1, 1.0], size_m=[0.03, 0.08]))
    with pytest.raises(ValidationError, match="at most 3 axes"):
        Region.model_validate(region(mass_kg=[0.2, 1.0], friction=[0.1, 1.0], size_m=[0.03, 0.08], sensor_noise_m=[0.0, 0.03]))
    assert MAX_AXES_PER_REGION == 3


def test_volume_floor_enforced_and_computed_as_a_fraction_of_the_space():
    r = Region.model_validate(region(mass_kg=[0.05, 0.525]))  # half of the mass axis
    assert r.volume_fraction() == pytest.approx(0.5)
    ok = region(mass_kg=[0.05, 0.3], friction=[0.1, 0.4])  # 0.263 * 0.273 = 0.072
    assert Region.model_validate(ok).volume_fraction() > MIN_VOLUME_FRACTION
    with pytest.raises(ValidationError, match="covers only"):
        Region.model_validate(region(mass_kg=[0.5, 0.55], friction=[0.2, 0.25]))  # 0.0526 * 0.0455 = 0.24%
    # three narrow axes multiply to far below 2% even if each looks reasonable
    with pytest.raises(ValidationError, match="covers only"):
        Region.model_validate(region(mass_kg=[0.5, 0.7], friction=[0.2, 0.4], size_m=[0.05, 0.06]))


def test_rationale_is_always_flagged_unverified():
    r = Region.model_validate(region(mass_kg=[0.2, 1.0]))
    assert r.unverified is True and r.model_dump()["unverified"] is True
    with pytest.raises(ValidationError):
        Region.model_validate({**region(mass_kg=[0.2, 1.0]), "unverified": False})
    g, _ = gen_with([json.dumps(GOOD)])
    out = g.generate(50, master_seed=2)
    assert all(rg.unverified for rg in out.proposal.regions)


def test_all_regions_invalid_goes_through_the_retry_path_then_falls_back():
    too_many = {"regions": [{"name": "a", "rationale": "r", "ranges": {"mass_kg": [0.2, 1.0], "friction": [0.1, 1.0],
                                                                          "size_m": [0.03, 0.08], "sensor_noise_m": [0.0, 0.03]}}]}
    g, fake = gen_with([json.dumps(too_many), json.dumps(too_many)])
    out = g.generate(50, master_seed=1)
    assert fake.calls == 2 and out.source == "coverage_only_fallback"
    assert "at most 3 axes" in fake.sent[1][-1]["content"]  # the reason was fed back on the retry
    g, fake = gen_with([json.dumps(too_many), json.dumps(GOOD)])  # corrected on retry
    assert g.generate(50, master_seed=1).source == "llm"


def test_prompt_states_the_constraints():
    from app.scenarios.generator import build_prompt
    _, user = build_prompt()
    assert "AT MOST 3" in user and "2%" in user and "unverified" in user


def test_generator_sends_thinking_off_and_a_token_cap_but_analyst_fixer_do_not_disable_reasoning():
    from app.llm import controls
    g, fake = gen_with([json.dumps(GOOD)])
    g.generate(50, master_seed=1)
    kw = fake.kws[0]
    assert kw["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}} and kw["max_tokens"] == controls.GENERATOR_MAX_TOKENS
    assert "reasoning_effort" not in kw  # reasoning_effort="none" does not work on this model (see controls.py)
    assert controls.ANALYST_MAX_TOKENS >= 6000 and controls.FIXER_MAX_TOKENS >= 4000  # caps stop runaways only


# ---------------------------------------------------------------- P4.6: partial acceptance, repair, fallback chain
class FakeByModel:
    """Routes replies by the `model` argument: {model_id: [reply | Exception, ...]}."""

    def __init__(self, plan):
        self.plan, self.calls_by_model, self.kws = {k: list(v) for k, v in plan.items()}, {}, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        m = kw["model"]
        self.calls_by_model[m] = self.calls_by_model.get(m, 0) + 1
        self.kws.append(kw)
        r = self.plan[m].pop(0)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=r))], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))


PRIMARY, FALLBACK = "nvidia/fast-primary", "nvidia/nemotron-fallback"


def chain_gen(plan, fallback=FALLBACK):
    env = {"NEBIUS_API_KEY": "k", "NEBIUS_MODEL_FAST": PRIMARY, "NEBIUS_MODEL_REASONING": "r"}
    if fallback:
        env["NEBIUS_MODEL_FALLBACK"] = fallback
    fake = FakeByModel(plan)
    return ScenarioGenerator(llm=LLMClient(load_settings(env), fake)), fake


TINY = {"name": "tiny", "rationale": "r", "ranges": {"mass_kg": [0.5, 0.52], "friction": [0.5, 0.52]}}
OKR = {"name": "ok", "rationale": "r", "ranges": {"mass_kg": [0.3, 0.9], "friction": [0.1, 0.6]}}


def test_partial_acceptance_keeps_valid_regions_logs_the_dropped_one_and_does_not_retry():
    g, fake = chain_gen({PRIMARY: [json.dumps({"regions": [OKR, TINY, {**OKR, "name": "ok2"}]})]})
    out = g.generate(100, master_seed=1)
    assert out.source == "llm" and out.model == PRIMARY and fake.calls_by_model == {PRIMARY: 1}
    assert [r.name for r in out.proposal.regions] == ["ok", "ok2"]
    assert len(out.dropped_regions) == 1 and out.dropped_regions[0]["name"] == "tiny" and "covers only" in out.dropped_regions[0]["reason"]
    assert {s.tag for s in out.scenarios if s.tag != "cov"} == {"tgt:ok", "tgt:ok2"}  # nothing is sampled from the dropped region
    t = out.generator_trail[0]
    assert (t["outcome"], t["regions_valid"], t["regions_dropped"]) == ("ok", 2, 1)


def test_at_least_one_valid_region_is_required_then_retry_then_next_model():
    g, fake = chain_gen({PRIMARY: [json.dumps({"regions": [TINY]}), json.dumps({"regions": [TINY]})], FALLBACK: [json.dumps({"regions": [OKR]})]})
    out = g.generate(50, master_seed=1)
    assert fake.calls_by_model == {PRIMARY: 2, FALLBACK: 1}  # primary tried twice (validation retry), then the second model
    assert out.source == "llm" and out.model == FALLBACK
    assert [t["stage"] + ":" + t["outcome"] for t in out.generator_trail] == ["primary:validation_failed_after_retry", "fallback_model:ok"]


def test_values_slightly_outside_bounds_are_clamped_and_logged_far_ones_are_invalid():
    near = {"name": "near", "rationale": "r", "ranges": {"friction": [0.05, 0.6], "mass_kg": [0.3, 1.05]}}  # 0.05 below / above: within 10% of the range
    far = {"name": "far", "rationale": "r", "ranges": {"friction": [-0.5, 0.6]}}
    g, _ = chain_gen({PRIMARY: [json.dumps({"regions": [near, far]})]})
    out = g.generate(60, master_seed=1)
    assert [r.name for r in out.proposal.regions] == ["near"]
    assert out.proposal.regions[0].ranges == {"friction": [0.1, 0.6], "mass_kg": [0.3, 1.0]}
    assert {(c["axis"], c["end"], c["from"], c["to"]) for c in out.clamped_values} == {("friction", "lo", 0.05, 0.1), ("mass_kg", "hi", 1.05, 1.0)}
    assert out.dropped_regions[0]["name"] == "far" and "outside allowed" in out.dropped_regions[0]["reason"]
    for s in out.scenarios:  # every scenario respects the frozen bounds regardless
        assert 0.1 <= s.friction <= 1.2 and 0.05 <= s.mass_kg <= 1.0


def test_timeout_on_the_primary_triggers_the_next_nemotron_model_without_a_transport_retry():
    g, fake = chain_gen({PRIMARY: [TimeoutError("hung endpoint")], FALLBACK: [json.dumps({"regions": [OKR]})]})
    out = g.generate(50, master_seed=1)
    assert fake.calls_by_model == {PRIMARY: 1, FALLBACK: 1}  # no second try on the hung model
    assert out.source == "llm" and out.model == FALLBACK
    assert out.generator_trail[0]["outcome"] == "transport_error_or_timeout" and out.generator_trail[1]["outcome"] == "ok"
    from app.llm import controls
    assert fake.kws[0]["timeout"] == controls.GENERATOR_TIMEOUT_S and fake.kws[1]["timeout"] == controls.GENERATOR_FALLBACK_TIMEOUT_S
    assert fake.kws[0]["max_tokens"] == controls.GENERATOR_MAX_TOKENS and fake.kws[1]["max_tokens"] == controls.GENERATOR_FALLBACK_MAX_TOKENS


def test_all_models_failing_gives_a_correctly_labelled_coverage_only_set():
    g, fake = chain_gen({PRIMARY: [TimeoutError("x")], FALLBACK: [TimeoutError("y")]})
    out = g.generate(80, master_seed=4)
    assert out.source == "coverage_only_fallback" and out.model is None and out.proposal is None
    assert (out.n_coverage, out.n_targeted, len(out.scenarios)) == (80, 0, 80)
    assert [t["stage"] for t in out.generator_trail] == ["primary", "fallback_model", "coverage_only_fallback"]
    again = ScenarioGenerator(fixture_path=FIX).generate(80, master_seed=4, targeted_fraction=0.0)  # it is the plain coverage sweep
    assert [s.model_dump() for s in out.scenarios] == [s.model_dump() for s in again.scenarios]


def test_no_fallback_model_configured_goes_straight_to_coverage_after_the_primary():
    g, fake = chain_gen({PRIMARY: [TimeoutError("x")]}, fallback=None)
    out = g.generate(50, master_seed=1)
    assert out.source == "coverage_only_fallback" and fake.calls_by_model == {PRIMARY: 1}


def test_budget_exhaustion_is_loud_not_a_fallback():
    from app.llm.client import LLMBudgetExceeded
    env = {"NEBIUS_API_KEY": "k", "NEBIUS_MODEL_FAST": PRIMARY, "NEBIUS_MODEL_REASONING": "r", "MAX_LLM_CALLS_PER_RUN": "1"}
    fake = FakeByModel({PRIMARY: [json.dumps({"regions": [TINY]}), json.dumps({"regions": [OKR]})]})
    g = ScenarioGenerator(llm=LLMClient(load_settings(env), fake))
    with pytest.raises(LLMBudgetExceeded):
        g.generate(50, master_seed=1)


def test_source_and_model_are_recorded_in_the_output_object():
    g, _ = chain_gen({PRIMARY: [json.dumps({"regions": [OKR]})]})
    d = g.generate(50, master_seed=1).model_dump()
    assert d["source"] == "llm" and d["model"] == PRIMARY and "generator_trail" in d and "dropped_regions" in d and "clamped_values" in d
    fx = ScenarioGenerator(fixture_path=FIX).generate(50, master_seed=1).model_dump()
    assert fx["source"] == "fixture" and fx["model"] is None
