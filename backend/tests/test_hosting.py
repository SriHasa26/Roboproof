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
    assert hosting.max_sweep_n(host) == 50 and hosting.max_batch_rows(host) == 50
    assert hosting.max_sweep_n({**host, "MAX_SWEEP_N": "30"}) == 30
    assert hosting.max_sweep_n({**host, "MAX_SWEEP_N": "9999"}) == 200      # never above the documented cap
    assert hosting.max_batch_rows({**host, "MAX_BATCH_ROWS": "abc"}) == 50   # junk falls back to the default
    assert hosting.max_sweep_n({"PLAYGROUND_MAX_SWEEP_N": "80"}) == 80       # the older name still works
    c = PlaygroundConfig.from_env({**host, "MAX_BATCH_ROWS": "20"})
    assert (c.max_sweep_n, c.max_batch_rows) == (50, 20)


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
