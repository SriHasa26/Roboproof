from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Callable

from ..core import gate_config as cfg
from ..core.schemas import CheckStatus, GateCheck, Policy, Result, Scenario
from ..core.seeds import BLOCKS
from ..core.stats import wilson
from ..gate.gate import decide_verdict, frac, meets_fraction, regression_budget

MATCH, MISMATCH, UNVERIFIABLE, INFO = "match", "mismatch", "unverifiable", "info"
DASHBOARD_RUNS = Path("frontend") / "public" / "data" / "runs"


@dataclass
class Row:
    group: str        # recompute | resimulate | integrity | limits
    id: str
    name: str
    stored: str
    recomputed: str
    status: str       # match | mismatch | unverifiable | info
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def jl(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _s(x) -> str:
    if isinstance(x, float):
        return f"{x:.4f}".rstrip("0").rstrip(".") if x != int(x) else str(int(x))
    return str(x)


def cmp(group: str, id_: str, name: str, stored, recomputed, note: str = "") -> Row:
    return Row(group, id_, name, _s(stored), _s(recomputed), MATCH if _s(stored) == _s(recomputed) else MISMATCH, note)


def unverifiable(group: str, id_: str, name: str, why: str, stored: str = "") -> Row:
    return Row(group, id_, name, stored, "not recomputed", UNVERIFIABLE, why)


# ------------------------------------------------------------------ 1. recompute from stored counts (no simulation)
def _status(ok: bool) -> str:
    return "pass" if ok else "fail"


def recompute_run(run_dir: Path, official_row: dict | None = None, dash: dict | None = None) -> list[Row]:
    s, rep = jl(run_dir / "summary.json"), jl(run_dir / "gate_report.json")["report"]
    chk = {c["id"]: c for c in rep["checks"]}
    rows: list[Row] = []
    R = rows.append
    final = s["attempts"][-1]

    # thresholds stored in the gate report must be the frozen config values
    th3, th4, th5 = chk["G3"]["threshold"], chk["G4"]["threshold"], chk["G5"]["threshold"]
    R(cmp("recompute", "cfg", "thresholds in the stored gate report equal the frozen config",
          f"G3 {th3['min_fix_rate']}, G4 {th4['budget_frac']}, G5 {th5['min_pass_rate']}/{th5['min_improvement']}",
          f"G3 {cfg.GATE_TARGET_FIX_RATE}, G4 {cfg.GATE_REGRESSION_BUDGET_FRAC}, G5 {cfg.GATE_HELDOUT_TARGET}/{cfg.GATE_MIN_IMPROVEMENT}",
          "a different threshold would make every recomputation below meaningless"))

    # stored baseline cross-checks (per-scenario results are stored for the analysis set)
    base = {r["scenario_id"]: r for r in jl(run_dir / "baseline_results.json")["results"]}
    tf = jl(run_dir / "targeted_failures.json")["all"]
    passes_before = sum(1 for r in base.values() if r["success"])
    R(cmp("recompute", "base_n", "analysis-set size: stored per-scenario results vs reported n", len(base), s["metrics"]["analysis"]["before"]["n"]))
    R(cmp("recompute", "base_rate", "unpatched analysis pass rate: from stored per-scenario results", s["metrics"]["analysis"]["before"]["pass_rate"], round(passes_before / len(base), 4)))
    R(cmp("recompute", "targeted_fail", "every targeted scenario failed in the stored unpatched results (failing count = targeted count)", len(tf), sum(1 for i in tf if not base[i]["success"])))
    # statuses re-derived from the stored observed numbers with the gate's own functions
    o1, o2, o3, o4, o5, o6 = (chk[k]["observed"] for k in ("G1", "G2", "G3", "G4", "G5", "G6"))
    rec = {
        "G1": _status(o1["mismatches"] == 0),
        "G2": _status(o2["not_reproduced"] == 0),
        "G3": _status(meets_fraction(o3["fixed"], o3["targeted"], cfg.GATE_TARGET_FIX_RATE)),
        "G4": _status(o4["regressions"] <= regression_budget(o4["previously_passing"])),
        "G6": _status(not o6.get("incomplete_runs")),
    }
    R(cmp("recompute", "G3_inputs", "G3 targeted count equals the stored targeted set", o3["targeted"], len(tf)))
    R(cmp("recompute", "G4_prev", "G4 previously-passing count equals the stored baseline passes", o4["previously_passing"], passes_before))
    R(cmp("recompute", "G4_budget", "G4 regression budget: floor(2% x previously passing)", chk["G4"]["threshold"]["budget"], regression_budget(o4["previously_passing"])))
    kp, kb, n = o5["patched_passes"], o5["unpatched_passes"], o5["n"]
    conds = {"target": meets_fraction(kp, n, cfg.GATE_HELDOUT_TARGET), "improvement": Fraction(kp - kb, n) >= frac(cfg.GATE_MIN_IMPROVEMENT),
             "wilson_lower_above_baseline": wilson(kp, n)[0] > kb / n}
    rec["G5"] = _status(all(conds.values()))
    for k in ("G1", "G2", "G3", "G4", "G5", "G6"):
        R(cmp("recompute", k, f"{k} status re-derived from the stored numbers", chk[k]["status"], rec[k]))
    R(cmp("recompute", "G5_conds", "G5 conditions (target / improvement / Wilson lower above baseline)", o5["conditions"], conds))
    R(cmp("recompute", "G5_lower", "G5 patched Wilson 95% lower bound", o5["patched_wilson95_lower"], round(wilson(kp, n)[0], 4)))
    R(cmp("recompute", "G5_impr", "G5 improvement (percentage points)", o5["improvement"], round(kp / n - kb / n, 4)))
    # Wilson intervals of every reported pass rate, from the counts
    def wrow(key: str, label: str, k: int, nn: int, stored: dict):
        lo, hi = wilson(k, nn)
        R(cmp("recompute", key, f"{label}: pass rate and Wilson 95% interval", f"{stored['pass_rate']} {stored['pass_rate_ci95']}", f"{round(k / nn, 4)} {[round(lo, 4), round(hi, 4)]}", f"from {k} of {nn}"))
    an = s["metrics"]["analysis"]
    wrow("W_an_before", "analysis, unpatched", passes_before, len(base), an["before"])
    wrow("W_an_after", "analysis, patched", round(an["after"]["pass_rate"] * an["after"]["n"]), an["after"]["n"], an["after"])
    ver = s["metrics"]["verification"]
    wrow("W_ver_before", "held-out, unpatched", kb, n, ver["before"])
    wrow("W_ver_after", "held-out, patched", kp, n, ver["after"])
    # verdict
    gc = [GateCheck(id=k, name=k, status=CheckStatus(rec[k] if k in rec else "pass")) for k in ("G1", "G2", "G3", "G4", "G5", "G6")]
    verdict = decide_verdict(gc).value
    R(cmp("recompute", "verdict", "verdict (documented precedence) from the re-derived statuses", s["verdict"], verdict))
    R(cmp("recompute", "verdict_gate", "verdict stored in gate_report.json", rep["verdict"], verdict))
    # internal consistency of the attempt that was gated
    sel = final["candidates"][final["selected_index"]]
    R(cmp("recompute", "cand_G3", "selected candidate (fixed/targeted) equals the gate's G3 numbers", f"{sel['fixed']}/{sel['targeted']}", f"{final['dev_checks']['G3']['observed']['fixed']}/{final['dev_checks']['G3']['observed']['targeted']}"))
    R(cmp("recompute", "cand_G4", "selected candidate regressions equal the gate's G4 numbers", sel["regressions"], final["dev_checks"]["G4"]["observed"]["regressions"]))
    R(cmp("recompute", "regressed_ids", "regressed scenario ids: stored list length equals the regression count", len(final["regressed_scenario_ids"]), o4["regressions"]))
    # the same facts in the other stored files
    if official_row is not None:
        R(cmp("recompute", "summary_row", "official_summary.json row: verdict, attempts, final checks", f"{official_row['verdict']} / {official_row['attempts']} / {official_row['final_checks']}",
              f"{s['verdict']} / {s['n_attempts']} / {s['checks']}"))
        R(cmp("recompute", "summary_rate", "official_summary.json row: held-out pass rate after", official_row["verification_after"]["pass_rate"], round(kp / n, 4)))
    if dash is not None:
        R(cmp("recompute", "dash_verdict", "dashboard JSON: verdict and gate statuses", f"{dash['verdict']} / {[c['status'] for c in dash['gate']['checks']]}", f"{s['verdict']} / {[s['checks'][k] for k in ('G1', 'G2', 'G3', 'G4', 'G5', 'G6')]}"))
        R(cmp("recompute", "dash_rate", "dashboard JSON: held-out pass rate after", dash["metrics"]["verification"]["after"]["pass_rate"], round(kp / n, 4)))
    return rows


# ------------------------------------------------------------------ 2. re-simulation of the ANALYSIS set (never held-out)
def _scenarios(run_dir: Path) -> list[Scenario]:
    scns = [Scenario(**sc) for sc in jl(run_dir / "analysis_set.json")["scenarios"]]
    assert all(sc.seed < BLOCKS["rehearsal"][0] for sc in scns), "analysis-set seeds must be dev seeds"
    return scns


def default_runner(timeout_s: float):
    from ..runner.local import LocalRunner
    return LocalRunner(shard_timeout_s=timeout_s)


def resimulate_run(run_dir: Path, runner_factory: Callable[[float], object] = default_runner, timeout_s: float = 60.0, all_attempts: bool = False) -> list[Row]:
    """Re-run the stored analysis set with the unpatched policy and the selected patch(es); compare every number with what was stored."""
    t0 = time.perf_counter()
    s = jl(run_dir / "summary.json")
    scns = _scenarios(run_dir)
    stored_base = {r["scenario_id"]: Result(**r) for r in jl(run_dir / "baseline_results.json")["results"]}
    targeted = jl(run_dir / "targeted_failures.json")["all"]
    runner = runner_factory(timeout_s)

    def run(policy: Policy) -> dict[str, Result]:
        rr = runner.run(policy, scns, shards=min(10, len(scns)))  # type: ignore[attr-defined]
        if not rr.complete:
            raise RuntimeError("re-simulation did not complete (a shard timed out or failed)")
        return {r.scenario_id: r for r in rr.results}

    rows: list[Row] = []
    R = rows.append
    now = run(Policy())
    same = sum(1 for i, r in now.items() if i in stored_base and r.model_dump() == stored_base[i].model_dump())
    R(cmp("resimulate", "base_same", "unpatched policy: re-run results identical to the stored per-scenario results", f"{len(stored_base)} of {len(stored_base)}", f"{same} of {len(now)}", "success, collision, time, place error, slip, reason all equal"))
    R(cmp("resimulate", "base_rate", "unpatched analysis pass rate", s["metrics"]["analysis"]["before"]["pass_rate"], round(sum(r.success for r in now.values()) / len(now), 4)))
    R(cmp("resimulate", "targeted_fail", "targeted failures still fail on the unpatched policy (failing count = targeted count)", len(targeted), sum(1 for i in targeted if not now[i].success)))
    attempts = s["attempts"] if all_attempts else s["attempts"][-1:]
    for a in attempts:
        tag = f"attempt {a['attempt']}"
        pol = Policy(**a["patched_policy"])
        got = run(pol)
        sel = a["candidates"][a["selected_index"]]
        passing_before = [i for i, r in now.items() if r.success]
        fixed = sum(got[i].success for i in targeted)
        regressed = sorted(i for i in passing_before if not got[i].success)
        R(cmp("resimulate", f"fixed_{a['attempt']}", f"{tag}: targeted failures fixed by the selected patch", f"{sel['fixed']} of {sel['targeted']}", f"{fixed} of {len(targeted)}"))
        R(cmp("resimulate", f"reg_{a['attempt']}", f"{tag}: regressions (previously passing, now failing)", f"{sel['regressions']} of {sel['previously_passing']}", f"{len(regressed)} of {len(passing_before)}"))
        R(cmp("resimulate", f"regids_{a['attempt']}", f"{tag}: the regressed scenario ids", a["regressed_scenario_ids"], regressed))
        R(cmp("resimulate", f"rate_{a['attempt']}", f"{tag}: patched analysis pass rate", sel["pass_rate"], round(sum(r.success for r in got.values()) / len(got), 3), "stored with 3 decimals in the candidate table"))
        g3, g4 = a["dev_checks"]["G3"], a["dev_checks"]["G4"]
        R(cmp("resimulate", f"G3_{a['attempt']}", f"{tag}: G3 (fixed enough) status", g3["status"], _status(meets_fraction(fixed, len(targeted), cfg.GATE_TARGET_FIX_RATE))))
        R(cmp("resimulate", f"G4_{a['attempt']}", f"{tag}: G4 (no regressions within budget) status", g4["status"], _status(len(regressed) <= regression_budget(len(passing_before)))))
        if a is s["attempts"][-1]:
            an = s["metrics"]["analysis"]["after"]
            R(cmp("resimulate", "after_rate", "final patch: analysis pass rate and collision rate", f"{an['pass_rate']} / {an['collision_rate']}",
                  f"{round(sum(r.success for r in got.values()) / len(got), 4)} / {round(sum(r.collision for r in got.values()) / len(got), 4)}"))
    rows.append(Row("resimulate", "elapsed", "re-simulation wall-clock time", "", f"{time.perf_counter() - t0:.1f} s", INFO, f"{len(scns)} analysis scenarios x {1 + len(attempts)} policies, this machine"))
    return rows


def limits_rows() -> list[Row]:
    return [
        unverifiable("limits", "heldout_counts", "held-out pass counts (G5: 400 fresh scenarios, unpatched and patched)",
                     "Held-out seeds are gate-only and single-use, and per-scenario held-out results were not stored, so they cannot be re-simulated. They are checked for internal consistency only (Wilson intervals, thresholds, verdict)."),
        unverifiable("limits", "model_outputs", "model outputs (scenario regions, hypotheses, candidate patches)",
                     "A model's reply is not reproducible. What is checkable: the stored raw replies and call log (see the model-call log), and that every number downstream of them was measured by the simulator and the gate."),
        unverifiable("limits", "analysis_set_origin", "how the analysis set was generated",
                     "Regenerating it needs the model. The stored scenario list is what was simulated, and re-simulating it reproduces the stored results."),
    ]


# ------------------------------------------------------------------ 3. integrity: ledger, protocol ordering, freeze
class Git:
    def __init__(self, root: Path):
        self.root = root

    def __call__(self, *args: str) -> tuple[int, str]:
        try:
            p = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, timeout=30)
            return p.returncode, p.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return 127, ""

    @property
    def available(self) -> bool:
        return self(" rev-parse".strip(), "--git-dir")[0] == 0


