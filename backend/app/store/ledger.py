"""Seed ledger: records which seed block each run used, and enforces single use of rehearsal / held-out blocks."""
from __future__ import annotations

from ..core.seeds import BLOCKS
from .db import Database

EXCLUSIVE = ("rehearsal", "held_out")  # a sub-block of these can be used once, ever


class SeedBlockReusedError(RuntimeError):
    pass


class SeedLedgerError(RuntimeError):
    pass


class SeedLedger:
    def __init__(self, db: Database):
        self.db = db

    def _check_range(self, block: str, start: int, count: int) -> None:
        if block not in BLOCKS:
            raise SeedLedgerError(f"unknown seed block {block!r}")
        lo, hi = BLOCKS[block]
        if count < 1 or start < lo or start + count > hi:
            raise SeedLedgerError(f"[{start}, {start + count}) is outside the {block} block [{lo}, {hi})")

    def _overlaps(self, block: str, start: int, count: int) -> list[tuple]:
        return self.db.conn.execute(
            "SELECT run_id, start, count FROM seed_ledger WHERE block_name=? AND start < ? AND start + count > ?",
            (block, start + count, start),
        ).fetchall()

    def record_use(self, run_id: str, block: str, start: int, count: int, purpose: str, rehearsal: bool = False) -> None:
        """Record that `run_id` used seeds [start, start+count) of `block`. Rehearsal and held-out sub-blocks are single use."""
        self._check_range(block, start, count)
        if block in EXCLUSIVE:
            prior = self._overlaps(block, start, count)
            if prior:
                raise SeedBlockReusedError(
                    f"{block} seeds [{start}, {start + count}) were already used by run {prior[0][0]}; allocate a fresh block")
        self.db.conn.execute(
            "INSERT INTO seed_ledger (run_id, block_name, start, count, purpose, rehearsal) VALUES (?,?,?,?,?,?)",
            (run_id, block, start, count, purpose, int(rehearsal)),
        )
        self.db.conn.commit()

    def allocate(self, run_id: str, block: str, count: int, purpose: str, rehearsal: bool = False) -> int:
        """Reserve the next free sub-block of `count` seeds in an exclusive block; returns its start."""
        if block not in EXCLUSIVE:
            raise SeedLedgerError(f"only {EXCLUSIVE} blocks are allocated by the ledger; dev seeds are chosen by the caller")
        lo, _ = BLOCKS[block]
        row = self.db.conn.execute("SELECT MAX(start + count) FROM seed_ledger WHERE block_name=?", (block,)).fetchone()
        start = max(lo, row[0] or lo)
        self.record_use(run_id, block, start, count, purpose, rehearsal)
        return start

    def rows(self) -> list[tuple]:
        return self.db.conn.execute("SELECT run_id, block_name, start, count, purpose, rehearsal FROM seed_ledger ORDER BY id").fetchall()
