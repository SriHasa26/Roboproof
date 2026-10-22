"""Proof-of-Robustness Gate tests: every path, with a stub runner (no simulator, no held-out seeds ever run).

World: 250 analysis scenarios; baseline fails scenarios with index % 5 == 0 (50 failures, 200 passes, so the G4 budget is
floor(0.02 x 200) = 4). Patches are identified by grip_force:
  50 good (fixes all, regresses none)   41 fixes only 60%     42 regresses 5      43 regresses 4
Verification sets: pass iff (seed % 20)/20 < rate, so the pass rate equals `rate` exactly for multiples of 0.05.
"""
import pytest

from app.core.schemas import CheckStatus, FailureReason, Policy, Result, Verdict
from app.runner.base import JobRunner, RunResult
from app.core.schemas import ShardResult
from app.gate.gate import ProofGate, decide_verdict
from app.gate.verification import make_verification_set
from app.scenarios.sweep import latin_hypercube
from app.store.db import Database
from app.store.ledger import SeedBlockReusedError, SeedLedger

BASE_GRIP = Policy().grip_force
FIX = {50: (50, 0), 41: (30, 0), 42: (50, 5), 43: (50, 4)}  # grip -> (targeted fixed out of 50, regressions)


def res(s, ok, t=3.0):
    return Result(scenario_id=s.id, seed=s.seed, success=ok, collision=False, completion_time_s=t, final_place_error_m=0.0,
                  max_slip_m=0.0, failure_reason=None if ok else FailureReason.MISSED_GRASP)


