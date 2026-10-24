"""Validation, isolated execution, limits and result shaping for the playground. Calls the frozen simulator, sampler and evidence code read-only."""
from __future__ import annotations

import json
import math
import multiprocessing as mp
import os
import secrets
import tempfile
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.bounds import INT_POLICY_PARAMS, POLICY_BOUNDS, SCENARIO_BOUNDS
from ..core.schemas import FailureReason, Policy, Result, Scenario
from ..core.stats import wilson
from .batch import BATCH_SEED_BASE, BatchError, parse_batch, results_csv
from .spec import DEFAULT_SEED, PG_SEED_MAX, PG_SEED_MIN, default_policy_dict

MAX_FRAMES = 300
SWEEP_SEED_SPAN = 5900  # sweep seed -> seed block start = 200000 + (seed % 5900) * 100; the largest block ends below 790300

EXPLAIN = {
    "MISSED_GRASP": "The gripper closed but never took hold of the cube, so nothing was lifted. Typical causes: the sensed position was off (sensor noise) or the grip was too weak.",
    "SLIPPED_ON_LIFT": "The cube slipped out of the fingers while being lifted. Typical causes: a heavy or slippery cube, too little grip force, or a fast lift.",
    "DROPPED_IN_TRANSIT": "The cube was lifted but fell while being carried toward the target.",
    "COLLISION": "The gripper or the cube hit the low wall between the pick and place positions.",
    "PLACED_OUTSIDE_ZONE": "The cube was put down, but outside the green target zone or not upright.",
    "TIMEOUT": "The motion did not finish within the simulator's time limit.",
}


