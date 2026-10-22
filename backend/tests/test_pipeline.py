"""End-to-end pipeline wiring with a FAKE LLM and a rule-based runner (no simulator, no network, no held-out seeds).

Simulated world: a scenario passes iff grip_force x friction >= 12 x mass. The default grip (15) fails heavy slippery cubes; a larger
grip fixes more, with no regressions. The point is to test the plumbing: generator -> baseline -> evidence -> analyst -> candidates
-> code-side evaluation and selection -> gate on the selected candidate only -> verification once.
"""
import json
import time
from types import SimpleNamespace

import pytest

from app.core.config import load_settings
from app.core.schemas import FailureReason, Policy, Result, ShardResult
from app.pipeline import PipelineConfig, run_pipeline
from app.runner.base import JobRunner, RunResult
from app.store.db import Database
from app.store.ledger import SeedLedger

FAKE_KEY = "sk-test-key-9f8e7d6c5b4a"
GEN = {"regions": [{"name": "heavy_slippery", "rationale": "r", "ranges": {"mass_kg": [0.4, 1.0], "friction": [0.1, 0.6]}},
                   {"name": "tiny_bad", "rationale": "r", "ranges": {"mass_kg": [0.5, 0.52], "friction": [0.5, 0.52]}}]}  # 2nd is dropped by validation


def cand(changes, why="why"):
    return {"changes": changes, "rationale": why, "expected_effect": "fewer failures"}


STRONG = [cand({"grip_force": 25}), cand({"grip_force": 80, "grasp_hold_steps": 70, "retry_count": 2}), cand({"lift_speed": 0.2, "retry_count": 1}),
          cand({"grip_force": 40, "grasp_hold_steps": 30})]
WEAK = [cand({"grip_force": 16}), cand({"grip_force": 18, "grasp_hold_steps": 12, "retry_count": 1}), cand({"lift_speed": 0.29, "retry_count": 1}),
        cand({"grip_force": 17, "grasp_hold_steps": 11}), ]


class FakeLLM:
    """Routes by the prompt: generator / analyst / fixer. Fixer replies are consumed in order."""

    def __init__(self, fixer_replies, gen_reply=None):
        self.fixer_replies, self.gen_reply, self.calls = list(fixer_replies), gen_reply or json.dumps(GEN), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        sys_, user = kw["messages"][0]["content"], kw["messages"][1]["content"]
        if "Propose RISKY regions" in sys_:
            out = self.gen_reply
        elif "robotics test analyst" in sys_:
            ev = json.loads(user)["evidence"]
            out = json.dumps({"hypotheses": [{"id": "H1", "statement": "weak grip on heavy slippery cubes", "region": {"mass_kg": [0.4, 1.0], "friction": [0.1, 0.6]},
                                              "mechanism": "friction capacity too low", "levers": [{"param": "grip_force", "direction": "increase"}],
                                              "prediction": "failures fall when grip rises", "evidence_refs": [ev[0]["id"]]}]})
        else:
            out = json.dumps({"candidates": self.fixer_replies.pop(0)})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=out))], usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50))


class RuleRunner(JobRunner):
    name = "rule"

    def __init__(self):
        self.calls = []

    def _run(self, policy, scenarios, shards, held_out):
        self.calls.append((policy.grip_force, len(scenarios), scenarios[0].tag, held_out))
        rs = []
        for s in scenarios:
            ok = policy.grip_force * s.friction >= 12 * s.mass_kg
            rs.append(Result(scenario_id=s.id, seed=s.seed, success=ok, collision=False, completion_time_s=3.0, final_place_error_m=0.0,
                             max_slip_m=0.0, failure_reason=None if ok else FailureReason.SLIPPED_ON_LIFT))
        shard = ShardResult(shard_id="s0", status="COMPLETED", runner="local", results=rs, n_expected=len(scenarios))
        return RunResult.build("rule", [shard], [[s.id for s in scenarios]], 0.01, image_build_id="img-test")


def run(tmp_path, fixer_replies, **env):
    settings = load_settings({"NEBIUS_API_KEY": FAKE_KEY, "NEBIUS_MODEL_FAST": "fast-m", "NEBIUS_MODEL_REASONING": "reason-m",
                              "NEBIUS_MODEL_FALLBACK": "fallback-m", **env})
    fake, runner, db = FakeLLM(fixer_replies), RuleRunner(), Database(":memory:")
    res = run_pipeline(settings, runner, db, SeedLedger(db), PipelineConfig("t1", tmp_path, master_seed=5, n=250, shards=5, rehearsal=True),
                       env={"ROBOPROOF_IMAGE_ID": "img-test"}, pricing={}, openai_client=fake)
    return res, fake, runner, db


def test_first_attempt_success_end_to_end(tmp_path):
    res, fake, runner, db = run(tmp_path, [STRONG])
    assert res["error"] is None and res["verdict"] == "VERIFIED" and res["rehearsal"] is True and res["n_attempts"] == 1
    assert res["generator"]["source"] == "llm" and res["generator"]["model"] == "fast-m" and res["generator"]["n_regions_used"] == 1
    assert [d["name"] for d in res["generator"]["dropped_regions"]] == ["tiny_bad"]
    at = res["attempts"][0]
    assert len(at["candidates"]) == 4 and at["selected_index"] == 1  # grip 80 fixes the most; selection is by rule, not by the model
    assert [c["selected"] for c in at["candidates"]] == [False, True, False, False]
    assert all(c["complete"] and c["targeted"] > 0 for c in at["candidates"]) and at["candidates"][1]["fixed"] >= at["candidates"][0]["fixed"]
    assert at["dev_checks"]["G3"]["status"] == "pass" and at["diversity_violations"] == [] and at["regression_budget"] >= 0
    assert res["checks"] == {k: "pass" for k in ("G1", "G2", "G3", "G4", "G5", "G6")}
    # the three LLM stages used the right models; one fixer call produced all four candidates
    assert [c["model"] for c in fake.calls] == ["fast-m", "reason-m", "reason-m"]


