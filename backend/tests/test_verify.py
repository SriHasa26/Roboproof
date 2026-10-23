"""The verifier must catch tampering and refuse held-out data. Temp copies are used for every alteration; the real recorded runs are never written."""
import json
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.schemas import Result
from app.live.config import LiveConfig
from app.live.manager import RunManager
from app.playground.service import PlaygroundConfig, PlaygroundService
from app.verify import api as vapi
from app.verify import core
from app.verify.core import MISMATCH, integrity_rows, jl, recompute_run, resimulate_run

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL = ROOT / "recorded_runs" / "official_001"
RUN = "official_03_seed3303"
pytestmark = pytest.mark.skipif(not (OFFICIAL / RUN / "summary.json").exists(), reason="recorded official runs are not in this checkout")


def bad(rows):
    return {r.id for r in rows if r.status == MISMATCH}


def copy_run(tmp_path, name=RUN):
    dst = tmp_path / "recorded_runs" / "official_001" / name
    shutil.copytree(OFFICIAL / name, dst)
    return dst


def edit(path: Path, fn):
    d = json.loads(path.read_text(encoding="utf-8"))
    fn(d)
    path.write_text(json.dumps(d), encoding="utf-8")


def test_untouched_official_runs_recompute_clean():
    for d in sorted(OFFICIAL.glob("official_0*")):
        rows = recompute_run(d)
        assert bad(rows) == set(), (d.name, bad(rows))
        assert len(rows) >= 25


def test_altered_gate_count_is_detected(tmp_path):
    d = copy_run(tmp_path)
    edit(d / "gate_report.json", lambda g: next(c for c in g["report"]["checks"] if c["id"] == "G3")["observed"].__setitem__("fixed", 5))
    assert {"G3", "G3_inputs"} & bad(recompute_run(d)) or bad(recompute_run(d)) != set()
    assert bad(recompute_run(d)) != set()


def test_altered_held_out_count_is_detected(tmp_path):
    d = copy_run(tmp_path)
    edit(d / "gate_report.json", lambda g: next(c for c in g["report"]["checks"] if c["id"] == "G5")["observed"].__setitem__("patched_passes", 399))
    assert {"G5_lower", "G5_impr", "W_ver_after"} <= bad(recompute_run(d))


def test_flipped_stored_baseline_result_is_detected(tmp_path):
    d = copy_run(tmp_path)

    def flip(b):
        r = next(x for x in b["results"] if x["success"])
        r["success"], r["failure_reason"] = False, "MISSED_GRASP"
    edit(d / "baseline_results.json", flip)
    assert {"base_rate", "G4_prev"} & bad(recompute_run(d))


def test_altered_verdict_and_status_are_detected(tmp_path):
    d = copy_run(tmp_path)
    edit(d / "summary.json", lambda s: s.__setitem__("verdict", "VERIFIED"))
    assert "verdict" in bad(recompute_run(d))  # official_03 is FAILED (G5), so a stored VERIFIED cannot be reproduced
    d2 = copy_run(tmp_path / "b", "official_01_seed3101")
    edit(d2 / "gate_report.json", lambda g: next(c for c in g["report"]["checks"] if c["id"] == "G4").__setitem__("status", "fail"))
    assert "G4" in bad(recompute_run(d2))


def test_altered_threshold_in_stored_report_is_detected(tmp_path):
    d = copy_run(tmp_path)
    edit(d / "gate_report.json", lambda g: next(c for c in g["report"]["checks"] if c["id"] == "G5")["threshold"].__setitem__("min_pass_rate", 0.5))
    assert "cfg" in bad(recompute_run(d))


def test_duplicated_held_out_block_is_detected(tmp_path):
    a, b = copy_run(tmp_path, "official_01_seed3101"), copy_run(tmp_path, "official_02_seed3202")
    edit(b / "summary.json", lambda s: s["verification_set"].__setitem__("start", 900000))  # same block as run 1
    assert "blocks_distinct" in bad(integrity_rows(tmp_path, [a, b], None, "", git=SimpleNamespace(available=False)))


def test_block_outside_the_held_out_range_is_detected(tmp_path):
    a = copy_run(tmp_path, "official_01_seed3101")
    edit(a / "summary.json", lambda s: s["verification_set"].__setitem__("start", 850000))  # a rehearsal-block start
    assert "blocks_range" in bad(integrity_rows(tmp_path, [a], None, "", git=SimpleNamespace(available=False)))


