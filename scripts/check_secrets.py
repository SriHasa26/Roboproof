"""Verify the Nebius key is not in any tracked file or git history, .env.example holds placeholders only, and .env is
gitignored. Prints counts and file names only, never the value. Exit code 1 on any problem.

Run on the host (needs git):  python scripts/check_secrets.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.secrets_check import run_check  # noqa: E402

rep = run_check(ROOT)
print(f"NEBIUS_API_KEY in .env: {'set' if rep.key_present else 'missing'}")
print(f"tracked files containing it: {len(rep.tracked_files_with_key)} {rep.tracked_files_with_key}")
print(f"commits containing it (all refs): {rep.commits_with_key}")
print(f".env.example placeholder problems: {len(rep.env_example_problems)} {rep.env_example_problems}")
print(f".env gitignored: {rep.env_ignored}")
print("RESULT:", "OK" if rep.ok else "PROBLEMS: " + "; ".join(rep.problems))
sys.exit(0 if rep.ok else 1)
