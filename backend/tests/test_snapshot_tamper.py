"""Build-snapshot git facts for the container, and the tamper demo (never writes to the repo)."""
import subprocess
import sys
from pathlib import Path

import pytest

from app.verify.core import MATCH, UNVERIFIABLE, SNAPSHOT_REL, verify_all

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "recorded_runs" / "official_001"
pytestmark = pytest.mark.skipif(not (RUNS / "official_summary.json").exists(), reason="official runs not present")


class NoGit:
    available = False

    def __call__(self, *a):
        return 127, ""


def test_without_git_the_integrity_rows_come_from_the_snapshot_and_say_so():
    if not (ROOT / SNAPSHOT_REL).exists():
        pytest.skip("no git facts snapshot")
    res = verify_all(ROOT, resim=False, git=NoGit())
    git_rows = [r for r in res["integrity"] if r["id"].split("_")[0] in {"protocol", "ancestry", "freeze", "tag"}]
    assert git_rows and all(r["status"] == MATCH for r in git_rows)
    assert all("from build snapshot" in r["note"] for r in git_rows)


def test_without_git_and_snapshot_the_rows_are_cannot_check(tmp_path, monkeypatch):
    import app.verify.core as core
    monkeypatch.setattr(core.SnapshotGit, "load", classmethod(lambda cls, root: None))
    res = verify_all(ROOT, resim=False, git=NoGit())
    assert any(r["id"] == "protocol_time" and r["status"] == UNVERIFIABLE for r in res["integrity"])


def test_tamper_demo_detects_the_change_and_leaves_the_repo_untouched():
    before = {p: p.read_bytes() for p in (RUNS / "official_03_seed3303").glob("*.json")}
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "tamper_demo.py")], capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "MISMATCH" in p.stdout and "repository files unchanged: yes" in p.stdout
    assert before == {q: q.read_bytes() for q in before}
