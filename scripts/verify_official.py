"""Verify the recorded OFFICIAL runs from first principles. Pure code: no LLM calls, no network, no held-out seeds.

  scripts/dock.sh python scripts/verify_official.py                 # everything (about 1 minute for the 5 runs)
  scripts/dock.sh python scripts/verify_official.py --no-resim      # recompute from stored numbers only (seconds)
  scripts/dock.sh python scripts/verify_official.py --run official_03_seed3303 --all-attempts
  scripts/dock.sh python scripts/verify_official.py --json verify_report.json
  scripts/dock.sh python scripts/verify_official.py --export-ledger-snapshot   # write docs/evidence/seed_ledger_snapshot.json from the ledger database

It recomputes the Wilson intervals, the G1 to G6 statuses and the verdict from the stored counts; re-simulates each run's ANALYSIS set (never
held-out) for the unpatched policy and the selected patch and compares every number with the stored candidate table; checks seed-ledger
integrity and that the protocol was committed before the first official run. Exit code 1 on any mismatch. Things that cannot be re-verified
(held-out counts, model outputs) are listed, not faked.
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.verify.core import MATCH, MISMATCH, UNVERIFIABLE, tally, verify_all  # noqa: E402

MARK = {"match": "MATCH   ", "mismatch": "MISMATCH", "unverifiable": "CANNOT  ", "info": "info    "}


def export_snapshot() -> None:
    db = ROOT / "backend" / "data" / "roboproof.sqlite"
    if not db.exists():
        sys.exit("no ledger database at backend/data/roboproof.sqlite")
    c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    cols = ["run_id", "block_name", "start", "count", "purpose", "rehearsal", "created_at", "status", "note"]
    rows = [dict(zip(cols, r)) for r in c.execute(f"SELECT {', '.join(cols)} FROM seed_ledger ORDER BY id")]
    out = ROOT / "docs" / "evidence" / "seed_ledger_snapshot.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"note": "Snapshot of the seed_ledger table (the database itself is gitignored). created_at is SQLite CURRENT_TIMESTAMP (UTC). "
                               "A snapshot is evidence of what the ledger said when exported, not tamper-proof; the verifier prefers the live database when present.",
                               "exported_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "rows": rows}, indent=1), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} ({len(rows)} rows)")


def show(title: str, rows: list[dict]) -> None:
    print(f"\n== {title}")
    for r in rows:
        line = f"  [{MARK[r['status']]}] {r['name']}"
        print(line)
        if r["status"] != "info" or r["recomputed"]:
            print(f"      stored: {r['stored'] or '-'}   recomputed: {r['recomputed']}")
        if r["note"]:
            print(f"      note: {r['note']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-resim", action="store_true", help="skip the re-simulation of the analysis sets")
    ap.add_argument("--all-attempts", action="store_true", help="also re-simulate the earlier attempts' selected patches")
    ap.add_argument("--run", help="verify one run, e.g. official_03_seed3303")
    ap.add_argument("--timeout", type=float, default=120.0, help="per-shard timeout (s)")
    ap.add_argument("--json", help="write the full report to this file")
    ap.add_argument("--export-ledger-snapshot", action="store_true")
    ap.add_argument("--export-git-snapshot", action="store_true", help="write docs/evidence/git_facts_snapshot.json (run before building the image)")
    ap.add_argument("--quiet", action="store_true", help="print only mismatches and the summary table")
    a = ap.parse_args()
    if a.export_ledger_snapshot:
        export_snapshot()
        return 0
    if a.export_git_snapshot:
        from app.verify.core import SNAPSHOT_REL, export_git_facts
        dirs = sorted(d for d in (ROOT / "recorded_runs" / "official_001").glob("official_*") if (d / "summary.json").exists())
        (ROOT / SNAPSHOT_REL).write_text(json.dumps(export_git_facts(ROOT, dirs), indent=1) + chr(10), encoding="utf-8")
        print(f"wrote {SNAPSHOT_REL}")
        return 0
    res = verify_all(ROOT, resim=not a.no_resim, all_attempts=a.all_attempts, timeout_s=a.timeout, only=a.run)
    for rid, rows in res["runs"].items():
        show(rid, [r for r in rows if not a.quiet or r["status"] in (MISMATCH, UNVERIFIABLE)])
    show("integrity (ledger, protocol before runs, freeze)", [r for r in res["integrity"] if not a.quiet or r["status"] in (MISMATCH, UNVERIFIABLE)])
    show("what cannot be re-verified, and why", res["limits"])
    print("\n== summary per run")
    print(f"  {'run':26} {'match':>6} {'mismatch':>9} {'cannot':>7}")
    bad = 0
    for rid, rows in res["runs"].items():
        m = sum(r["status"] == MATCH for r in rows)
        x = sum(r["status"] == MISMATCH for r in rows)
        u = sum(r["status"] == UNVERIFIABLE for r in rows)
        bad += x
        print(f"  {rid:26} {m:>6} {x:>9} {u:>7}")
    im, ix, iu = (sum(r["status"] == s for r in res["integrity"]) for s in (MATCH, MISMATCH, UNVERIFIABLE))
    bad += ix
    print(f"  {'integrity':26} {im:>6} {ix:>9} {iu:>7}")
    t = tally(res)
    print(f"\n  TOTAL: {t[MATCH]} match, {t[MISMATCH]} mismatch, {t[UNVERIFIABLE]} cannot be checked here, plus {t['unverifiable_listed']} limits listed above.")
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("  RESULT:", "ALL CHECKS THAT COULD RUN MATCH" if bad == 0 else f"{bad} MISMATCH(ES)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
