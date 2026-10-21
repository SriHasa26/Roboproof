"""Simulator freeze fingerprint.

The experiment is only meaningful if the simulator, the parameter ranges and the default policy do not
change between baseline, fix and held-out runs. This module fingerprints them. A deliberate change must go
through scripts/refreeze.py, which rewrites FROZEN_HASH.txt and the golden results.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..core.bounds import INT_POLICY_PARAMS, POLICY_BOUNDS, SCENARIO_BOUNDS

HERE = Path(__file__).resolve().parent
HASH_FILE = HERE / "FROZEN_HASH.txt"
# Source files whose bytes define simulator behaviour. (Line endings are normalised before hashing.)
SOURCE_FILES = [HERE / "pickplace.py"]


def _norm(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def components() -> dict[str, str]:
    out = {f"src:{p.name}": hashlib.sha256(_norm(p.read_bytes())).hexdigest() for p in SOURCE_FILES}
    bounds = json.dumps(
        {"scenario": SCENARIO_BOUNDS, "policy": POLICY_BOUNDS, "int_params": sorted(INT_POLICY_PARAMS)},
        sort_keys=True,
    )
    out["bounds+defaults"] = hashlib.sha256(bounds.encode()).hexdigest()
    return out


def freeze_hash() -> str:
    comps = components()
    return hashlib.sha256(json.dumps(comps, sort_keys=True).encode()).hexdigest()


def render() -> str:
    lines = [f"freeze_hash {freeze_hash()}"] + [f"{k} {v}" for k, v in sorted(components().items())]
    return "\n".join(lines) + "\n"


def read_committed() -> str:
    return HASH_FILE.read_text(encoding="utf-8")