class PlaygroundError(Exception):
    def __init__(self, status: int, code: str, message: str, errors: list | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.errors = status, code, message, errors or []


@dataclass
class PlaygroundConfig:
    enabled: bool = True                 # PLAYGROUND_ENABLED: kill switch
    rate_scenario_per_min: int = 20      # PLAYGROUND_RATE_SCENARIO_PER_MIN (per client IP)
    rate_sweep_per_10min: int = 6        # PLAYGROUND_RATE_SWEEP_PER_10MIN (per client IP)
    max_concurrent: int = 2              # PLAYGROUND_MAX_CONCURRENT simulations at once
    scenario_timeout_s: float = 20.0     # SCENARIO_TIMEOUT_S (or PLAYGROUND_SCENARIO_TIMEOUT_S); 30 in host mode
    sweep_timeout_s: float = 60.0        # SWEEP_TIMEOUT_S (or PLAYGROUND_SWEEP_TIMEOUT_S): whole sweep, both policies; 90 in host mode
    batch_timeout_s: float = 60.0        # BATCH_TIMEOUT_S: whole batch, both policies; defaults to the sweep value
    verify_timeout_s: float = 54.0       # VERIFY_TIMEOUT_S: per-shard limit of the re-simulation
    interpret_timeout_s: float | None = None   # INTERPRET_TIMEOUT_S: per model call (default: the module's 45 s / 60 s)
    analyze_timeout_s: float | None = None     # ANALYZE_TIMEOUT_S: per model call (default: LLM_TIMEOUT_S)
    verify_enabled: bool = True          # VERIFY_ENABLED: off in host mode (render.yaml): the re-simulation does not fit a free instance
    max_sweep_n: int = 200               # MAX_SWEEP_N (or PLAYGROUND_MAX_SWEEP_N); default 50 in host mode
    max_batch_rows: int = 200            # MAX_BATCH_ROWS; default 50 in host mode
    analyze_usd_est: float = 0.03        # reserved against the daily spend cap before an analyze call
    interpret_usd_est: float = 0.005     # reserved against the daily spend cap before an interpret call
    rate_interpret_per_hour: int = 10    # PLAYGROUND_RATE_INTERPRET_PER_HOUR (per client IP)
    trust_proxy: bool = False            # LIVE_TRUST_PROXY (shared with the live service)

    @staticmethod
    def from_env(env: dict | None = None) -> "PlaygroundConfig":
        e = env if env is not None else dict(os.environ)
        c = PlaygroundConfig()

        def num(k, d):
            try:
                return float(e[k]) if e.get(k) not in (None, "") else d
            except ValueError:
                return d
        c.enabled = e.get("PLAYGROUND_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
        c.rate_scenario_per_min = int(num("PLAYGROUND_RATE_SCENARIO_PER_MIN", c.rate_scenario_per_min))
        c.rate_sweep_per_10min = int(num("PLAYGROUND_RATE_SWEEP_PER_10MIN", c.rate_sweep_per_10min))
        c.rate_interpret_per_hour = int(num("PLAYGROUND_RATE_INTERPRET_PER_HOUR", c.rate_interpret_per_hour))
        from .. import hosting
        c.max_concurrent = max(1, int(num("PLAYGROUND_MAX_CONCURRENT", 1 if hosting.host_mode(e) and hosting.effective_cpus() <= 1 else c.max_concurrent)))
        host = hosting.host_mode(e)
        c.scenario_timeout_s = hosting.env_float(e, ("SCENARIO_TIMEOUT_S", "PLAYGROUND_SCENARIO_TIMEOUT_S"), 30.0 if host else c.scenario_timeout_s)
        c.sweep_timeout_s = hosting.env_float(e, ("SWEEP_TIMEOUT_S", "PLAYGROUND_SWEEP_TIMEOUT_S"), 90.0 if host else c.sweep_timeout_s)
        c.batch_timeout_s = hosting.env_float(e, ("BATCH_TIMEOUT_S",), c.sweep_timeout_s)
        c.verify_timeout_s = hosting.env_float(e, ("VERIFY_TIMEOUT_S",), c.verify_timeout_s)
        c.interpret_timeout_s = hosting.env_float(e, ("INTERPRET_TIMEOUT_S",), 0.0) or None
        c.analyze_timeout_s = hosting.env_float(e, ("ANALYZE_TIMEOUT_S",), 0.0) or None
        c.verify_enabled = hosting.verify_enabled(e)
        c.max_sweep_n = hosting.max_sweep_n(e)  # never above the documented cap of 200
        c.max_batch_rows = hosting.max_batch_rows(e)
        c.trust_proxy = e.get("LIVE_TRUST_PROXY", "").strip().lower() in ("1", "true", "yes", "on")
        return c


# ------------------------------------------------------------------ request models (strict; nothing else is accepted)
def _bounded(name: str, lo: float, hi: float, integer: bool):
    def check(v):
        if isinstance(v, bool):
            raise ValueError("must be a number")
        if not math.isfinite(float(v)):
            raise ValueError("must be a finite number")
        if integer and float(v) != int(v):
            raise ValueError("must be a whole number")
        if not (lo <= float(v) <= hi):
            raise ValueError(f"must be between {lo} and {hi}")
        return int(v) if integer else float(v)
    return check


class ScenarioIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mass_kg: float = Field(allow_inf_nan=False)
    friction: float = Field(allow_inf_nan=False)
    size_m: float = Field(allow_inf_nan=False)
    pos_offset_x: float = Field(allow_inf_nan=False)
    pos_offset_y: float = Field(allow_inf_nan=False)
    sensor_noise_m: float = Field(allow_inf_nan=False)
    gripper_delay_steps: int

    @model_validator(mode="after")
    def _bounds(self):
        for k, (lo, hi) in SCENARIO_BOUNDS.items():
            _bounded(k, lo, hi, k == "gripper_delay_steps")(getattr(self, k))
        return self


class PolicyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grip_force: float | None = Field(default=None, allow_inf_nan=False)
    approach_speed: float | None = Field(default=None, allow_inf_nan=False)
    lift_height: float | None = Field(default=None, allow_inf_nan=False)
    lift_speed: float | None = Field(default=None, allow_inf_nan=False)
    grasp_hold_steps: float | None = Field(default=None, allow_inf_nan=False)
    place_slow_factor: float | None = Field(default=None, allow_inf_nan=False)
    retry_count: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def _bounds(self):
        for k, (lo, hi, _) in POLICY_BOUNDS.items():
            v = getattr(self, k)
            if v is not None:
                _bounded(k, lo, hi, k in INT_POLICY_PARAMS)(v)
        return self

    def to_policy(self) -> Policy:
        d = default_policy_dict()
        for k in d:
            v = getattr(self, k)
            if v is not None:
                d[k] = int(v) if k in INT_POLICY_PARAMS else float(v)
        return Policy(**d)


def _check_seed(v: int | None) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool) or not (PG_SEED_MIN <= v < PG_SEED_MAX):
        raise ValueError(f"seed must be a whole number from {PG_SEED_MIN} to {PG_SEED_MAX - 1} (playground range; held-out and rehearsal seeds are not allowed)")
    return v


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: ScenarioIn
    policy: PolicyIn = PolicyIn()
    seed: int | None = None

    @field_validator("seed")
    @classmethod
    def _seed(cls, v):
        return _check_seed(v)


class SweepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: PolicyIn = PolicyIn()
    n: int = Field(ge=1)
    seed: int | None = None

    @field_validator("seed")
    @classmethod
    def _seed(cls, v):
        return _check_seed(v)


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: PolicyIn = PolicyIn()
    csv: str = Field(min_length=1, max_length=160_000)  # the byte cap (100 KB) is enforced when parsing


class InterpretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=300)
    access_code: str | None = None


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sweep_id: str = Field(min_length=4, max_length=32, pattern=r"^[0-9a-f]+$")
    access_code: str | None = None