def test_ledger_row_problems_are_detected(tmp_path):
    a = copy_run(tmp_path, "official_01_seed3101")
    rid = jl(a / "summary.json")["run_id"]
    row = {"run_id": rid, "block_name": "held_out", "start": 900000, "count": 400, "status": "used"}
    assert not bad(integrity_rows(tmp_path, [a], [row], "x", git=SimpleNamespace(available=False)))
    assert f"ledger_{rid}" in bad(integrity_rows(tmp_path, [a], [{**row, "status": "allocated"}], "x", git=SimpleNamespace(available=False)))
    assert f"ledger_{rid}" in bad(integrity_rows(tmp_path, [a], [row, {**row, "status": "used"}], "x", git=SimpleNamespace(available=False)))  # allocated twice
    other = {"run_id": "someone_else", "block_name": "held_out", "start": 900100, "count": 50, "status": "used"}
    assert "ledger_others" in bad(integrity_rows(tmp_path, [a], [row, other], "x", git=SimpleNamespace(available=False)))


def test_protocol_commit_dated_after_a_run_is_detected(tmp_path):
    a = copy_run(tmp_path, "official_01_seed3101")
    prov = jl(a / "summary.json")["provenance"]
    started = datetime.strptime(jl(a / "LABEL.json")["started"], "%Y-%m-%d %H:%M:%S")

    def fake_git(when):
        def g(*args):
            if args[0] == "log":
                return 0, when
            if args[0] in ("merge-base", "diff"):
                return 0, ""
            if args[0] == "show":
                return 0, f"pipeline_hash {prov['pipeline_hash']}\n"
            return 0, prov["tag_commit"]
        g.available = True
        return g
    before = f"{started.year - 1}-01-01T00:00:00+00:00"
    after = f"{started.year + 1}-01-01T00:00:00+00:00"
    assert "protocol_time" not in bad(integrity_rows(tmp_path, [a], None, "", git=fake_git(before)))
    assert "protocol_time" in bad(integrity_rows(tmp_path, [a], None, "", git=fake_git(after)))


def test_hash_recorded_in_the_run_must_match_the_commit(tmp_path):
    a = copy_run(tmp_path, "official_01_seed3101")
    prov = jl(a / "summary.json")["provenance"]

    def g(*args):
        return (0, "pipeline_hash deadbeef\n") if args[0] == "show" else (0, "2000-01-01T00:00:00+00:00" if args[0] == "log" else prov["tag_commit"])
    g.available = True
    assert f"freeze_{jl(a / 'summary.json')['run_id']}" in bad(integrity_rows(tmp_path, [a], None, "", git=g))


# ------------------------------------------------------------------ re-simulation never touches held-out seeds
class SpyRunner:
    """Replays the stored baseline for any policy and records every seed it is asked to run."""
    seeds: list[int] = []

    def __init__(self, run_dir):
        self.base = [Result(**r) for r in jl(run_dir / "baseline_results.json")["results"]]

    def run(self, policy, scenarios, shards=10, held_out=False):
        assert held_out is False
        SpyRunner.seeds += [s.seed for s in scenarios]
        return SimpleNamespace(complete=True, results=self.base)


def test_resimulation_uses_only_analysis_set_dev_seeds():
    d = OFFICIAL / RUN
    SpyRunner.seeds = []
    rows = resimulate_run(d, runner_factory=lambda t: SpyRunner(d))
    assert SpyRunner.seeds and max(SpyRunner.seeds) < 800_000 and min(SpyRunner.seeds) >= 1000
    assert any(r.id == "base_same" and r.status == "match" for r in rows)  # the stored baseline replays identically


def test_tampered_analysis_set_with_a_held_out_seed_is_refused(tmp_path):
    d = copy_run(tmp_path)
    edit(d / "analysis_set.json", lambda a: a["scenarios"][0].__setitem__("seed", 900_001))
    with pytest.raises(AssertionError):
        resimulate_run(d, runner_factory=lambda t: SpyRunner(d))


def test_incomplete_resimulation_is_an_error_not_a_pass(tmp_path):
    d = OFFICIAL / RUN
    r = SimpleNamespace(run=lambda *a, **k: SimpleNamespace(complete=False, results=[]))
    with pytest.raises(RuntimeError):
        resimulate_run(d, runner_factory=lambda t: r)


