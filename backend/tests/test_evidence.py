"""Evidence computation on synthetic data with a KNOWN failure structure: a scenario fails iff mass > 0.6 and friction < 0.4,
plus a few extra failures when sensor noise > 0.027."""
import json

import pytest

from app.analysis.evidence import MIN_SUPPORT, TREE_DEPTH, compute_evidence, region_contains, scenarios_in_region
from app.core.schemas import FailureReason, Result, Scenario
from app.core.stats import wilson
from app.scenarios.sweep import latin_hypercube


def synth(n=400, seed=5, rule=None):
    scns = latin_hypercube(n, seed)
    rule = rule or (lambda s: (s.mass_kg > 0.6 and s.friction < 0.4) or s.sensor_noise_m > 0.027)
    res = []
    for s in scns:
        bad = rule(s)
        res.append(Result(scenario_id=s.id, seed=s.seed, success=not bad, collision=False, completion_time_s=3.0 + s.mass_kg,
                          final_place_error_m=0.0, max_slip_m=0.0,
                          failure_reason=FailureReason.SLIPPED_ON_LIFT if bad else None))
    return scns, res


def test_wilson_basic():
    lo, hi = wilson(50, 100)
    assert 0.40 < lo < 0.41 and 0.59 < hi < 0.60
    assert wilson(0, 0) == (0.0, 1.0)
    assert wilson(0, 10)[0] == 0.0 and wilson(10, 10)[1] == 1.0


def test_ids_are_stable_and_sequential_and_output_deterministic():
    scns, res = synth()
    a, b = compute_evidence(scns, res), compute_evidence(scns, res)
    assert a.model_dump_json() == b.model_dump_json()
    assert [i.id for i in a.items] == [f"E{k}" for k in range(1, len(a.items) + 1)]
    assert a.get("E1").kind == "metrics" and a.get("E2").kind == "reasons" and a.get("E999") is None


def test_metrics_and_reasons_match_the_data():
    scns, res = synth()
    ev = compute_evidence(scns, res)
    m = ev.get("E1").data
    nfail = sum(not r.success for r in res)
    assert m["n"] == 400 and m["n_fail"] == nfail and m["pass_rate"] == pytest.approx(1 - nfail / 400, abs=1e-4)
    assert m["pass_rate_ci95"][0] < m["pass_rate"] < m["pass_rate_ci95"][1]
    assert ev.get("E2").data["counts"] == {"SLIPPED_ON_LIFT": nfail}


def test_bins_partition_each_axis_and_show_the_known_effect():
    scns, res = synth()
    ev = compute_evidence(scns, res)
    bins = [i for i in ev.items if i.kind == "bin"]
    assert len(bins) == 7 * 5
    for ax in {b.data["axis"] for b in bins}:
        assert sum(b.data["n"] for b in bins if b.data["axis"] == ax) == 400  # every scenario in exactly one bin
    mass = [b for b in bins if b.data["axis"] == "mass_kg"]
    assert mass[-1].data["fail_rate"] > mass[0].data["fail_rate"] + 0.1  # heaviest bin fails more than the lightest
    lo, hi = mass[-1].data["fail_rate_ci95"]
    assert lo <= mass[-1].data["fail_rate"] <= hi
    noise_top = [b for b in bins if b.data["axis"] == "sensor_noise_m"][-1]
    assert noise_top.data["fail_rate"] > 0.5


def test_interaction_scan_finds_mass_x_friction_and_respects_support():
    scns, res = synth()
    inter = [i for i in compute_evidence(scns, res).items if i.kind == "interaction"]
    assert inter and len(inter) <= 8
    assert all(i.data["n"] >= MIN_SUPPORT for i in inter)
    assert all(i.data["excess_over_max_marginal"] > 0.05 for i in inter)
    assert sorted(inter[0].data["axes"]) == ["friction", "mass_kg"]  # strongest interaction first
    excess = [i.data["excess_over_max_marginal"] for i in inter]
    assert excess == sorted(excess, reverse=True)


def test_tree_leaf_recovers_the_failing_region_with_support_and_depth_limits():
    scns, res = synth()
    leaves = [i for i in compute_evidence(scns, res).items if i.kind == "tree_leaf"]
    assert leaves
    for l in leaves:
        assert l.data["n"] >= MIN_SUPPORT and len(l.data["path"]) <= TREE_DEPTH and l.data["fail_rate"] >= 0.5
    best = leaves[0]
    # the top leaf should sit inside the true region: heavy and slippery (or very noisy)
    r = best.data["region"]
    heavy_slippery = r.get("mass_kg", [0, 0])[0] >= 0.5 and r.get("friction", [9, 9])[1] <= 0.5
    noisy = r.get("sensor_noise_m", [0, 0])[0] >= 0.02
    assert heavy_slippery or noisy
    # region predicates are checkable and agree with the reported counts
    inside = scenarios_in_region(r, scns)
    assert len(inside) == best.data["n"]
    assert sum(not x.success for x in res if x.scenario_id in {s.id for s in inside}) == best.data["n_fail"]


def test_small_or_clean_data_gives_no_interactions_or_leaves_and_does_not_crash():
    scns, res = synth(n=40, rule=lambda s: False)
    ev = compute_evidence(scns, res)
    assert ev.get("E1").data["n_fail"] == 0
    assert not [i for i in ev.items if i.kind in ("interaction", "tree_leaf")]
    scns, res = synth(n=20, rule=lambda s: s.mass_kg > 0.5)
    assert all(i.data["n"] >= MIN_SUPPORT for i in compute_evidence(scns, res).items if i.kind in ("interaction", "tree_leaf"))
    e = compute_evidence([], [])
    assert e.n_scenarios == 0 and e.get("E1").data["pass_rate"] == 0.0


def test_region_contains_is_inclusive():
    s = Scenario(id="x", mass_kg=0.5, friction=0.3, size_m=0.05, pos_offset_x=0, pos_offset_y=0, sensor_noise_m=0.0,
                 gripper_delay_steps=4, seed=1)
    assert region_contains({"mass_kg": [0.5, 0.9]}, s) and region_contains({"mass_kg": [0.1, 0.5], "friction": [0.3, 0.3]}, s)
    assert not region_contains({"mass_kg": [0.51, 0.9]}, s)
    json.dumps(compute_evidence(*synth(60)).model_dump())  # fully JSON-serialisable
