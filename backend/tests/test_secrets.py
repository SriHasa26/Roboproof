"""Secrets checker tests, on throw-away git repos with a fake key. Never touches the real .env."""
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.secrets_check import check_env_example, run_check

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available (sim image)")
FAKE = "fake-test-key-0123456789abcdefghijklmnopqrstuv"


def git(root, *a):
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)


def make_repo(tmp_path, tracked: dict, ignore=".env\n", env_value=FAKE):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".gitignore").write_text(ignore)
    (tmp_path / ".env").write_text(f"NEBIUS_API_KEY={env_value}\n")
    (tmp_path / ".env.example").write_text("NEBIUS_API_KEY=your-key-here\nNEBIUS_BASE_URL=https://api.example.com/v1/\n")
    for name, text in tracked.items():
        (tmp_path / name).write_text(text)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_clean_repo_passes(tmp_path):
    rep = run_check(make_repo(tmp_path, {"a.txt": "hello"}))
    assert rep.ok and rep.key_present and rep.tracked_files_with_key == [] and rep.commits_with_key == 0 and rep.env_ignored


def test_key_in_tracked_file_is_found_by_name_not_value(tmp_path):
    rep = run_check(make_repo(tmp_path, {"leak.txt": f"x={FAKE}"}))
    assert not rep.ok and rep.tracked_files_with_key == ["leak.txt"] and rep.commits_with_key == 1
    assert FAKE not in repr(rep)  # the report never carries the value


def test_key_removed_but_still_in_history_is_flagged(tmp_path):
    root = make_repo(tmp_path, {"leak.txt": f"x={FAKE}"})
    (root / "leak.txt").write_text("clean")
    git(root, "commit", "-qam", "remove")
    rep = run_check(root)
    assert rep.tracked_files_with_key == [] and rep.commits_with_key == 2 and not rep.ok  # added, then removed


def test_env_not_ignored_is_flagged(tmp_path):
    rep = run_check(make_repo(tmp_path, {}, ignore="", env_value=""))
    assert not rep.env_ignored and not rep.ok


def test_env_example_must_be_placeholders(tmp_path):
    p = tmp_path / ".env.example"
    p.write_text("NEBIUS_API_KEY=" + FAKE + "\n")
    assert check_env_example(p)
    p.write_text("NEBIUS_API_KEY=your-key-here\nNEBIUS_MODEL_FAST=\nLLM_TIMEOUT_S=120\nROBOPROOF_DB=backend/data/x.sqlite\n")
    assert check_env_example(p) == []
    p.write_text("SOME_SECRET=abcdefghijklmnopqrstuvwxyz0123456789ABCD\n")
    assert check_env_example(p)