class StubRunner(JobRunner):
    name = "stub"

    def __init__(self, ver=None, fail=None, nondeterministic=False, unreproduce_first_target=False):
        self.ver = {"base": 0.70, 50: 0.95, 41: 0.95, 42: 0.95, 43: 0.95, **(ver or {})}
        self.fail, self.nondet, self.unrepro = fail, nondeterministic, unreproduce_first_target
        self.calls: list[tuple] = []
        self.base_calls = 0

    def outcome(self, policy, s, base_call_no):
        g = round(policy.grip_force)
        if s.tag == "verify":
            rate = self.ver["base"] if g == BASE_GRIP else self.ver[g]
            return res(s, (s.seed % 20) / 20 < rate)
        idx = s.seed - 1000
        failing = idx % 5 == 0
        if g == BASE_GRIP:
            if self.unrepro and base_call_no >= 3 and idx == 0:
                return res(s, True)  # a targeted failure that does not fail again
            return res(s, not failing, t=3.0 + (0.5 if self.nondet and base_call_no >= 2 else 0.0))
        fixed_n, _ = FIX[g]
        if failing:
            return res(s, (idx // 5) < fixed_n)
        return res(s, True)  # passing scenarios stay passing here; setup() adds the intended regressions

    def _run(self, policy, scenarios, shards, held_out):
        g = round(policy.grip_force)
        if g == BASE_GRIP:
            self.base_calls += 1
        self.calls.append((g, len(scenarios), held_out))
        mode = self.fail(policy, scenarios) if self.fail else None
        n = len(scenarios)
        if mode:
            shard = ShardResult(shard_id="s0", status=mode, runner="local", results=[], n_expected=n, error="injected")
        else:
            shard = ShardResult(shard_id="s0", status="COMPLETED", runner="local", n_expected=n,
                                results=[self.outcome(policy, s, self.base_calls) for s in scenarios])
        return RunResult.build("stub", [shard], [[s.id for s in scenarios]], 0.01)


@pytest.fixture
def world():
    scns = latin_hypercube(250, 3)
    return scns


def setup(stub, scns, grip, vset_n=400, with_vset=True, rehearsal=True):
    # patch behaviour for regressions: scenario (idx % 5 == 1 and idx // 5 < regress_n) fails
    orig = stub.outcome

    def outcome(policy, s, c):
        r = orig(policy, s, c)
        g = round(policy.grip_force)
        if s.tag != "verify" and g != BASE_GRIP and g in FIX:
            idx = s.seed - 1000
            if idx % 5 == 1:
                return res(s, (idx // 5) >= FIX[g][1])
        return r

    stub.outcome = outcome
    base = stub.run(Policy(), scns, shards=5)
    targeted = [r.scenario_id for r in base.results if not r.success]
    gate = ProofGate(stub, shards=5, rehearsal=rehearsal)
    gate.prepare(Policy(), scns, base, targeted)
    patched = Policy(grip_force=grip)
    dev = gate.dev_stage(patched)
    ledger = SeedLedger(Database(":memory:"))
    vset = make_verification_set(ledger, "run", rehearsal=rehearsal, n=vset_n) if with_vset else None
    return gate, dev, patched, vset


def status(report, cid):
    return next(c for c in report.checks if c.id == cid).status


def verdict_of(stub, scns, grip, **kw):
    gate, dev, patched, vset = setup(stub, scns, grip, **kw)
    return gate.finalize(dev, patched, vset)


# ---------------------------------------------------------------- the happy path and the budget
def test_all_checks_pass_gives_verified(world):
    stub = StubRunner()
    rep = verdict_of(stub, world, 50)
    assert rep.verdict == Verdict.VERIFIED and rep.rehearsal is True
    assert [c.status for c in rep.checks] == [CheckStatus.PASS] * 6
    assert rep.metrics["analysis"]["before"].pass_rate == 0.8 and rep.metrics["analysis"]["after"].pass_rate == 1.0
    assert rep.metrics["verification"]["after"].pass_rate == 0.95 and rep.metrics["verification"]["before"].pass_rate == 0.70
    assert rep.verification_set["block"] == "rehearsal" and rep.strict_zero_budget == {"regressions": 0, "pass": True}


def test_regressions_within_budget_pass_but_strict_zero_budget_fails_and_is_shown_separately(world):
    rep = verdict_of(StubRunner(), world, 43)  # 4 regressions, budget floor(0.02 x 200) = 4
    g4 = next(c for c in rep.checks if c.id == "G4")
    assert g4.status == CheckStatus.PASS and g4.threshold["budget"] == 4 and g4.observed["regressions"] == 4
    assert rep.strict_zero_budget == {"regressions": 4, "pass": False} and len(rep.regressed_scenario_ids) == 4
    assert rep.verdict == Verdict.VERIFIED  # within budget


def test_regressions_above_budget_fail(world):
    rep = verdict_of(StubRunner(), world, 42)  # 5 regressions > 4
    assert status(rep, "G4") == CheckStatus.FAIL and rep.verdict == Verdict.FAILED
    assert len(rep.regressed_scenario_ids) == 5 and rep.strict_zero_budget["pass"] is False
    g5 = next(c for c in rep.checks if c.id == "G5")
    assert g5.status == CheckStatus.SKIPPED_AFTER_FAILURE  # verification block not spent


def test_fix_rate_below_threshold_fails(world):
    rep = verdict_of(StubRunner(), world, 41)  # fixes 30 of 50 = 0.6 < 0.70
    g3 = next(c for c in rep.checks if c.id == "G3")
    assert g3.status == CheckStatus.FAIL and g3.observed["fix_rate"] == 0.6 and rep.verdict == Verdict.FAILED


# ---------------------------------------------------------------- G1, G2
def test_nondeterministic_sample_fails(world):
    rep = verdict_of(StubRunner(nondeterministic=True), world, 50)
    g1 = next(c for c in rep.checks if c.id == "G1")
    assert g1.status == CheckStatus.FAIL and g1.observed["mismatches"] > 0 and rep.verdict == Verdict.FAILED


def test_unreproduced_targeted_failure_fails(world):
    rep = verdict_of(StubRunner(unreproduce_first_target=True), world, 50)
    g2 = next(c for c in rep.checks if c.id == "G2")
    assert g2.status == CheckStatus.FAIL and g2.observed["not_reproduced"] == 1 and rep.verdict == Verdict.FAILED


def test_g1_sample_is_a_fixed_evenly_spaced_subset(world):
    stub = StubRunner()
    verdict_of(stub, world, 50)
    sizes = [n for g, n, _ in stub.calls if g == BASE_GRIP]
    assert sizes[:3] == [250, 30, 50]  # baseline, G1 sample (default 30), G2 targeted failures


# ---------------------------------------------------------------- G5 and each of its conditions
def test_heldout_below_target_fails(world):
    rep = verdict_of(StubRunner(ver={50: 0.85}), world, 50)
    g5 = next(c for c in rep.checks if c.id == "G5")
    assert g5.status == CheckStatus.FAIL and g5.observed["conditions"]["target"] is False and rep.verdict == Verdict.FAILED
    assert g5.observed["conditions"]["improvement"] is True


def test_improvement_below_minimum_fails(world):
    rep = verdict_of(StubRunner(ver={"base": 0.90, 50: 0.95}), world, 50)  # target and Wilson ok, +0.05 < +0.10
    c = next(c for c in rep.checks if c.id == "G5").observed["conditions"]
    assert c == {"target": True, "improvement": False, "wilson_lower_above_baseline": True} and rep.verdict == Verdict.FAILED


def test_wilson_lower_bound_not_above_baseline_fails(world):
    # n=20: patched 18/20 = 0.90 (target ok, +0.20 improvement ok) but Wilson lower ~0.70 is not above the unpatched 0.70
    rep = verdict_of(StubRunner(ver={"base": 0.70, 50: 0.90}), world, 50, vset_n=20)
    g5 = next(c for c in rep.checks if c.id == "G5")
    assert g5.observed["conditions"] == {"target": True, "improvement": True, "wilson_lower_above_baseline": False}
    assert g5.status == CheckStatus.FAIL and rep.verdict == Verdict.FAILED


def test_heldout_flag_follows_the_block_and_verification_is_rehearsal_here(world):
    stub = StubRunner()
    verdict_of(stub, world, 50)
    assert [h for g, n, h in stub.calls if n == 400] == [False, False]  # rehearsal block: held_out flag off
    stub = StubRunner()
    rep = verdict_of(stub, world, 50, rehearsal=False)  # a real held-out block, but still only a stub: nothing is simulated
    assert [h for g, n, h in stub.calls if n == 400] == [True, True] and rep.rehearsal is False


def test_reusing_a_verification_set_raises(world):
    gate, dev, patched, vset = setup(StubRunner(), world, 50)
    gate.finalize(dev, patched, vset)
    with pytest.raises(SeedBlockReusedError):
        gate.finalize(dev, patched, vset)


def test_new_block_each_time_from_the_ledger():
    ledger = SeedLedger(Database(":memory:"))
    a = make_verification_set(ledger, "r1", rehearsal=False, n=400)
    b = make_verification_set(ledger, "r2", rehearsal=False, n=400)
    assert b.start == a.start + 400
    with pytest.raises(SeedBlockReusedError):
        ledger.record_use("r3", "held_out", a.start, 400, "G5")


# ---------------------------------------------------------------- G6 and UNVERIFIED
@pytest.mark.parametrize("mode", ["FAILED", "TIMEOUT"])
def test_crashed_or_timed_out_shard_gives_unverified(world, mode):
    stub = StubRunner(fail=lambda p, scns: mode if round(p.grip_force) == 50 and len(scns) == 250 else None)
    rep = verdict_of(stub, world, 50)
    assert rep.verdict == Verdict.UNVERIFIED
    assert status(rep, "G6") == CheckStatus.FAIL
    assert status(rep, "G3") == CheckStatus.NOT_RUN and status(rep, "G4") == CheckStatus.NOT_RUN  # never counted as pass


def test_g1_not_run_gives_unverified(world):
    stub = StubRunner(fail=lambda p, scns: "FAILED" if round(p.grip_force) == BASE_GRIP and len(scns) == 30 else None)
    rep = verdict_of(stub, world, 50)
    assert status(rep, "G1") == CheckStatus.NOT_RUN and rep.verdict == Verdict.UNVERIFIED


def test_incomplete_verification_run_gives_unverified(world):
    stub = StubRunner(fail=lambda p, scns: "TIMEOUT" if len(scns) == 400 and round(p.grip_force) == 50 else None)
    rep = verdict_of(stub, world, 50)
    assert status(rep, "G5") == CheckStatus.NOT_RUN and status(rep, "G6") == CheckStatus.FAIL and rep.verdict == Verdict.UNVERIFIED


def test_g6_failure_outranks_an_ordinary_failure(world):
    # patch 41 fails G3, and a crashed G1 re-run makes G6 fail: the spec makes that UNVERIFIED, not FAILED
    stub = StubRunner(fail=lambda p, scns: "FAILED" if round(p.grip_force) == BASE_GRIP and len(scns) == 30 else None)
    rep = verdict_of(stub, world, 41)
    assert status(rep, "G3") == CheckStatus.FAIL and rep.verdict == Verdict.UNVERIFIED


def test_incomplete_baseline_is_unverified_not_a_pass(world):
    scns = world
    stub = StubRunner(fail=lambda p, s: "FAILED" if round(p.grip_force) == BASE_GRIP and len(s) == 250 else None)
    base = stub.run(Policy(), scns, shards=5)
    assert not base.complete
    gate = ProofGate(stub, shards=5, rehearsal=True)
    gate.prepare(Policy(), scns, base, [])
    dev = gate.dev_stage(Policy(grip_force=50))
    rep = gate.finalize(dev, Policy(grip_force=50), make_verification_set(SeedLedger(Database(":memory:")), "r", True, 20))
    assert rep.verdict == Verdict.UNVERIFIED and status(rep, "G6") == CheckStatus.FAIL


def test_no_targeted_failures_is_unverified(world):
    stub = StubRunner()
    base = stub.run(Policy(), world, shards=5)
    gate = ProofGate(stub, shards=5, rehearsal=True)
    gate.prepare(Policy(), world, base, [])
    rep = gate.finalize(gate.dev_stage(Policy(grip_force=50)), Policy(grip_force=50), None)
    assert status(rep, "G2") == CheckStatus.NOT_RUN and rep.verdict == Verdict.UNVERIFIED


def test_noop_patch_fails_g3_and_never_verifies(world):
    stub = StubRunner()
    gate, dev, patched, vset = setup(stub, world, int(BASE_GRIP))  # same grip as the baseline -> identical behaviour
    # an identical policy behaves like the baseline, so nothing is fixed
    assert dev.checks["G3"].status == CheckStatus.FAIL
    rep = gate.finalize(dev, patched, vset)
    assert rep.verdict == Verdict.FAILED and rep.checks[4].status == CheckStatus.SKIPPED_AFTER_FAILURE


def test_decide_verdict_precedence_unit():
    from app.core.schemas import GateCheck

    def mk(**st):
        return [GateCheck(id=k, name=k, status=CheckStatus(v)) for k, v in st.items()]

    ok = dict(G1="pass", G2="pass", G3="pass", G4="pass", G5="pass", G6="pass")
    assert decide_verdict(mk(**ok)) == Verdict.VERIFIED
    assert decide_verdict(mk(**{**ok, "G4": "fail"})) == Verdict.FAILED
    assert decide_verdict(mk(**{**ok, "G5": "not_run"})) == Verdict.UNVERIFIED
    assert decide_verdict(mk(**{**ok, "G6": "fail", "G4": "fail"})) == Verdict.UNVERIFIED
    assert decide_verdict(mk(**{**ok, "G6": "not_run"})) == Verdict.UNVERIFIED


# ---------------------------------------------------------------- rehearsal helpers
def test_dev_failure_without_a_verification_set_is_failed_not_unverified(world):
    gate, dev, patched, _ = setup(StubRunner(), world, 42, with_vset=False)  # 5 regressions
    rep = gate.finalize(dev, patched, None)
    g5 = next(c for c in rep.checks if c.id == "G5")
    assert g5.status == CheckStatus.SKIPPED_AFTER_FAILURE and rep.verdict == Verdict.FAILED


def test_diagnostic_g5_runs_on_rehearsal_only_and_never_rescues_a_failed_patch(world):
    gate, dev, patched, vset = setup(StubRunner(), world, 42)  # G4 fails
    rep = gate.finalize(dev, patched, vset, diagnostic_g5=True)
    g5 = next(c for c in rep.checks if c.id == "G5")
    assert g5.status == CheckStatus.PASS and "DIAGNOSTIC" in g5.details
    assert rep.verdict == Verdict.FAILED  # G4 still failed
    gate, dev, patched, vset = setup(StubRunner(), world, 42, rehearsal=False)  # a held-out block
    with pytest.raises(ValueError, match="never on a held-out block"):
        gate.finalize(dev, patched, vset, diagnostic_g5=True)
    assert vset.consumed is False  # the block was not touched


# ---------------------------------------------------------------- verdict precedence: one test per line of the rule
def test_precedence_1_g6_fail_gives_unverified_even_with_a_failed_check(world):
    stub = StubRunner(fail=lambda p, scns: "FAILED" if round(p.grip_force) == BASE_GRIP and len(scns) == 30 else None)
    rep = verdict_of(stub, world, 41)  # G3 fails AND the G1 re-run crashed (G6 fails)
    assert status(rep, "G3") == CheckStatus.FAIL and status(rep, "G6") == CheckStatus.FAIL and rep.verdict == Verdict.UNVERIFIED


def test_precedence_1_a_check_that_could_not_run_gives_unverified():
    from app.core.schemas import GateCheck
    cs = [GateCheck(id=i, name=i, status=CheckStatus.PASS) for i in ("G1", "G2", "G3", "G4", "G6")]
    cs.append(GateCheck(id="G5", name="G5", status=CheckStatus.NOT_RUN))
    assert decide_verdict(cs) == Verdict.UNVERIFIED


def test_precedence_2_complete_execution_plus_failure_gives_failed_with_g5_skipped(world):
    rep = verdict_of(StubRunner(), world, 41)  # G3 fails, everything finished
    assert status(rep, "G6") == CheckStatus.PASS and status(rep, "G3") == CheckStatus.FAIL
    assert status(rep, "G5") == CheckStatus.SKIPPED_AFTER_FAILURE and rep.verdict == Verdict.FAILED


def test_precedence_3_verified_only_with_everything_passing_and_nothing_skipped():
    from app.core.schemas import GateCheck
    ok = [GateCheck(id=i, name=i, status=CheckStatus.PASS) for i in ("G1", "G2", "G3", "G4", "G5", "G6")]
    assert decide_verdict(ok) == Verdict.VERIFIED
    skipped_without_failure = [c if c.id != "G5" else GateCheck(id="G5", name="G5", status=CheckStatus.SKIPPED_AFTER_FAILURE) for c in ok]
    assert decide_verdict(skipped_without_failure) == Verdict.UNVERIFIED  # inconsistent state is never VERIFIED


def test_skipped_status_is_distinct_from_not_run():
    assert CheckStatus.SKIPPED_AFTER_FAILURE != CheckStatus.NOT_RUN and CheckStatus.SKIPPED_AFTER_FAILURE.value == "skipped_after_failure"