SNAPSHOT_REL = "docs/evidence/git_facts_snapshot.json"


class SnapshotGit:
    """Answers the few git questions the integrity checks ask from a committed snapshot of git's own answers, for environments with no .git
    (the container image). It is evidence taken from git at export time, not a live check, and the rows say so."""

    available = True

    def __init__(self, facts: dict):
        self.f = facts

    @classmethod
    def load(cls, root: Path):
        p = root / SNAPSHOT_REL
        return cls(jl(p)) if p.exists() else None

    def __call__(self, *a: str) -> tuple[int, str]:
        f = self.f
        try:
            if a[0] == "log":
                return (0, f["commit_times"][a[-1]]) if a[-1] in f["commit_times"] else (1, "")
            if a[0] == "merge-base":
                return (0 if f["ancestry"][f"{a[2]}>{a[3]}"] else 1, "")
            if a[0] == "diff":
                return (0 if f["protocol_unchanged"][f"{a[2]}>{a[3]}"] else 1, "")
            if a[0] == "show":
                c = a[1].split(":")[0]
                return (0, f["frozen_hash_files"][c]) if c in f["frozen_hash_files"] else (1, "")
            if a[0] == "rev-parse":
                t = a[1].split("^")[0]
                return (0, f["tags"][t]) if t in f["tags"] else (1, "")
        except KeyError:
            pass
        return 1, ""


