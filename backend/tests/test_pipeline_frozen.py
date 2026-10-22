"""Pipeline freeze: the hash test and the official-run guard. The guard is tested with a fake git, on a copy of the frozen files."""
import shutil
from pathlib import Path

import pytest

from app.core import provenance as pv
from app.core.config import load_settings
from app.core.provenance import (FROZEN_FILES, OfficialRunRefused, REPO_ROOT, TAG, compute_pipeline_hash, official_preflight,
                                 read_committed_hash, render_hash_file)

MSG = (
    "\n\nThe frozen pipeline changed ({what}).\n"
    "Prompts, generator, evidence, analyst, fixer, gate, gate config and the runner base are frozen once the git tag\n"
    "'pipeline-frozen' exists: anything run before the tag is a rehearsal, and an OFFICIAL run refuses to start when these files\n"
    "differ from the tag. If the change is deliberate, re-freeze on purpose:\n"
    "  python scripts/refreeze_pipeline.py --i-understand-this-invalidates-rehearsals\n"
    "commit, create a new tag, and treat every earlier run as a rehearsal.\n"
)


def test_frozen_files_exist_and_hash_matches_the_committed_hash_file():
    missing = [f for f in FROZEN_FILES if not (REPO_ROOT / f).exists()]
    assert not missing, f"frozen file list names files that do not exist: {missing}"
    committed = read_committed_hash()
    assert committed is not None, "FROZEN_PIPELINE_HASH.txt is missing; run scripts/refreeze_pipeline.py"
    current = compute_pipeline_hash()
    if committed != current:
        lines = (REPO_ROOT / pv.HASH_FILE_REL).read_text().splitlines()[1:]
        old = dict(l.split() for l in lines)
        new = dict(l.split() for l in render_hash_file().splitlines()[1:])
        changed = [k for k in new if old.get(k) != new[k]]
        pytest.fail(MSG.format(what=", ".join(changed) or "hash"))


# ------------------------------------------------------------------ the official-run guard, with a fake git
def make_root(tmp_path):
    for rel in FROZEN_FILES:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, dst)
    (tmp_path / pv.HASH_FILE_REL).write_text(render_hash_file(tmp_path))
    return tmp_path


class FakeGit:
    def __init__(self, root, status="", has_tag=True, tag_overrides=None, head="abc123", tag_commit="def456", available=True):
        self.root, self.status, self.has_tag, self.over = root, status, has_tag, tag_overrides or {}
        self.head, self.tag_commit, self.available = head, tag_commit, available

    def __call__(self, *args):
        if not self.available:
            return 127, ""
        if args == ("rev-parse", "HEAD"):
            return 0, self.head + "\n"
        if args == ("status", "--porcelain"):
            return 0, self.status
        if args[:2] == ("rev-parse", "--verify"):
            return (0, self.tag_commit + "\n") if self.has_tag else (128, "")
        if args[0] == "show":
            rel = args[1].split(":", 1)[1]
            return 0, self.over.get(rel, (self.root / rel).read_bytes())
        raise AssertionError(args)


ENV = {"ROBOPROOF_IMAGE_ID": "sha256:abc"}


def go(tmp_path, env=ENV, **kw):
    root = make_root(tmp_path)
    git = FakeGit(root, **kw)
    return official_preflight(env, root=root, git=git, model_fast="fast-m", model_reasoning="reason-m", runner_name="local")


def test_clean_tree_matching_tag_is_allowed_and_provenance_recorded(tmp_path):
    p = go(tmp_path)
    assert (p.commit, p.tag, p.tag_commit, p.image_build_id) == ("abc123", TAG, "def456", "sha256:abc")
    assert (p.model_fast, p.model_reasoning, p.runner_name, p.official) == ("fast-m", "reason-m", "local", True)
    assert len(p.pipeline_hash) == 64 and p.python


def test_dirty_working_tree_is_refused(tmp_path):
    with pytest.raises(OfficialRunRefused, match="not clean"):
        go(tmp_path, status=" M backend/app/pipeline.py\n?? stray.txt\n")


