"""Run manager: one live REHEARSAL at a time, as a subprocess of the existing pipeline script.

Progress events come from three real sources (nothing is invented):
  * the subprocess output (filtered, secrets scrubbed),
  * artifact files appearing in the run's output folder (the pipeline writes them as each stage completes),
  * the llm_calls table the pipeline itself fills as each model call finishes (read-only).
The pipeline writes candidate tables and gate results together when it finishes, so those events arrive together at the end.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import secrets
import signal
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import LiveConfig
from .scrub import scrub, scrub_obj

RUN_ID_RE = re.compile(r"^live_\d{8}t\d{6}_[0-9a-f]{4}$")
SEED_LO, SEED_HI = 5000, 75000  # master seeds: always far below the held-out range (>= 900000)
MAX_LOG_LINES = 300
NOISE = ("argv[0]=", "pybullet build time")
# the only files a client may download from a run folder (by this short name)
SERVED_FILES = {"summary.json", "gate_report.json", "hypotheses.json", "targeted_failures.json", "LABEL.json", "events.jsonl", "meta.json"}


class LiveError(Exception):
    def __init__(self, status: int, code: str, message: str, extra: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra or {}


@dataclass
class RunState:
    id: str
    seed: int
    dir: Path
    cancel_token: str = ""
    status: str = "queued"      # queued running finished cancelled timeout error
    verdict: str | None = None
    cost_usd: float | None = None
    created: str = ""
    started: str = ""
    ended: str = ""
    events: list[dict] = field(default_factory=list)
    seen: set = field(default_factory=set)
    cancel_requested: bool = False
    proc: subprocess.Popen | None = None
    log_lines: int = 0
    last_llm_id: int = 0

    @property
    def done(self) -> bool:
        return self.status in ("finished", "cancelled", "timeout", "error")

    @property
    def rid_dir(self) -> Path:
        return self.dir / "out" / f"run_01_seed{self.seed}"

    def meta(self) -> dict:
        return {"id": self.id, "status": self.status, "verdict": self.verdict, "estimated_cost_usd": self.cost_usd, "created": self.created,
                "started": self.started, "ended": self.ended, "master_seed": self.seed, "mode": "rehearsal", "official": False,
                "n_events": len(self.events)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _jload(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass


class RunManager:
    def __init__(self, cfg: LiveConfig, env: dict[str, str] | None = None):
        self.cfg = cfg
        self.env = env  # None: the real process environment
        self.lock = threading.RLock()
        self.current: RunState | None = None
        self.runs: dict[str, RunState] = {}
        self.ip_hits: dict[str, list[float]] = {}
        cfg.runs_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- quota ledger (per UTC day, persisted)
    @property
    def _ledger_path(self) -> Path:
        return self.cfg.runs_dir / "ledger.json"

    def _ledger(self) -> dict:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        data = _jload(self._ledger_path) or {}
        return {"day": day, **(data.get(day) or {"runs": 0, "usd": 0.0})}

    def _ledger_add(self, runs: int = 0, usd: float = 0.0) -> None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cur = self._ledger()
        data = {day: {"runs": cur["runs"] + runs, "usd": round(cur["usd"] + usd, 6)}}  # older days are dropped
        self._ledger_path.write_text(json.dumps(data), encoding="utf-8")

    def reserve_spend(self, usd: float) -> None:
        """Count an estimated spend (e.g. a playground analyze call) against the daily spend cap, or refuse."""
        with self.lock:
            if self._ledger()["usd"] + usd > self.cfg.daily_usd_cap:
                raise LiveError(429, "daily_usd_cap", "The daily estimated spend cap has been reached. Try again tomorrow.")
            self._ledger_add(usd=usd)

    def adjust_spend(self, delta_usd: float) -> None:
        with self.lock:
            self._ledger_add(usd=delta_usd)

    def status(self) -> dict:
        with self.lock:
            led = self._ledger()
            return {
                "enabled": self.cfg.enabled, "busy": bool(self.current and not self.current.done),
                "current_run_id": self.current.id if self.current and not self.current.done else None,
                "access_code_required": bool(self.cfg.access_code),
                "runs_left_today": max(0, self.cfg.daily_run_cap - led["runs"]),
                "estimated_usd_left_today": round(max(0.0, self.cfg.daily_usd_cap - led["usd"]), 4),
                "daily_run_cap": self.cfg.daily_run_cap, "daily_usd_cap": self.cfg.daily_usd_cap,
                "mode": "rehearsal", "note": "A live run is always a rehearsal on rehearsal seeds. It is never an official result.",
                "cost_note": "Spend figures are estimates from run artifacts; billing is not checked.",
            }

    # ---------------------------------------------------------------- start / get / cancel
    def start(self, ip: str, code: str | None) -> RunState:
        c = self.cfg
        with self.lock:
            if not c.enabled:
                raise LiveError(503, "disabled", "Live runs are switched off on this server.")
            if c.access_code and not secrets.compare_digest((code or "").encode(), c.access_code.encode()):
                raise LiveError(401, "access_code", "A valid access code is required to start a live run.")
            now = time.time()
            ih = hashlib.sha256(ip.encode()).hexdigest()[:12]
            hits = [t for t in self.ip_hits.get(ih, []) if now - t < 3600]
            if len(hits) >= c.per_ip_per_hour:
                raise LiveError(429, "rate_limited", f"At most {c.per_ip_per_hour} live runs per hour per visitor. Try again later.")
            led = self._ledger()
            if led["runs"] >= c.daily_run_cap:
                raise LiveError(429, "daily_run_cap", "The daily live-run quota has been reached. Try again tomorrow, or replay a recorded run.")
            if led["usd"] + c.est_run_usd > c.daily_usd_cap:
                raise LiveError(429, "daily_usd_cap", "The daily estimated spend cap has been reached. Try again tomorrow, or replay a recorded run.")
            if self.current and not self.current.done:
                raise LiveError(409, "busy", "Another live run is in progress. Only one run can go at a time.", {"current_run_id": self.current.id})
            rid = f"live_{datetime.now(timezone.utc).strftime('%Y%m%dt%H%M%S')}_{secrets.token_hex(2)}"
            seed = SEED_LO + secrets.randbelow(SEED_HI - SEED_LO)
            assert seed < 900_000  # a live run can never use a held-out seed
            st = RunState(id=rid, seed=seed, dir=c.runs_dir / rid, cancel_token=secrets.token_urlsafe(16), created=_now())
            st.dir.mkdir(parents=True)
            self.runs[rid] = st
            self.current = st
            self.ip_hits[ih] = hits + [now]
            self._ledger_add(runs=1, usd=c.est_run_usd)  # reserve; corrected to the real estimate when the run ends
            self._emit(st, "run", "info", f"Live REHEARSAL accepted (master seed {seed}). Not an official result; verification uses the rehearsal seed block.",
                       {"mode": "rehearsal", "master_seed": seed})
            threading.Thread(target=self._worker, args=(st,), daemon=True, name=f"live-{rid}").start()
            return st

    def get(self, rid: str) -> RunState | None:
        if not RUN_ID_RE.match(rid):
            return None
        with self.lock:
            if rid in self.runs:
                return self.runs[rid]
            d = self.cfg.runs_dir / rid
            meta = _jload(d / "meta.json")
            if not meta:
                return None
            st = RunState(id=rid, seed=int(meta.get("master_seed", 0)), dir=d, status=meta.get("status", "error"), verdict=meta.get("verdict"),
                          cost_usd=meta.get("estimated_cost_usd"), created=meta.get("created", ""), started=meta.get("started", ""), ended=meta.get("ended", ""))
            try:
                st.events = [json.loads(line) for line in (d / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            except OSError:
                st.events = []
            if not st.done:  # a run that was interrupted by a server restart
                st.status = "error"
            self.runs[rid] = st
            return st

    def cancel(self, rid: str, token: str) -> RunState:
        st = self.get(rid)
        if st is None:
            raise LiveError(404, "not_found", "No such run.")
        if not secrets.compare_digest(token.encode(), st.cancel_token.encode() if st.cancel_token else b"\x00"):
            raise LiveError(403, "forbidden", "Only the visitor who started the run can cancel it.")
        if st.done:
            raise LiveError(409, "finished", "That run has already ended.")
        st.cancel_requested = True
        return st

    # ---------------------------------------------------------------- events
    def _emit(self, st: RunState, stage: str, status: str, message: str, data: dict | None = None) -> None:
        with self.lock:
            ev = {"seq": len(st.events), "time": _now(), "stage": stage, "status": status, "message": scrub(message, self.env),
                  "data": scrub_obj(data or {}, self.env)}
            st.events.append(ev)
            try:
                with (st.dir / "events.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps(ev) + "\n")
            except OSError:
                pass

    def _save_meta(self, st: RunState) -> None:
        try:
            (st.dir / "meta.json").write_text(json.dumps(st.meta()), encoding="utf-8")
        except OSError:
            pass

    # ---------------------------------------------------------------- worker
    def _command(self, st: RunState) -> list[str]:
        # fixed argument list: nothing here comes from the client
        return [self.cfg.python_exe, str(self.cfg.pipeline_script), "--seeds", str(st.seed), "--out", str(st.dir / "out")]

    def _worker(self, st: RunState) -> None:
        c = self.cfg
        env = dict(self.env if self.env is not None else os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env.pop("LIVE_ACCESS_CODE", None)  # the pipeline needs no live-service secrets
        t0 = time.time()
        st.started, st.status = _now(), "running"
        self._save_meta(st)
        try:
            proc = subprocess.Popen(self._command(st), cwd=str(c.pipeline_script.parents[1]), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, errors="replace", bufsize=1, start_new_session=(os.name == "posix"))
        except OSError as e:
            self._finish(st, "error", f"Could not start the pipeline: {e}")
            return
        st.proc = proc
        lines: queue.Queue = queue.Queue()
        threading.Thread(target=lambda: [lines.put(ln) for ln in proc.stdout], daemon=True).start()  # type: ignore[union-attr]
        self._emit(st, "run", "info", "Pipeline process started.", {"command": "scripts/run_reliability.py (fixed arguments, one rehearsal seed)"})
        end_reason = None
        while True:
            self._drain(st, lines)
            self._scan(st)
            self._poll_llm(st)
            if st.cancel_requested:
                _kill(proc); end_reason = "cancelled"; break
            if time.time() - t0 > c.timeout_s:
                _kill(proc); end_reason = "timeout"; break
            if proc.poll() is not None:
                time.sleep(0.2)
                break
            time.sleep(c.poll_s)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _kill(proc)
        time.sleep(0.2)
        self._drain(st, lines); self._scan(st); self._poll_llm(st)
        if end_reason == "cancelled":
            self._finish(st, "cancelled", "Run cancelled. No verdict was produced.")
        elif end_reason == "timeout":
            self._finish(st, "timeout", f"Run stopped after {int(c.timeout_s)} s (time limit). No verdict was produced.")
        else:
            summ = _jload(st.rid_dir / "summary.json")
            if summ is None:
                self._finish(st, "error", f"The pipeline exited (code {proc.returncode}) without writing a result. No verdict was produced.")
            else:
                st.verdict = summ.get("verdict")
                cost = summ.get("estimated_cost_usd")
                st.cost_usd = float(cost) if cost is not None else None
                if st.verdict is None:
                    self._finish(st, "finished", f"The run ended without a verdict: {(summ.get('error') or 'no error text')[:200]}")
                else:
                    self._finish(st, "finished", f"Verdict: {st.verdict}")

    def _finish(self, st: RunState, status: str, message: str) -> None:
        with self.lock:
            st.status, st.ended = status, _now()
            if st.cost_usd is not None:  # replace the reservation with the run's own estimate
                self._ledger_add(usd=st.cost_usd - self.cfg.est_run_usd)
            self._emit(st, "verdict" if status == "finished" else "run", "error" if status in ("error", "timeout") else "done", message,
                       {"final_status": status, "verdict": st.verdict, "estimated_cost_usd": st.cost_usd})
            self._emit(st, "end", "done", "end of stream", {})
            self._save_meta(st)
            if self.current is st:
                self.current = None

    def _drain(self, st: RunState, lines: queue.Queue) -> None:
        while True:
            try:
                ln = lines.get_nowait()
            except queue.Empty:
                return
            ln = ln.rstrip()
            if not ln or any(n in ln for n in NOISE) or st.log_lines >= MAX_LOG_LINES:
                continue
            st.log_lines += 1
            self._emit(st, "log", "info", ln[:400])

    def _poll_llm(self, st: RunState) -> None:
        p = self.cfg.db_path
        if not p or not Path(p).exists():
            return
        try:
            con = sqlite3.connect(f"file:{Path(p).as_posix()}?mode=ro", uri=True, timeout=1)
            rows = con.execute("SELECT id,purpose,model,attempt,latency_s,prompt_tokens,completion_tokens,ok,error FROM llm_calls WHERE run_id=? AND id>? ORDER BY id",
                               (f"run_01_seed{st.seed}", st.last_llm_id)).fetchall()
            con.close()
        except sqlite3.Error:
            return
        stage_of = {"scenario_generation": "generator", "analyst": "analyst", "fixer": "fixer"}
        for (i, purpose, model, attempt, lat, pt, ct, ok, err) in rows:
            st.last_llm_id = i
            res = "ok" if ok else f"rejected by validation: {(err or '')[:140]}"
            self._emit(st, stage_of.get(purpose, purpose), "info",
                       f"Model call ({purpose}, try {attempt}) on {str(model).split('/')[-1]}: {lat:.1f}s, {pt} + {ct} tokens, {res}",
                       {"purpose": purpose, "model": model, "attempt": attempt, "latency_s": lat, "prompt_tokens": pt, "completion_tokens": ct, "ok": bool(ok)})

    # artifacts in the order the pipeline writes them
    def _scan(self, st: RunState) -> None:
        d = st.rid_dir
        if not d.exists():
            return
        for name in ("LABEL.json", "analysis_set.json", "baseline_results.json", "evidence.json", "hypotheses.json", "summary.json"):
            if name in st.seen or not (d / name).exists():
                continue
            if name == "summary.json" and not (d / "gate_report.json").exists() and not _jload(d / "summary.json"):
                continue
            data = _jload(d / name)
            if data is None:  # being written right now: try again on the next poll
                continue
            st.seen.add(name)
            getattr(self, "_on_" + name.split(".")[0])(st, data)

    def _on_LABEL(self, st, d):
        self._emit(st, "generator", "start", "Scenario generator: asking the fast Nemotron model for risky regions.", {})

    def _on_analysis_set(self, st, d):
        self._emit(st, "generator", "done", f"{d.get('n_coverage', 0) + d.get('n_targeted', 0)} scenarios ready: {d.get('n_coverage')} from the code-made coverage sweep, "
                   f"{d.get('n_targeted')} from model-proposed regions (source: {d.get('source')}).",
                   {"source": d.get("source"), "model": d.get("model"), "n_coverage": d.get("n_coverage"), "n_targeted": d.get("n_targeted"),
                    "dropped_regions": len(d.get("dropped_regions") or [])})
        self._emit(st, "baseline", "start", "Simulating the unpatched policy on every scenario (PyBullet, local container).", {})

    def _on_baseline_results(self, st, d):
        res = d.get("results") or []
        n_fail = sum(1 for r in res if not r.get("success"))
        self._emit(st, "baseline", "done", f"Baseline finished: {n_fail} of {len(res)} scenarios fail on the unpatched policy.",
                   {"n": len(res), "n_fail": n_fail, "runner": d.get("runner_name"), "wall_clock_s": d.get("wall_clock_s")})

    def _on_evidence(self, st, d):
        self._emit(st, "evidence", "done", "Failure statistics computed in code (failure rate per axis bin, decision tree, reason codes).", {})
        self._emit(st, "analyst", "start", "Analyst: asking the reasoning Nemotron model for testable hypotheses.", {})

    def _on_hypotheses(self, st, d):
        n = len(d) if isinstance(d, list) else len(d.get("hypotheses", d) if isinstance(d, dict) else [])
        self._emit(st, "analyst", "done", f"{n} hypotheses received (model wording is an unverified opinion; numbers come from code).", {"n_hypotheses": n})
        self._emit(st, "fixer", "start", "Fixer: proposing candidate patches; code will measure every candidate.", {})

    def _on_summary(self, st, s):
        gate = _jload(st.rid_dir / "gate_report.json") or {}
        for a in s.get("attempts") or []:
            cands = [{"index": c.get("index"), "applied": c.get("applied"), "fixed": c.get("fixed"), "targeted": c.get("targeted"),
                      "regressions": c.get("regressions"), "pass_rate": c.get("pass_rate"), "selected": c.get("selected"), "complete": c.get("complete")}
                     for c in a.get("candidates") or []]
            self._emit(st, "fixer", "done", f"Attempt {a.get('attempt')}: {len(cands)} candidates measured by code; candidate {a.get('selected_index')} selected "
                       f"(regression budget {a.get('regression_budget')}).",
                       {"attempt": a.get("attempt"), "selected_index": a.get("selected_index"), "regression_budget": a.get("regression_budget"),
                        "selection_rule": a.get("selection_rule"), "candidates": cands, "dev_stage_passed": a.get("dev_stage_passed"), "patched_policy": a.get("patched_policy")})
        for ck in (gate.get("report") or {}).get("checks") or []:
            self._emit(st, "gate", "done", f"{ck.get('id')} {str(ck.get('status')).upper()}: {ck.get('name')}", {"check": ck})
        self._emit(st, "gate", "info", "Gate results are written together when the pipeline finishes, so G1 to G6 arrive here at the end.",
                   {"metrics": s.get("metrics"), "strict_zero_budget": s.get("strict_zero_budget")})
