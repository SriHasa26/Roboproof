"""OFFICIAL run: refuses to start unless the pipeline freeze checks pass (see backend/app/core/provenance.py).

Do NOT run this until the project owner says so: it allocates a fresh single-use HELD-OUT seed block (>= 900000) and spends it on G5.
Usage (in the sim image, from a clean working tree at or after the 'pipeline-frozen' tag):
  scripts/dock.sh python scripts/run_official.py --name official_001 [--master-seed N]
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import load_settings  # noqa: E402
from app.pipeline import PipelineConfig, run_pipeline  # noqa: E402
from app.runner.local import LocalRunner  # noqa: E402
from app.store.db import Database  # noqa: E402
from app.store.ledger import SeedLedger  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True)
ap.add_argument("--master-seed", type=int, default=2026)
ap.add_argument("--n", type=int, default=250)
a = ap.parse_args()
settings = load_settings(dotenv_path=ROOT / ".env")
db = Database(str(ROOT / settings.db_path))
res = run_pipeline(settings, LocalRunner(), db, SeedLedger(db), PipelineConfig(a.name, ROOT / "recorded_runs", a.master_seed, n=a.n, rehearsal=False, official=True),
                   env=dict(os.environ))
print("OFFICIAL RUN", a.name, "verdict:", res.get("verdict"), "error:", res.get("error"))
