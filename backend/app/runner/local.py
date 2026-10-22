"""LocalRunner: shards run as separate processes on this machine (the labelled fallback to Nebius Serverless Jobs).

Each shard runs in its own process, writes <workdir>/shard-NNNN/results.json, and is killed if it exceeds
`shard_timeout_s`. PyBullet creates its own client per scenario, so forked children are independent.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import tempfile
import time
import traceback
from pathlib import Path
from typing import Callable

from pydantic import TypeAdapter

from ..core.schemas import Policy, Result, Scenario, ShardResult
from .base import JobRunner, RunResult, split_into_shards

ShardFn = Callable[[Policy, list[Scenario], bool], list[Result]]
_RESULTS = TypeAdapter(list[Result])


def run_shard_scenarios(policy: Policy, scenarios: list[Scenario], held_out: bool = False) -> list[Result]:
    from ..sim.pickplace import run_scenario  # imported lazily: PyBullet only exists in the sim image

    return [run_scenario(policy, s, held_out=held_out)[0] for s in scenarios]


def _shard_main(fn: ShardFn, policy: Policy, scenarios: list[Scenario], held_out: bool, out_dir: str) -> None:
    out = Path(out_dir)
    try:
        results = fn(policy, scenarios, held_out)
        tmp = out / "results.json.tmp"
        tmp.write_bytes(_RESULTS.dump_json(results))
        os.replace(tmp, out / "results.json")  # atomic: a half-written file is never read as a result
    except BaseException:
        (out / "error.txt").write_text(traceback.format_exc())
        raise SystemExit(1)


class LocalRunner(JobRunner):
    name = "local"

    def __init__(self, max_workers: int | None = None, shard_timeout_s: float = 900.0,
                 workdir: str | Path | None = None, shard_fn: ShardFn = run_shard_scenarios):
        self.max_workers = max_workers or os.cpu_count() or 2
        self.shard_timeout_s = shard_timeout_s
        self.workdir = Path(workdir) if workdir else None
        self.shard_fn = shard_fn
        self.ctx = mp.get_context("fork" if "fork" in mp.get_all_start_methods() else "spawn")

    def _run(self, policy: Policy, scenarios: list[Scenario], shards: int, held_out: bool) -> RunResult:
        chunks = split_into_shards(scenarios, shards)
        root = self.workdir or Path(tempfile.mkdtemp(prefix="roboproof-run-"))
        root.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        specs = [(i, c, root / f"shard-{i:04d}") for i, c in enumerate(chunks)]
        for _, _, d in specs:
            d.mkdir(parents=True, exist_ok=True)
        status: dict[int, ShardResult] = {}
        pending = list(specs)
        running: dict[int, tuple] = {}  # idx -> (proc, spec, start)

        def finish(idx: int, proc, spec, started: float, timed_out: bool) -> None:
            _, chunk, d = spec
            wall = time.perf_counter() - started
            sid = f"shard-{idx:04d}"
            mk = lambda st, results=(), err=None: ShardResult(  # noqa: E731
                shard_id=sid, status=st, runner="local", results=list(results), n_expected=len(chunk),
                wall_clock_s=round(wall, 3), error=err)
            if timed_out:
                status[idx] = mk("TIMEOUT", err=f"killed after {self.shard_timeout_s}s")
                return
            rfile = d / "results.json"
            if proc.exitcode != 0 or not rfile.exists():
                err = (d / "error.txt").read_text()[-500:] if (d / "error.txt").exists() else f"exit code {proc.exitcode}"
                status[idx] = mk("FAILED", err=err)
                return
            try:
                got = _RESULTS.validate_json(rfile.read_bytes())
            except Exception as e:  # malformed output
                status[idx] = mk("FAILED", err=f"unreadable results.json: {type(e).__name__}")
                return
            want = [(s.id, s.seed) for s in chunk]
            if [(r.scenario_id, r.seed) for r in got] != want:
                status[idx] = mk("FAILED", err=f"returned {len(got)} results for {len(want)} scenarios (ids/seeds/order mismatch)")
                return
            status[idx] = mk("COMPLETED", results=got)

        while pending or running:
            while pending and len(running) < self.max_workers:
                spec = pending.pop(0)
                p = self.ctx.Process(target=_shard_main, args=(self.shard_fn, policy, spec[1], held_out, str(spec[2])))
                p.start()
                running[spec[0]] = (p, spec, time.perf_counter())
            for idx in list(running):
                p, spec, started = running[idx]
                if not p.is_alive():
                    p.join()
                    finish(idx, p, spec, started, False)
                    del running[idx]
                elif time.perf_counter() - started > self.shard_timeout_s:
                    p.kill()
                    p.join()
                    finish(idx, p, spec, started, True)
                    del running[idx]
            time.sleep(0.02)

        shards_out = [status[i] for i in range(len(specs))]
        return RunResult.build("local", shards_out, [[s.id for s in c] for c in chunks],
                               wall_clock_s=round(time.perf_counter() - t0, 3), cpu_count=os.cpu_count(),
                               image_build_id=os.environ.get("ROBOPROOF_IMAGE_ID"))
