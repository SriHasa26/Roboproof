"""Playground tests. The simulator is replaced by fakes unless a test says otherwise, so none of these make an LLM call or spend credits."""
import multiprocessing as mp
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.bounds import POLICY_BOUNDS, SCENARIO_BOUNDS
from app.core.schemas import PATCHABLE_PARAMS, FailureReason, Result
from app.live.config import LiveConfig
from app.live.manager import RunManager
from app.playground import service as svc_mod
from app.playground.api import install
from app.playground.service import PlaygroundConfig, PlaygroundError

GOOD_SCN = {"mass_kg": 0.2, "friction": 0.8, "size_m": 0.05, "pos_offset_x": 0.0, "pos_offset_y": 0.0, "sensor_noise_m": 0.0, "gripper_delay_steps": 0}
JSON = {"Content-Type": "application/json"}


def fake_scenario(policy, scenario, timeout_s):
    ok = scenario.mass_kg < 0.5
    return {"result": {"scenario_id": scenario.id, "seed": scenario.seed, "success": ok, "collision": False, "completion_time_s": 3.0, "final_place_error_m": 0.01,
                       "max_slip_m": 0.0, "failure_reason": None if ok else "SLIPPED_ON_LIFT", "trajectory_summary": {}},
            "trajectory": {"dt": 0.025, "frames": [], "n_frames_original": 0}, "world": {}}


def fake_sweep(policy, scenarios, timeout_s):
    out = []
    for s in scenarios:
        ok = s.mass_kg < 0.5 or policy.grip_force > 40
        out.append(Result(scenario_id=s.id, seed=s.seed, success=ok, collision=False, completion_time_s=3.0, final_place_error_m=0.01, max_slip_m=0.0,
                          failure_reason=None if ok else FailureReason.SLIPPED_ON_LIFT))
    return out


def make(tmp_path, scenario_fn=fake_scenario, sweep_fn=fake_sweep, live_enabled=False, **kw):
    pcfg = PlaygroundConfig(**kw)
    live = RunManager(LiveConfig(enabled=live_enabled, runs_dir=tmp_path / "lr", access_code=""))
    app = FastAPI()
    svc = install(app, live, pcfg)
    svc.scenario_fn, svc.sweep_fn = scenario_fn, sweep_fn
    return TestClient(app), svc, live


def test_spec_comes_from_the_frozen_config(tmp_path):
    c, *_ = make(tmp_path)
    s = c.get("/api/sim/spec").json()
    assert {p["name"]: (p["min"], p["max"], p["default"]) for p in s["policy"]} == dict(POLICY_BOUNDS)
    assert {p["name"]: (p["min"], p["max"]) for p in s["scenario"]} == dict(SCENARIO_BOUNDS)
    assert {p["name"] for p in s["policy"] if p["tunable"]} == set(PATCHABLE_PARAMS)
    assert {p["name"] for p in s["policy"] if not p["tunable"]} == {"approach_speed", "place_slow_factor"}
    assert s["max_sweep_n"] == 200 and s["seed"]["max"] < 800_000 and "not a gate verdict" in s["label"]
    for pr in s["presets"]:  # presets are inputs and must be valid
        if pr["scenario"]:
            assert c.post("/api/sim/scenario", json={"scenario": pr["scenario"]}).status_code == 200


@pytest.mark.parametrize("patch", [
    {"mass_kg": 5.0}, {"mass_kg": 0.01}, {"friction": 2.0}, {"size_m": 0.5}, {"sensor_noise_m": -0.1}, {"gripper_delay_steps": 21},
    {"gripper_delay_steps": 2.5}, {"mass_kg": "heavy"}, {"mass_kg": None}, {"pos_offset_x": 1}])
def test_scenario_bounds_rejected(tmp_path, patch):
    c, *_ = make(tmp_path)
    assert c.post("/api/sim/scenario", json={"scenario": {**GOOD_SCN, **patch}}).status_code == 422


def _raw(scn_extra="", pol=""):
    base = '{"mass_kg": 0.2, "friction": 0.8, "size_m": 0.05, "pos_offset_x": 0, "pos_offset_y": 0, "sensor_noise_m": 0, "gripper_delay_steps": 0}'
    return '{"scenario": ' + base.replace('"mass_kg": 0.2', scn_extra or '"mass_kg": 0.2') + pol + '}'


@pytest.mark.parametrize("raw", [_raw('"mass_kg": NaN'), _raw('"mass_kg": Infinity'), _raw('"mass_kg": -Infinity'), _raw(pol=', "policy": {"grip_force": NaN}'),
                                 _raw(pol=', "policy": {"lift_speed": Infinity}')])