# ------------------------------------------------------------------ endpoint
def make_client(tmp_path, verify_fn=None, **kw):
    live = RunManager(LiveConfig(enabled=False, runs_dir=tmp_path / "lr"))
    svc = PlaygroundService(PlaygroundConfig(**kw))
    app = FastAPI()
    calls = []

    def fn(root, **k):
        calls.append(k)
        return (verify_fn or (lambda root, **k: core.verify_all(ROOT, resim=False, only=k.get("only"))))(root, **k)
    vapi.install(app, svc, live, verify_fn=fn)
    return TestClient(app), calls, svc


def test_endpoint_lists_and_verifies_only_known_official_runs(tmp_path):
    c, calls, _ = make_client(tmp_path)
    assert RUN in c.get("/api/verify").json()["runs"]
    r = c.post(f"/api/verify/{RUN}")
    assert r.status_code == 200
    b = r.json()
    assert b["run_id"] == RUN and b["tally"]["mismatch"] == 0 and b["rows"] and "held-out seeds never used" in b["mode"] and calls[0]["resim"] is True
    for bad_id in ("official_99_seed1", "../official_01_seed3101", "official_01_seed3101/../x", "rehearsal_001", "official_03_seed3303%00", "OFFICIAL_03_seed3303"):
        assert c.post(f"/api/verify/{bad_id}").status_code in (404, 405), bad_id
    assert len(calls) == 1  # nothing ran for the refused ids


def test_endpoint_cannot_be_told_to_use_held_out_data(tmp_path):
    c, calls, _ = make_client(tmp_path)
    r = c.post(f"/api/verify/{RUN}", json={"held_out": True, "seed": 900000, "resim": False})
    assert r.status_code == 200 and calls[0]["resim"] is True and calls[0]["only"] == RUN  # a body is ignored: the id is the only input


def test_endpoint_guards(tmp_path):
    c, _, _ = make_client(tmp_path, rate_sweep_per_10min=100)
    assert [c.post(f"/api/verify/{RUN}").status_code for _ in range(6)] == [200] * 6
    assert c.post(f"/api/verify/{RUN}").status_code == 429
    c, _, _ = make_client(tmp_path, enabled=False)
    assert c.post(f"/api/verify/{RUN}").status_code == 503
    c, _, svc = make_client(tmp_path)
    for _ in range(svc.cfg.max_concurrent):
        assert svc.slots.acquire(blocking=False)
    r = c.post(f"/api/verify/{RUN}")
    assert r.status_code == 503 and r.json()["error"] == "busy"


def test_endpoint_timeout_maps_to_504(tmp_path):
    def boom(root, **k):
        raise RuntimeError("shard timed out")
    c, _, _ = make_client(tmp_path, verify_fn=boom)
    assert c.post(f"/api/verify/{RUN}").status_code == 504


def test_verifier_code_never_names_held_out_apis():
    for f in Path(core.__file__).parent.glob("*.py"):
        t = f.read_text(encoding="utf-8")
        assert "held_out=True" not in t and "HELDOUT_SEED_BASE" not in t, f.name


# ------------------------------------------------------------------ the real thing (needs the simulator)
def test_real_resimulation_matches_stored_numbers_and_is_deterministic():
    pytest.importorskip("pybullet")
    a = core.verify_all(ROOT, resim=True, only=RUN, timeout_s=120)
    b = core.verify_all(ROOT, resim=True, only=RUN, timeout_s=120)
    strip = lambda rows: [{k: v for k, v in r.items() if r["id"] != "elapsed"} for r in rows]  # noqa: E731
    assert strip(a["runs"][RUN]) == strip(b["runs"][RUN])
    assert not [r for r in a["runs"][RUN] if r["status"] == MISMATCH], [r for r in a["runs"][RUN] if r["status"] == MISMATCH]
    assert any(r["group"] == "resimulate" and r["id"] == "base_same" and r["status"] == "match" for r in a["runs"][RUN])


# ------------------------------------------------------------------ "Re-run in Playground": one stored scenario, its stored (dev) seed
def make_rerun_client(tmp_path, scenario_fn):
    c, calls, svc = make_client(tmp_path, rate_sweep_per_10min=100)
    svc.scenario_fn = scenario_fn
    return c, svc