def test_missing_tag_is_refused(tmp_path):
    with pytest.raises(OfficialRunRefused, match="does not exist"):
        go(tmp_path, has_tag=False)


def test_frozen_file_differing_from_the_tag_is_refused(tmp_path):
    root = make_root(tmp_path)
    old = (root / "backend/app/gate/gate.py").read_bytes() + b"\n# older version at the tag\n"
    with pytest.raises(OfficialRunRefused, match="differ from the tag"):
        official_preflight(ENV, root=root, git=FakeGit(root, tag_overrides={"backend/app/gate/gate.py": old}))


def test_line_endings_alone_do_not_count_as_a_change(tmp_path):
    root = make_root(tmp_path)
    lf = (root / "backend/app/gate/gate.py").read_bytes().replace(b"\r\n", b"\n")  # the copy may already be CRLF on Windows
    crlf = lf.replace(b"\n", b"\r\n")
    official_preflight(ENV, root=root, git=FakeGit(root, tag_overrides={"backend/app/gate/gate.py": crlf}))


def test_stale_committed_hash_file_is_refused(tmp_path):
    root = make_root(tmp_path)
    (root / "backend/app/core/gate_config.py").write_text((root / "backend/app/core/gate_config.py").read_text() + "\n# edited\n")
    over = {rel: (root / rel).read_bytes() for rel in FROZEN_FILES}  # pretend the tag has the edited file too
    with pytest.raises(OfficialRunRefused, match="FROZEN_PIPELINE_HASH.txt"):
        official_preflight(ENV, root=root, git=FakeGit(root, tag_overrides=over))


def test_unknown_image_build_id_is_refused(tmp_path):
    with pytest.raises(OfficialRunRefused, match="ROBOPROOF_IMAGE_ID"):
        go(tmp_path, env={})


def test_no_git_means_no_official_run(tmp_path):
    with pytest.raises(OfficialRunRefused, match="cannot run git"):
        go(tmp_path, available=False)


def test_all_problems_are_listed_together(tmp_path):
    with pytest.raises(OfficialRunRefused) as ei:
        go(tmp_path, env={}, status=" M x\n", has_tag=False)
    text = str(ei.value)
    assert "not clean" in text and "does not exist" in text and "ROBOPROOF_IMAGE_ID" in text


# ------------------------------------------------------------------ run_pipeline refuses before doing anything
class Boom:
    name = "boom"

    def run(self, *a, **k):
        raise AssertionError("the runner must not be touched by a refused run")


def settings(**env):
    base = {"NEBIUS_API_KEY": "k", "NEBIUS_MODEL_FAST": "f", "NEBIUS_MODEL_REASONING": "r"}
    return load_settings({**base, **env})


def test_official_run_is_refused_before_any_work(tmp_path):
    from app.pipeline import PipelineConfig, run_pipeline
    from app.store.db import Database
    from app.store.ledger import SeedLedger
    db = Database(":memory:")
    cfg = PipelineConfig(run_id="o1", out_dir=tmp_path, master_seed=1, rehearsal=False, official=True)
    with pytest.raises(OfficialRunRefused):
        run_pipeline(settings(), Boom(), db, SeedLedger(db), cfg, env={})  # no image id -> refused whatever git says
    assert not (tmp_path / "o1").exists() and SeedLedger(db).rows() == []


def test_invalid_combinations_are_refused(tmp_path):
    from app.pipeline import PipelineConfig, run_pipeline
    from app.store.db import Database
    from app.store.ledger import SeedLedger
    db = Database(":memory:")
    with pytest.raises(ValueError, match="cannot be a rehearsal"):
        run_pipeline(settings(), Boom(), db, SeedLedger(db), PipelineConfig("x", tmp_path, 1, rehearsal=True, official=True), env=ENV)
    with pytest.raises(ValueError, match="LLM_DEV_CACHE"):
        run_pipeline(settings(LLM_DEV_CACHE="1"), Boom(), db, SeedLedger(db), PipelineConfig("x", tmp_path, 1), env=ENV)
