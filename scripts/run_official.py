"""OFFICIAL batch per docs/OFFICIAL_PROTOCOL.md: K = 5 official runs, master seeds fixed in the protocol, each on a fresh single-use
HELD-OUT seed block (>= 900000). DO NOT RUN until the project owner says so: it spends five held-out blocks.

Each run goes through the official-run guard (backend/app/core/provenance.py): clean working tree, frozen files equal to the
`pipeline-frozen-v2` tag, protocol committed, image build id known, no threshold overrides in the environment.
Repeat rule (protocol section 6): an infrastructure error before G5 executed may be repeated ONCE with a new run id; the original stays
in the report and its block is retired unused. A run where G5 executed is final. Every run is reported; nothing is re-rolled.

Usage (in the sim image, from a clean tree at the tag):
  scripts/dock.sh python scripts/run_official.py --confirm-spend-heldout-blocks
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.config import load_settings  # noqa: E402
from app.pipeline import PipelineConfig, fetch_pricing, run_pipeline  # noqa: E402
from app.runner.local import LocalRunner  # noqa: E402
from app.store.db import Database  # noqa: E402
from app.store.ledger import SeedLedger  # noqa: E402
from run_reliability import is_infra, row, summarize  # noqa: E402

PROTOCOL_SEEDS = [3101, 3202, 3303, 3404, 3505]  # pre-registered in docs/OFFICIAL_PROTOCOL.md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm-spend-heldout-blocks", action="store_true", required=True)
    ap.add_argument("--out", default=str(ROOT / "recorded_runs" / "official_001"))
    ap.add_argument("--n", type=int, default=250)
    a = ap.parse_args()
    settings = load_settings(dotenv_path=ROOT / ".env")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    db = Database(str(ROOT / settings.db_path))
    ledger = SeedLedger(db)
    pricing = fetch_pricing(settings, {settings.model_fast, settings.model_reasoning})
    rows, n429, stop = [], 0, None
    for i, seed in enumerate(PROTOCOL_SEEDS, 1):
        rid = f"official_{i:02d}_seed{seed}"
        res = run_pipeline(settings, LocalRunner(), db, ledger, PipelineConfig(rid, out, seed, n=a.n, rehearsal=False, official=True),
                           env=dict(os.environ), pricing=pricing)
        rows.append(row(res))
        print(f"{rid}: verdict={res.get('verdict')} attempts={res.get('n_attempts')} g5_executed={res.get('g5_executed')} error={res.get('error')}", flush=True)
        if is_infra(res.get("error")) and not res.get("g5_executed"):  # protocol section 6: one repeat, original stays reported
            rid2 = rid + "_repeat1"
            res = run_pipeline(settings, LocalRunner(), db, ledger, PipelineConfig(rid2, out, seed, n=a.n, rehearsal=False, official=True),
                               env=dict(os.environ), pricing=pricing)
            rows.append(row(res))
            print(f"{rid2}: verdict={res.get('verdict')} g5_executed={res.get('g5_executed')} error={res.get('error')}", flush=True)
        err = res.get("error") or ""
        if " 401" in err or " 402" in err or "AuthenticationError" in err:
            stop = f"stopped after {rid}: authentication/payment error"
        n429 += " 429" in err or "RateLimitError" in err
        if n429 >= 2:
            stop = f"stopped after {rid}: repeated 429"
        if stop:
            print(stop)
            break
    summarize(rows, out, "OFFICIAL BATCH per docs/OFFICIAL_PROTOCOL.md. " + (stop or "All pre-registered runs executed.") +
              " Run 1 is the headline run by rule. LocalRunner (local fallback, not Nebius). Held-out blocks were single use.",
              title="official_001", kind="OFFICIAL BATCH (pre-registered, docs/OFFICIAL_PROTOCOL.md)", stem="official_summary", sidebyside=False)
    print("summary written to", out)


if __name__ == "__main__":
    main()
