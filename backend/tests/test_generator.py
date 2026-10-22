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
        self.replies, self.calls = list(replies), 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls += 1
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


def test_malformed_json_retries_once_then_fails_loudly():
    g, fake = gen_with(["not json at all", "{still bad"])
    with pytest.raises(LLMValidationError):
        g.generate(50, master_seed=1)
    assert fake.calls == 2


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
