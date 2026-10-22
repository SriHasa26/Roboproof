"""Check that the Nebius API key never appears in tracked files or git history. Reports counts and file names only,
never the secret value itself."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

PLACEHOLDERS = {"", "your-key-here", "changeme", "xxx"}
URLISH = re.compile(r"^(https?://\S+|[\w./\\-]+)$")


@dataclass
class SecretsReport:
    key_present: bool = False
    tracked_files_with_key: list[str] = field(default_factory=list)
    commits_with_key: int = 0
    env_example_problems: list[str] = field(default_factory=list)
    env_ignored: bool = False
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def read_env_value(env_path: Path, name: str) -> str | None:
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith(f"{name}=") and not line.startswith("#"):
            return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


def _git(root: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, input=stdin)


def check_env_example(path: Path) -> list[str]:
    """.env.example must hold placeholders or harmless defaults only (URLs, paths, small numbers)."""
    problems = []
    if not path.exists():
        return [".env.example is missing"]
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = (s.strip() for s in line.split("=", 1))
        if name.endswith(("KEY", "TOKEN", "SECRET", "PASSWORD")) and value not in PLACEHOLDERS:
            problems.append(f".env.example line {n}: {name} is not a placeholder")
        elif value and value not in PLACEHOLDERS and not URLISH.match(value):
            problems.append(f".env.example line {n}: {name} has an unexpected value")
        elif len(value) >= 32 and "/" not in value and "." not in value[:3]:
            problems.append(f".env.example line {n}: {name} looks like a secret")
    return problems


def run_check(root: Path, env_path: Path | None = None, key_name: str = "NEBIUS_API_KEY") -> SecretsReport:
    root = Path(root)
    env_path = env_path or root / ".env"
    rep = SecretsReport()
    secret = read_env_value(env_path, key_name)
    rep.key_present = secret is not None
    if secret:
        # tracked files in the working tree
        g = _git(root, "grep", "-l", "-F", "-e", secret)
        rep.tracked_files_with_key = [l for l in g.stdout.splitlines() if l.strip()]
        # whole history (all refs); count commits that add or remove the string
        h = _git(root, "log", "--all", "-S", secret, "--oneline")
        rep.commits_with_key = len([l for l in h.stdout.splitlines() if l.strip()])
        if rep.tracked_files_with_key:
            rep.problems.append(f"key found in {len(rep.tracked_files_with_key)} tracked file(s): {rep.tracked_files_with_key}")
        if rep.commits_with_key:
            rep.problems.append(f"key found in git history ({rep.commits_with_key} commit(s))")
    rep.env_example_problems = check_env_example(root / ".env.example")
    rep.problems += rep.env_example_problems
    ign = _git(root, "check-ignore", "-q", ".env")
    rep.env_ignored = ign.returncode == 0
    if not rep.env_ignored:
        rep.problems.append(".env is not gitignored")
    return rep
