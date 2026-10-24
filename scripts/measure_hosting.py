"""Measure peak memory and time of a single scenario, a 50-row sweep and a 50-row batch in the host image under two resource limits.

Run from the repo root on a machine with Docker, after `docker build -f docker/Dockerfile.host -t roboproof-host:dev .`:

  python scripts/measure_hosting.py                      # prints a table
  python scripts/measure_hosting.py --out docs/HOSTING_MEASUREMENTS.md

Each (limit, operation) pair gets a FRESH container, so the peak is that operation's peak plus the idle server. Peak memory is the cgroup's own
high-water mark (memory.peak) read inside the container; docker's sampled usage is shown beside it. "Killed" means the container's OOMKilled
flag or any oom_kill event in its memory cgroup, which also catches a single simulator worker process killed while the server stays up.
Every number is measured here and now on this machine; none is estimated. Nothing is deployed and no model is called.
"""
import argparse
import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "roboproof-host:dev"
PORT = 8037
PROFILES = [("512 MB / 0.5 CPU", "512m", "0.5"), ("2 GB / 2 CPUs", "2g", "2")]


def sh(*a: str, timeout: float = 120) -> str:
    p = subprocess.run(list(a), capture_output=True, text=True, timeout=timeout)
    return p.stdout.strip()


def http(method: str, path: str, body: dict | None = None, timeout: float = 600) -> tuple[int, dict | str]:
    req = urllib.request.Request(f"http://localhost:{PORT}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if raw[:1] in "{[" else raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return 0, f"{type(e).__name__}: {e}"


def mib(n: float) -> float:
    return round(n / 2**20, 1)


def cgroup_read(cid: str, name: str) -> str:
    return sh("docker", "exec", cid, "cat", f"/sys/fs/cgroup/{name}")


def peak_bytes(cid: str) -> int | None:
    for f in ("memory.peak", "memory/memory.max_usage_in_bytes"):
        v = cgroup_read(cid, f)
        if v.isdigit():
            return int(v)
    return None


def oom_kills(cid: str) -> int | None:
    for f in ("memory.events", "memory/memory.oom_control"):
        txt = cgroup_read(cid, f)
        for line in txt.splitlines():
            if line.startswith("oom_kill ") and line.split()[1].isdigit():
                return int(line.split()[1])
    return None


class Sampler(threading.Thread):
    """Samples `docker stats` while a request runs (a cross-check for the cgroup high-water mark)."""

    def __init__(self, cid: str):
        super().__init__(daemon=True)
        self.cid, self.peak, self.stop = cid, 0.0, False

    def run(self) -> None:
        while not self.stop:
            out = sh("docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", self.cid, timeout=20)
            try:
                used = out.split("/")[0].strip()
                num = float("".join(c for c in used if c.isdigit() or c == "."))
                unit = used.lstrip("0123456789. ")
                self.peak = max(self.peak, num * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "B": 1 / 2**20}.get(unit, 1))
            except ValueError:
                pass


def rows_csv(spec: dict, n: int) -> str:
    cols = [p["name"] for p in spec["scenario"]]
    lines = [",".join(cols)]
    for i in range(n):
        cells = []
        for j, p in enumerate(spec["scenario"]):
            f = (i * 0.37 + j * 0.173) % 1
            v = p["min"] + (p["max"] - p["min"]) * f
            cells.append(str(int(round(v))) if p.get("integer") else f"{v:.4f}")
        lines.append(",".join(cells))
    return "\n".join(lines)


def one(profile: tuple[str, str, str], op: str) -> dict:
    label, mem, cpus = profile
    sh("docker", "rm", "-f", "rp-measure")
    t0 = time.time()
    cid = sh("docker", "run", "-d", "--name", "rp-measure", "--memory", mem, "--memory-swap", mem, "--cpus", cpus, "-p", f"{PORT}:8000",
             "-e", "ROBOPROOF_HOST_MODE=1", IMAGE)
    out: dict = {"profile": label, "op": op, "cid": cid[:12]}
    if not cid:
        return {**out, "error": "container did not start"}
    ok = False
    for _ in range(240):
        st, body = http("GET", "/api/health", timeout=3)
        if st == 200:
            ok = True
            break
        time.sleep(0.5)
    out["start_s"] = round(time.time() - t0, 1)
    if not ok:
        out["error"] = "health check never succeeded: " + sh("docker", "logs", "--tail", "5", cid)
        sh("docker", "rm", "-f", "rp-measure")
        return out
    ver = http("GET", "/api/version")[1]
    out["workers"] = ver.get("workers") if isinstance(ver, dict) else None
    out["effective_cpus"] = ver.get("effective_cpus") if isinstance(ver, dict) else None
    time.sleep(1.0)
    out["idle_peak_mib"] = mib(peak_bytes(cid) or 0)
    spec = http("GET", "/api/sim/spec")[1]
    if op == "scenario":
        path, body = "/api/sim/scenario", {"scenario": next(x for x in spec["presets"] if x["id"] == "benign")["scenario"]}
    elif op == "sweep50":
        path, body = "/api/sim/sweep", {"n": 50, "seed": spec["seed"]["default"]}
    else:
        path, body = "/api/sim/batch", {"csv": rows_csv(spec, 50)}
    s = Sampler(cid)
    s.start()
    t1 = time.perf_counter()
    status, resp = http("POST", path, body)
    out["seconds"] = round(time.perf_counter() - t1, 1)
    s.stop = True
    s.join(timeout=15)
    out["http"] = status
    if isinstance(resp, dict):
        out["server_wall_s"] = resp.get("wall_clock_s") or (resp.get("result") or {}).get("wall_clock_s")
        out["detail"] = resp.get("message") or (f"n={resp.get('metrics', {}).get('n')}" if resp.get("metrics") else "ok")
    else:
        out["detail"] = str(resp)[:120]
    pk = peak_bytes(cid)
    out["peak_mib"] = mib(pk) if pk else None
    out["sampled_peak_mib"] = round(s.peak, 1) if s.peak else None
    out["oom_kill_events"] = oom_kills(cid)
    ins = sh("docker", "inspect", "-f", "{{.State.OOMKilled}} {{.State.Running}} {{.State.ExitCode}}", cid).split()
    out["container_oom_killed"] = ins[0] == "true" if ins else None
    out["still_running"] = ins[1] == "true" if len(ins) > 1 else None
    out["killed"] = bool(out["container_oom_killed"] or (out["oom_kill_events"] or 0) > 0 or not out["still_running"])
    sh("docker", "rm", "-f", "rp-measure")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="write a markdown report here")
    a = ap.parse_args()
    if not sh("docker", "image", "inspect", "-f", "{{.Id}}", IMAGE):
        sys.exit(f"build the image first: docker build -f docker/Dockerfile.host -t {IMAGE} .")
    results = []
    for prof in PROFILES:
        for op in ("scenario", "sweep50", "batch50"):
            print(f"... {prof[0]}: {op}", flush=True)
            r = one(prof, op)
            results.append(r)
            print("   ", json.dumps({k: v for k, v in r.items() if k != "cid"}), flush=True)
    head = "| Limit | Operation | HTTP | Time | Peak memory (cgroup) | Sampled peak | Idle server | Workers | Killed? | Start to healthy |\n|---|---|---|---|---|---|---|---|---|---|"
    lines = [head]
    names = {"scenario": "1 scenario", "sweep50": "50-scenario sweep", "batch50": "50-row batch"}
    for r in results:
        if "error" in r:
            lines.append(f"| {r['profile']} | {names[r['op']]} | - | - | - | - | - | - | ERROR: {r['error'][:80]} | {r.get('start_s', '-')} s |")
            continue
        lines.append(f"| {r['profile']} | {names[r['op']]} | {r['http']} | {r['seconds']} s | {r['peak_mib']} MiB | {r['sampled_peak_mib']} MiB | {r['idle_peak_mib']} MiB | {r['workers']} | "
                     f"{'YES' if r['killed'] else 'no'} (oom events {r['oom_kill_events']}) | {r['start_s']} s |")
    table = "\n".join(lines)
    print("\n" + table)
    if a.out:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        info = sh("docker", "version", "--format", "Docker {{.Server.Version}} on {{.Server.Os}}/{{.Server.Arch}}")
        Path(a.out).write_text(
            f"# Hosting measurements\n\nGenerated by `scripts/measure_hosting.py` on {stamp} ({info}), image `{IMAGE}`. Each row is one run in a fresh container with the stated "
            "`--memory` (swap disabled) and `--cpus`. Peak memory is the container cgroup's high-water mark (idle server included); \"killed\" means an OOM kill of the container or "
            "of any process in it. These are single measurements on a development machine (a Windows laptop with Docker Desktop), not benchmarks, and a host's CPU is "
            "typically slower, so treat the times as a lower bound.\n\n" + table + "\n\n```json\n" + json.dumps(results, indent=1) + "\n```\n", encoding="utf-8")
        print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
