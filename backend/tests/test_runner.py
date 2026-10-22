"""LocalRunner integrity tests. Shard behaviour is injected with tiny shard functions (no PyBullet needed);
the identical-results and metrics tests use the real simulator and run only in the sim image."""
import multiprocessing as mp
import os
import time

import pytest

from app.core.schemas import Policy, Result, Scenario
from app.core.seeds import HELDOUT_SEED_BASE, HeldOutSeedError
from app.runner.base import split_into_shards
from app.runner.local import LocalRunner
from app.store.db import Database

pytestmark = pytest.mark.skipif("fork" not in mp.get_all_start_methods(), reason="needs fork (Linux image)")


def scns(n, start=1000):
    return [Scenario(id=f"s{i}", mass_kg=0.2, friction=0.8, size_m=0.05, pos_offset_x=0, pos_offset_y=0,
                     sensor_noise_m=0.0, gripper_delay_steps=0, seed=start + i) for i in range(n)]


def fake_result(s, success=True):
    from app.core.schemas import FailureReason
    return Result(scenario_id=s.id, seed=s.seed, success=success, collision=False, completion_time_s=1.0,
                  final_place_error_m=0.0, max_slip_m=0.0, failure_reason=None if success else FailureReason.TIMEOUT)


def ok_fn(policy, scenarios, held_out):
    return [fake_result(s) for s in scenarios]


def crash_fn(policy, scenarios, held_out):
    if any(s.id == "s7" for s in scenarios):
        os._exit(3)  # hard crash, no cleanup
    return ok_fn(policy, scenarios, held_out)


def raise_fn(policy, scenarios, held_out):
    if any(s.id == "s2" for s in scenarios):
        raise RuntimeError("boom")
    return ok_fn(policy, scenarios, held_out)


def hang_fn(policy, scenarios, held_out):
    if any(s.id == "s5" for s in scenarios):
        time.sleep(60)
    return ok_fn(policy, scenarios, held_out)


def short_fn(policy, scenarios, held_out):
    out = ok_fn(policy, scenarios, held_out)
    return out[:-1] if any(s.id == "s3" for s in scenarios) else out


def wrong_ids_fn(policy, scenarios, held_out):
    out = ok_fn(policy, scenarios, held_out)
    if any(s.id == "s3" for s in scenarios):
        out[0] = fake_result(scns(1, 5000)[0])
    return out


def test_split_into_shards_is_contiguous_and_balanced():
    chunks = split_into_shards(scns(23), 5)
    assert [len(c) for c in chunks] == [5, 5, 5, 4, 4]
    assert [s.id for c in chunks for s in c] == [f"s{i}" for i in range(23)]


def test_all_shards_complete():
    run = LocalRunner(shard_fn=ok_fn).run(Policy(), scns(20), shards=4)
    assert run.complete and run.shards_total == 4 and run.shards_ok == 4 and run.shards_failed == 0
    assert [r.scenario_id for r in run.results] == [f"s{i}" for i in range(20)]
    assert run.missing_scenario_ids == [] and run.runner_name == "local" and run.wall_clock_s > 0


def test_crashed_shard_marked_failed_and_results_missing_not_counted():
    run = LocalRunner(shard_fn=crash_fn).run(Policy(), scns(20), shards=4)  # s7 lives in shard 1 (5..9)
    assert not run.complete and run.shards_failed == 1 and run.shards_ok == 3
    bad = [s for s in run.shards if not s.complete]
    assert len(bad) == 1 and bad[0].status == "FAILED" and bad[0].results == []
    assert run.missing_scenario_ids == [f"s{i}" for i in range(5, 10)]
    assert len(run.results) == 15 and run.pass_rate() == 1.0  # missing ones are neither passes nor failures
    assert all(r.scenario_id not in run.missing_scenario_ids for r in run.results)


def test_python_exception_in_shard_marked_failed_with_error_text():
    run = LocalRunner(shard_fn=raise_fn).run(Policy(), scns(10), shards=2)
    assert not run.complete
    bad = next(s for s in run.shards if not s.complete)
    assert bad.status == "FAILED" and "boom" in (bad.error or "")


def test_timed_out_shard_marked_timeout_and_killed():
    t0 = time.time()
    run = LocalRunner(shard_fn=hang_fn, shard_timeout_s=1.5).run(Policy(), scns(10), shards=2)
    assert time.time() - t0 < 20  # did not wait for the 60 s sleep
    assert not run.complete
    bad = next(s for s in run.shards if not s.complete)
    assert bad.status == "TIMEOUT" and len(run.missing_scenario_ids) == 5


def test_short_result_list_is_failed_not_partial():
    run = LocalRunner(shard_fn=short_fn).run(Policy(), scns(8), shards=2)
    bad = next(s for s in run.shards if not s.complete)
    assert bad.status == "FAILED" and "returned 3 results for 4" in bad.error
    assert len(run.results) == 4 and len(run.missing_scenario_ids) == 4 and not run.complete


def test_wrong_scenario_ids_is_failed():
    run = LocalRunner(shard_fn=wrong_ids_fn).run(Policy(), scns(8), shards=2)
    assert not run.complete and run.shards_failed == 1


def test_worker_limit_respected_and_more_shards_than_scenarios_clamped():
    run = LocalRunner(shard_fn=ok_fn, max_workers=1).run(Policy(), scns(3), shards=10)
    assert run.shards_total == 3 and run.complete


def test_runner_refuses_heldout_seeds_without_flag():
    with pytest.raises(HeldOutSeedError):
        LocalRunner(shard_fn=ok_fn).run(Policy(), scns(3, start=HELDOUT_SEED_BASE), shards=1)
    with pytest.raises(HeldOutSeedError):  # and the flag requires held-out seeds
        LocalRunner(shard_fn=ok_fn).run(Policy(), scns(3), shards=1, held_out=True)


def test_incomplete_run_is_stored_without_missing_rows():
    db = Database(":memory:")
    s = scns(20)
    run = LocalRunner(shard_fn=crash_fn).run(Policy(), s, shards=4)
    db.save_batch("b1", "crashy", Policy(), s, run, "fixture")
    assert len(db.batch_rows("b1")) == 15
    assert db.conn.execute("SELECT complete, n_missing FROM batches").fetchone() == (0, 5)


# ---- real simulator (sim image only)
def test_real_sim_results_identical_across_runs_and_metrics_recorded():
    pytest.importorskip("pybullet")
    from app.scenarios.sweep import latin_hypercube

    s = latin_hypercube(24, sweep_seed=99, seed_base=3000)
    a = LocalRunner().run(Policy(), s, shards=4)
    b = LocalRunner().run(Policy(), s, shards=3)  # different sharding, same results
    assert a.complete and b.complete
    assert [r.model_dump() for r in a.results] == [r.model_dump() for r in b.results]
    assert all(r.completion_time_s > 0 for r in a.results)
    assert all(isinstance(r.collision, bool) for r in a.results)
    db = Database(":memory:")
    db.save_batch("real", "t", Policy(), s, a, "fixture")
    rows = db.batch_rows("real")
    assert len(rows) == 24 and all(len(r) == 17 for r in rows)