def test_nan_and_infinity_rejected(tmp_path, raw):
    c, *_ = make(tmp_path)
    assert c.post("/api/sim/scenario", content=raw, headers=JSON).status_code == 422


@pytest.mark.parametrize("pol", [{"grip_force": 500}, {"grip_force": 1}, {"retry_count": 4}, {"retry_count": 1.5}, {"grasp_hold_steps": -1}, {"unknown": 1}, {"approach_speed": 9}])
def test_policy_bounds_rejected(tmp_path, pol):
    c, *_ = make(tmp_path)
    assert c.post("/api/sim/scenario", json={"scenario": GOOD_SCN, "policy": pol}).status_code == 422


@pytest.mark.parametrize("seed", [900_000, 900_001, 800_000, 850_000, 99_999, 0, -5, 10**9])
def test_held_out_rehearsal_and_dev_seeds_rejected(tmp_path, seed):
    c, *_ = make(tmp_path)
    assert c.post("/api/sim/scenario", json={"scenario": GOOD_SCN, "seed": seed}).status_code == 422
    assert c.post("/api/sim/sweep", json={"n": 10, "seed": seed}).status_code == 422


def test_extra_fields_rejected(tmp_path):
    c, *_ = make(tmp_path)
    for extra in ({"official": True}, {"held_out": True}, {"command": "ls"}):
        assert c.post("/api/sim/scenario", json={"scenario": GOOD_SCN, **extra}).status_code == 422
        assert c.post("/api/sim/sweep", json={"n": 5, **extra}).status_code == 422


def test_valid_scenario_and_seed_boundaries(tmp_path):
    c, *_ = make(tmp_path)
    r = c.post("/api/sim/scenario", json={"scenario": GOOD_SCN, "seed": 799_999})
    assert r.status_code == 200 and r.json()["seed"] == 799_999 and "not a gate verdict" in r.json()["mode"]
    assert c.post("/api/sim/scenario", json={"scenario": GOOD_SCN, "seed": 100_000}).status_code == 200


def test_sweep_cap_and_seed_range(tmp_path):
    c, svc, _ = make(tmp_path)
    assert c.post("/api/sim/sweep", json={"n": 201}).status_code == 422
    assert c.post("/api/sim/sweep", json={"n": 0}).status_code == 422
    r = c.post("/api/sim/sweep", json={"n": 200, "seed": 799_999})
    assert r.status_code == 200
    b = r.json()
    assert len(b["rows"]["ids"]) == 200 and max(b["rows"]["seed"]) < 800_000 and min(b["rows"]["seed"]) >= 200_000
    assert b["metrics"]["n"] == 200 and len(b["metrics"]["pass_rate_ci95"]) == 2 and b["default_metrics"]["n"] == 200
    assert len(b["rows"]["default_ok"]) == 200 and all(x["axis"] in SCENARIO_BOUNDS for x in b["evidence_bins"])


def test_sweep_same_input_same_output_and_default_is_cached(tmp_path):
    calls = []

    def counting(policy, scns, t):
        calls.append(policy.grip_force)
        return fake_sweep(policy, scns, t)
    c, *_ = make(tmp_path, sweep_fn=counting, rate_sweep_per_10min=10)
    body = {"n": 20, "seed": 123_456, "policy": {"grip_force": 60}}
    a, b = c.post("/api/sim/sweep", json=body).json(), c.post("/api/sim/sweep", json=body).json()
    for k in ("metrics", "default_metrics", "rows", "evidence_bins"):
        assert a[k] == b[k]
    assert calls == [60.0, 15.0, 60.0]  # the default policy's results on these scenarios are cached by (n, seed)


def test_kill_switch(tmp_path):
    c, *_ = make(tmp_path, enabled=False)
    assert c.post("/api/sim/scenario", json={"scenario": GOOD_SCN}).status_code == 503
    assert c.post("/api/sim/sweep", json={"n": 5}).status_code == 503
    assert c.get("/api/sim/spec").json()["enabled"] is False


def test_rate_limit_per_ip(tmp_path):
    c, *_ = make(tmp_path, rate_scenario_per_min=2, rate_sweep_per_10min=1)
    assert [c.post("/api/sim/scenario", json={"scenario": GOOD_SCN}).status_code for _ in range(3)] == [200, 200, 429]
    assert c.post("/api/sim/sweep", json={"n": 5}).status_code == 200
    r = c.post("/api/sim/sweep", json={"n": 5})
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"


