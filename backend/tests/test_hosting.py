"""Small-host settings: real CPU limit, host-mode defaults, the pipeline-only switch, retention, single-container serving. No model calls."""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import hosting
from app.live.api import install as install_live
from app.live.config import LiveConfig
from app.playground.api import install as install_playground
from app.playground.service import PlaygroundConfig

FAKE = Path(__file__).parent / "fake_pipeline.py"


def cg(tmp_path, **files):
    for name, text in files.items():
        p = tmp_path / name.replace("__", "/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp_path


def test_cpu_limit_from_cgroup_v2(tmp_path):
    assert hosting.cpu_quota(cg(tmp_path, **{"cpu.max": "50000 100000"})) == 0.5
    assert hosting.worker_count(tmp_path) == 1          # half a CPU still gets one worker, not the host's core count
    assert hosting.cpu_quota(cg(tmp_path, **{"cpu.max": "max 100000"})) is None


def test_cpu_limit_from_cgroup_v1_and_unlimited(tmp_path):
    d = cg(tmp_path, **{"cpu__cpu.cfs_quota_us": "200000", "cpu__cpu.cfs_period_us": "100000"})
    assert hosting.cpu_quota(d) == 2.0 and hosting.worker_count(d) <= 2
    assert hosting.cpu_quota(cg(tmp_path / "x", **{"cpu__cpu.cfs_quota_us": "-1", "cpu__cpu.cfs_period_us": "100000"})) is None
    assert hosting.worker_count(tmp_path / "nothing-here") >= 1  # no cgroup files at all (e.g. a laptop)


def test_memory_limit(tmp_path):
    assert hosting.memory_limit_bytes(cg(tmp_path, **{"memory.max": str(512 * 2**20)})) == 512 * 2**20
    assert hosting.memory_limit_bytes(cg(tmp_path / "u", **{"memory.max": "max"})) is None


def test_host_mode_defaults_and_overrides():
    assert hosting.max_sweep_n({}) == 200 and hosting.max_batch_rows({}) == 200
    host = {"ROBOPROOF_HOST_MODE": "1"}
    assert hosting.max_sweep_n(host) == 20 and hosting.max_batch_rows(host) == 20
    assert hosting.max_sweep_n({**host, "MAX_SWEEP_N": "30"}) == 30
    assert hosting.max_sweep_n({**host, "MAX_SWEEP_N": "9999"}) == 200      # never above the documented cap
    assert hosting.max_batch_rows({**host, "MAX_BATCH_ROWS": "abc"}) == 20   # junk falls back to the default
    assert hosting.max_sweep_n({"PLAYGROUND_MAX_SWEEP_N": "80"}) == 80       # the older name still works
    c = PlaygroundConfig.from_env({**host, "MAX_BATCH_ROWS": "20"})
    assert (c.max_sweep_n, c.max_batch_rows) == (20, 20)


def test_live_config_from_env(tmp_path):
    c = LiveConfig.from_env({"RUN_TIMEOUT_S": "240", "LIVE_PIPELINE_ENABLED": "0", "DATA_DIR": str(tmp_path), "LIVE_KEEP_RUNS": "5"})
    assert c.timeout_s == 240 and c.pipeline_enabled is False and c.keep_runs == 5 and c.runs_dir == tmp_path / "live_runs"
    assert LiveConfig.from_env({"LIVE_TIMEOUT_S": "99"}).timeout_s == 99
    assert LiveConfig.from_env({}).pipeline_enabled is True


def make(tmp_path, monkeypatch, **kw):
    monkeypatch.setenv("FAKE_MODE", "ok")
    cfg = LiveConfig(enabled=True, runs_dir=tmp_path / "live_runs", pipeline_script=FAKE, python_exe=sys.executable, poll_s=0.05, per_ip_per_hour=50, **kw)
    app = FastAPI()
    mgr = install_live(app, cfg)
    return app, TestClient(app), mgr


def test_pipeline_switch_disables_only_the_pipeline(tmp_path, monkeypatch):
    app, c, mgr = make(tmp_path, monkeypatch, pipeline_enabled=False)
    assert c.get("/api/live/status").json()["pipeline_enabled"] is False and c.get("/api/health").json()["pipeline_enabled"] is False
    r = c.post("/api/runs", json={})
    assert r.status_code == 503 and r.json()["error"] == "pipeline_disabled" and "locally" in r.json()["message"]
    assert not list((tmp_path / "live_runs").glob("live_*"))   # nothing was started or written
    # the playground keeps working, and analyze / interpret are still gated by LIVE_ENABLED, not by the pipeline switch
    install_playground(app, mgr, PlaygroundConfig(max_sweep_n=50, max_batch_rows=50))
    spec = c.get("/api/sim/spec").json()
    assert spec["max_sweep_n"] == 50 and spec["batch"]["max_rows"] == 50 and spec["analyze_available"] is True and spec["interpret_available"] is True


def test_batch_and_sweep_caps_follow_config(tmp_path, monkeypatch):
    app, c, mgr = make(tmp_path, monkeypatch)
    install_playground(app, mgr, PlaygroundConfig(max_sweep_n=10, max_batch_rows=2))
    assert c.post("/api/sim/sweep", json={"n": 11}).status_code == 422
    row = "0.2,0.8,0.05,0,0,0,0"
    head = "mass_kg,friction,size_m,pos_offset_x,pos_offset_y,sensor_noise_m,gripper_delay_steps"
    r = c.post("/api/sim/batch", json={"csv": "\n".join([head, row, row, row])})
    assert r.status_code == 413 and "At most 2 rows" in r.json()["message"]


def test_old_runs_are_pruned_to_keep_runs(tmp_path, monkeypatch):
    app, c, mgr = make(tmp_path, monkeypatch, keep_runs=3)
    runs = tmp_path / "live_runs"
    for i in range(6):
        d = runs / f"live_2026010{i}t000000_aaa{i}"
        d.mkdir(parents=True)
        (d / "meta.json").write_text('{"id": "x", "status": "finished", "created": "x"}')
    r = c.post("/api/runs", json={})
    assert r.status_code == 201
    names = sorted(p.name for p in runs.glob("live_*"))
    assert len(names) == 3 and r.json()["id"] in names and names[:2] == ["live_20260104t000000_aaa4", "live_20260105t000000_aaa5"]  # the two newest old runs are kept


def test_unknown_api_path_is_json_404_and_site_is_served(tmp_path, monkeypatch):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<html><title>site</title></html>")
    monkeypatch.setenv("FRONTEND_DIR", str(site))
    for m in [k for k in sys.modules if k == "app.api.main"]:
        del sys.modules[m]
    from app.api.main import app
    c = TestClient(app)
    assert c.get("/").status_code == 200 and "site" in c.get("/").text
    r = c.get("/api/does-not-exist")
    assert r.status_code == 404 and r.json()["error"] == "not_found"      # JSON, not the site's index.html
    assert c.get("/api/health").json()["status"] == "ok"
    del sys.modules["app.api.main"]


def test_prepare_data_dir_creates_live_runs(tmp_path):
    d = hosting.prepare_data_dir({"DATA_DIR": str(tmp_path / "rp")})
    assert (d / "live_runs").is_dir()
    assert hosting.data_dir({}) == Path(hosting.DEFAULT_DATA_DIR)


@pytest.mark.skipif(not Path("/proc/self/cgroup").exists(), reason="cgroups are a Linux thing")
def test_live_cgroup_values_are_sane():
    assert hosting.worker_count() >= 1 and hosting.effective_cpus() > 0


def test_startup_self_check_reports_a_broken_simulator(monkeypatch):
    import builtins
    from app.api import main
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "pybullet":
            raise ImportError("no pybullet in this test")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(RuntimeError, match="STARTUP SELF-CHECK FAILED"):
        main.startup_self_check()


# ---------------------------------------------------------------- timeouts, verify switch, worker counts (free host with about 0.1 CPU)
def test_every_timeout_is_configurable_and_host_mode_is_roomier():
    c = PlaygroundConfig.from_env({})
    assert (c.scenario_timeout_s, c.sweep_timeout_s, c.batch_timeout_s, c.verify_timeout_s) == (20.0, 60.0, 60.0, 54.0)
    assert c.interpret_timeout_s is None and c.analyze_timeout_s is None and c.verify_enabled is True
    h = PlaygroundConfig.from_env({"ROBOPROOF_HOST_MODE": "1"})
    assert (h.scenario_timeout_s, h.sweep_timeout_s, h.batch_timeout_s) == (30.0, 90.0, 90.0)
    e = PlaygroundConfig.from_env({"SCENARIO_TIMEOUT_S": "7", "SWEEP_TIMEOUT_S": "33", "BATCH_TIMEOUT_S": "44", "VERIFY_TIMEOUT_S": "99",
                                   "INTERPRET_TIMEOUT_S": "12", "ANALYZE_TIMEOUT_S": "88", "VERIFY_ENABLED": "0"})
    assert (e.scenario_timeout_s, e.sweep_timeout_s, e.batch_timeout_s, e.verify_timeout_s, e.interpret_timeout_s, e.analyze_timeout_s, e.verify_enabled) == (7, 33, 44, 99, 12, 88, False)
    assert PlaygroundConfig.from_env({"PLAYGROUND_SWEEP_TIMEOUT_S": "40"}).sweep_timeout_s == 40  # the older names still work


def test_slow_message_is_plain_on_a_free_host():
    m = hosting.slow_message(30, "the simulation", {"ROBOPROOF_HOST_MODE": "1"})
    assert "took too long on the free host" in m and "30 s" in m and "locally" in m
    assert "free host" not in hosting.slow_message(30, "the simulation", {})


def test_a_timed_out_simulation_says_so_on_a_free_host(monkeypatch):
    from app.core.schemas import Policy, Scenario
    from app.playground.service import PlaygroundError, run_scenario_isolated
    monkeypatch.setenv("ROBOPROOF_HOST_MODE", "1")
    scn = Scenario(id="t", seed=200001, tag="t", mass_kg=0.2, friction=0.8, size_m=0.05, pos_offset_x=0, pos_offset_y=0, sensor_noise_m=0, gripper_delay_steps=0)
    with pytest.raises(PlaygroundError) as ei:
        run_scenario_isolated(Policy(), scn, 0.0001)
    assert ei.value.status == 504 and "took too long on the free host" in ei.value.message


def test_verify_can_be_switched_off(tmp_path, monkeypatch):
    app, c, mgr = make(tmp_path, monkeypatch)
    install_playground(app, mgr, PlaygroundConfig(verify_enabled=False))
    assert c.get("/api/health").json()["verify_enabled"] is False and c.get("/api/sim/spec").json()["verify_enabled"] is False
    ids = c.get("/api/verify").json()["runs"]
    rid = ids[0] if ids else "official_01_seed3101"
    r = c.post(f"/api/verify/{rid}")
    if ids:
        assert r.status_code == 503 and r.json()["error"] == "verify_disabled" and "locally or on a larger host" in r.json()["message"] and r.json()["commands"]
    # the cheap single-scenario re-run is not the expensive re-simulation and stays available
    assert c.get("/api/verify").status_code == 200


def test_interpret_passes_its_timeout_and_reports_a_slow_model():
    from app.llm.client import LLMTransportError
    from app.playground.interpret import InterpretError, interpret

    class Slow:
        seen = []

        def complete_json(self, *a, **k):
            Slow.seen.append(k["timeout"])
            raise LLMTransportError("timed out")
    with pytest.raises(InterpretError) as ei:
        interpret(Slow(), "a heavy cube", "m1", "m2", 7.0)
    assert Slow.seen == [7.0, 7.0] and "took too long (limit 7 s)" in ei.value.message


def test_every_simulating_path_gets_the_container_worker_count(monkeypatch):
    """Sweep, batch, verify (and the pipeline pool, see scripts/run_live_pipeline.py) must never fall back to the host's core count."""
    import ast
    import app.runner.local as local
    from app.playground.service import run_sweep_isolated
    from app.verify import core
    monkeypatch.setattr(hosting, "worker_count", lambda cgroup=hosting.CGROUP: 1)
    seen = []

    class Fake:
        def __init__(self, max_workers=None, **kw):
            seen.append(max_workers)

        def run(self, *a, **k):
            from types import SimpleNamespace
            return SimpleNamespace(complete=True, results=[])
    monkeypatch.setattr(local, "LocalRunner", Fake)
    run_sweep_isolated(None, [], 5.0)
    core.default_runner(5.0)
    assert seen == [1, 1]
    root = Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for f in root.rglob("*.py"):
        if "runner" in f.parts:
            continue
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "LocalRunner" and not any(k.arg == "max_workers" for k in node.keywords):
                offenders.append(f"{f.name}:{node.lineno}")
    assert not offenders, offenders
    src = (root.parents[1] / "scripts" / "run_live_pipeline.py").read_text(encoding="utf-8")
    assert "os.cpu_count = worker_count" in src
