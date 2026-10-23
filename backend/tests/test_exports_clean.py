"""Nothing secret may be in the files the dashboard serves or the evidence we commit: no API key, no bearer tokens, no prompts."""
import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "frontend" / "public" / "data"
PATTERNS = [re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), re.compile(r"Bearer\s+[A-Za-z0-9._\-]{12,}"), re.compile(r"nvapi-[A-Za-z0-9_\-]{12,}"), re.compile(r"(?i)api[_-]?key\"?\s*[:=]\s*\"[A-Za-z0-9_\-]{16,}")]


def real_key() -> str | None:
    k = os.environ.get("NEBIUS_API_KEY")
    env = ROOT / ".env"
    if not k and env.exists():
        for ln in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if ln.startswith("NEBIUS_API_KEY="):
                k = ln.split("=", 1)[1].strip().strip('"').strip("'")
    return k if k and len(k) >= 8 else None


def files():
    out = [p for p in DATA.rglob("*") if p.is_file() and p.suffix in (".json", ".md", ".txt")]
    out += [p for p in (ROOT / "docs" / "evidence").rglob("*") if p.is_file()]
    return out


@pytest.mark.skipif(not DATA.exists(), reason="no exported data in this checkout")
def test_no_key_or_token_pattern_in_served_or_evidence_files():
    key = real_key()
    for p in files():
        t = p.read_text(encoding="utf-8", errors="ignore")
        if key:
            assert key not in t, f"the API key is in {p.relative_to(ROOT)}"  # the key itself is never printed
        for pat in PATTERNS:
            assert not pat.search(t), f"{pat.pattern} matched in {p.relative_to(ROOT)}"


@pytest.mark.skipif(not (DATA / "calls").exists(), reason="no exported call logs")
def test_call_logs_carry_replies_but_never_prompts():
    for p in (DATA / "calls").glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        assert "messages" not in json.dumps(d) and all("messages" not in r for r in d.get("replies", []))
        assert d["totals"]["calls"] == len(d["calls"])
    live = DATA / "live_replay" / "calls.json"
    if live.exists():
        d = json.loads(live.read_text(encoding="utf-8"))
        assert d["response_metadata_captured"] is True and all((c["response_id"] or "").startswith("chatcmpl-") for c in d["calls"])