def test_unselected_candidates_never_reach_a_verification_set(tmp_path):
    res, fake, runner, db = run(tmp_path, [STRONG])
    ver = {g for g, n, tag, held in runner.calls if tag == "verify"}
    assert ver == {Policy().grip_force, 80.0}  # only the baseline and the selected candidate (grip 80) were run on the verification set
    assert all(held is False for *_, held in runner.calls)  # rehearsal: the held-out flag is never set
    assert [tag for g, n, tag, h in runner.calls if tag == "verify"] == ["verify", "verify"]
    rows = SeedLedger(db).rows()
    assert len(rows) == 1 and rows[0][1] == "rehearsal" and rows[0][5] == 1  # exactly one verification block, a rehearsal one


def test_second_attempt_sees_the_first_attempts_candidate_table_and_nothing_from_verification(tmp_path):
    res, fake, runner, db = run(tmp_path, [WEAK, STRONG])
    assert res["n_attempts"] == 2 and res["verdict"] == "VERIFIED"
    assert res["attempts"][0]["dev_checks"]["G3"]["status"] == "fail" and res["attempts"][1]["dev_checks"]["G3"]["status"] == "pass"
    fixer_calls = [c for c in fake.calls if "tune a robot" in c["messages"][0]["content"]]
    assert len(fixer_calls) == 2
    first, second = (json.loads(c["messages"][1]["content"]) for c in fixer_calls)
    assert first["earlier_attempts"] == []
    prev = second["earlier_attempts"][0]
    assert prev["attempt"] == 1 and len(prev["candidates"]) == 4 and sum(r["selected"] for r in prev["candidates"]) == 1
    assert all("per_hypothesis_fixed" in r and r["targeted"] > 0 for r in prev["candidates"])
    text = fixer_calls[1]["messages"][0]["content"].lower() + fixer_calls[1]["messages"][1]["content"].lower()
    for banned in ("g5", "held_out", "held-out", "verification", "rehearsal", "800000", "900000"):
        assert banned not in text


def test_artifacts_record_generator_source_model_candidates_and_timers(tmp_path):
    res, *_ = run(tmp_path, [STRONG])
    out = tmp_path / "t1"
    for f in ("LABEL.json", "analysis_set.json", "baseline_results.json", "evidence.json", "hypotheses.json", "targeted_failures.json",
              "gate_report.json", "llm_transcript.json", "summary.json"):
        assert (out / f).exists(), f
    a = json.loads((out / "analysis_set.json").read_text())
    assert a["source"] == "llm" and a["model"] == "fast-m" and a["generator_trail"][0]["outcome"] == "ok" and a["dropped_regions"][0]["name"] == "tiny_bad"
    s = json.loads((out / "summary.json").read_text())
    for stage in ("generate_scenarios_llm", "baseline_run", "evidence", "analyst_llm", "gate_prepare_g1_g2", "fixer_llm_attempt1", "candidate_evals_attempt1",
                  "dev_stage_attempt1", "verification_g5"):
        assert stage in s["timings_s"], stage
    assert "candidate_evals_total_s" in s["gate_timings_s"] and "g1_fresh_process_rerun_s" in s["gate_timings_s"] and s["llm_seconds"] >= 0
    assert s["provenance"]["official"] is False and s["provenance"]["pipeline_hash"]
    base = json.loads((out / "baseline_results.json").read_text())
    assert base["runner_name"] == "rule" and base["image_build_id"] == "img-test"  # compare_runs.py-compatible
    for f in out.iterdir():  # the API key must not appear in any artifact
        assert FAKE_KEY not in f.read_text(encoding="utf-8"), f.name


def test_coverage_only_fallback_still_runs_the_pipeline_when_the_generator_fails(tmp_path):
    bad = json.dumps({"regions": [{"name": "x", "rationale": "r", "ranges": {"mass_kg": [0.5, 0.51]}}]})
    settings = load_settings({"NEBIUS_API_KEY": "k", "NEBIUS_MODEL_FAST": "fast-m", "NEBIUS_MODEL_REASONING": "reason-m"})
    fake = FakeLLM([STRONG], gen_reply=bad)
    db = Database(":memory:")
    res = run_pipeline(settings, RuleRunner(), db, SeedLedger(db), PipelineConfig("t2", tmp_path, 5, n=250, shards=5), env={"ROBOPROOF_IMAGE_ID": "i"},
                       pricing={}, openai_client=fake)
    assert res["generator"]["source"] == "coverage_only_fallback" and res["generator"]["model"] is None
    assert res["generator_value"]["tgt"]["n"] == 0 and res["generator_value"]["cov"]["n"] == 250
    assert res["verdict"] in ("VERIFIED", "FAILED", "UNVERIFIED") and res["error"] is None


def test_recorded_runs_refuse_the_dev_cache(tmp_path):
    with pytest.raises(ValueError, match="LLM_DEV_CACHE"):
        run(tmp_path, [STRONG], LLM_DEV_CACHE="1")
