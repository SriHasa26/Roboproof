"""Deliberately (re-)freeze the pipeline fingerprint: rewrites backend/app/core/FROZEN_PIPELINE_HASH.txt.

Afterwards: commit, create a NEW git tag (see core/provenance.py TAG), and treat every earlier run as a rehearsal.
Usage: python scripts/refreeze_pipeline.py --i-understand-this-invalidates-rehearsals
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core import provenance as pv  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--i-understand-this-invalidates-rehearsals", action="store_true", required=True)
ap.parse_args()
(ROOT / pv.HASH_FILE_REL).write_text(pv.render_hash_file(ROOT), encoding="utf-8")
print("pipeline hash:", pv.compute_pipeline_hash(ROOT))
print("next: git add -A && git commit, then git tag", pv.TAG, "(delete the old tag first if re-freezing)")