def stored_default(scn_id):
    return next(r for r in jl(OFFICIAL / RUN / "baseline_results.json")["results"] if r["scenario_id"] == scn_id)


def replaying_fn(seen):
    from app.core.schemas import Policy

    def fn(policy, scenario, timeout):
        seen.append((policy == Policy(), scenario.seed))
        res = dict(stored_default(scenario.id)) if policy == Policy() else {**stored_default(scenario.id), "success": True, "failure_reason": None}
        return {"result": res, "trajectory": {"dt": 0.025, "frames": []}, "world": {}}
    return fn


def test_rerun_lists_failing_scenarios_and_the_final_patch(tmp_path):
    c, _ = make_rerun_client(tmp_path, replaying_fn([]))
    b = c.get(f"/api/verify/{RUN}/scenarios").json()
    assert b["failing"] and b["n_failing"] >= len(b["failing"]) and set(b["final_patch"]) >= {"grip_force", "lift_speed"}
    assert b["failing"][0]["targeted"] is True  # targeted failures first
    assert c.get("/api/verify/official_99_seed1/scenarios").status_code == 404


def test_rerun_uses_the_stored_dev_seed_and_compares_with_the_stored_result(tmp_path):
    seen = []
    c, _ = make_rerun_client(tmp_path, replaying_fn(seen))
    sid = c.get(f"/api/verify/{RUN}/scenarios").json()["failing"][0]["id"]
    r = c.post(f"/api/verify/{RUN}/rerun", json={"scenario_id": sid})
    assert r.status_code == 200
    b = r.json()
    assert b["matches_stored"] is True and b["default"]["result"]["success"] is False and b["patched"]["result"]["success"] is True
    stored_seed = next(s["seed"] for s in jl(OFFICIAL / RUN / "analysis_set.json")["scenarios"] if s["id"] == sid)
    assert b["seed"] == stored_seed < 100_000 and seen == [(True, stored_seed), (False, stored_seed)]  # a dev seed, taken from the stored data


def test_rerun_flags_a_result_that_differs_from_the_stored_one(tmp_path):
    def liar(policy, scenario, timeout):
        res = dict(stored_default(scenario.id))
        res["completion_time_s"] = 99.0
        return {"result": res, "trajectory": {"dt": 0.025, "frames": []}, "world": {}}
    c, _ = make_rerun_client(tmp_path, liar)
    sid = c.get(f"/api/verify/{RUN}/scenarios").json()["failing"][0]["id"]
    assert c.post(f"/api/verify/{RUN}/rerun", json={"scenario_id": sid}).json()["matches_stored"] is False


def test_rerun_refuses_unknown_scenarios_runs_and_client_seeds(tmp_path):
    seen = []
    c, _ = make_rerun_client(tmp_path, replaying_fn(seen))
    assert c.post(f"/api/verify/{RUN}/rerun", json={"scenario_id": "cov-99999"}).status_code == 404
    assert c.post(f"/api/verify/official_99_seed1/rerun", json={"scenario_id": "cov-1000"}).status_code == 404
    for body in ({"scenario_id": "cov-1000", "seed": 900000}, {"scenario_id": "cov-1000", "policy": {"grip_force": 80}}, {"scenario_id": "../x"}, {"scenario_id": "a" * 41}, {}):
        assert c.post(f"/api/verify/{RUN}/rerun", json=body).status_code == 422, body
    assert seen == []  # nothing ran


def test_rerun_refuses_a_tampered_held_out_seed(tmp_path, monkeypatch):
    root = tmp_path / "root"
    d = root / "recorded_runs" / "official_001" / RUN
    shutil.copytree(OFFICIAL / RUN, d)
    edit(d / "analysis_set.json", lambda a: a["scenarios"][0].__setitem__("seed", 900_005))
    sid = jl(d / "analysis_set.json")["scenarios"][0]["id"]
    live = RunManager(LiveConfig(enabled=False, runs_dir=tmp_path / "lr"))
    svc = PlaygroundService(PlaygroundConfig())
    seen = []
    svc.scenario_fn = replaying_fn(seen)
    app = FastAPI()
    vapi.install(app, svc, live, root=root)
    r = TestClient(app).post(f"/api/verify/{RUN}/rerun", json={"scenario_id": sid})
    assert r.status_code == 403 and seen == []
