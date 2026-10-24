"""Settings for running as one small container on a free host (for example Render free): the container's real CPU and memory limits,
a runtime data directory, and the small default limits used in host mode. Nothing here touches the frozen pipeline or the simulator.

Host mode is switched on by ROBOPROOF_HOST_MODE=1 (the host Dockerfile sets it). Counters kept under DATA_DIR (the daily live-run
quota, run folders) live on local disk, which such hosts lose when the instance spins down, so they reset when the host restarts."""
from __future__ import annotations

import math
import os
from pathlib import Path

CGROUP = Path("/sys/fs/cgroup")
DEFAULT_DATA_DIR = "/tmp/roboproof"
HOST_MAX_SWEEP_N = 50
HOST_MAX_BATCH_ROWS = 50
HARD_MAX_SWEEP_N = 200   # the documented cap, never exceeded
HARD_MAX_BATCH_ROWS = 200


def _flag(v: str | None, default: bool = False) -> bool:
    return default if v is None or v == "" else v.strip().lower() in ("1", "true", "yes", "on")


def host_mode(env: dict | None = None) -> bool:
    return _flag((env if env is not None else os.environ).get("ROBOPROOF_HOST_MODE"))


def _read(p: Path) -> str | None:
    try:
        return p.read_text().strip()
    except OSError:
        return None


def cpu_quota(cgroup: Path = CGROUP) -> float | None:
    """CPUs the container may use, from its cgroup limit (v2 cpu.max, then v1 cfs quota), or None when unlimited or unknown."""
    v2 = _read(cgroup / "cpu.max")
    if v2:
        q, _, period = v2.partition(" ")
        if q != "max" and period.isdigit() and q.isdigit() and int(period) > 0:
            return int(q) / int(period)
        return None
    q1, p1 = _read(cgroup / "cpu" / "cpu.cfs_quota_us"), _read(cgroup / "cpu" / "cpu.cfs_period_us")
    if q1 and p1 and q1.lstrip("-").isdigit() and p1.isdigit() and int(q1) > 0 and int(p1) > 0:
        return int(q1) / int(p1)
    return None


def effective_cpus(cgroup: Path = CGROUP) -> float:
    """The CPU count this container can really use: the smaller of the cgroup quota and the visible (affinity) CPUs.
    os.cpu_count() reports the host's cores inside a limited container, which would start far too many workers."""
    try:
        visible = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        visible = os.cpu_count() or 1
    q = cpu_quota(cgroup)
    return min(float(visible), q) if q else float(visible)


def worker_count(cgroup: Path = CGROUP) -> int:
    """Simulator worker processes: the real CPU limit rounded up, at least 1 (a 0.5 CPU container gets 1 worker)."""
    return max(1, math.ceil(effective_cpus(cgroup) - 1e-9))


def memory_limit_bytes(cgroup: Path = CGROUP) -> int | None:
    for p in (cgroup / "memory.max", cgroup / "memory" / "memory.limit_in_bytes"):
        v = _read(p)
        if v and v.isdigit() and int(v) < 1 << 60:
            return int(v)
    return None


def data_dir(env: dict | None = None) -> Path:
    return Path((env if env is not None else os.environ).get("DATA_DIR") or DEFAULT_DATA_DIR)


def env_int(env: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(float(env[key])) if env.get(key) not in (None, "") else default
    except ValueError:
        v = default
    return max(lo, min(hi, v))


def max_sweep_n(env: dict | None = None) -> int:
    """MAX_SWEEP_N (or the older PLAYGROUND_MAX_SWEEP_N), default 50 in host mode and 200 otherwise, never above 200."""
    e = env if env is not None else dict(os.environ)
    default = HOST_MAX_SWEEP_N if host_mode(e) else HARD_MAX_SWEEP_N
    d = env_int(e, "PLAYGROUND_MAX_SWEEP_N", default, 1, HARD_MAX_SWEEP_N)
    return env_int(e, "MAX_SWEEP_N", d, 1, HARD_MAX_SWEEP_N)


def max_batch_rows(env: dict | None = None) -> int:
    e = env if env is not None else dict(os.environ)
    return env_int(e, "MAX_BATCH_ROWS", HOST_MAX_BATCH_ROWS if host_mode(e) else HARD_MAX_BATCH_ROWS, 1, HARD_MAX_BATCH_ROWS)


def prepare_data_dir(env: dict | None = None) -> Path:
    """Create DATA_DIR (and its live_runs folder) so a non-root user can write runtime data there."""
    d = data_dir(env)
    (d / "live_runs").mkdir(parents=True, exist_ok=True)
    return d