# ------------------------------------------------------------------ isolated single-scenario execution (killable on timeout)
def _scenario_job(policy_d: dict, scenario_d: dict, out_file: str) -> None:
    from ..sim import pickplace as pp
    from ..sim.recorder import record_scenario
    policy, scenario = Policy(**policy_d), Scenario(**scenario_d)
    with tempfile.TemporaryDirectory(prefix="pg-") as td:
        result, traj, _ = record_scenario(policy, scenario, td, gif=False)
        data = json.loads(Path(traj).read_text())
    frames = data["frames"]
    if len(frames) > MAX_FRAMES:
        stride = math.ceil(len(frames) / MAX_FRAMES)
        keep = frames[::stride]
        if keep[-1] is not frames[-1]:
            keep.append(frames[-1])
        frames = keep
    Path(out_file).write_text(json.dumps({
        "result": result.model_dump(mode="json"),
        "trajectory": {"dt": data["dt"], "frames": frames, "n_frames_original": len(data["frames"])},
        "world": {"target_xy": list(pp.TARGET_XY), "zone_radius": pp.ZONE_RADIUS, "wall_x": pp.WALL_X, "wall_half": list(pp.WALL_HALF),
                  "palm_half": list(pp.PALM_HALF), "finger_half": list(pp.FINGER_HALF), "finger_z": pp.FINGER_Z, "finger_y0": pp.FINGER_Y0,
                  "size_m": scenario.size_m},
    }))


def run_scenario_isolated(policy: Policy, scenario: Scenario, timeout_s: float) -> dict:
    ctx = mp.get_context("fork" if "fork" in mp.get_all_start_methods() else "spawn")
    with tempfile.TemporaryDirectory(prefix="pg-run-") as td:
        out = str(Path(td) / "out.json")
        p = ctx.Process(target=_scenario_job, args=(policy.model_dump(), scenario.model_dump(), out))
        p.start()
        p.join(timeout_s)
        if p.is_alive():
            p.kill()
            p.join()
            from ..hosting import slow_message
            raise PlaygroundError(504, "timeout", slow_message(timeout_s, "the simulation"))
        if p.exitcode != 0 or not Path(out).exists():
            raise PlaygroundError(500, "sim_failed", "The simulation process failed.")
        return json.loads(Path(out).read_text())


def run_sweep_isolated(policy: Policy, scenarios: list[Scenario], timeout_s: float) -> list[Result]:
    from ..runner.local import LocalRunner  # LocalRunner: shards run as killable processes with a per-shard timeout
    from ..hosting import worker_count  # the container's real CPU limit, not the host's core count
    rr = LocalRunner(max_workers=worker_count(), shard_timeout_s=timeout_s).run(policy, scenarios, shards=min(10, len(scenarios)))
    if not rr.complete:
        from ..hosting import slow_message
        raise PlaygroundError(504, "timeout", slow_message(timeout_s, "the sweep (some shards timed out or failed)"))
    return rr.results


# ------------------------------------------------------------------ the service
def _metrics(results: list[Result]) -> dict:
    n = len(results)
    k = sum(r.success for r in results)
    lo, hi = wilson(k, n)
    times = [r.completion_time_s for r in results if r.success]
    reasons: dict[str, int] = {}
    for r in results:
        if r.failure_reason:
            reasons[r.failure_reason.value] = reasons.get(r.failure_reason.value, 0) + 1
    return {"n": n, "passes": k, "pass_rate": round(k / n, 4), "pass_rate_ci95": [round(lo, 4), round(hi, 4)],
            "collision_rate": round(sum(r.collision for r in results) / n, 4),
            "mean_completion_time_s": round(sum(times) / len(times), 3) if times else None,
            "failure_reasons": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])))}


