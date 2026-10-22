"""Seed blocks, the seed ledger and code-only verification sets."""
import ast
from pathlib import Path

import pytest

from app.core.seeds import BLOCKS, HELDOUT_SEED_BASE, HeldOutSeedError
from app.gate.verification import make_verification_set
from app.store.db import Database
from app.store.ledger import SeedBlockReusedError, SeedLedger, SeedLedgerError

ROOT = Path(__file__).resolve().parents[2]


def ledger():
    return SeedLedger(Database(":memory:"))


def test_blocks_are_disjoint_and_ordered():
    items = sorted(BLOCKS.values())
    for (a_lo, a_hi), (b_lo, b_hi) in zip(items, items[1:]):
        assert a_lo < a_hi <= b_lo
    assert BLOCKS["held_out"][0] == HELDOUT_SEED_BASE and BLOCKS["rehearsal"][1] == HELDOUT_SEED_BASE


def test_existing_dev_usage_is_inside_dev_block():
    lo, hi = BLOCKS["dev"]
    for start, count in ((1000, 300), (3000, 24), (50000, 300)):  # sweeps, runner test, set B
        assert lo <= start and start + count <= hi


def test_allocation_is_sequential_and_never_overlaps():
    L = ledger()
    a = L.allocate("r1", "rehearsal", 400, "G5")
    b = L.allocate("r2", "rehearsal", 400, "G5")
    assert a == 800_000 and b == 800_400
    h = L.allocate("r3", "held_out", 400, "G5")
    assert h == HELDOUT_SEED_BASE and L.allocate("r4", "held_out", 400, "G5") == HELDOUT_SEED_BASE + 400


def test_reusing_a_heldout_or_rehearsal_block_raises():
    L = ledger()
    first = L.allocate("official-1", "held_out", 400, "G5")
    second = L.allocate("official-2", "held_out", 400, "G5")
    for s, n in ((first, 400), (first + 399, 400), (second - 10, 20)):  # exact, overlap at the end, straddling two blocks
        with pytest.raises(SeedBlockReusedError):
            L.record_use("official-3", "held_out", s, n, "G5")
    r = L.allocate("rh-1", "rehearsal", 100, "G5", rehearsal=True)
    with pytest.raises(SeedBlockReusedError):
        L.record_use("rh-2", "rehearsal", r, 100, "G5")


def test_dev_blocks_may_overlap_but_are_recorded_and_range_checked():
    L = ledger()
    L.record_use("a", "dev", 1000, 300, "sweep")
    L.record_use("b", "dev", 1000, 300, "baseline")  # re-using dev seeds is normal
    assert len(L.rows()) == 2
    with pytest.raises(SeedLedgerError):
        L.record_use("c", "dev", 850_000, 10, "x")  # not a dev seed
    with pytest.raises(SeedLedgerError):
        L.record_use("c", "rehearsal", 10, 10, "x")
    with pytest.raises(SeedLedgerError):
        L.allocate("c", "dev", 10, "x")  # the ledger only allocates exclusive blocks
    with pytest.raises(SeedLedgerError):
        L.record_use("c", "rehearsal", 899_990, 50, "x")  # spills over into held-out


def test_rehearsal_verification_set_uses_rehearsal_block_and_dev_rules():
    L = ledger()
    v = make_verification_set(L, "run-1", rehearsal=True, n=400)
    seeds = [s.seed for s in v.scenarios]
    assert v.rehearsal and v.block_name == "rehearsal" and v.sampler == "latin_hypercube"
    assert len(v.scenarios) == 400 and min(seeds) >= 800_000 and max(seeds) < HELDOUT_SEED_BASE
    assert all(s.tag == "verify" for s in v.scenarios)
    v2 = make_verification_set(L, "run-2", rehearsal=True, n=400)
    assert v2.start == v.start + 400 and not ({s.seed for s in v.scenarios} & {s.seed for s in v2.scenarios})


def test_heldout_verification_set_is_in_heldout_block_and_not_run_here():
    L = ledger()
    v = make_verification_set(L, "official", rehearsal=False, n=400)
    assert v.held_out and all(s.seed >= HELDOUT_SEED_BASE for s in v.scenarios)  # generated only; nothing simulated


def test_verification_set_is_deterministic_for_a_given_block():
    a = make_verification_set(ledger(), "x", rehearsal=True, n=50)
    b = make_verification_set(ledger(), "y", rehearsal=True, n=50)
    assert a.scenarios == b.scenarios  # same fresh ledger -> same start -> same scenarios


def test_verification_module_has_no_llm_dependency():
    src = (ROOT / "backend" / "app" / "gate" / "verification.py").read_text(encoding="utf-8")
    imported = {n.module or "" for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)}
    assert not any("llm" in m or "generator" in m or "analysis" in m for m in imported)


def test_only_the_gate_allocates_or_uses_heldout_blocks():
    """No module outside app/gate/ (and tests) may name the 'held_out' block in a ledger call."""
    offenders = []
    for base in (ROOT / "backend" / "app", ROOT / "scripts"):
        for f in base.rglob("*.py"):
            if (ROOT / "backend" / "app" / "gate") in f.parents or f.name == "ledger.py":
                continue
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in ("allocate", "record_use"):
                    consts = [a.value for a in list(node.args) + [k.value for k in node.keywords] if isinstance(a, ast.Constant)]
                    if "held_out" in consts:
                        offenders.append(f"{f.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, offenders


# ---------------------------------------------------------------- P4.6: used / retired_unused statuses
def test_blocks_are_marked_used_or_retired_unused_and_never_reused():
    L = ledger()
    a = L.allocate("run-a", "held_out", 400, "G5")
    b = L.allocate("run-b", "held_out", 400, "G5")
    assert L.retire("run-a", "G5 did not execute") == 1 and L.mark_used("run-b") == 1
    st = {r[0]: r[4:] for r in L.status_rows()}
    assert st["run-a"] == ("retired_unused", "G5 did not execute") and st["run-b"] == ("used", None)
    assert L.retire("run-b", "late") == 0 and L.mark_used("run-a") == 0  # a block already settled is left alone
    with pytest.raises(SeedBlockReusedError):  # retired is NOT free: the single-use rule still holds
        L.record_use("repeat-of-a", "held_out", a, 400, "G5")
    assert L.allocate("run-a_repeat1", "held_out", 400, "G5") == b + 400  # the repeat gets a fresh block


def test_dev_blocks_are_untouched_by_retire():
    L = ledger()
    L.record_use("x", "dev", 1000, 300, "sweep")
    assert L.retire("x", "n/a") == 0


def test_database_migrates_a_ledger_created_before_status_columns(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE seed_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, block_name TEXT, start INTEGER, count INTEGER, "
              "purpose TEXT, rehearsal INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    c.execute("INSERT INTO seed_ledger (run_id, block_name, start, count, purpose, rehearsal) VALUES ('old','rehearsal',800000,400,'G5',1)")
    c.commit()
    c.close()
    db = Database(str(path))
    assert [r[4] for r in SeedLedger(db).status_rows()] == ["allocated"]  # old rows survive and get the default status
