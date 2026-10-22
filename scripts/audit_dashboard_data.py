"""Flag null / NaN / empty-string values in every JSON under frontend/public/data (display audit; read-only)."""
import json, math, sys
from pathlib import Path

D = Path(__file__).resolve().parents[1] / "frontend" / "public" / "data"
bad = 0


def walk(x, path, f):
    global bad
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) or x == "":
        bad += 1
        print(f"{f}: {path} = {x!r}")
    elif isinstance(x, dict):
        for k, v in x.items():
            walk(v, f"{path}.{k}", f)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            walk(v, f"{path}[{i}]", f)


for p in sorted(D.rglob("*.json")):
    walk(json.loads(p.read_text(encoding="utf-8")), "", p.relative_to(D))
print("flagged:", bad)
sys.exit(0)
