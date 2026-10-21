"""Print models available to your Nebius Token Factory key (GET /v1/models).

PENDING_KEY: requires NEBIUS_API_KEY in .env. Usage: python scripts/list_models.py [--verbose] [--filter nemotron]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import ConfigError, load_settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true", help="request ?verbose=true (adds pricing/context length)")
    ap.add_argument("--filter", default="", help="case-insensitive substring filter on model id")
    args = ap.parse_args()

    s = load_settings(dotenv_path=Path(__file__).resolve().parents[1] / ".env")
    if not s.api_key:
        print("NEBIUS_API_KEY is not set. Copy .env.example to .env and fill it in.", file=sys.stderr)
        return 2
    try:
        import httpx

        r = httpx.get(
            s.base_url.rstrip("/") + "/models",
            params={"verbose": "true"} if args.verbose else None,
            headers={"Authorization": f"Bearer {s.api_key}"},
            timeout=s.llm_timeout_s,
        )
        r.raise_for_status()
    except (httpx.HTTPError, ConfigError) as e:
        print(f"request failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    models = [m for m in r.json().get("data", []) if args.filter.lower() in m.get("id", "").lower()]
    for m in sorted(models, key=lambda m: m.get("id", "")):
        extra = ""
        if args.verbose:
            extra = f"  ctx={m.get('context_length')} pricing={m.get('pricing')}"
        print(m.get("id"), extra)
    print(f"\n{len(models)} model(s). Set NEBIUS_MODEL_FAST and NEBIUS_MODEL_REASONING in .env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