def export_git_facts(root: Path, run_dirs: list[Path]) -> dict:
    """Ask real git the exact questions integrity_rows asks, for the commits the runs recorded."""
    git = Git(root)
    sums = [jl(d / "summary.json") for d in run_dirs]
    prov = sums[0]["provenance"]
    pc = prov["protocol_commit"]
    out: dict = {"exported_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "head": git("rev-parse", "HEAD")[1], "commit_times": {}, "ancestry": {}, "protocol_unchanged": {}, "frozen_hash_files": {}, "tags": {}}
    out["commit_times"][pc] = git("log", "-1", "--format=%cI", pc)[1]
    for s in sums:
        c = s["provenance"]["commit"]
        out["ancestry"][f"{pc}>{c}"] = git("merge-base", "--is-ancestor", pc, c)[0] == 0
        out["protocol_unchanged"][f"{pc}>{c}"] = git("diff", "--quiet", pc, c, "--", "docs/OFFICIAL_PROTOCOL.md")[0] == 0
        out["frozen_hash_files"][c] = git("show", f"{c}:backend/app/core/FROZEN_PIPELINE_HASH.txt")[1]
    out["tags"][prov["tag"]] = git("rev-parse", f"{prov['tag']}^{{commit}}")[1]
    return out


def _utc(ts: str) -> datetime:
    """Run timestamps are written by the container (UTC); the ledger's CURRENT_TIMESTAMP is UTC too, which corroborates it."""
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def integrity_rows(root: Path, run_dirs: list[Path], ledger_rows: list[dict] | None = None, ledger_source: str = "", git=None) -> list[Row]:
    rows: list[Row] = []
    R = rows.append
    summaries = [jl(d / "summary.json") for d in run_dirs]
    labels = [jl(d / "LABEL.json") for d in run_dirs]
    blocks = [(s["run_id"], s["verification_set"]["start"], s["verification_set"]["count"]) for s in summaries]
    lo_h = BLOCKS["held_out"][0]
    R(cmp("integrity", "blocks_range", "every official verification block lies in the held-out range (>= 900000), none in dev or rehearsal", "all", "all" if all(st >= lo_h for _, st, _ in blocks) else "NOT all"))
    ov = [(a[0], b[0]) for i, a in enumerate(blocks) for b in blocks[i + 1:] if a[1] < b[1] + b[2] and b[1] < a[1] + a[2]]
    R(cmp("integrity", "blocks_distinct", "official held-out blocks are pairwise disjoint (single use)", "no overlaps", "no overlaps" if not ov else f"overlaps: {ov}"))
    R(cmp("integrity", "blocks_unique_runs", "each official run used its own held-out block (runs = distinct blocks)", len(blocks), len({b[1] for b in blocks})))
    if ledger_rows is not None:
        held = [r for r in ledger_rows if r["block_name"] == "held_out"]
        for rid, st, ct in blocks:
            mine = [r for r in held if r["run_id"] == rid]
            R(cmp("integrity", f"ledger_{rid}", f"seed ledger: {rid} allocated its block once and it is marked used", [(st, ct, "used")], [(r["start"], r["count"], r["status"]) for r in mine]))
        others = [r for r in ledger_rows if r["run_id"] not in {b[0] for b in blocks} and r["block_name"] == "held_out"]
        R(cmp("integrity", "ledger_others", "no other run overlaps an official held-out block in the ledger", "none", "none" if not any(any(a["start"] < st + ct and st < a["start"] + a["count"] for _, st, ct in blocks) for a in others) else "OVERLAP"))
        R(Row("integrity", "ledger_source", "ledger evidence source", "", ledger_source, INFO, "the ledger database is gitignored; a snapshot of its rows is committed for checkouts without it"))
    else:
        R(unverifiable("integrity", "ledger", "seed ledger rows", "no ledger database or snapshot found; checked the blocks recorded in each run's summary only"))
    # no rehearsal / dev study run used an official block
    clash = []
    for f in (root / "recorded_runs").glob("*/*/summary.json"):
        if "official_001" in str(f):
            continue
        try:
            vs = jl(f).get("verification_set") or {}
        except (ValueError, OSError):
            continue
        if vs.get("start") is not None and any(vs["start"] < st + ct and st < vs["start"] + vs.get("count", 0) for _, st, ct in blocks):
            clash.append(str(f.parent.name))
    R(cmp("integrity", "no_study_overlap", "no rehearsal or study run used an official held-out block", "none", "none" if not clash else f"clash: {clash}"))
    # protocol before the first official run
    git = git or Git(root)
    snap_note = ""
    if not git.available:
        snap = SnapshotGit.load(root)
        if snap:
            git, snap_note = snap, f"from build snapshot of git facts (exported {snap.f.get('exported_utc', '?')} UTC from the repository, not a live git check)"
    n_before = len(rows)
    if not git.available:
        for k, n in (("protocol_time", "protocol file committed before the first official run started"), ("ancestry", "each official run's commit descends from the protocol commit"), ("freeze", "pipeline hash at the run's commit equals the hash recorded in the run")):
            R(unverifiable("integrity", k, n, "no git history in this environment"))
        return rows
    prov = summaries[0]["provenance"]
    pcommit = prov["protocol_commit"]
    rc, ctime = git("log", "-1", "--format=%cI", pcommit)
    first = min(_utc(lab["started"]) for lab in labels)
    if rc == 0 and ctime:
        ct = datetime.fromisoformat(ctime)
        R(Row("integrity", "protocol_time", "protocol file committed before the first official run started", f"protocol commit {pcommit[:7]} at {ct.astimezone(timezone.utc):%Y-%m-%d %H:%M:%S} UTC",
              f"first run started {first:%Y-%m-%d %H:%M:%S} UTC", MATCH if ct < first else MISMATCH, f"gap {(first - ct).total_seconds() / 60:.0f} min; run start times are container clock (UTC), matching the ledger's UTC timestamps"))
    else:
        R(unverifiable("integrity", "protocol_time", "protocol commit time", f"commit {pcommit[:7]} not found in this repository"))
    # the protocol file is unchanged between its commit and every official run's commit, and the run commit descends from it
    for s in summaries:
        c = s["provenance"]["commit"]
        anc = git("merge-base", "--is-ancestor", pcommit, c)[0] == 0
        unchanged = git("diff", "--quiet", pcommit, c, "--", "docs/OFFICIAL_PROTOCOL.md")[0] == 0
        R(cmp("integrity", f"ancestry_{s['run_id']}", f"{s['run_id']}: run commit {c[:7]} descends from the protocol commit and the protocol file is unchanged", "yes / unchanged", f"{'yes' if anc else 'NO'} / {'unchanged' if unchanged else 'CHANGED'}"))
        rc, committed = git("show", f"{c}:backend/app/core/FROZEN_PIPELINE_HASH.txt")
        h = next((ln.split()[1] for ln in committed.splitlines() if ln.startswith("pipeline_hash ")), "") if rc == 0 else ""
        R(cmp("integrity", f"freeze_{s['run_id']}", f"{s['run_id']}: pipeline hash recorded in the run equals the hash committed at that commit", s["provenance"]["pipeline_hash"], h or "commit not found"))
    rc, tag_commit = git("rev-parse", f"{prov['tag']}^{{commit}}")
    R(cmp("integrity", "tag", f"git tag {prov['tag']} points at the commit recorded in the runs", prov["tag_commit"][:10], tag_commit[:10] if rc == 0 else "tag not found"))
    if snap_note:
        for r in rows[n_before:]:
            r.note = f"{r.note} | {snap_note}" if r.note else snap_note
    return rows


def load_ledger(root: Path, snapshot: Path | None = None) -> tuple[list[dict] | None, str]:
    db = root / "backend" / "data" / "roboproof.sqlite"
    cols = "run_id, block_name, start, count, purpose, rehearsal, created_at, status, note"
    if db.exists():
        try:
            c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
            rows = [dict(zip(cols.split(", "), r)) for r in c.execute(f"SELECT {cols} FROM seed_ledger ORDER BY id")]
            c.close()
            if rows:
                return rows, f"live ledger database ({db.relative_to(root).as_posix()})"
        except sqlite3.Error:
            pass
    snap = snapshot or root / "docs" / "evidence" / "seed_ledger_snapshot.json"
    if snap.exists():
        d = jl(snap)
        return d["rows"], f"committed snapshot ({snap.relative_to(root).as_posix()}, exported {d.get('exported_utc', '?')})"
    return None, ""


def verify_all(root: Path, runs_root: Path | None = None, resim: bool = True, all_attempts: bool = False, timeout_s: float = 60.0, only: str | None = None,
               runner_factory: Callable[[float], object] = default_runner, git=None) -> dict:
    runs_root = runs_root or root / "recorded_runs" / "official_001"
    dirs = sorted(d for d in runs_root.glob("official_*") if d.is_dir() and (d / "summary.json").exists())
    osum = jl(runs_root / "official_summary.json")["runs"] if (runs_root / "official_summary.json").exists() else []
    by_id = {r["run_id"]: r for r in osum}
    out: dict = {"runs": {}, "integrity": [], "limits": [r.as_dict() for r in limits_rows()]}
    for d in dirs:
        if only and d.name != only:
            continue
        dash_p = root / DASHBOARD_RUNS / f"{d.name}.json"
        rows = recompute_run(d, by_id.get(d.name), jl(dash_p) if dash_p.exists() else None)
        if resim:
            rows += resimulate_run(d, runner_factory=runner_factory, timeout_s=timeout_s, all_attempts=all_attempts)
        out["runs"][d.name] = [r.as_dict() for r in rows]
    ledger, src = load_ledger(root)
    out["integrity"] = [r.as_dict() for r in integrity_rows(root, dirs, ledger, src, git)]
    return out


def tally(result: dict) -> dict:
    rows = [r for rs in result["runs"].values() for r in rs] + result["integrity"]
    c = {MATCH: 0, MISMATCH: 0, UNVERIFIABLE: 0, INFO: 0}
    for r in rows:
        c[r["status"]] += 1
    c.update({"unverifiable_listed": len(result["limits"])})
    return c
