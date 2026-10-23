"""The gate decides pass or fail with plain code: it must not import any model client, SDK or analysis module."""
import ast
from pathlib import Path

GATE = Path(__file__).resolve().parents[1] / "app" / "gate"
FORBIDDEN = ("openai", "httpx", "requests", "anthropic", "app.llm", "app.analysis", "..llm", "..analysis")


def imports(path: Path) -> set[str]:
    out = set()
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            out.add(("." * n.level) + (n.module or ""))
    return out


def test_gate_modules_import_no_model_or_network_code():
    files = sorted(GATE.glob("*.py"))
    assert files
    for f in files:
        bad = {i for i in imports(f) if any(i == b or i.startswith(b + ".") or i.lstrip(".").startswith(("llm", "analysis")) for b in FORBIDDEN)}
        assert not bad, f"{f.name} imports {bad}"
