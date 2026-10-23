"""Live-service tests. They use tests/fake_pipeline.py in place of the real pipeline: no model calls, no simulation, no credits."""
import json
import os
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.live.api import install
from app.live.config import LiveConfig
from app.live.scrub import scrub

FAKE = Path(__file__).parent / "fake_pipeline.py"
SECRET = "sk-test-secret-1234567890"


def make(tmp_path, monkeypatch, mode="ok", **kw):
    monkeypatch.setenv("NEBIUS_API_KEY", SECRET)
    monkeypatch.setenv("FAKE_MODE", mode)
    cfg = LiveConfig(enabled=True, runs_dir=tmp_path / "live_runs", pipeline_script=FAKE, python_exe=sys.executable, poll_s=0.05, per_ip_per_hour=50, **kw)
    app = FastAPI()
    mgr = install(app, cfg)
    return TestClient(app), mgr, cfg


def wait(client, rid, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        m = client.get(f"/api/runs/{rid}").json()
        if m["status"] in ("finished", "cancelled", "timeout", "error"):
            return m
        time.sleep(0.1)
    raise AssertionError("run did not end")


def sse(client, rid, headers=None):
    with client.stream("GET", f"/api/runs/{rid}/events", headers=headers or {}) as r:
        assert r.status_code == 200
        out, ev = [], None
        for line in r.iter_lines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
        return out


def test_health_and_status(tmp_path, monkeypatch):
    c, _, _ = make(tmp_path, monkeypatch)
    assert c.get("/api/health").json()["status"] == "ok"
    s = c.get("/api/live/status").json()
    assert s["enabled"] and not s["busy"] and s["runs_left_today"] == 10 and s["mode"] == "rehearsal"


def test_kill_switch(tmp_path, monkeypatch):
    c, _, cfg = make(tmp_path, monkeypatch)
    cfg.enabled = False
    r = c.post("/api/runs", json={})
    assert r.status_code == 503 and r.json()["error"] == "disabled"
    assert c.get("/api/live/status").json()["enabled"] is False


def test_access_code(tmp_path, monkeypatch):
    c, _, _ = make(tmp_path, monkeypatch, access_code="letmein")
    assert c.get("/api/live/status").json()["access_code_required"] is True
    assert c.post("/api/runs", json={}).status_code == 401
    assert c.post("/api/runs", json={"access_code": "wrong"}).status_code == 401
    r = c.post("/api/runs", json={"access_code": "letmein"})
    assert r.status_code == 201
    wait(c, r.json()["id"])


@pytest.mark.parametrize("body", [{"seed": 950000}, {"master_seed": 950000}, {"official": True}, {"held_out": True}, {"n": 5000}, {"seeds": [900000]}])
def test_client_cannot_send_pipeline_parameters(tmp_path, monkeypatch, body):
    c, mgr, _ = make(tmp_path, monkeypatch)
    r = c.post("/api/runs", json=body)
    assert r.status_code == 422
    assert mgr.current is None and not any((tmp_path / "live_runs").glob("live_*"))


def test_run_is_a_rehearsal_with_a_dev_seed(tmp_path, monkeypatch):
    c, mgr, _ = make(tmp_path, monkeypatch)
    r = c.post("/api/runs", json={}).json()
    assert r["mode"] == "rehearsal" and r["official"] is False
    st = mgr.get(r["id"])
    assert 0 < st.seed < 900_000
    cmd = mgr._command(st)
    assert cmd[2:4] == ["--seeds", str(st.seed)] and "--official" not in cmd and len(cmd) == 6
    meta = wait(c, r["id"])
    assert meta["mode"] == "rehearsal" and meta["official"] is False and meta["verdict"] == "VERIFIED"


def test_single_run_lock_and_cancel(tmp_path, monkeypatch):
    c, _, _ = make(tmp_path, monkeypatch, mode="hang")
    first = c.post("/api/runs", json={})
    assert first.status_code == 201
    second = c.post("/api/runs", json={})
    assert second.status_code == 409 and second.json()["error"] == "busy"
    assert c.get("/api/live/status").json()["busy"] is True
    rid, tok = first.json()["id"], first.json()["cancel_token"]
    assert c.post(f"/api/runs/{rid}/cancel", json={"cancel_token": "nope"}).status_code == 403
    assert c.post(f"/api/runs/{rid}/cancel", json={"cancel_token": tok}).status_code == 200
    assert wait(c, rid)["status"] == "cancelled"
    again = c.post("/api/runs", json={})  # the lock is released
    assert again.status_code == 201
    c.post(f"/api/runs/{again.json()['id']}/cancel", json={"cancel_token": again.json()["cancel_token"]})
    wait(c, again.json()["id"])


def test_timeout_kills_the_run(tmp_path, monkeypatch):
    c, _, _ = make(tmp_path, monkeypatch, mode="hang", timeout_s=1.5)
    rid = c.post("/api/runs", json={}).json()["id"]
    m = wait(c, rid)
    assert m["status"] == "timeout" and m["verdict"] is None


def test_exit_without_result_is_error_not_verdict(tmp_path, monkeypatch):
    c, _, _ = make(tmp_path, monkeypatch, mode="nosummary")
    rid = c.post("/api/runs", json={}).json()["id"]
    m = wait(c, rid)
    assert m["status"] == "error" and m["verdict"] is None
    assert sse(c, rid)[-2]["message"].endswith("No verdict was produced.")


def test_per_ip_rate_limit(tmp_path, monkeypatch):
    c, mgr, cfg = make(tmp_path, monkeypatch)
    cfg.per_ip_per_hour, cfg.trust_proxy = 1, True
    a = c.post("/api/runs", json={}, headers={"X-Forwarded-For": "1.2.3.4"})
    assert a.status_code == 201
    wait(c, a.json()["id"])
    b = c.post("/api/runs", json={}, headers={"X-Forwarded-For": "1.2.3.4"})
    assert b.status_code == 429 and b.json()["error"] == "rate_limited"
    other = c.post("/api/runs", json={}, headers={"X-Forwarded-For": "5.6.7.8"})
    assert other.status_code == 201
    wait(c, other.json()["id"])


def test_daily_run_cap(tmp_path, monkeypatch):
    c, _, _ = make(tmp_path, monkeypatch, daily_run_cap=1)
    a = c.post("/api/runs", json={})
    wait(c, a.json()["id"])
    b = c.post("/api/runs", json={})
    assert b.status_code == 429 and b.json()["error"] == "daily_run_cap"
    assert c.get("/api/live/status").json()["runs_left_today"] == 0


def test_daily_usd_cap_uses_real_run_cost(tmp_path, monkeypatch):
    c, _, _ = make(tmp_path, monkeypatch, daily_usd_cap=0.10, est_run_usd=0.06)
    for _ in range(2):  # each run reserves 0.06 and then settles at its real 0.03
        r = c.post("/api/runs", json={})
        assert r.status_code == 201
        wait(c, r.json()["id"])
    s = c.get("/api/live/status").json()
    assert abs(s["estimated_usd_left_today"] - 0.04) < 1e-6
    third = c.post("/api/runs", json={})
    assert third.status_code == 429 and third.json()["error"] == "daily_usd_cap"


def test_sse_order_replay_and_secret_scrub(tmp_path, monkeypatch):
    c, _, _ = make(tmp_path, monkeypatch)
    rid = c.post("/api/runs", json={}).json()["id"]
    wait(c, rid)
    evs = sse(c, rid)
    assert [e["seq"] for e in evs] == list(range(len(evs)))
    assert evs[0]["stage"] == "run" and evs[-1]["stage"] == "end" and evs[-2]["stage"] == "verdict"
    assert evs[-2]["data"]["verdict"] == "VERIFIED"

    def first(stage, status):
        return next(i for i, e in enumerate(evs) if e["stage"] == stage and e["status"] == status)
    order = [first("generator", "start"), first("generator", "done"), first("baseline", "done"), first("evidence", "done"),
             first("analyst", "done"), first("fixer", "done"), first("verdict", "done")]
    assert order == sorted(order) and len(set(order)) == len(order)
    gates = [e["data"]["check"]["id"] for e in evs if e["stage"] == "gate" and "check" in e["data"]]
    assert gates == ["G1", "G2", "G3", "G4", "G5", "G6"]
    assert first("gate", "done") > first("fixer", "done")
    assert SECRET not in json.dumps(evs)
    assert any("[redacted]" in e["message"] for e in evs)  # the fake pipeline printed the key; the service scrubbed it
    # replay: a second (and a resumed) connection sees the same stream
    assert sse(c, rid) == evs
    assert sse(c, rid, {"Last-Event-ID": "3"}) == evs[4:]
    assert SECRET not in (tmp_path / "live_runs" / rid / "events.jsonl").read_text(encoding="utf-8")


def test_events_survive_a_manager_restart(tmp_path, monkeypatch):
    c, _, cfg = make(tmp_path, monkeypatch)
    rid = c.post("/api/runs", json={}).json()["id"]
    wait(c, rid)
    evs = sse(c, rid)
    c2 = TestClient(FastAPI())
    app2 = FastAPI()
    install(app2, cfg)
    c2 = TestClient(app2)
    assert sse(c2, rid) == evs


def test_file_serving_is_whitelisted_and_confined(tmp_path, monkeypatch):
    c, _, _ = make(tmp_path, monkeypatch)
    rid = c.post("/api/runs", json={}).json()["id"]
    wait(c, rid)
    assert c.get(f"/api/runs/{rid}/files/summary.json").status_code == 200
    assert c.get(f"/api/runs/{rid}/files/events.jsonl").status_code == 200
    for bad in ("ledger.json", "..%2f..%2fledger.json", "../meta.json", "analysis_set.json", "%2e%2e%2f%2e%2e%2fetc%2fpasswd", "summary.json%00"):
        assert c.get(f"/api/runs/{rid}/files/{bad}").status_code == 404, bad
    for bad_id in ("..", "..%2f..", "live_x", "../live_runs", "live_20250101t000000_zzzz", rid + "/../.."):
        assert c.get(f"/api/runs/{bad_id}").status_code == 404, bad_id
        assert c.get(f"/api/runs/{bad_id}/files/summary.json").status_code == 404, bad_id
    assert c.get("/api/runs/live_20250101t000000_abcd/events").status_code == 404


def test_scrub_function(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", SECRET)
    monkeypatch.setenv("LIVE_ACCESS_CODE", "hunter2hunter2")
    out = scrub(f"key={SECRET} code=hunter2hunter2 Authorization: Bearer abcdefghijkl123 nvapi-abcdefghijklmnop")
    assert SECRET not in out and "hunter2" not in out and "abcdefghijkl123" not in out and "nvapi-abcdef" not in out
