"""Live-service settings, read from environment variables (placeholders only in .env.example)."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _flag(v: str | None, default: bool = False) -> bool:
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def _num(v: str | None, default: float) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except ValueError:
        return default


@dataclass
class LiveConfig:
    enabled: bool = False                      # LIVE_ENABLED: kill switch, off unless explicitly turned on
    daily_run_cap: int = 10                    # LIVE_DAILY_RUN_CAP
    daily_usd_cap: float = 1.0                 # LIVE_DAILY_USD_CAP (estimated spend, from run artifacts)
    est_run_usd: float = 0.06                  # LIVE_EST_RUN_USD: reserved against the cap before a run's real cost is known
    access_code: str = ""                      # LIVE_ACCESS_CODE: optional shared code
    per_ip_per_hour: int = 3                   # LIVE_RATE_PER_IP_PER_HOUR
    allowed_origins: list[str] = field(default_factory=list)  # ALLOWED_ORIGINS, comma separated, never "*"
    trust_proxy: bool = False                  # LIVE_TRUST_PROXY: take the client IP from X-Forwarded-For
    timeout_s: float = 600.0                   # LIVE_TIMEOUT_S: kill a run after this long
    runs_dir: Path = ROOT / "live_runs"        # LIVE_RUNS_DIR (gitignored)
    pipeline_script: Path = ROOT / "scripts" / "run_live_pipeline.py"  # LIVE_PIPELINE_SCRIPT: server-side only (tests use a fake); wraps run_reliability.py with call-metadata capture
    python_exe: str = sys.executable
    db_path: str = ""                          # ROBOPROOF_DB, read-only, to show LLM calls as they finish
    poll_s: float = 0.5

    @staticmethod
    def from_env(env: dict[str, str] | None = None) -> "LiveConfig":
        e = env if env is not None else dict(os.environ)
        c = LiveConfig()
        c.enabled = _flag(e.get("LIVE_ENABLED"))
        c.daily_run_cap = int(_num(e.get("LIVE_DAILY_RUN_CAP"), c.daily_run_cap))
        c.daily_usd_cap = _num(e.get("LIVE_DAILY_USD_CAP"), c.daily_usd_cap)
        c.est_run_usd = _num(e.get("LIVE_EST_RUN_USD"), c.est_run_usd)
        c.access_code = e.get("LIVE_ACCESS_CODE", "")
        c.per_ip_per_hour = int(_num(e.get("LIVE_RATE_PER_IP_PER_HOUR"), c.per_ip_per_hour))
        c.allowed_origins = [o.strip() for o in e.get("ALLOWED_ORIGINS", "").split(",") if o.strip() and o.strip() != "*"]
        c.trust_proxy = _flag(e.get("LIVE_TRUST_PROXY"))
        c.timeout_s = _num(e.get("LIVE_TIMEOUT_S"), c.timeout_s)
        if e.get("LIVE_RUNS_DIR"):
            c.runs_dir = Path(e["LIVE_RUNS_DIR"])
        if e.get("LIVE_PIPELINE_SCRIPT"):
            c.pipeline_script = Path(e["LIVE_PIPELINE_SCRIPT"])
        c.db_path = e.get("ROBOPROOF_DB", "")
        return c
