"""Show that the verifier notices a changed number.

Copies one official run's stored files into a temporary folder, changes ONE number in the copy's gate report (by default raises the held-out
patched pass count of official_03, the run that FAILED at G5, past the 360 needed, as if someone wanted it to look VERIFIED), runs the same
recomputation the verifier uses on the untouched copy and on the tampered copy, prints both, and deletes the copy. Nothing in the repository
is written or changed; the copy is refused if its path is inside the repository.

  scripts/dock.sh python scripts/tamper_demo.py
  scripts/dock.sh python scripts/tamper_demo.py --run official_01_seed3101 --delta -5
Exit code 0 when the tampering was detected (the demo worked), 1 if it was NOT detected.
"""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.verify.core import MATCH, MISMATCH, recompute_run  # noqa: E402

FILES = ["summary.json", "gate_report.json", "baseline_results.json", "targeted_failures.json"]


def tally(rows) -> tuple[int, int]:
    return sum(r.status == MATCH for r in rows), sum(r.status == MISMATCH for r in rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default="official_03_seed3303")
    ap.add_argument("--delta", type=int, default=13, help="added to the stored G5 patched pass count in the copy (default +13)")
    a = ap.parse_args()
    src = ROOT / "recorded_runs" / "official_001" / a.run
    if not (src / "gate_report.json").exists():
        sys.exit(f"no stored run {a.run}")
    with tempfile.TemporaryDirectory(prefix="roboproof_tamper_") as tmp:
        work = Path(tmp).resolve()
        if ROOT.resolve() in work.parents or work == ROOT.resolve():
            sys.exit("refusing to work inside the repository")
        dst = work / a.run
        dst.mkdir()
        for f in FILES:
            shutil.copy2(src / f, dst / f)
        before_bytes = {f: (src / f).read_bytes() for f in FILES}

        rows0 = recompute_run(dst)
        m0, x0 = tally(rows0)
        print(f"untouched copy of {a.run}: {m0} checks match, {x0} mismatch")

        gp = dst / "gate_report.json"
        d = json.loads(gp.read_text(encoding="utf-8"))
        g5 = next(c for c in d["report"]["checks"] if c["id"] == "G5")["observed"]
        old = g5["patched_passes"]
        g5["patched_passes"] = old + a.delta
        gp.write_text(json.dumps(d), encoding="utf-8")
        print(f"\nTAMPER (in the temporary copy only): gate_report.json G5 patched_passes {old} -> {old + a.delta} (of {g5['n']} held-out scenarios)\n")

        rows1 = recompute_run(dst)
        m1, x1 = tally(rows1)
        for r in rows1:
            if r.status == MISMATCH:
                print(f"  MISMATCH  {r.name}\n            stored:     {r.stored}\n            recomputed: {r.recomputed}")
        print(f"\ntampered copy: {m1} match, {x1} MISMATCH")
        intact = all((src / f).read_bytes() == b for f, b in before_bytes.items())
    print("repository files unchanged:", "yes" if intact else "NO (this should never happen)")
    if x1:
        print(f"RESULT: the verifier detected the change ({x1} mismatching checks). A real verification of the repository data is unaffected.")
        return 0
    print("RESULT: the verifier did NOT detect the change.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
