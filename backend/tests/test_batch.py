"""CSV / pasted batches. The simulator is replaced by a fake unless a test says otherwise: no LLM calls, no credits."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.bounds import SCENARIO_BOUNDS
from app.core.schemas import FailureReason, Result
from app.live.config import LiveConfig
from app.live.manager import RunManager
from app.playground import service as svc_mod
from app.playground.api import install
from app.playground.batch import BATCH_SEED_BASE, COLUMNS, MAX_ROWS, csv_cell, parse_batch, results_csv, to_csv
from app.playground.service import PlaygroundConfig

HEADER = ",".join(COLUMNS)
ROW = "0.2,0.8,0.05,0,0,0,0"


def fake_sweep(policy, scenarios, timeout_s):
    out = []
    for s in scenarios:
        ok = s.mass_kg < 0.5 or policy.grip_force > 40
        out.append(Result(scenario_id=s.id, seed=s.seed, success=ok, collision=False, completion_time_s=3.0, final_place_error_m=0.01, max_slip_m=0.0,
                          failure_reason=None if ok else FailureReason.SLIPPED_ON_LIFT))
    return out


def make(tmp_path, sweep_fn=fake_sweep, **kw):
    live = RunManager(LiveConfig(enabled=False, runs_dir=tmp_path / "lr"))
    app = FastAPI()
    svc = install(app, live, PlaygroundConfig(**kw))
    svc.sweep_fn = sweep_fn
    return TestClient(app), svc


def post(c, csv_text, policy=None):
    return c.post("/api/sim/batch", json={"csv": csv_text, **({"policy": policy} if policy else {})})


def table(*rows, header=HEADER):
    return "\n".join([header, *rows]) + "\n"


# ------------------------------------------------------------------ header and columns
def test_valid_table_runs_and_assigns_deterministic_seeds(tmp_path):
    c, _ = make(tmp_path)
    r = post(c, table(ROW, "0.8,0.2,0.05,0,0,0.005,2", "0.2,0.8,0.05,0.01,-0.02,0,0"))
    assert r.status_code == 200
    b = r.json()
    assert b["n"] == 3 and b["rows"]["seed"] == [BATCH_SEED_BASE, BATCH_SEED_BASE + 1, BATCH_SEED_BASE + 2] and max(b["rows"]["seed"]) < 800_000
    assert b["rows"]["ok"] == [1, 0, 1] and b["metrics"]["n"] == 3 and len(b["metrics"]["pass_rate_ci95"]) == 2 and b["default_metrics"]["n"] == 3
    assert "not a gate verdict" in b["mode"]


@pytest.mark.parametrize("header,expect", [
    ("mass_kg,friction,size_m,pos_offset_x,pos_offset_y,sensor_noise_m", "missing column"),
    (HEADER + ",colour", "unknown column"),
    (HEADER + ",mass_kg", "duplicate column"),
    ("mass,friction,size_m,pos_offset_x,pos_offset_y,sensor_noise_m,gripper_delay_steps", "unknown column")])
def test_header_validation(tmp_path, header, expect):
    c, _ = make(tmp_path)
    r = post(c, header + "\n" + ROW + "\n")
    assert r.status_code == 422 and r.json()["error"] == "invalid_header"
    assert any(expect in e["problem"] for e in r.json()["errors"]) and all(e["row"] == 0 for e in r.json()["errors"])


def test_header_is_case_and_space_tolerant_and_tab_separated_paste_works(tmp_path):
    c, _ = make(tmp_path)
    assert post(c, " Mass_KG , Friction,size_m,pos_offset_x,pos_offset_y,sensor_noise_m,gripper_delay_steps\n" + ROW + "\n").status_code == 200
    tabs = "\n".join(["\t".join(COLUMNS), "\t".join(ROW.split(","))])
    assert post(c, tabs).status_code == 200


def test_empty_and_header_only(tmp_path):
    c, _ = make(tmp_path)
    assert post(c, "\n\n  \n").json()["error"] == "empty"
    r = post(c, HEADER + "\n")
    assert r.status_code == 422 and r.json()["error"] == "no_rows"


# ------------------------------------------------------------------ row-level errors, nothing runs
def test_row_level_errors_report_row_field_and_problem_and_run_nothing(tmp_path):
    calls = []

    def spy(p, s, t):
        calls.append(1)
        return fake_sweep(p, s, t)
    c, _ = make(tmp_path, sweep_fn=spy)
    bad = table(ROW, "5.0,0.8,0.05,0,0,0,0", "0.2,abc,0.05,0,0,0,0", "0.2,0.8,0.05,0,0,0,2.5", "0.2,0.8,0.05,0,0,nan,0", "0.2,0.8,0.05,0,0,inf,0", "0.2,0.8,0.05", "0.2,0.8,0.05,0,0,0,21")
    r = post(c, bad)
    assert r.status_code == 422 and r.json()["error"] == "invalid_rows" and calls == []
    got = {(e["row"], e["field"]) for e in r.json()["errors"]}
    assert {(2, "mass_kg"), (3, "friction"), (4, "gripper_delay_steps"), (5, "sensor_noise_m"), (6, "sensor_noise_m"), (7, "(row)"), (8, "gripper_delay_steps")} <= got
    e2 = next(e for e in r.json()["errors"] if e["row"] == 2)
    assert "outside the allowed range" in e2["problem"] and e2["line"] == 3  # row 2 is on line 3 of the file (line 1 is the header)
    assert not any(e["row"] == 1 for e in r.json()["errors"])


def test_every_bound_is_enforced_per_column(tmp_path):
    c, _ = make(tmp_path, rate_sweep_per_10min=100)
    for i, (k, (lo, hi)) in enumerate(SCENARIO_BOUNDS.items()):
        for v in (lo - 1e-3 * max(1, abs(hi)), hi + 1e-3 * max(1, abs(hi))):
            cells = ROW.split(",")
            cells[i] = repr(v)
            r = post(c, table(",".join(cells)))
            assert r.status_code == 422 and r.json()["errors"][0]["field"] == k, (k, v)
        cells = ROW.split(",")
        cells[i] = repr(lo)  # the bounds themselves are allowed
        assert post(c, table(",".join(cells))).status_code == 200


def test_error_list_is_capped(tmp_path):
    c, _ = make(tmp_path)
    r = post(c, table(*(["9,0.8,0.05,0,0,0,0"] * 150)))
    assert r.status_code == 422 and len(r.json()["errors"]) == 40 and "150 problems" in r.json()["message"]


# ------------------------------------------------------------------ caps
def test_row_and_size_caps(tmp_path):
    c, _ = make(tmp_path)
    assert post(c, table(*([ROW] * MAX_ROWS))).status_code == 200
    r = post(c, table(*([ROW] * (MAX_ROWS + 1))))
    assert r.status_code == 413 and r.json()["error"] == "too_many_rows"
    big = HEADER + "\n" + "\n".join([ROW] * 3) + "\n" + "#" * (101 * 1024) + "\n"
    r = post(c, big)
    assert r.status_code == 413 and r.json()["error"] == "too_large"
    assert c.post("/api/sim/batch", json={"csv": "x" * 200_000}).status_code == 422


def test_policy_and_extra_fields_are_validated(tmp_path):
    c, _ = make(tmp_path)
    assert post(c, table(ROW), {"grip_force": 500}).status_code == 422
    assert c.post("/api/sim/batch", json={"csv": table(ROW), "seed": 900_000}).status_code == 422
    assert c.post("/api/sim/batch", json={"csv": table(ROW), "official": True}).status_code == 422


# ------------------------------------------------------------------ determinism, default comparison, template
def test_same_input_same_output_and_default_is_compared_on_identical_rows(tmp_path):
    calls = []

    def spy(p, s, t):
        calls.append(p.grip_force)
        return fake_sweep(p, s, t)
    c, _ = make(tmp_path, sweep_fn=spy, rate_sweep_per_10min=10)
    t = table(ROW, "0.8,0.2,0.05,0,0,0.005,2")
    a, b = post(c, t, {"grip_force": 60}).json(), post(c, t, {"grip_force": 60}).json()
    for k in ("metrics", "default_metrics", "rows", "results_csv"):
        assert a[k] == b[k]
    assert a["rows"]["ok"] == [1, 1] and a["rows"]["default_ok"] == [1, 0]
    assert calls == [60.0, 15.0, 60.0]  # default results cached for identical rows


def test_template_round_trips(tmp_path):
    c, _ = make(tmp_path)
    r = c.get("/api/sim/batch/template")
    assert r.status_code == 200 and r.text.splitlines()[0] == HEADER and "attachment" in r.headers["content-disposition"]
    assert len(parse_batch(r.text)) == len(r.text.strip().splitlines()) - 1
    assert post(c, r.text).status_code == 200


def test_spec_advertises_the_batch_limits(tmp_path):
    c, _ = make(tmp_path)
    b = c.get("/api/sim/spec").json()["batch"]
    assert b["max_rows"] == 200 and b["max_kb"] == 100 and b["columns"] == COLUMNS


# ------------------------------------------------------------------ guards and CSV injection
def test_rate_limit_kill_switch_and_concurrency(tmp_path):
    c, _ = make(tmp_path, rate_sweep_per_10min=1)
    assert post(c, table(ROW)).status_code == 200
    assert post(c, table(ROW)).status_code == 429
    c, _ = make(tmp_path, enabled=False)
    assert post(c, table(ROW)).status_code == 503
    c, svc = make(tmp_path)
    for _ in range(svc.cfg.max_concurrent):
        assert svc.slots.acquire(blocking=False)
    r = post(c, table(ROW))
    assert r.status_code == 503 and r.json()["error"] == "busy"


def test_timeout_maps_to_504(tmp_path):
    def boom(p, s, t):
        raise svc_mod.PlaygroundError(504, "timeout", "too slow")
    c, _ = make(tmp_path, sweep_fn=boom)
    assert post(c, table(ROW)).status_code == 504


@pytest.mark.parametrize("v", ["=1+1", "+SUM(A1)", "-2+3", "@cmd", "\tcmd", "\rcmd"])
def test_csv_injection_is_neutralised_in_text_cells(v):
    assert csv_cell(v) == "'" + v
    out = to_csv(["a"], [[v]])
    assert out.splitlines()[1].lstrip('"').startswith("'")
    assert csv_cell(-0.05) == -0.05 and csv_cell("ok") == "ok" and csv_cell("") == ""  # numbers stay numbers


def test_results_csv_is_safe_and_complete(tmp_path):
    c, _ = make(tmp_path)
    b = post(c, table(ROW, "0.8,0.2,0.05,-0.01,0,0.005,2")).json()
    lines = b["results_csv"].strip().splitlines()
    assert len(lines) == 3 and lines[0].startswith(HEADER) and "-0.01" in lines[2]  # negative numbers are not mangled
    rows = dict(b["rows"])
    rows["ids"] = ["=cmd|' /C calc'!A0"] + rows["ids"][1:]  # a hostile text cell in a text column
    assert "'=cmd" in results_csv(rows)


def test_no_held_out_seeds_and_no_frozen_files_named(tmp_path):
    c, _ = make(tmp_path)
    b = post(c, table(*([ROW] * 50))).json()
    assert 100_000 <= min(b["rows"]["seed"]) and max(b["rows"]["seed"]) < 800_000
    from pathlib import Path
    t = (Path(svc_mod.__file__).parent / "batch.py").read_text(encoding="utf-8")
    assert "held_out=True" not in t and "HELDOUT_SEED_BASE" not in t


def test_real_simulator_batch_is_deterministic(tmp_path):
    pytest.importorskip("pybullet")
    live = RunManager(LiveConfig(enabled=False, runs_dir=tmp_path / "lr"))
    app = FastAPI()
    install(app, live, PlaygroundConfig(rate_sweep_per_10min=10))
    c = TestClient(app)
    t = table(ROW, "0.8,0.2,0.05,0,0,0.005,2", "0.2,0.8,0.03,0,0,0,15")
    a, b = post(c, t, {"grip_force": 40}).json(), post(c, t, {"grip_force": 40}).json()
    assert a["rows"]["ok"] == b["rows"]["ok"] and a["rows"]["time_s"] == b["rows"]["time_s"] and a["metrics"] == b["metrics"]
