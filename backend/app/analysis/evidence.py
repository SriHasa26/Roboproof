"""Evidence computation: PURE CODE, no LLM. Everything the analyst may talk about is computed here and given a stable id.

Items (ids assigned in this order, so the same input always gives the same ids):
  E1 metrics; E2 failure reasons; then 5-bin failure rates per axis (7 axes x 5 bins) with Wilson 95% intervals;
  then the top pairwise interaction cells; then failing leaves of a depth<=3 decision tree.
Region predicates are inclusive ranges: lo <= value <= hi for every listed axis.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations

import numpy as np

from ..core.bounds import SCENARIO_BOUNDS
from ..core.schemas import Result, Scenario
from ..core.stats import wilson
from .models import EvidenceItem, EvidenceReport

AXES = list(SCENARIO_BOUNDS)
N_BINS = 5          # per-axis failure-rate bins
PAIR_BINS = 3       # per-axis bins for the interaction scan
MIN_SUPPORT = 15    # minimum scenarios in an interaction cell / tree leaf
TOP_INTERACTIONS = 8
MIN_EXCESS = 0.05   # a cell must beat its marginal rates by at least this to be listed
TREE_DEPTH = 3
FAIL_LEAF_RATE = 0.5  # a leaf is "failing" if at least half of its scenarios fail
MAX_THRESHOLDS = 30


def region_contains(region: dict[str, list[float]], s: Scenario) -> bool:
    return all(lo <= getattr(s, ax) <= hi for ax, (lo, hi) in region.items())


def scenarios_in_region(region: dict[str, list[float]], scenarios: list[Scenario]) -> list[Scenario]:
    return [s for s in scenarios if region_contains(region, s)]


def _bin(v: float, lo: float, hi: float, nb: int) -> int:
    return max(0, min(int((v - lo) / (hi - lo) * nb), nb - 1))


def _edges(ax: str, b: int, nb: int) -> list[float]:
    lo, hi = SCENARIO_BOUNDS[ax]
    return [round(lo + (hi - lo) * b / nb, 4), round(lo + (hi - lo) * (b + 1) / nb, 4)]


def _rate(nf: int, n: int) -> float:
    return round(nf / n, 4) if n else 0.0


def _gini(nf: int, n: int) -> float:
    if n == 0:
        return 0.0
    p = nf / n
    return 2 * p * (1 - p)


def _tree_leaves(X: np.ndarray, y: np.ndarray) -> list[dict]:
    """Greedy Gini tree, depth <= TREE_DEPTH, >= MIN_SUPPORT scenarios per leaf. Deterministic."""
    leaves: list[dict] = []

    def grow(idx: np.ndarray, depth: int, region: dict[str, list[float]], path: list[str]) -> None:
        n, nf = len(idx), int(y[idx].sum())
        best = None  # (weighted_gini, axis_idx, thr)
        if depth < TREE_DEPTH and n >= 2 * MIN_SUPPORT:
            parent = _gini(nf, n)
            for j, ax in enumerate(AXES):
                vals = np.unique(X[idx, j])
                if len(vals) < 2:
                    continue
                mids = np.round((vals[:-1] + vals[1:]) / 2, 4)
                mids = np.unique(mids)
                if len(mids) > MAX_THRESHOLDS:
                    mids = mids[np.linspace(0, len(mids) - 1, MAX_THRESHOLDS).astype(int)]
                for thr in mids:
                    left = idx[X[idx, j] <= thr]
                    nl = len(left)
                    nr = n - nl
                    if nl < MIN_SUPPORT or nr < MIN_SUPPORT:
                        continue
                    nfl = int(y[left].sum())
                    w = (nl * _gini(nfl, nl) + nr * _gini(nf - nfl, nr)) / n
                    if w < parent - 1e-9 and (best is None or w < best[0] - 1e-12):
                        best = (w, j, float(thr))
        if best is None:
            leaves.append({"region": {k: list(v) for k, v in region.items()}, "n": n, "n_fail": nf, "path": list(path)})
            return
        _, j, thr = best
        ax = AXES[j]
        lo, hi = region.get(ax, list(SCENARIO_BOUNDS[ax]))
        lreg = {**region, ax: [lo, min(hi, thr)]}
        rreg = {**region, ax: [max(lo, thr), hi]}
        grow(idx[X[idx, j] <= thr], depth + 1, lreg, path + [f"{ax} <= {thr:g}"])
        grow(idx[X[idx, j] > thr], depth + 1, rreg, path + [f"{ax} > {thr:g}"])

    grow(np.arange(len(y)), 0, {}, [])
    return leaves


def compute_evidence(scenarios: list[Scenario], results: list[Result]) -> EvidenceReport:
    by_id = {r.scenario_id: r for r in results}
    rows = [(s, by_id[s.id]) for s in scenarios if s.id in by_id]
    n = len(rows)
    items: list[EvidenceItem] = []

    def add(kind: str, title: str, data: dict) -> str:
        item_id = f"E{len(items) + 1}"
        items.append(EvidenceItem(id=item_id, kind=kind, title=title, data=data))
        return item_id

    fails = [not r.success for _, r in rows]
    n_fail = sum(fails)
    ok_times = [r.completion_time_s for _, r in rows if r.success]
    lo_ci, hi_ci = wilson(n - n_fail, n)
    add("metrics", "Overall baseline metrics", {
        "n": n, "n_fail": n_fail, "pass_rate": _rate(n - n_fail, n), "pass_rate_ci95": [round(lo_ci, 4), round(hi_ci, 4)],
        "collision_rate": _rate(sum(r.collision for _, r in rows), n),
        "mean_completion_time_s_successes": round(sum(ok_times) / len(ok_times), 3) if ok_times else None,
    })
    reasons = Counter(r.failure_reason.value for _, r in rows if r.failure_reason)
    add("reasons", "Failure reasons", {"counts": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])))})

    X = np.array([[getattr(s, ax) for ax in AXES] for s, _ in rows], dtype=float).reshape(n, len(AXES))
    y = np.array(fails, dtype=int)

    # 1) per-axis bins
    for j, ax in enumerate(AXES):
        lo, hi = SCENARIO_BOUNDS[ax]
        idx = [_bin(v, lo, hi, N_BINS) for v in X[:, j]]
        for b in range(N_BINS):
            sel = [i for i, bi in enumerate(idx) if bi == b]
            nb, nfb = len(sel), int(y[sel].sum()) if sel else 0
            wl, wh = wilson(nfb, nb)
            e = _edges(ax, b, N_BINS)
            add("bin", f"{ax} in [{e[0]}, {e[1]}]", {
                "axis": ax, "range": e, "n": nb, "n_fail": nfb, "fail_rate": _rate(nfb, nb),
                "fail_rate_ci95": [round(wl, 4), round(wh, 4)]})

    # 2) pairwise interactions on coarse bins
    pb = {ax: [_bin(v, *SCENARIO_BOUNDS[ax], PAIR_BINS) for v in X[:, j]] for j, ax in enumerate(AXES)}
    marg = {}
    for ax in AXES:
        for b in range(PAIR_BINS):
            sel = [i for i, bi in enumerate(pb[ax]) if bi == b]
            marg[(ax, b)] = (len(sel), int(y[sel].sum()) if sel else 0)
    cells = []
    for a, b2 in combinations(AXES, 2):
        grid: dict[tuple[int, int], list[int]] = {}
        for i in range(n):
            c = grid.setdefault((pb[a][i], pb[b2][i]), [0, 0])
            c[0] += 1
            c[1] += int(y[i])
        for (ba, bb), (cn, cf) in grid.items():
            if cn < MIN_SUPPORT:
                continue
            ma, mb = marg[(a, ba)], marg[(b2, bb)]
            ra, rb = _rate(ma[1], ma[0]), _rate(mb[1], mb[0])
            excess = round(_rate(cf, cn) - max(ra, rb), 4)
            if excess > MIN_EXCESS:
                cells.append((-excess, -cn, a, b2, ba, bb, cn, cf, ra, rb))
    for _, _, a, b2, ba, bb, cn, cf, ra, rb in sorted(cells)[:TOP_INTERACTIONS]:
        ea, eb = _edges(a, ba, PAIR_BINS), _edges(b2, bb, PAIR_BINS)
        add("interaction", f"{a} in {ea} x {b2} in {eb}", {
            "axes": [a, b2], "region": {a: ea, b2: eb}, "n": cn, "n_fail": cf, "fail_rate": _rate(cf, cn),
            "marginal_fail_rates": {a: ra, b2: rb}, "excess_over_max_marginal": round(_rate(cf, cn) - max(ra, rb), 4)})

    # 3) decision tree: failing leaves only
    leaves = [l for l in _tree_leaves(X, y) if l["n"] >= MIN_SUPPORT and _rate(l["n_fail"], l["n"]) >= FAIL_LEAF_RATE]
    leaves.sort(key=lambda l: (-_rate(l["n_fail"], l["n"]), -l["n"], l["path"]))
    for l in leaves:
        wl, wh = wilson(l["n_fail"], l["n"])
        add("tree_leaf", "Failing region: " + (" AND ".join(l["path"]) or "all scenarios"), {
            "region": {ax: [round(v[0], 4), round(v[1], 4)] for ax, v in l["region"].items()}, "path": l["path"],
            "n": l["n"], "n_fail": l["n_fail"], "fail_rate": _rate(l["n_fail"], l["n"]),
            "fail_rate_ci95": [round(wl, 4), round(wh, 4)]})
    return EvidenceReport(n_scenarios=n, items=items)
