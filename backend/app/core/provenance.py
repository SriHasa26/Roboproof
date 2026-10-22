"""Pipeline freeze fingerprint and the guard for OFFICIAL runs.

After the git tag `pipeline-frozen`, the prompts, evidence, analyst, fixer, gate and their config are fixed. Anything run
before the tag is a rehearsal. An official run (official=True) refuses to start unless:
  - the working tree is clean,
  - the tag exists and the current hash of the frozen files equals the hash of those files AT THE TAG,
  - the committed FROZEN_PIPELINE_HASH.txt agrees,
  - the container image build id is known (env ROBOPROOF_IMAGE_ID).
It records commit, tag, hash, image build id, model ids and runner name in the run artifacts.
Changing a frozen file is a deliberate re-freeze: scripts/refreeze_pipeline.py, then a new tag.
"""
from __future__ import annotations

import hashlib
import platform
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

TAG = "pipeline-frozen"
HASH_FILE_REL = "backend/app/core/FROZEN_PIPELINE_HASH.txt"
FROZEN_FILES = [
    "backend/app/pipeline.py",
    "backend/app/core/provenance.py", "backend/app/core/gate_config.py", "backend/app/core/seeds.py",
    "backend/app/core/schemas.py", "backend/app/core/stats.py",
    "backend/app/llm/client.py", "backend/app/llm/controls.py",
    "backend/app/scenarios/generator.py", "backend/app/scenarios/proposal.py", "backend/app/scenarios/sweep.py",
    "backend/app/analysis/evidence.py", "backend/app/analysis/analyst.py", "backend/app/analysis/fixer.py",
    "backend/app/analysis/models.py",
    "backend/app/gate/gate.py", "backend/app/gate/verification.py",
    "backend/app/store/ledger.py",
    "backend/app/runner/base.py", "backend/app/runner/local.py",
]
REPO_ROOT = Path(__file__).resolve().parents[3]

GitFn = Callable[..., tuple[int, str]]


class OfficialRunRefused(RuntimeError):
    pass


def _norm(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def _digest(contents: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for rel in sorted(contents):
        h.update(rel.encode() + b"\0" + hashlib.sha256(_norm(contents[rel])).hexdigest().encode() + b"\n")
    return h.hexdigest()


def compute_pipeline_hash(root: Path = REPO_ROOT) -> str:
    return _digest({rel: (Path(root) / rel).read_bytes() for rel in FROZEN_FILES})


def render_hash_file(root: Path = REPO_ROOT) -> str:
    comps = {rel: hashlib.sha256(_norm((Path(root) / rel).read_bytes())).hexdigest() for rel in FROZEN_FILES}
    return f"pipeline_hash {compute_pipeline_hash(root)}\n" + "".join(f"{k} {v}\n" for k, v in sorted(comps.items()))


def read_committed_hash(root: Path = REPO_ROOT) -> str | None:
    p = Path(root) / HASH_FILE_REL
    if not p.exists():
        return None
    first = p.read_text(encoding="utf-8").splitlines()[0].split()
    return first[1] if len(first) == 2 and first[0] == "pipeline_hash" else None


def make_git(root: Path = REPO_ROOT) -> GitFn:
    def git(*args: str) -> tuple[int, str]:
        try:
            # -c options: the repo may be a bind mount owned by another user (safe.directory), with a different file-mode view, and
            # CRLF working-tree files on a Windows host (autocrlf=true makes line endings alone not count as a change)
            p = subprocess.run(["git", "-c", "safe.directory=*", "-c", "core.fileMode=false", "-c", "core.autocrlf=true", *args], cwd=root,
                               capture_output=True, text=False)
        except FileNotFoundError:
            return 127, ""
        return p.returncode, p.stdout.decode("utf-8", errors="replace") if args[:1] != ("show",) else p.stdout  # type: ignore[return-value]
    return git


def hash_at_ref(git: GitFn, ref: str) -> str:
    contents = {}
    for rel in FROZEN_FILES:
        rc, out = git("show", f"{ref}:{rel}")
        if rc != 0:
            raise OfficialRunRefused(f"cannot read {rel} at {ref} (is it committed in the tag?)")
        contents[rel] = out if isinstance(out, bytes) else out.encode()
    return _digest(contents)


@dataclass
class Provenance:
    commit: str
    tag: str
    tag_commit: str
    pipeline_hash: str
    image_build_id: str
    model_fast: str | None
    model_reasoning: str | None
    runner_name: str | None
    official: bool
    python: str

    def as_dict(self) -> dict:
        return asdict(self)


def official_preflight(env: dict, root: Path = REPO_ROOT, git: GitFn | None = None, model_fast: str | None = None,
                       model_reasoning: str | None = None, runner_name: str | None = None) -> Provenance:
    """Raise OfficialRunRefused unless an official run may start. Returns the provenance to record."""
    git = git or make_git(root)
    problems: list[str] = []
    rc, head = git("rev-parse", "HEAD")
    if rc != 0:
        raise OfficialRunRefused("cannot run git here, so the working tree and the tag cannot be verified")
    head = head.strip()
    rc, status = git("status", "--porcelain")
    if rc != 0 or status.strip():
        problems.append("working tree is not clean (uncommitted or untracked files): " + ", ".join(l[3:] for l in status.splitlines()[:5]))
    rc, tag_commit = git("rev-parse", "--verify", f"{TAG}^{{commit}}")
    tag_commit = tag_commit.strip()
    current = compute_pipeline_hash(root)
    if rc != 0:
        problems.append(f"git tag '{TAG}' does not exist")
    else:
        at_tag = hash_at_ref(git, TAG)
        if at_tag != current:
            problems.append(f"frozen files differ from the tag '{TAG}' (current {current[:12]}, at tag {at_tag[:12]}); "
                            f"a change to them is a deliberate re-freeze, and anything run before a new tag is a rehearsal")
    committed = read_committed_hash(root)
    if committed != current:
        problems.append(f"FROZEN_PIPELINE_HASH.txt ({(committed or 'missing')[:12]}) does not match the frozen files ({current[:12]})")
    image = env.get("ROBOPROOF_IMAGE_ID")
    if not image:
        problems.append("ROBOPROOF_IMAGE_ID is not set (run via scripts/dock.sh so the image build id is recorded)")
    if problems:
        raise OfficialRunRefused("official run refused:\n  - " + "\n  - ".join(problems))
    return Provenance(commit=head, tag=TAG, tag_commit=tag_commit, pipeline_hash=current, image_build_id=image,
                      model_fast=model_fast, model_reasoning=model_reasoning, runner_name=runner_name, official=True,
                      python=platform.python_version())


def describe_unofficial(env: dict, model_fast: str | None, model_reasoning: str | None, runner_name: str | None,
                        root: Path = REPO_ROOT) -> dict:
    """Best-effort provenance for non-official runs (never refuses)."""
    git = make_git(root)
    rc, head = git("rev-parse", "HEAD")
    rc2, status = git("status", "--porcelain")
    return {"commit": head.strip() if rc == 0 else None, "working_tree_clean": (rc2 == 0 and not status.strip()) if rc2 == 0 else None,
            "pipeline_hash": compute_pipeline_hash(root), "image_build_id": env.get("ROBOPROOF_IMAGE_ID"), "model_fast": model_fast,
            "model_reasoning": model_reasoning, "runner_name": runner_name, "official": False, "python": platform.python_version()}
