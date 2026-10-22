"""Analyst tests with a mocked LLM. Grounding is enforced in code, targeted failures are chosen by code."""
import json
from types import SimpleNamespace

import pytest

from app.analysis.analyst import MIN_REGION_SUPPORT, analyze, build_prompt, targeted_failures
from app.analysis.evidence import compute_evidence
from app.core.config import load_settings
from app.core.schemas import Policy
from app.llm.client import LLMClient, LLMValidationError
from tests.test_evidence import synth


class Fake:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.replies.pop(0)))],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50))


def client(replies):
    s = load_settings({"NEBIUS_API_KEY": "k", "NEBIUS_MODEL_FAST": "f", "NEBIUS_MODEL_REASONING": "r"})
    fake = Fake(replies)
    return LLMClient(s, fake), fake


def hyp(**over):
    h = {"id": "H1", "statement": "Heavy slippery cubes slip out of a weak grip.", "region": {"mass_kg": [0.6, 1.0], "friction": [0.1, 0.4]},
         "mechanism": "Friction capacity 2*mu*F is below the weight plus inertial load.",
         "levers": [{"param": "grip_force", "direction": "increase"}], "prediction": "Failures in this region fall when grip_force rises.",
         "evidence_refs": ["E38"]}
    h.update(over)
    return h


def reply(*hs):
    return json.dumps({"hypotheses": list(hs)})


@pytest.fixture(scope="module")
def data():
    scns, res = synth()
    ev = compute_evidence(scns, res)
    ref = next(i.id for i in ev.items if i.kind == "interaction")
    return scns, res, ev, ref


def test_valid_hypothesis_accepted(data):
    scns, res, ev, ref = data
    c, fake = client([reply(hyp(evidence_refs=[ref, "E1"]))])
    hs = analyze(c, ev, scns, Policy())
    assert hs[0].id == "H1" and hs[0].levers[0].param == "grip_force" and len(fake.calls) == 1
    assert fake.calls[0]["model"] == "r"  # the reasoning model


def test_unknown_evidence_id_rejected_then_corrected_via_retry(data):
    scns, res, ev, ref = data
    c, fake = client([reply(hyp(evidence_refs=["E999"])), reply(hyp(evidence_refs=[ref]))])
    assert analyze(c, ev, scns, Policy())[0].evidence_refs == [ref]
    assert "E999" in fake.calls[1]["messages"][-1]["content"]  # the error was fed back


def test_unknown_evidence_id_twice_fails_loudly(data):
    scns, res, ev, ref = data
    c, _ = client([reply(hyp(evidence_refs=["E999"])), reply(hyp(evidence_refs=["E998"]))])
    with pytest.raises(LLMValidationError, match="do not exist"):
        analyze(c, ev, scns, Policy())


def test_region_with_too_little_support_rejected(data):
    scns, res, ev, ref = data
    tiny = {"mass_kg": [0.5, 0.51], "friction": [0.5, 0.51], "size_m": [0.05, 0.051]}
    c, fake = client([reply(hyp(region=tiny, evidence_refs=[ref])), reply(hyp(region=tiny, evidence_refs=[ref]))])
    with pytest.raises(LLMValidationError, match=f"at least {MIN_REGION_SUPPORT}"):
        analyze(c, ev, scns, Policy())


def test_non_tunable_lever_rejected(data):
    scns, res, ev, ref = data
    bad = hyp(levers=[{"param": "approach_speed", "direction": "decrease"}], evidence_refs=[ref])
    c, _ = client([reply(bad), reply(bad)])
    with pytest.raises(LLMValidationError, match="not a tunable parameter"):
        analyze(c, ev, scns, Policy())


def test_out_of_bounds_region_and_duplicate_ids_rejected(data):
    scns, res, ev, ref = data
    c, _ = client([reply(hyp(region={"mass_kg": [0.6, 5.0]}, evidence_refs=[ref])), reply(hyp(region={"mass_kg": [0.6, 5.0]}, evidence_refs=[ref]))])
    with pytest.raises(LLMValidationError, match="outside allowed"):
        analyze(c, ev, scns, Policy())
    dup = reply(hyp(evidence_refs=[ref]), hyp(evidence_refs=[ref]))
    c, _ = client([dup, dup])
    with pytest.raises(LLMValidationError, match="duplicate"):
        analyze(c, ev, scns, Policy())


def test_empty_evidence_refs_and_empty_levers_rejected(data):
    scns, res, ev, ref = data
    for bad in (hyp(evidence_refs=[]), hyp(levers=[], evidence_refs=[ref])):
        c, _ = client([reply(bad), reply(bad)])
        with pytest.raises(LLMValidationError):
            analyze(c, ev, scns, Policy())


def test_targeted_failures_are_baseline_failures_inside_regions(data):
    scns, res, ev, ref = data
    from app.analysis.models import Hypothesis
    h1 = Hypothesis.model_validate(hyp(evidence_refs=[ref]))
    h2 = Hypothesis.model_validate(hyp(id="H2", region={"sensor_noise_m": [0.027, 0.03]}, evidence_refs=[ref]))
    t = targeted_failures([h1, h2], scns, res)
    failed = {r.scenario_id for r in res if not r.success}
    byid = {s.id: s for s in scns}
    assert t["by_hypothesis"]["H1"] and all(i in failed for i in t["all"])
    assert all(byid[i].mass_kg >= 0.6 and byid[i].friction <= 0.4 for i in t["by_hypothesis"]["H1"])
    assert all(byid[i].sensor_noise_m >= 0.027 for i in t["by_hypothesis"]["H2"])
    assert t["all"] == sorted(set(t["by_hypothesis"]["H1"]) | set(t["by_hypothesis"]["H2"]))
    # a passing scenario inside the region is not targeted
    inside_pass = [s.id for s in scns if s.id not in failed and s.mass_kg >= 0.6 and s.friction <= 0.4]
    assert not (set(inside_pass) & set(t["all"]))


def test_prompt_contains_evidence_ids_and_only_tunable_levers(data):
    scns, res, ev, ref = data
    system, user = build_prompt(ev, Policy())
    assert ref in user and "E1" in user and "approach_speed" not in user and "place_slow_factor" not in user
    assert "grip_force" in user and "Do NOT state statistics" in system
