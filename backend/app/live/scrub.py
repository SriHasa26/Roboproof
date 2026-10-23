"""Remove secrets from any text before it is logged, stored or sent to a client."""
from __future__ import annotations

import os
import re

_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|ACCESS_CODE)", re.I)
_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{8,}", re.I)
_SK = re.compile(r"\b(sk|nb|nvapi)[-_][A-Za-z0-9_\-]{12,}\b")


def secret_values(env: dict[str, str] | None = None) -> list[str]:
    e = env if env is not None else os.environ
    vals = {v for k, v in e.items() if _NAME.search(k) and v and len(v) >= 6}
    return sorted(vals, key=len, reverse=True)


def scrub(text: str, env: dict[str, str] | None = None) -> str:
    for v in secret_values(env):
        text = text.replace(v, "[redacted]")
    text = _BEARER.sub(r"\1[redacted]", text)
    return _SK.sub("[redacted]", text)


def scrub_obj(x, env: dict[str, str] | None = None):
    if isinstance(x, str):
        return scrub(x, env)
    if isinstance(x, dict):
        return {k: scrub_obj(v, env) for k, v in x.items()}
    if isinstance(x, list):
        return [scrub_obj(v, env) for v in x]
    return x