class PlaygroundService:
    def __init__(self, cfg: PlaygroundConfig, scenario_fn: Callable[..., dict] = run_scenario_isolated,
                 sweep_fn: Callable[..., list[Result]] = run_sweep_isolated):
        self.cfg, self.scenario_fn, self.sweep_fn = cfg, scenario_fn, sweep_fn
        self.slots = threading.BoundedSemaphore(cfg.max_concurrent)
        self.hits: dict[tuple[str, str], deque] = {}
        self.lock = threading.Lock()
        self.default_cache: OrderedDict[tuple[int, int], list[Result]] = OrderedDict()
        self.sweeps: OrderedDict[str, dict] = OrderedDict()

    # --- guards
    def _enabled(self) -> None:
        if not self.cfg.enabled:
            raise PlaygroundError(503, "disabled", "The playground is switched off on this server.")

    def _rate(self, ip: str, kind: str, limit: int, window_s: float) -> None:
        now = time.time()
        with self.lock:
            q = self.hits.setdefault((ip, kind), deque())
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                raise PlaygroundError(429, "rate_limited", f"Too many {kind} runs from this address. Try again in a minute or two.")
            q.append(now)

    class _Slot:
        def __init__(self, sem):
            self.sem = sem

        def __enter__(self):
            if not self.sem.acquire(blocking=False):
                raise PlaygroundError(503, "busy", "The simulator is busy with other visitors' runs. Try again in a few seconds.")

        def __exit__(self, *a):
            self.sem.release()

    # --- single scenario
    def scenario(self, req: ScenarioRequest, ip: str) -> dict:
        self._enabled()
        self._rate(ip, "scenario", self.cfg.rate_scenario_per_min, 60)
        seed = req.seed if req.seed is not None else DEFAULT_SEED
        scn = Scenario(id=f"pg-{seed}", seed=seed, tag="playground", **req.scenario.model_dump())
        pol = req.policy.to_policy()
        t0 = time.perf_counter()
        with self._Slot(self.slots):
            out = self.scenario_fn(pol, scn, self.cfg.scenario_timeout_s)
        res = out["result"]
        reason = res.get("failure_reason")
        return {"mode": "playground (exploration, not a gate verdict)", "runner": "local simulator (fallback, not Nebius)", "seed": seed,
                "scenario": scn.model_dump(), "policy": pol.model_dump(), "result": res,
                "explanation": EXPLAIN.get(reason) if reason else "The cube was lifted, carried over the wall and placed upright inside the target zone.",
                "trajectory": out["trajectory"], "world": out["world"], "wall_clock_s": round(time.perf_counter() - t0, 2),
                "frozen_note": "Frozen simulator and parameter ranges. Not part of the official evaluation."}

    # --- sweep
    @staticmethod
    def _scenarios(n: int, seed: int) -> list[Scenario]:
        from ..scenarios.sweep import latin_hypercube
        return latin_hypercube(n, seed, tag="pg", seed_base=200_000 + (seed % SWEEP_SEED_SPAN) * 100)

    def sweep(self, req: SweepRequest, ip: str) -> dict:
        from ..analysis.evidence import compute_evidence
        self._enabled()
        if req.n > self.cfg.max_sweep_n:
            raise PlaygroundError(422, "too_many", f"A sweep may use at most {self.cfg.max_sweep_n} scenarios.")
        self._rate(ip, "sweep", self.cfg.rate_sweep_per_10min, 600)
        seed = req.seed if req.seed is not None else DEFAULT_SEED
        scns = self._scenarios(req.n, seed)
        pol = req.policy.to_policy()
        default = Policy()
        per_phase = self.cfg.sweep_timeout_s * 0.45
        t0 = time.perf_counter()
        with self._Slot(self.slots):
            res = self.sweep_fn(pol, scns, per_phase)
            key = (req.n, seed)
            if pol == default:
                dres = res
            else:
                with self.lock:
                    dres = self.default_cache.get(key)
                if dres is None:
                    dres = self.sweep_fn(default, scns, per_phase)
                    with self.lock:
                        self.default_cache[key] = dres
                        while len(self.default_cache) > 32:
                            self.default_cache.popitem(last=False)
        ev = compute_evidence(scns, res)
        bins = [{"axis": i.data["axis"], "range": i.data["range"], "n": i.data["n"], "n_fail": i.data["n_fail"], "fail_rate": i.data["fail_rate"]}
                for i in ev.items if i.kind == "bin"]
        dmap = {r.scenario_id: r for r in dres}
        rows = {"ids": [s.id for s in scns], "ok": [1 if r.success else 0 for r in res], "reason": [r.failure_reason.value if r.failure_reason else None for r in res],
                "collision": [1 if r.collision else 0 for r in res], "time_s": [r.completion_time_s for r in res],
                "default_ok": [1 if dmap[s.id].success else 0 for s in scns], "default_reason": [dmap[s.id].failure_reason.value if dmap[s.id].failure_reason else None for s in scns],
                "seed": [s.seed for s in scns]}
        for ax in SCENARIO_BOUNDS:
            rows[ax] = [float(getattr(s, ax)) for s in scns]  # full precision: replaying a point reproduces its result exactly
        sid = secrets.token_hex(6)
        with self.lock:
            self.sweeps[sid] = {"id": sid, "scenarios": scns, "results": res, "policy": pol, "n": req.n, "seed": seed}
            while len(self.sweeps) > 20:
                self.sweeps.popitem(last=False)
        return {"mode": "playground (exploration, not a gate verdict)", "runner": "local simulator (fallback, not Nebius)", "sweep_id": sid, "n": req.n, "seed": seed,
                "policy": pol.model_dump(), "default_policy": default.model_dump(), "metrics": _metrics(res), "default_metrics": _metrics(dres),
                "evidence_bins": bins, "rows": rows, "wall_clock_s": round(time.perf_counter() - t0, 2),
                "sampler": "Latin-hypercube coverage sweep over the frozen parameter ranges (seeded)",
                "frozen_note": "Frozen simulator and parameter ranges. Not part of the official evaluation."}

    # --- batch of user-supplied scenarios (CSV or pasted rows)
    def batch(self, req: BatchRequest, ip: str) -> dict:
        from ..analysis.evidence import compute_evidence
        self._enabled()
        try:
            recs = parse_batch(req.csv, self.cfg.max_batch_rows)  # every row validated first; nothing runs if any row is invalid
        except BatchError as e:
            raise PlaygroundError(e.status, e.code, e.message, e.errors)
        self._rate(ip, "batch", self.cfg.rate_sweep_per_10min, 600)
        scns = [Scenario(id=f"pgb-{i + 1}", seed=BATCH_SEED_BASE + i, tag="playground-batch", **r) for i, r in enumerate(recs)]
        pol, default = req.policy.to_policy(), Policy()
        per_phase = self.cfg.batch_timeout_s * 0.45
        key = tuple((s.seed, s.mass_kg, s.friction, s.size_m, s.pos_offset_x, s.pos_offset_y, s.sensor_noise_m, s.gripper_delay_steps) for s in scns)
        t0 = time.perf_counter()
        with self._Slot(self.slots):
            res = self.sweep_fn(pol, scns, per_phase)
            if pol == default:
                dres = res
            else:
                with self.lock:
                    dres = self.default_cache.get(key)  # type: ignore[arg-type]
                if dres is None:
                    dres = self.sweep_fn(default, scns, per_phase)
                    with self.lock:
                        self.default_cache[key] = dres  # type: ignore[index]
                        while len(self.default_cache) > 32:
                            self.default_cache.popitem(last=False)
        try:
            ev = compute_evidence(scns, res)
            bins = [{"axis": i.data["axis"], "range": i.data["range"], "n": i.data["n"], "n_fail": i.data["n_fail"], "fail_rate": i.data["fail_rate"]} for i in ev.items if i.kind == "bin"]
        except Exception:  # tiny tables can be too small for the evidence code's bins; the rest of the answer does not depend on it
            bins = []
        dmap = {r.scenario_id: r for r in dres}
        rows = {"ids": [s.id for s in scns], "ok": [1 if r.success else 0 for r in res], "reason": [r.failure_reason.value if r.failure_reason else None for r in res],
                "collision": [1 if r.collision else 0 for r in res], "time_s": [r.completion_time_s for r in res],
                "default_ok": [1 if dmap[s.id].success else 0 for s in scns], "default_reason": [dmap[s.id].failure_reason.value if dmap[s.id].failure_reason else None for s in scns],
                "seed": [s.seed for s in scns]}
        for ax in SCENARIO_BOUNDS:
            rows[ax] = [float(getattr(s, ax)) for s in scns]
        return {"mode": "playground batch (exploration, not a gate verdict)", "runner": "local simulator (fallback, not Nebius)", "n": len(scns), "policy": pol.model_dump(),
                "default_policy": default.model_dump(), "metrics": _metrics(res), "default_metrics": _metrics(dres), "evidence_bins": bins, "rows": rows,
                "results_csv": results_csv(rows), "seeds": f"assigned by row: {BATCH_SEED_BASE} + row index (playground range)", "wall_clock_s": round(time.perf_counter() - t0, 2),
                "frozen_note": "Frozen simulator and parameter ranges. Not part of the official evaluation."}

    def get_sweep(self, sid: str) -> dict:
        with self.lock:
            s = self.sweeps.get(sid)
        if s is None:
            raise PlaygroundError(404, "not_found", "That sweep is no longer stored on the server. Run the sweep again.")
        return s