def test_concurrency_cap(tmp_path):
    gate = threading.Event()

    def slow(policy, scenario, t):
        gate.wait(5)
        return fake_scenario(policy, scenario, t)
    c, *_ = make(tmp_path, scenario_fn=slow, max_concurrent=2, rate_scenario_per_min=100)
    codes: list[int] = []
    ts = [threading.Thread(target=lambda: codes.append(c.post("/api/sim/scenario", json={"scenario": GOOD_SCN}).status_code)) for _ in range(2)]
    for t in ts:
        t.start()
    time.sleep(0.6)
    third = c.post("/api/sim/scenario", json={"scenario": GOOD_SCN})
    assert third.status_code == 503 and third.json()["error"] == "busy"
    gate.set()
    for t in ts:
        t.join()
    assert sorted(codes) == [200, 200]
    assert c.post("/api/sim/scenario", json={"scenario": GOOD_SCN}).status_code == 200  # slots are released


def test_timeout_maps_to_504(tmp_path):
    def boom(policy, scenario, t):
        raise PlaygroundError(504, "timeout", "too slow")
    c, *_ = make(tmp_path, scenario_fn=boom)
    r = c.post("/api/sim/scenario", json={"scenario": GOOD_SCN})
    assert r.status_code == 504 and r.json()["error"] == "timeout"


@pytest.mark.skipif("fork" not in mp.get_all_start_methods(), reason="needs fork so the patched job reaches the child")
def test_isolated_run_is_killed_on_timeout(monkeypatch):
    monkeypatch.setattr(svc_mod, "_scenario_job", lambda *a: time.sleep(30))
    from app.core.schemas import Policy, Scenario
    scn = Scenario(id="pg-1", seed=200_001, **GOOD_SCN)
    t0 = time.time()
    with pytest.raises(PlaygroundError) as e:
        svc_mod.run_scenario_isolated(Policy(), scn, 1.0)
    assert e.value.status == 504 and time.time() - t0 < 10


def test_analyze_is_guarded(tmp_path):
    c, svc, live = make(tmp_path, live_enabled=False)
    sid = c.post("/api/sim/sweep", json={"n": 30, "seed": 111_111}).json()["sweep_id"]
    assert c.post("/api/sim/analyze", json={"sweep_id": sid}).status_code == 503  # live backend disabled: no spend possible
    live.cfg.enabled, live.cfg.access_code = True, "letmein"
    assert c.post("/api/sim/analyze", json={"sweep_id": sid}).status_code == 401
    live.cfg.access_code, live.cfg.daily_usd_cap = "", 0.01
    r = c.post("/api/sim/analyze", json={"sweep_id": sid})  # reservation 0.03 would exceed the 0.01 cap
    assert r.status_code == 429 and r.json()["error"] == "daily_usd_cap"
    assert c.post("/api/sim/analyze", json={"sweep_id": "../etc"}).status_code == 422


def test_analyze_needs_enough_failures(tmp_path):
    def all_pass(p, s, t):
        return [Result(scenario_id=x.id, seed=x.seed, success=True, collision=False, completion_time_s=3.0, final_place_error_m=0.0, max_slip_m=0.0) for x in s]
    c, svc, live = make(tmp_path, sweep_fn=all_pass, live_enabled=True)
    sid = c.post("/api/sim/sweep", json={"n": 20, "seed": 111_111}).json()["sweep_id"]
    r = c.post("/api/sim/analyze", json={"sweep_id": sid})
    assert r.status_code == 422 and r.json()["error"] == "too_few_failures"


def test_playground_code_never_names_held_out_apis():
    from pathlib import Path
    for f in Path(svc_mod.__file__).parent.glob("*.py"):
        t = f.read_text(encoding="utf-8")
        assert "held_out=True" not in t and "HELDOUT_SEED_BASE" not in t, f.name


def test_real_simulator_is_deterministic_and_returns_a_trajectory(tmp_path):
    pytest.importorskip("pybullet")
    c, svc, _ = make(tmp_path, scenario_fn=svc_mod.run_scenario_isolated)
    body = {"scenario": GOOD_SCN, "policy": {"grip_force": 40}, "seed": 300_005}
    a, b = c.post("/api/sim/scenario", json=body).json(), c.post("/api/sim/scenario", json=body).json()
    assert a["result"] == b["result"] and a["trajectory"]["frames"] == b["trajectory"]["frames"]
    assert 0 < len(a["trajectory"]["frames"]) <= 300 and {"palm", "cube", "cube_q", "gap", "q"} <= set(a["trajectory"]["frames"][0])
    assert a["result"]["scenario_id"] == "pg-300005" and a["explanation"]
